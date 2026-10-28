from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.ai.speech.types import SpeechEventType
from speech_worker.session import SpeechSession


@dataclass
class FakeRuntime:
    vad_outputs: list[list[list[int]]]
    vad_calls: list[dict] = field(default_factory=list)
    transcribe_calls: list[tuple[bytes, int]] = field(default_factory=list)
    speaker_calls: list[tuple[bytes, int]] = field(default_factory=list)

    def vad_stream(
        self,
        pcm: bytes,
        sample_rate: int,
        *,
        cache: dict,
        is_final: bool,
        chunk_size_ms: int = 200,
    ) -> list[list[int]]:
        self.vad_calls.append(
            {
                "pcm": pcm,
                "sample_rate": sample_rate,
                "cache": cache,
                "is_final": is_final,
                "chunk_size_ms": chunk_size_ms,
            }
        )
        return self.vad_outputs.pop(0) if self.vad_outputs else []

    def transcribe(self, pcm: bytes, sample_rate: int) -> dict:
        self.transcribe_calls.append((pcm, sample_rate))
        return {"text": "测试口供", "confidence": 0.93}

    def speaker_embedding(self, pcm: bytes, sample_rate: int, *, backend_key: str | None = None) -> dict:
        self.speaker_calls.append((pcm, sample_rate))
        return {
            "embedding": [0.6, 0.8],
            "backend_key": "eres2net_large",
            "model_id": "eres2net",
        }


class MissingSpeakerMetadataRuntime(FakeRuntime):
    def speaker_embedding(self, pcm: bytes, sample_rate: int, *, backend_key: str | None = None) -> dict:
        self.speaker_calls.append((pcm, sample_rate))
        return {"embedding": [0.6, 0.8]}


class StreamingRuntime(FakeRuntime):
    streaming_asr_available = True

    def __init__(self, vad_outputs: list[list[list[int]]]):
        super().__init__(vad_outputs)
        self.stream_calls: list[bytes] = []

    def transcribe_stream(self, pcm: bytes, sample_rate: int, *, cache: dict, is_final: bool = False) -> str:
        self.stream_calls.append(bytes(pcm))
        return "实时字幕"


class StreamingFinalRuntime(StreamingRuntime):
    def __init__(self, vad_outputs: list[list[list[int]]]):
        super().__init__(vad_outputs)
        self.stream_final_flags: list[bool] = []

    def transcribe_stream(self, pcm: bytes, sample_rate: int, *, cache: dict, is_final: bool = False) -> str:
        self.stream_calls.append(bytes(pcm))
        self.stream_final_flags.append(is_final)
        return "流" if not is_final else "尾"


def _pcm(ms: int, sample_rate: int = 16000, value: int = 1) -> bytes:
    samples = sample_rate * ms // 1000
    frame = int(value).to_bytes(2, byteorder="little", signed=True)
    return frame * samples


def test_push_pcm_feeds_only_new_chunk_into_streaming_vad():
    runtime = FakeRuntime(vad_outputs=[[], []])
    session = SpeechSession("session-1", 16000, runtime, chunk_size_ms=200)
    chunk1 = _pcm(200, value=1)
    chunk2 = _pcm(200, value=2)

    assert session.push_pcm(chunk1) == []
    assert session.push_pcm(chunk2) == []

    assert [call["pcm"] for call in runtime.vad_calls] == [chunk1, chunk2]
    assert runtime.vad_calls[0]["cache"] is runtime.vad_calls[1]["cache"]
    assert runtime.vad_calls[0]["is_final"] is False
    assert runtime.vad_calls[1]["is_final"] is False
    assert runtime.vad_calls[0]["chunk_size_ms"] == 200
    assert session.stream_offset_ms == 400


def test_start_then_end_decodes_utterance_once_with_shared_bounds():
    runtime = FakeRuntime(vad_outputs=[[[0, -1]], [[-1, 300]]])
    session = SpeechSession("session-2", 16000, runtime, chunk_size_ms=200)
    first = _pcm(200, value=1)
    second = _pcm(200, value=2)

    start_events = session.push_pcm(first)
    assert [event.type for event in start_events] == [SpeechEventType.VAD_START]
    assert start_events[0].start_ms == 0
    assert runtime.transcribe_calls == []
    assert runtime.speaker_calls == []

    final_events = session.push_pcm(second)
    assert [event.type for event in final_events] == [
        SpeechEventType.VAD_END,
        SpeechEventType.ASR_FINAL,
    ]
    assert [(event.start_ms, event.end_ms) for event in final_events] == [(0, 300)] * 2
    assert final_events[1].text == "测试口供"
    assert final_events[1].confidence == 0.93
    assert final_events[1].details["stage_one_asr_only"] is True
    assert final_events[1].details["asr_start_sample"] == 0
    assert final_events[1].details["asr_end_sample"] == 4800
    assert all(event.type is not SpeechEventType.ASR_PARTIAL for event in final_events)

    expected_utterance = first + _pcm(100, value=2)
    assert runtime.transcribe_calls == [(expected_utterance, 16000)]
    assert runtime.speaker_calls == []


def test_active_utterance_emits_a_preview_without_waiting_for_vad_end():
    runtime = StreamingRuntime(vad_outputs=[[[0, -1]], []])
    session = SpeechSession("session-preview", 16000, runtime, chunk_size_ms=200)

    session.push_pcm(_pcm(200, value=1))
    events = session.push_pcm(_pcm(1500, value=2))

    assert [event.type for event in events] == [SpeechEventType.ASR_PARTIAL]
    assert events[0].text
    assert events[0].start_ms == 0
    # Only two complete 600ms streaming windows have been consumed.
    assert events[0].end_ms == 1200
    assert events[0].model_id == "paraformer-streaming"
    assert events[0].details == {"preview": True, "cumulative": True}
    assert runtime.transcribe_calls == []
    assert runtime.speaker_calls == []


def test_stage_one_does_not_require_a_speaker_runtime():
    runtime = MissingSpeakerMetadataRuntime(vad_outputs=[[[0, 100]]])
    session = SpeechSession("session-no-model", 16000, runtime, chunk_size_ms=200)

    events = session.push_pcm(_pcm(200, value=3))

    assert any(event.type is SpeechEventType.ASR_FINAL for event in events)
    assert not any(event.type is SpeechEventType.SPEAKER_RESULT for event in events)
    assert runtime.speaker_calls == []


def test_streaming_preview_uses_a_600ms_audio_window():
    runtime = StreamingRuntime(vad_outputs=[[[0, -1]], []])
    session = SpeechSession("session-fast-preview", 16000, runtime, chunk_size_ms=200)

    assert not any(event.type is SpeechEventType.ASR_PARTIAL for event in session.push_pcm(_pcm(400)))
    events = session.push_pcm(_pcm(200))

    partials = [event for event in events if event.type is SpeechEventType.ASR_PARTIAL]
    assert len(partials) == 1
    assert partials[0].text == "实时字幕"
    assert partials[0].end_ms == 600
    assert runtime.stream_calls == [_pcm(600)]


def test_streaming_result_is_finalized_without_blocking_offline_asr():
    runtime = StreamingFinalRuntime(vad_outputs=[[[0, -1]], [], [[-1, 800]]])
    session = SpeechSession("session-streaming-final", 16000, runtime, chunk_size_ms=200)

    session.push_pcm(_pcm(400))
    partial_events = session.push_pcm(_pcm(200))
    final_events = session.push_pcm(_pcm(200))

    partials = [event for event in partial_events if event.type is SpeechEventType.ASR_PARTIAL]
    finals = [event for event in final_events if event.type is SpeechEventType.ASR_FINAL]
    assert len(partials) == 1
    assert len(finals) == 1
    assert finals[0].text == "流尾"
    assert finals[0].model_id == "paraformer-streaming"
    assert finals[0].details["stage_one_asr_only"] is True
    assert runtime.transcribe_calls == []
    assert runtime.stream_calls == [_pcm(600), _pcm(200)]
    assert runtime.stream_final_flags == [False, True]


def test_delayed_start_recovers_audio_from_preroll_using_absolute_vad_time():
    runtime = FakeRuntime(vad_outputs=[[], [[100, -1]], [[-1, 500]]])
    session = SpeechSession(
        "session-3",
        16000,
        runtime,
        chunk_size_ms=200,
        pre_roll_ms=600,
    )
    first = _pcm(200, value=1)
    second = _pcm(200, value=2)
    third = _pcm(200, value=3)

    assert session.push_pcm(first) == []
    start_events = session.push_pcm(second)
    assert len(start_events) == 1
    assert start_events[0].type is SpeechEventType.VAD_START
    assert start_events[0].start_ms == 100

    final_events = session.push_pcm(third)
    finals = [event for event in final_events if event.type is SpeechEventType.ASR_FINAL]
    assert [(event.start_ms, event.end_ms) for event in finals] == [(100, 500)]

    expected = _pcm(100, value=1) + second + _pcm(100, value=3)
    assert runtime.transcribe_calls == [(expected, 16000)]
    assert runtime.speaker_calls == []


def test_complete_segment_in_one_vad_result_is_decoded_once():
    runtime = FakeRuntime(vad_outputs=[[[50, 150]]])
    session = SpeechSession("session-4", 16000, runtime, chunk_size_ms=200)
    chunk = _pcm(200, value=7)

    events = session.push_pcm(chunk)

    assert [event.type for event in events] == [
        SpeechEventType.VAD_START,
        SpeechEventType.VAD_END,
        SpeechEventType.ASR_FINAL,
    ]
    assert events[0].start_ms == 50
    assert [(event.start_ms, event.end_ms) for event in events[1:]] == [(50, 150)] * 2
    assert runtime.transcribe_calls == [(_pcm(100, value=7), 16000)]
    assert runtime.speaker_calls == []


def test_finalize_flushes_vad_and_closes_active_utterance_without_duplicate_decode():
    runtime = FakeRuntime(vad_outputs=[[[100, -1]], [[-1, 200]]])
    session = SpeechSession("session-5", 16000, runtime, chunk_size_ms=200)
    chunk = _pcm(200, value=9)

    session.push_pcm(chunk)
    events = session.finalize()

    assert runtime.vad_calls[-1]["pcm"] == b""
    assert runtime.vad_calls[-1]["is_final"] is True
    assert [event.type for event in events] == [
        SpeechEventType.VAD_END,
        SpeechEventType.ASR_FINAL,
    ]
    assert [(event.start_ms, event.end_ms) for event in events] == [(100, 200)] * 2
    expected = _pcm(100, value=9)
    assert runtime.transcribe_calls == [(expected, 16000)]
    assert runtime.speaker_calls == []

    assert session.finalize() == []
    assert len(runtime.transcribe_calls) == 1
    assert runtime.speaker_calls == []


# --------------------------------------------------------------------------- Stage 1 ASR
class SpeakerChangeRuntime(FakeRuntime):
    """Speaker embeddings that flip half way through the utterance.

    The tests build a two-tone PCM: samples before the tone change embed as one speaker, the
    rest as the orthogonal one, so a window straddling the boundary dips to cosine 0.
    """

    TONE_BOUNDARY_SAMPLE = 100

    def speaker_embedding(self, pcm: bytes, sample_rate: int, *, backend_key: str | None = None) -> dict:
        self.speaker_calls.append((pcm, sample_rate))
        first = int.from_bytes(pcm[:2], byteorder="little", signed=True)
        embedding = [1.0, 0.0] if first < self.TONE_BOUNDARY_SAMPLE else [0.0, 1.0]
        return {"embedding": embedding, "backend_key": "eres2net_large", "model_id": "eres2net"}


def _two_tone_pcm(first_ms: int, second_ms: int, sample_rate: int = 16000) -> bytes:
    return _pcm(first_ms, sample_rate, value=1) + _pcm(second_ms, sample_rate, value=200)


def test_long_utterance_stays_one_asr_range_without_speaker_inference():
    """Stage 1 retains full text for later speaker analysis."""
    runtime = SpeakerChangeRuntime(vad_outputs=[[[0, -1]], [[-1, 6000]]])
    session = SpeechSession("session-split", 16000, runtime, chunk_size_ms=200)
    session.push_pcm(_pcm(3000, value=1))

    events = session.push_pcm(_pcm(3000, value=200))

    finals = [event for event in events if event.type is SpeechEventType.ASR_FINAL]
    assert [(event.start_ms, event.end_ms) for event in finals] == [(0, 6000)]
    assert len(runtime.transcribe_calls) == 1
    assert runtime.speaker_calls == []
    assert not any(event.type is SpeechEventType.SPEAKER_RESULT for event in events)


def test_long_utterance_is_retained_as_one_asr_result():
    """Long utterances stay whole for the later speaker-analysis stage."""
    runtime = FakeRuntime(vad_outputs=[[[0, -1]], [[-1, 6000]]])
    session = SpeechSession("session-flat", 16000, runtime, chunk_size_ms=200)
    session.push_pcm(_pcm(3000, value=1))

    events = session.push_pcm(_pcm(3000, value=1))

    finals = [event for event in events if event.type is SpeechEventType.ASR_FINAL]
    assert len(finals) == 1
    assert finals[0].start_ms == 0
    assert finals[0].details["stage_one_asr_only"] is True
    assert len(runtime.transcribe_calls) == 1
    assert runtime.speaker_calls == []


def test_short_utterance_is_transcribed_without_speaker_inference():
    runtime = FakeRuntime(vad_outputs=[[[0, -1]], [[-1, 1200]]])
    session = SpeechSession("session-short", 16000, runtime, chunk_size_ms=200)
    session.push_pcm(_pcm(1000, value=1))

    events = session.push_pcm(_pcm(200, value=1))

    finals = [event for event in events if event.type is SpeechEventType.ASR_FINAL]
    assert [(event.start_ms, event.end_ms) for event in finals] == [(0, 1200)]
    assert finals[0].details["stage_one_asr_only"] is True
    assert runtime.speaker_calls == []
