from __future__ import annotations

import logging
import time
from typing import Any, Callable, Protocol

from app.ai.errors import WorkerCrashedError
from app.ai.speech.types import SpeechEvent, SpeechEventType
from speech_worker.speaker_turn_splitter import SpeakerTurnSplitter, TurnSpan

logger = logging.getLogger(__name__)


PCM_SAMPLE_WIDTH_BYTES = 2
_PRODUCT_SPEAKER_BACKEND = "eres2net_large"
_STREAMING_CHUNK_MS = 600  # Align with Paraformer's ten 60 ms output frames.
# Paraformer online uses chunk_size=[0, 10, 5] (5 * 60ms = 300ms right-context
# lookahead), so final tokens of an utterance may flush in the chunk straddling
# or immediately following VAD end_ms.
_STREAMING_LOOKAHEAD_MS = 300


class SpeechRuntime(Protocol):
    def vad_stream(
        self,
        pcm: bytes,
        sample_rate: int,
        *,
        cache: dict[str, Any],
        is_final: bool,
        chunk_size_ms: int = 200,
    ) -> list[list[int]]: ...

    def transcribe(self, pcm: bytes, sample_rate: int) -> dict[str, Any]: ...

    def transcribe_stream(
        self,
        pcm: bytes,
        sample_rate: int,
        *,
        cache: dict[str, Any],
        is_final: bool = False,
    ) -> str: ...

class SpeechSession:
    """Session-local streaming VAD state and utterance assembly.

    Input is 16-bit mono PCM. FunASR streaming VAD timestamps are treated as
    absolute milliseconds from the beginning of this session. Only new PCM is
    passed to VAD; a bounded pre-roll window is retained so delayed VAD start
    events can recover already-received audio without keeping the whole stream.
    """

    def __init__(
        self,
        session_id: str,
        sample_rate: int,
        runtime: SpeechRuntime,
        *,
        speaker_backend_key: str = _PRODUCT_SPEAKER_BACKEND,
        authoritative_speaker_backend_key: str | None = None,
        chunk_size_ms: int = 200,
        pre_roll_ms: int = 1200,
        turn_splitter: Any | None = None,
        split_min_ms: int = 3000,
        base_sample: int = 0,
    ) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if int(sample_rate) <= 0:
            raise ValueError("sample_rate must be positive")
        if int(chunk_size_ms) <= 0:
            raise ValueError("chunk_size_ms must be positive")
        if int(pre_roll_ms) < 0:
            raise ValueError("pre_roll_ms cannot be negative")
        if int(base_sample) < 0:
            raise ValueError("base_sample cannot be negative")
        backend_key = str(speaker_backend_key or _PRODUCT_SPEAKER_BACKEND).strip().lower()
        if backend_key != _PRODUCT_SPEAKER_BACKEND:
            raise ValueError("speaker_backend_key must be eres2net_large")
        authoritative_key = (
            None
            if authoritative_speaker_backend_key is None
            else str(authoritative_speaker_backend_key).strip().lower()
        )
        if authoritative_key is not None and authoritative_key != _PRODUCT_SPEAKER_BACKEND:
            raise ValueError("authoritative speaker backend must match the single session backend")

        self.session_id = session_id
        self.sample_rate = int(sample_rate)
        self.runtime = runtime
        self.chunk_size_ms = int(chunk_size_ms)
        self.pre_roll_ms = int(pre_roll_ms)
        # Keep the legacy constructor arguments for compatibility; Stage 1 does not
        # construct a splitter or call a speaker backend.
        del turn_splitter, split_min_ms
        self.base_sample = int(base_sample)
        self._base_offset_ms = self._samples_to_ms(self.base_sample)

        self.pre_roll_pcm = b""
        self.current_utterance_pcm = bytearray()
        self.vad_cache: dict[str, Any] = {}
        self.utterance_start_ms: int | None = None
        self.stream_offset_ms = self._base_offset_ms
        self.last_activity_monotonic = time.monotonic()

        self._pre_roll_start_ms = self._base_offset_ms
        self._capture_start_ms: int | None = None
        self._stream_samples = self.base_sample
        self._finalized = False
        self._last_partial_end_ms: int | None = None
        self.streaming_cache: dict[str, Any] = {}
        self._stream_staging = bytearray()
        self._stream_chunk_start_sample = self.base_sample
        self._stream_text_chunks: list[tuple[int, int, str]] = []
        self._stream_text_floor_ms = self._base_offset_ms
        self._last_partial_text = ""
        self._stream_prime_pending = False
        self._streaming_method = getattr(runtime, "transcribe_stream", None)
        self._streaming_enabled = callable(self._streaming_method) and bool(
            getattr(runtime, "streaming_asr_available", True)
        )
        self._streaming_status_reported = False

    def push_pcm(self, pcm: bytes) -> list[SpeechEvent]:
        if self._finalized:
            raise RuntimeError("speech session is already finalized")
        if not isinstance(pcm, (bytes, bytearray, memoryview)):
            raise TypeError("pcm must be bytes-like")
        chunk = bytes(pcm)
        if len(chunk) % PCM_SAMPLE_WIDTH_BYTES:
            raise ValueError("PCM16 input must contain complete 2-byte samples")
        if not chunk:
            return []

        chunk_samples = len(chunk) // PCM_SAMPLE_WIDTH_BYTES
        self._stream_samples += chunk_samples
        chunk_end_ms = self._samples_to_ms(self._stream_samples)
        self.stream_offset_ms = chunk_end_ms
        self.last_activity_monotonic = time.monotonic()

        if self.utterance_start_ms is None:
            self._append_pre_roll(chunk, chunk_end_ms)
        else:
            self.current_utterance_pcm.extend(chunk)

        vad_events = self.runtime.vad_stream(
            chunk,
            self.sample_rate,
            cache=self.vad_cache,
            is_final=False,
            chunk_size_ms=self.chunk_size_ms,
        )
        events = self._consume_vad_events(vad_events)
        events.extend(self._stream_audio(chunk))
        events.extend(self._preview_transcript())
        return events

    def finalize(self) -> list[SpeechEvent]:
        if self._finalized:
            return []

        self.last_activity_monotonic = time.monotonic()
        vad_events = self.runtime.vad_stream(
            b"",
            self.sample_rate,
            cache=self.vad_cache,
            is_final=True,
            chunk_size_ms=self.chunk_size_ms,
        )
        events = self._consume_vad_events(vad_events)

        if self.utterance_start_ms is not None:
            if self.stream_offset_ms > self.utterance_start_ms:
                events.extend(self._finish_utterance(self.stream_offset_ms, forced_final=True))
            else:
                self._reset_utterance()

        self._finalized = True
        return events

    @staticmethod
    def split_speaker_turns(
        pcm: bytes,
        sample_rate: int,
        embed: Callable[[bytes], list[float]],
        *,
        splitter: Any | None = None,
    ) -> list[TurnSpan]:
        """Run the existing calibrated splitter against an archived utterance."""
        engine = splitter or SpeakerTurnSplitter()
        return engine.split(pcm, sample_rate, embed)

    def _consume_vad_events(self, vad_events: list[list[int]]) -> list[SpeechEvent]:
        events: list[SpeechEvent] = []
        for segment in vad_events:
            if not isinstance(segment, (list, tuple)) or len(segment) != 2:
                raise WorkerCrashedError("FunASR streaming VAD event must contain [start_ms, end_ms]")
            start_ms, end_ms = int(segment[0]), int(segment[1])
            if start_ms >= 0:
                start_ms += self._base_offset_ms
            if end_ms >= 0:
                end_ms += self._base_offset_ms

            if start_ms >= 0 and end_ms == -1:
                if self.utterance_start_ms is None:
                    events.append(self._start_utterance(start_ms))
                continue

            if start_ms == -1 and end_ms >= 0:
                if self.utterance_start_ms is not None:
                    events.extend(self._finish_utterance(end_ms))
                continue

            if start_ms >= 0 and end_ms >= 0:
                if self.utterance_start_ms is None:
                    events.append(self._start_utterance(start_ms))
                events.extend(self._finish_utterance(end_ms))
                continue

            if start_ms == -1 and end_ms == -1:
                continue
            raise WorkerCrashedError(
                "FunASR streaming VAD returned invalid negative boundary",
                details={"segment": [start_ms, end_ms]},
            )
        return events

    def _start_utterance(self, start_ms: int) -> SpeechEvent:
        # FunASR 的流式 VAD 在它自己的处理网格上报边界（chunk_size_ms=200，且每
        # max_single_segment_time 强制切一刀）。该网格可能比按字节累计的
        # stream_offset_ms 领先不到一个 chunk；原先会被当成崩溃而中止整段采集。
        # 改为钳位：边界只用于切分我们已持有的 PCM，下游索引本就有界。
        if start_ms > self.stream_offset_ms:
            logger.warning(
                "FunASR VAD start is beyond received audio; clamping",
                extra={
                    "session_id": self.session_id,
                    "start_ms": start_ms,
                    "stream_offset_ms": self.stream_offset_ms,
                },
            )
            start_ms = self.stream_offset_ms

        capture_start_ms = max(start_ms, self._pre_roll_start_ms)
        offset_ms = max(0, capture_start_ms - self._pre_roll_start_ms)
        offset_bytes = min(len(self.pre_roll_pcm), self._ms_to_bytes(offset_ms))
        self.current_utterance_pcm = bytearray(self.pre_roll_pcm[offset_bytes:])
        self.utterance_start_ms = start_ms
        self._capture_start_ms = capture_start_ms
        self._stream_prime_pending = self._streaming_enabled
        self.pre_roll_pcm = b""
        self._pre_roll_start_ms = self.stream_offset_ms

        details: dict[str, Any] = {}
        if capture_start_ms != start_ms:
            details["pre_roll_truncated"] = True
            details["captured_from_ms"] = capture_start_ms
        start_sample = self._ms_to_samples(start_ms)
        details["asr_start_sample"] = start_sample
        details["replay_start_sample"] = max(
            0,
            start_sample - self._ms_to_samples(self.pre_roll_ms),
        )
        return SpeechEvent(
            type=SpeechEventType.VAD_START,
            session_id=self.session_id,
            start_ms=start_ms,
            details=details,
        )

    def _finish_utterance(self, end_ms: int, *, forced_final: bool = False) -> list[SpeechEvent]:
        start_ms = self.utterance_start_ms
        capture_start_ms = self._capture_start_ms
        if start_ms is None or capture_start_ms is None:
            return []
        if end_ms > self.stream_offset_ms:
            logger.warning(
                "FunASR VAD end is beyond received audio; clamping",
                extra={
                    "session_id": self.session_id,
                    "end_ms": end_ms,
                    "stream_offset_ms": self.stream_offset_ms,
                },
            )
            end_ms = self.stream_offset_ms
        if end_ms <= start_ms:
            # 钳位后可能退化为零长片段；丢掉这一片即可，绝不中止整段采集。
            logger.warning(
                "FunASR VAD segment collapsed after clamping; dropping it",
                extra={
                    "session_id": self.session_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                },
            )
            self._reset_utterance()
            return []

        captured_duration_ms = max(0, end_ms - capture_start_ms)
        utterance_bytes = min(len(self.current_utterance_pcm), self._ms_to_bytes(captured_duration_ms))
        utterance_pcm = bytes(self.current_utterance_pcm[:utterance_bytes])
        trailing_pcm = bytes(self.current_utterance_pcm[utterance_bytes:])

        streaming_text: str | None = None
        if utterance_pcm and self._streaming_enabled:
            capture_start_sample = self._ms_to_samples(capture_start_ms)
            consumed_samples = max(0, self._stream_chunk_start_sample - capture_start_sample)
            consumed_bytes = min(len(utterance_pcm), consumed_samples * PCM_SAMPLE_WIDTH_BYTES)
            pending_pcm = utterance_pcm[consumed_bytes:]
            if pending_pcm:
                try:
                    text = str(
                        self._streaming_method(
                            pending_pcm,
                            self.sample_rate,
                            cache=self.streaming_cache,
                            is_final=True,
                        )
                        or ""
                    ).strip()
                except Exception as exc:
                    code = str(getattr(exc, "code", "ASR_STREAMING_ERROR"))
                    logger.warning(
                        "streaming transcript finalization failed",
                        extra={"session_id": self.session_id, "error_code": code},
                    )
                    self._streaming_enabled = False
                else:
                    if text:
                        start_sample = capture_start_sample + consumed_bytes // PCM_SAMPLE_WIDTH_BYTES
                        end_sample = start_sample + len(pending_pcm) // PCM_SAMPLE_WIDTH_BYTES
                        self._stream_text_chunks.append(
                            (self._samples_to_ms(start_sample), self._samples_to_ms(end_sample), text)
                        )

            if self._streaming_enabled:
                # A 600ms streaming chunk that overlaps the end of speech often
                # has chunk_end > vad_end_ms (e.g. [2800, 3400] for end_ms=3360),
                # and Paraformer's 300ms right-context lookahead can emit the
                # final characters in the chunk starting right at end_ms.
                # Requiring chunk_end <= end_ms dropped the tail of every
                # utterance and visibly rolled back the live transcript.
                cutoff_ms = end_ms + _STREAMING_LOOKAHEAD_MS
                current_chunks = [
                    item for item in self._stream_text_chunks
                    if item[0] >= self._stream_text_floor_ms
                    and item[1] > start_ms
                    and item[0] < cutoff_ms
                ]
                assembled_text = "".join(item[2] for item in current_chunks).strip()
                if assembled_text:
                    streaming_text = assembled_text

        self._stream_text_floor_ms = max(self._stream_text_floor_ms, end_ms)
        self._reset_utterance()
        self._set_pre_roll_after_boundary(trailing_pcm, end_ms)

        if not utterance_pcm:
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_END,
                    session_id=self.session_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    details={"forced_final": forced_final} if forced_final else {},
                )
            ]

        asr = (
            {"text": streaming_text, "confidence": None, "model_id": "paraformer-streaming"}
            if streaming_text is not None
            else self.runtime.transcribe(utterance_pcm, self.sample_rate)
        )
        start_sample = self._ms_to_samples(start_ms)
        end_sample = self._ms_to_samples(end_ms)
        details: dict[str, Any] = {
            "stage_one_asr_only": True,
            "asr_start_sample": start_sample,
            "asr_end_sample": end_sample,
        }
        if forced_final:
            details["forced_final"] = True
        if asr.get("model_version") is not None:
            details["model_version"] = str(asr["model_version"])
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                details={"forced_final": True} if forced_final else {},
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=str(asr.get("text") or ""),
                confidence=None if asr.get("confidence") is None else float(asr["confidence"]),
                model_id=str(asr.get("model_id") or "paraformer"),
                details=details,
            ),
        ]

    def _stream_audio(self, pcm: bytes) -> list[SpeechEvent]:
        if not self._streaming_enabled or self.utterance_start_ms is None:
            return []

        if self._stream_prime_pending:
            # VAD reports speech start after buffering some audio. Seed this
            # utterance's online cache from its retained pre-roll (which already
            # includes the current input chunk) instead of running the large
            # streaming model on the silence that preceded it.
            pcm = bytes(self.current_utterance_pcm)
            self._stream_staging.clear()
            self.streaming_cache.clear()
            if self._capture_start_ms is not None:
                self._stream_chunk_start_sample = self._ms_to_samples(self._capture_start_ms)
            self._stream_prime_pending = False

        self._stream_staging.extend(pcm)
        chunk_samples = max(1, int(round(self.sample_rate * _STREAMING_CHUNK_MS / 1000)))
        chunk_bytes = chunk_samples * PCM_SAMPLE_WIDTH_BYTES
        events: list[SpeechEvent] = []
        while len(self._stream_staging) >= chunk_bytes:
            stream_chunk = bytes(self._stream_staging[:chunk_bytes])
            del self._stream_staging[:chunk_bytes]
            start_sample = self._stream_chunk_start_sample
            end_sample = start_sample + chunk_samples
            self._stream_chunk_start_sample = end_sample
            try:
                text = str(
                    self._streaming_method(
                        stream_chunk,
                        self.sample_rate,
                        cache=self.streaming_cache,
                        is_final=False,
                    )
                    or ""
                ).strip()
            except Exception as exc:
                code = str(getattr(exc, "code", "ASR_STREAMING_ERROR"))
                logger.warning(
                    "streaming transcript preview failed",
                    extra={"session_id": self.session_id, "error_code": code},
                )
                self._streaming_enabled = False
                self._stream_staging.clear()
                if not self._streaming_status_reported:
                    self._streaming_status_reported = True
                    events.append(
                        SpeechEvent(
                            type=SpeechEventType.ASR_PREVIEW_STATUS,
                            session_id=self.session_id,
                            details={"status": "ERROR", "code": code},
                        )
                    )
                break
            if text:
                start_ms = self._samples_to_ms(start_sample)
                end_ms = self._samples_to_ms(end_sample)
                self._stream_text_chunks.append((start_ms, end_ms, text))

        # The VAD caps a turn at five seconds. Keep only that turn, bounded pre-roll,
        # and one analysis chunk of timestamped preview history.
        keep_after_ms = max(
            self._base_offset_ms,
            self.stream_offset_ms - self.pre_roll_ms - 5_000 - _STREAMING_CHUNK_MS,
        )
        self._stream_text_chunks = [
            item for item in self._stream_text_chunks if item[1] > keep_after_ms
        ]
        return events

    def _preview_transcript(self) -> list[SpeechEvent]:
        """Emit cumulative text assembled from fresh streaming-model chunks only."""
        start_ms = self.utterance_start_ms
        if start_ms is None or not self._streaming_enabled:
            return []
        current_chunks = [
            item for item in self._stream_text_chunks
            if item[0] >= self._stream_text_floor_ms
            and item[1] > start_ms
            and item[1] <= self.stream_offset_ms
        ]
        if not current_chunks:
            return []
        end_ms = current_chunks[-1][1]
        text = "".join(item[2] for item in current_chunks).strip()
        if not text or (text == self._last_partial_text and end_ms == self._last_partial_end_ms):
            return []
        self._last_partial_text = text
        self._last_partial_end_ms = end_ms
        return [
            SpeechEvent(
                type=SpeechEventType.ASR_PARTIAL,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                model_id="paraformer-streaming",
                details={"preview": True, "cumulative": True},
            )
        ]

    def _append_pre_roll(self, pcm: bytes, end_ms: int) -> None:
        max_bytes = self._ms_to_bytes(self.pre_roll_ms)
        if max_bytes <= 0:
            self.pre_roll_pcm = b""
            self._pre_roll_start_ms = end_ms
            return
        combined = self.pre_roll_pcm + pcm
        if len(combined) > max_bytes:
            combined = combined[-max_bytes:]
        self.pre_roll_pcm = combined
        retained_ms = self._bytes_to_ms(len(combined))
        self._pre_roll_start_ms = max(0, end_ms - retained_ms)

    def _set_pre_roll_after_boundary(self, pcm: bytes, boundary_ms: int) -> None:
        max_bytes = self._ms_to_bytes(self.pre_roll_ms)
        if max_bytes <= 0 or not pcm:
            self.pre_roll_pcm = b""
            self._pre_roll_start_ms = self.stream_offset_ms
            return
        kept = pcm[-max_bytes:]
        kept_ms = self._bytes_to_ms(len(kept))
        self.pre_roll_pcm = kept
        self._pre_roll_start_ms = max(boundary_ms, self.stream_offset_ms - kept_ms)

    def _reset_utterance(self) -> None:
        self.current_utterance_pcm = bytearray()
        self.utterance_start_ms = None
        self._capture_start_ms = None
        self._last_partial_end_ms = None
        self._last_partial_text = ""
        self._stream_staging.clear()
        self._stream_text_chunks.clear()
        self.streaming_cache.clear()
        self._stream_prime_pending = False
        self._stream_chunk_start_sample = self._stream_samples

    def _ms_to_bytes(self, milliseconds: int) -> int:
        samples = self._ms_to_samples(milliseconds)
        return max(0, samples) * PCM_SAMPLE_WIDTH_BYTES

    def _ms_to_samples(self, milliseconds: int) -> int:
        return max(0, int(round(int(milliseconds) * self.sample_rate / 1000.0)))

    def _bytes_to_ms(self, size: int) -> int:
        samples = int(size) // PCM_SAMPLE_WIDTH_BYTES
        return self._samples_to_ms(samples)

    def _samples_to_ms(self, samples: int) -> int:
        return int(round(int(samples) * 1000.0 / self.sample_rate))
