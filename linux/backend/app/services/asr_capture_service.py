from __future__ import annotations

import logging
import math
import queue
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.ai.speech.calibration import MODEL_BASELINE_THRESHOLD
from app.ai.speech.types import SpeechEvent, SpeechEventType
from app.database.models import (
    ASRCaptureSession,
    ASRFragment,
    OfficerVoiceprint,
    SessionVoiceAssignment,
)
from app.domain.enums import SessionStatus
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import speaker_calibrations as calibration_repo
from app.repositories import speaker_compare_evidence as compare_evidence_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.interrogation_projection_service import InterrogationProjectionService
from app.services.speaker_backend_compare import (
    SpeakerBackendCompareCoordinator,
    SpeakerBackendDiagnostic,
)
from app.services.speaker_calibration_runtime import ResolvedSpeakerCalibration
from app.services.speaker_mode import (
    MODE_DECLARED_KEY,
    MODE_DEGRADED_KEY,
    MODE_EFFECTIVE_KEY,
    MODE_REASON_KEY,
    FULL,
    SUSPECT_ONLY,
    SUSPECT_PLUS_INTERROGATOR,
    SUSPECT_PLUS_RECORDER,
    SpeakerModeConfig,
    decision_roles,
    mode_decision_detail,
    narrow_decision_roles,
)
from app.services.serializers import iso_utc
from app.services.speaker_policy import SpeakerRole, SpeakerSource, decide_speaker


logger = logging.getLogger(__name__)
PublishEvent = Callable[[str, str, dict[str, Any]], None]
FragmentSink = Callable[[str, str], None]
CaptureFinishedSink = Callable[[str, str], None]
CalibrationResolver = Callable[[Any], ResolvedSpeakerCalibration]
_FLOAT32_BYTES = 4
_AUDIO_LEVEL_INTERVAL_SECONDS = 0.04


@dataclass
class _CaptureRuntime:
    case_id: str
    interrogation_session_id: str
    capture_session_id: str
    speech_session_id: str
    speaker_threshold: float
    speaker_margin: float | None
    threshold_source: str
    calibration_id: str | None
    calibration_status: str
    speaker_model_fingerprint: str | None
    microphone_fingerprint: str | None
    authoritative_speaker_backend: str | None = None
    secondary_speaker_backend: str | None = None
    secondary_calibration: ResolvedSpeakerCalibration | None = None
    #: The mode this capture declares from its bound roles, captured before the
    #: operating point narrows anything, so a degradation stays reported as such.
    #: ``start()`` seeds it from the session's voice assignment; every persisted
    #: fragment refreshes it from the roles that fragment really bound.
    declared_recognition_mode: str = SUSPECT_ONLY
    sample_rate: int = 16_000
    capture_started_at: str | None = None
    live_transcript_status: str = "UNKNOWN"
    speaker_backend: str = "eres2net_large"
    durable_sample_cursor: int = 0
    storage_error: str | None = None
    consume_events: Callable[[list[SpeechEvent] | None], None] = lambda _events: None
    capture_finished_sink: Callable[[], None] = lambda: None
    capture_error_sink: Callable[[Exception], None] = lambda _exc: None
    inference_error_sink: Callable[[Exception], None] = lambda _exc: None
    local_inference_queue: queue.Queue[bytes | None] = field(default_factory=queue.Queue)
    local_inference_thread: threading.Thread | None = None
    local_inference_done: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    ordinal: int = 0
    seen_utterances: set[tuple[int, int]] = field(default_factory=set)
    audio_level_sample_count: int = 0
    last_audio_level_published_at: float | None = None


@dataclass
class _PreparationRuntime:
    case_id: str
    speech_session_id: str
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    text_parts: list[str] = field(default_factory=list)
    seen_utterances: set[tuple[int, int]] = field(default_factory=set)
    last_error: str | None = None


class AsrCaptureService:
    """Own the single ALSA -> speech-worker audio path.

    Formal interrogation capture persists speaker-attributed ASR fragments and
    drives the template projection. Question-preparation dictation deliberately
    reuses the same offline speech runtime and microphone but remains memory-only:
    it has no interrogation session, requires no voiceprint, emits no dialogue
    events, and writes no ASR capture/fragment rows.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        device_manager: Any,
        ai_supervisor: Any,
        publish_event: PublishEvent,
        sample_rate: int = 16_000,
        read_timeout: float = 0.2,
        calibration_resolver: CalibrationResolver | None = None,
        secondary_calibration_resolver: CalibrationResolver | None = None,
        fragment_sink: FragmentSink | None = None,
        capture_finished_sink: CaptureFinishedSink | None = None,
        speaker_model_key: str = "eres2net_large",
        speaker_authoritative_backend: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.device_manager = device_manager
        self.ai_supervisor = ai_supervisor
        self.publish_event = publish_event
        self.sample_rate = int(sample_rate)
        self.read_timeout = max(0.001, float(read_timeout))
        self.calibration_resolver = calibration_resolver
        self.secondary_calibration_resolver = secondary_calibration_resolver
        self.fragment_sink = fragment_sink
        self.capture_finished_sink = capture_finished_sink
        self.speaker_model_key = str(speaker_model_key or "eres2net_large").strip().lower()
        if self.speaker_model_key != "eres2net_large":
            raise ValueError("speaker_model_key must be eres2net_large")
        configured_authority = (
            None
            if speaker_authoritative_backend is None
            else str(speaker_authoritative_backend).strip().lower()
        )
        if configured_authority is not None and configured_authority != self.speaker_model_key:
            raise ValueError("speaker_authoritative_backend must match the single backend")
        self.compare_coordinator = None
        self.authoritative_speaker_backend = self.speaker_model_key
        self.secondary_speaker_backend = None
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")

        self._lock = threading.RLock()
        self._active: dict[str, _CaptureRuntime] = {}
        self._last_error: dict[str, str | None] = {}
        self._preparation: dict[str, _PreparationRuntime] = {}
        self._preparation_results: dict[str, dict[str, Any]] = {}
        self._live_speech_coordinator: Any | None = None

    def set_live_speech_coordinator(self, coordinator: Any) -> None:
        self._live_speech_coordinator = coordinator

    def ingest_browser_frame(
        self,
        case_id: str,
        capture_id: str,
        source_sequence: int,
        start_sample: int,
        pcm: bytes,
    ) -> dict[str, int]:
        with self._lock:
            runtime = self._active.get(str(case_id).strip())
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, str(capture_id))
            recording_status = None if capture is None else capture.recording_status
        if recording_status in {"INCOMPLETE", "COMPLETE"}:
            if self._live_speech_coordinator is None:
                raise RuntimeError("durable browser audio ingress is unavailable")
            return self._live_speech_coordinator.replay_browser_frame(
                case_id=case_id,
                capture_id=capture_id,
                source_sequence=source_sequence,
                start_sample=start_sample,
                pcm=bytes(pcm),
            )
        if runtime is None or runtime.capture_session_id != str(capture_id):
            raise RuntimeError("browser audio capture is not active")
        if self._live_speech_coordinator is None:
            raise RuntimeError("durable browser audio ingress is unavailable")
        durable_end = self._live_speech_coordinator.append_audio(
            runtime,
            bytes(pcm),
            source_sequence=source_sequence,
            expected_start_sample=start_sample,
        )
        return {"ackSequence": source_sequence, "durableSampleEnd": durable_end}

    def mark_browser_capture_incomplete(self, case_id: str, capture_id: str, reason: str) -> bool:
        if self._live_speech_coordinator is None:
            raise RuntimeError("durable browser audio ingress is unavailable")
        marked = self._live_speech_coordinator.mark_browser_capture_incomplete(case_id, capture_id, reason)
        with self._lock:
            runtime = self._active.get(str(case_id).strip())
        if marked and runtime is not None and runtime.capture_session_id == str(capture_id):
            runtime.stop_event.set()
            thread = runtime.thread
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(1.0, self.read_timeout * 5.0))
        return marked

    def complete_browser_capture_recovery(
        self,
        case_id: str,
        capture_id: str,
        next_sequence: int,
        next_sample: int,
    ) -> dict[str, int | str]:
        if self._live_speech_coordinator is None:
            raise RuntimeError("durable browser audio ingress is unavailable")
        return self._live_speech_coordinator.complete_browser_capture_recovery(
            case_id=case_id,
            capture_id=capture_id,
            next_sequence=next_sequence,
            next_sample=next_sample,
        )

    def resume_browser_capture(self, runtime: _CaptureRuntime) -> None:
        """Rebind an interrupted browser capture after archive recovery."""
        if not callable(getattr(self.device_manager, "start_record", None)):
            raise RuntimeError("browser audio input is unavailable")
        with self._lock:
            if self._any_capture_active_locked() or self._any_preparation_active_locked():
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "已有录音正在占用麦克风", 409)
            self.device_manager.start_record()
            thread = threading.Thread(
                target=self._capture_loop,
                args=(runtime,),
                daemon=True,
                name=f"asr-capture-{runtime.capture_session_id[:8]}",
            )
            runtime.thread = thread
            runtime.stop_event.clear()
            self._last_error[runtime.case_id] = None
            self._active[runtime.case_id] = runtime
            thread.start()

    def start(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        if not case_id:
            raise DomainError("CASE_ID_REQUIRED", "案件编号不能为空", 400)
        ensure_storage = getattr(self._live_speech_coordinator, "assert_storage_available_for_capture", None)
        if callable(ensure_storage):
            ensure_storage()

        with self._lock:
            existing = self._active.get(case_id)
            if existing is not None and existing.thread is not None and existing.thread.is_alive():
                raise DomainError("ASR_CAPTURE_ALREADY_ACTIVE", "该案件正在进行语音采集", 409)
            if self._any_preparation_active_locked():
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "准备阶段语音输入正在占用麦克风", 409)

        with self.session_factory() as db:
            case_repo.get(db, case_id)
            interrogation_session = session_repo.active_for_case(db, case_id)
            if interrogation_session is None:
                raise DomainError("SESSION_NOT_ACTIVE", "请先开始审讯再启动语音采集", 409)
            if interrogation_session.status != SessionStatus.RUNNING.value:
                raise DomainError("SESSION_NOT_RUNNING", "当前审讯未处于进行状态", 409)
            try:
                resolved = self._resolve_calibration(db)
            except Exception:
                logger.exception("speaker calibration is unavailable for case %s", case_id)
                resolved = self._unavailable_calibration()
            secondary_calibration = None
            capture = asr_repo.create_capture_session(
                db,
                case_id=case_id,
                interrogation_session_id=interrogation_session.id,
                sample_rate=self.sample_rate,
            )
            db.flush()
            calibration_repo.create_session_snapshot(
                db,
                capture_session_id=capture.id,
                interrogation_session_id=interrogation_session.id,
                calibration_id=resolved.calibration_id,
                threshold=resolved.threshold,
                margin=resolved.margin,
                threshold_source=resolved.source,
                calibration_status=resolved.status,
                speaker_backend_key=resolved.speaker_backend_key or self.authoritative_speaker_backend,
                speaker_model_fingerprint=resolved.speaker_model_fingerprint,
                microphone_fingerprint=resolved.microphone_fingerprint,
            )
            db.commit()
            capture_session_id = capture.id
            interrogation_session_id = interrogation_session.id
            capture_started_at = (
                iso_utc(capture.started_at)
            )
            # Seed the declared mode inside the session start() already owns: the
            # previous code opened a second one just for this, before the runtime row
            # existed.
            bound_roles = self._bound_roles(db, interrogation_session_id)
            initial_workflow_status = {
                "startedAt": capture.started_at.isoformat() if capture.started_at is not None else None,
                "recordingStatus": capture.recording_status,
                "asrStatus": capture.asr_status,
                "speakerStatus": capture.speaker_status,
                "audioSampleCount": int(capture.audio_sample_count or 0),
                "asrCursorSample": int(capture.asr_cursor_sample or 0),
                "voicedMs": int(capture.voiced_ms or 0),
                "finalFragmentCount": 0,
            }

        runtime = _CaptureRuntime(
            case_id=case_id,
            interrogation_session_id=interrogation_session_id,
            capture_session_id=capture_session_id,
            speech_session_id=capture_session_id,
            speaker_threshold=float(resolved.threshold),
            speaker_margin=None if resolved.margin is None else float(resolved.margin),
            threshold_source=str(resolved.source),
            calibration_id=resolved.calibration_id,
            calibration_status=str(resolved.status),
            speaker_model_fingerprint=resolved.speaker_model_fingerprint,
            microphone_fingerprint=resolved.microphone_fingerprint,
            authoritative_speaker_backend=self.authoritative_speaker_backend,
            secondary_speaker_backend=self.secondary_speaker_backend,
            secondary_calibration=secondary_calibration,
            declared_recognition_mode=self.declared_mode_for_roles(bound_roles),
            sample_rate=self.sample_rate,
            capture_started_at=capture_started_at,
            live_transcript_status=self._live_transcript_status(),
            speaker_backend=self.speaker_model_key,
        )
        runtime.consume_events = lambda events: self._consume_events(runtime, events)
        runtime.capture_finished_sink = lambda: self._capture_finished(runtime)
        runtime.capture_error_sink = lambda exc: self._record_runtime_error(runtime, exc)
        runtime.inference_error_sink = lambda exc: self._record_runtime_error(runtime, exc)

        audio_started = False
        try:
            if self._live_speech_coordinator is not None:
                self._live_speech_coordinator.open_capture(runtime)
            else:
                self._start_local_inference(runtime)
            self.device_manager.start_record()
            audio_started = True
        except Exception:
            if audio_started:
                self._safe_stop_audio()
            if self._live_speech_coordinator is not None:
                try:
                    self._live_speech_coordinator.finish_capture(runtime)
                except Exception:
                    logger.exception("failed to finalize capture %s after start error", runtime.capture_session_id)
            elif runtime.local_inference_thread is not None:
                runtime.local_inference_queue.put(None)
            self._finish_capture_row(runtime.capture_session_id)
            raise

        thread = threading.Thread(
            target=self._capture_loop,
            args=(runtime,),
            daemon=True,
            name=f"asr-capture-{capture_session_id[:8]}",
        )
        runtime.thread = thread
        with self._lock:
            self._last_error[case_id] = None
            self._active[case_id] = runtime
        thread.start()
        return self._runtime_status(
            runtime,
            active=True,
            last_error=None,
            workflow_status=initial_workflow_status,
        )

    def stop(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            runtime = self._active.get(case_id)
        if runtime is None:
            return self.status(case_id)

        runtime.stop_event.set()
        thread = runtime.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.read_timeout * 5.0))
            if thread.is_alive():
                raise DomainError("ASR_CAPTURE_STOP_TIMEOUT", "语音采集线程未能及时停止", 504)
        if runtime.local_inference_thread is not None:
            runtime.local_inference_done.wait(timeout=max(1.0, self.read_timeout * 5.0))
        return self.status(case_id)

    def status(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            runtime = self._active.get(case_id)
            last_error = self._last_error.get(case_id)
        if runtime is not None and runtime.thread is not None and runtime.thread.is_alive():
            return self._runtime_status(runtime, active=True, last_error=last_error)

        with self.session_factory() as db:
            capture = db.scalar(
                select(ASRCaptureSession)
                .where(ASRCaptureSession.case_id == case_id)
                .order_by(ASRCaptureSession.started_at.desc())
                .limit(1)
            )
            if capture is None:
                return {
                    "caseId": case_id,
                    "active": False,
                    "captureSessionId": None,
                    "interrogationSessionId": None,
                    "status": "IDLE",
                    "liveTranscriptStatus": self._live_transcript_status(),
                    "lastError": last_error,
                }
            return {
                "caseId": case_id,
                "active": False,
                "captureSessionId": capture.id,
                "interrogationSessionId": capture.interrogation_session_id,
                "status": capture.status,
                "sampleRate": capture.sample_rate,
                "liveTranscriptStatus": self._live_transcript_status(),
                "startedAt": capture.started_at.isoformat() if capture.started_at is not None else None,
                "endedAt": capture.ended_at.isoformat() if capture.ended_at is not None else None,
                "lastError": last_error,
                **self._capture_workflow_status(capture.id),
            }

    def start_preparation(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        if not case_id:
            raise DomainError("CASE_ID_REQUIRED", "案件编号不能为空", 400)

        with self.session_factory() as db:
            case_repo.get(db, case_id)

        with self._lock:
            if self._any_capture_active_locked():
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "正式审讯录音正在占用麦克风", 409)
            if self._any_preparation_active_locked():
                raise DomainError("ASR_PREPARATION_ALREADY_ACTIVE", "已有准备阶段语音输入正在进行", 409)

        runtime = _PreparationRuntime(
            case_id=case_id,
            speech_session_id=f"question-prep-{case_id}-{uuid4().hex}",
        )
        speech_open = False
        audio_started = False
        try:
            self.ai_supervisor.open_speech_session(
                runtime.speech_session_id,
                sample_rate=self.sample_rate,
            )
            speech_open = True
            self.device_manager.start_record()
            audio_started = True
        except Exception:
            if audio_started:
                self._safe_stop_audio()
            if speech_open:
                self._safe_finalize_close(runtime.speech_session_id)
            raise

        thread = threading.Thread(
            target=self._preparation_loop,
            args=(runtime,),
            daemon=True,
            name=f"question-prep-{case_id[:12]}",
        )
        runtime.thread = thread
        with self._lock:
            self._preparation[case_id] = runtime
            self._preparation_results.pop(case_id, None)
        thread.start()
        return self._preparation_status(runtime, active=True)

    def stop_preparation(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            runtime = self._preparation.get(case_id)
            prior_result = self._preparation_results.get(case_id)
        if runtime is None:
            if prior_result is not None:
                return dict(prior_result)
            return self._empty_preparation_status(case_id)

        runtime.stop_event.set()
        thread = runtime.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.read_timeout * 5.0))
            if thread.is_alive():
                raise DomainError("ASR_PREPARATION_STOP_TIMEOUT", "准备阶段语音输入未能及时停止", 504)

        with self._lock:
            result = self._preparation_results.get(case_id)
        return dict(result) if result is not None else self._preparation_status(runtime, active=False)

    def shutdown(self) -> None:
        with self._lock:
            case_ids = list(self._active)
            preparation_case_ids = list(self._preparation)
        for case_id in case_ids:
            try:
                self.stop(case_id)
            except Exception:
                pass
        for case_id in preparation_case_ids:
            try:
                self.stop_preparation(case_id)
            except Exception:
                pass

    def _capture_loop(self, runtime: _CaptureRuntime) -> None:
        failure: Exception | None = None
        try:
            while not runtime.stop_event.is_set():
                pcm = self.device_manager.read_audio_frames(timeout=self.read_timeout)
                if not pcm:
                    continue
                payload = bytes(pcm)
                self._publish_audio_level(runtime, payload, now=time.monotonic())
                for offset in range(0, len(payload), 32_000):
                    chunk = payload[offset : offset + 32_000]
                    if self._live_speech_coordinator is not None:
                        self._live_speech_coordinator.append_audio(runtime, chunk)
                    else:
                        runtime.local_inference_queue.put(chunk)
        except Exception as exc:
            failure = exc
        finally:
            try:
                self.device_manager.stop_record()
            except Exception as exc:
                if failure is None:
                    failure = exc
            if self._live_speech_coordinator is not None:
                try:
                    self._live_speech_coordinator.finish_capture(runtime)
                except Exception as exc:
                    if failure is None:
                        failure = exc
            elif runtime.local_inference_thread is not None:
                runtime.local_inference_queue.put(None)
            try:
                self._finish_capture_row(runtime.capture_session_id)
            except Exception as exc:
                if failure is None:
                    failure = exc
            with self._lock:
                if self._active.get(runtime.case_id) is runtime:
                    self._active.pop(runtime.case_id, None)
                if failure is not None:
                    self._last_error[runtime.case_id] = str(failure)

    def _publish_audio_level(self, runtime: _CaptureRuntime, pcm: bytes, *, now: float) -> None:
        sample_count = len(pcm) // 2
        if sample_count == 0:
            return
        runtime.audio_level_sample_count += sample_count
        if (
            runtime.last_audio_level_published_at is not None
            and now - runtime.last_audio_level_published_at < _AUDIO_LEVEL_INTERVAL_SECONDS
        ):
            return

        samples = [sample[0] for sample in struct.iter_unpack("<h", pcm[: sample_count * 2])]
        peak = max(abs(sample) for sample in samples)
        rms = math.sqrt(sum(sample * sample for sample in samples) / sample_count)
        runtime.last_audio_level_published_at = now
        self.publish_event(
            runtime.interrogation_session_id,
            "AUDIO_LEVEL",
            {
                "caseId": runtime.case_id,
                "captureSessionId": runtime.capture_session_id,
                "sampleCount": runtime.audio_level_sample_count,
                "sampleRate": runtime.sample_rate,
                "rms": rms,
                "peak": peak,
            },
        )

    def _start_local_inference(self, runtime: _CaptureRuntime) -> None:
        runtime.local_inference_done.clear()
        thread = threading.Thread(
            target=self._local_inference_loop,
            args=(runtime,),
            daemon=True,
            name=f"asr-inference-{runtime.capture_session_id[:8]}",
        )
        runtime.local_inference_thread = thread
        thread.start()

    def _local_inference_loop(self, runtime: _CaptureRuntime) -> None:
        opened = False
        try:
            self.ai_supervisor.open_speech_session(
                runtime.speech_session_id,
                sample_rate=self.sample_rate,
                speaker_backend="eres2net_large",
            )
            opened = True
            while True:
                pcm = runtime.local_inference_queue.get()
                try:
                    if pcm is None:
                        break
                    try:
                        events = self.ai_supervisor.push_speech_pcm(runtime.speech_session_id, pcm)
                        self._consume_events(runtime, events)
                    except Exception as exc:
                        runtime.inference_error_sink(exc)
                finally:
                    runtime.local_inference_queue.task_done()
        except Exception as exc:
            runtime.inference_error_sink(exc)
        finally:
            if opened:
                try:
                    runtime.consume_events(self.ai_supervisor.finalize_speech_session(runtime.speech_session_id))
                except Exception as exc:
                    runtime.inference_error_sink(exc)
                try:
                    self.ai_supervisor.close_speech_session(runtime.speech_session_id)
                except Exception as exc:
                    runtime.inference_error_sink(exc)
            try:
                runtime.capture_finished_sink()
            finally:
                runtime.local_inference_done.set()

    def _record_runtime_error(self, runtime: _CaptureRuntime, exc: Exception) -> None:
        with self._lock:
            self._last_error[runtime.case_id] = str(exc)

    def _capture_finished(self, runtime: _CaptureRuntime) -> None:
        if self.capture_finished_sink is not None:
            self.capture_finished_sink(runtime.case_id, runtime.interrogation_session_id)

    def _preparation_loop(self, runtime: _PreparationRuntime) -> None:
        failure: Exception | None = None
        try:
            while not runtime.stop_event.is_set():
                pcm = self.device_manager.read_audio_frames(timeout=self.read_timeout)
                if not pcm:
                    continue
                events = self.ai_supervisor.push_speech_pcm(runtime.speech_session_id, bytes(pcm))
                self._consume_preparation_events(runtime, events)
        except Exception as exc:
            failure = exc
        finally:
            try:
                final_events = self.ai_supervisor.finalize_speech_session(runtime.speech_session_id)
                self._consume_preparation_events(runtime, final_events)
            except Exception as exc:
                if failure is None:
                    failure = exc
            try:
                self.ai_supervisor.close_speech_session(runtime.speech_session_id)
            except Exception as exc:
                if failure is None:
                    failure = exc
            try:
                self.device_manager.stop_record()
            except Exception as exc:
                if failure is None:
                    failure = exc

            runtime.last_error = None if failure is None else str(failure)
            result = self._preparation_status(runtime, active=False)
            with self._lock:
                if self._preparation.get(runtime.case_id) is runtime:
                    self._preparation.pop(runtime.case_id, None)
                self._preparation_results[runtime.case_id] = result

    def _consume_preparation_events(
        self,
        runtime: _PreparationRuntime,
        events: list[SpeechEvent] | None,
    ) -> None:
        if not events:
            return
        for event in events:
            if event.type is not SpeechEventType.ASR_FINAL:
                continue
            text = str(event.text or "").strip()
            if not text:
                continue
            if event.start_ms is not None and event.end_ms is not None:
                key = (int(event.start_ms), int(event.end_ms))
                if key in runtime.seen_utterances:
                    continue
                runtime.seen_utterances.add(key)
            runtime.text_parts.append(text)

    def _consume_events(self, runtime: _CaptureRuntime, events: list[SpeechEvent] | None) -> list[str]:
        if not events:
            return []
        asr_by_range: dict[tuple[int, int], SpeechEvent] = {}
        speaker_by_range: dict[tuple[int, int], SpeechEvent] = {}
        compare_by_range: dict[tuple[int, int], SpeechEvent] = {}
        asr_only_events: list[SpeechEvent] = []
        partial_by_start: dict[int, SpeechEvent] = {}
        for event in events:
            if event.type is SpeechEventType.ASR_PARTIAL:
                text = str(event.text or "").strip()
                if text and event.start_ms is not None and event.end_ms is not None:
                    start_ms = int(event.start_ms)
                    previous = partial_by_start.get(start_ms)
                    if previous is None or int(previous.end_ms or 0) <= int(event.end_ms):
                        partial_by_start[start_ms] = event
                continue
            if event.type is SpeechEventType.ASR_PREVIEW_STATUS:
                details = event.details or {}
                runtime.live_transcript_status = (
                    "AVAILABLE" if str(details.get("status") or "").upper() == "AVAILABLE" else "ERROR"
                )
                self.publish_event(
                    runtime.interrogation_session_id,
                    "ASR_PREVIEW_STATUS",
                    {
                        "caseId": runtime.case_id,
                        "captureSessionId": runtime.capture_session_id,
                        "status": runtime.live_transcript_status,
                        "code": self._optional_text(details.get("code")),
                    },
                )
                continue
            if event.start_ms is None or event.end_ms is None:
                continue
            key = (int(event.start_ms), int(event.end_ms))
            if event.type is SpeechEventType.ASR_FINAL:
                if (event.details or {}).get("stage_one_asr_only"):
                    asr_only_events.append(event)
                else:
                    asr_by_range[key] = event
            elif event.type is SpeechEventType.SPEAKER_RESULT:
                speaker_by_range[key] = event
            elif event.type is SpeechEventType.SPEAKER_COMPARE_RESULT:
                compare_by_range[key] = event

        fragment_ids: list[str] = []
        for asr_event in asr_only_events:
            if not str(asr_event.text or "").strip():
                continue
            fragment_ids.append(self._persist_asr_only_fragment(runtime, asr_event))
            if asr_event.start_ms is not None and asr_event.end_ms is not None:
                runtime.seen_utterances.add((int(asr_event.start_ms), int(asr_event.end_ms)))

        for key, asr_event in asr_by_range.items():
            if key in runtime.seen_utterances:
                continue
            self._persist_fragment(
                runtime,
                key,
                asr_event,
                speaker_by_range.get(key),
                compare_by_range.get(key),
            )
            runtime.seen_utterances.add(key)

        finalized_starts = {start_ms for start_ms, _end_ms in runtime.seen_utterances}
        for start_ms, event in partial_by_start.items():
            if start_ms in finalized_starts:
                continue
            self.publish_event(
                runtime.interrogation_session_id,
                "ASR_PARTIAL",
                {
                    "caseId": runtime.case_id,
                    "captureSessionId": runtime.capture_session_id,
                    "text": str(event.text or "").strip(),
                    "startedAtMs": start_ms,
                    "endedAtMs": event.end_ms,
                },
            )
        return fragment_ids

    def _live_transcript_status(self) -> str:
        try:
            capabilities = self.ai_supervisor.capabilities()
        except Exception:
            logger.exception("failed to read streaming ASR readiness")
            return "ERROR"
        capability = capabilities.get("asrStreaming") if isinstance(capabilities, dict) else None
        if not isinstance(capability, dict):
            return "UNKNOWN"
        state = str(capability.get("state") or "").upper()
        if state in {"AVAILABLE", "READY"}:
            return "AVAILABLE"
        if state in {"MODEL_NOT_INSTALLED", "NOT_INSTALLED"}:
            return "MODEL_NOT_INSTALLED"
        if state in {"", "UNKNOWN", "NOT_CONFIGURED"}:
            return "UNKNOWN"
        return "ERROR"

    def _persist_asr_only_fragment(self, runtime: _CaptureRuntime, asr_event: SpeechEvent) -> str:
        start_ms = int(asr_event.start_ms or 0)
        end_ms = int(asr_event.end_ms or start_ms)
        details = asr_event.details or {}
        start_sample = int(
            details.get("asr_start_sample", round(start_ms * runtime.sample_rate / 1000))
        )
        end_sample = int(
            details.get("asr_end_sample", round(end_ms * runtime.sample_rate / 1000))
        )
        if start_sample < 0 or end_sample <= start_sample:
            raise ValueError("ASR final sample range is invalid")
        model_version = self._optional_text(details.get("model_version"))
        model_id = str(asr_event.model_id or "paraformer")
        idempotency_key = asr_repo.asr_final_idempotency_key(
            runtime.capture_session_id,
            start_sample,
            end_sample,
            model_version,
        )
        with self.session_factory() as db:
            fragment, created = asr_repo.create_or_update_asr_only_fragment(
                db,
                capture_session_id=runtime.capture_session_id,
                case_id=runtime.case_id,
                started_at_ms=start_ms,
                ended_at_ms=end_ms,
                raw_text=str(asr_event.text or "").strip(),
                asr_confidence=asr_event.confidence,
                model_id=model_id,
                model_version=model_version,
                idempotency_key=idempotency_key,
            )
            if created:
                capture = db.get(ASRCaptureSession, runtime.capture_session_id)
                if capture is not None:
                    capture.voiced_ms = max(0, int(capture.voiced_ms or 0)) + int(
                        round((end_sample - start_sample) * 1000 / runtime.sample_rate)
                    )
            db.commit()
            fragment_id = fragment.id
            payload = self._fragment_payload(fragment)
            payload["captureStartedAt"] = runtime.capture_started_at

        runtime.ordinal = max(runtime.ordinal, int(fragment.ordinal) + 1)
        payload["thresholdSource"] = "PENDING_ANALYSIS"
        payload["calibrationId"] = runtime.calibration_id
        payload["calibrationStatus"] = runtime.calibration_status
        payload.update(self.speaker_mode_capability(runtime))
        self.publish_event(runtime.interrogation_session_id, "ASR_FRAGMENT", payload)
        if self._live_speech_coordinator is not None:
            self._live_speech_coordinator.schedule_speaker_jobs(runtime.capture_session_id)
        if payload["speaker"] == "UNKNOWN":
            return fragment_id
        if self.fragment_sink is not None:
            try:
                self.fragment_sink(runtime.case_id, fragment_id)
            except Exception:
                logger.exception("qa fragment sink failed for fragment %s", fragment_id)
        else:
            try:
                with self.session_factory() as projection_db:
                    InterrogationProjectionService(projection_db).process_fragment(
                        runtime.case_id,
                        fragment_id,
                    )
                    projection_db.commit()
            except Exception:
                logger.exception("formal interrogation projection failed for fragment %s", fragment_id)
        return fragment_id

    def _persist_fragment(
        self,
        runtime: _CaptureRuntime,
        bounds: tuple[int, int],
        asr_event: SpeechEvent,
        speaker_event: SpeechEvent | None,
        compare_event: SpeechEvent | None = None,
    ) -> None:
        start_ms, end_ms = bounds
        with self.session_factory() as db:
            case = case_repo.get(db, runtime.case_id)
            candidates, enabled_roles = self._speaker_candidates(
                db,
                case=case,
                interrogation_session_id=runtime.interrogation_session_id,
                speaker_event=speaker_event,
                backend_key=(runtime.authoritative_speaker_backend or self.authoritative_speaker_backend),
            )

            threshold = float(runtime.speaker_threshold)
            threshold_source = str(runtime.threshold_source)
            persisted_margin = runtime.speaker_margin

            # A calibrated margin is needed only for comparing multiple enrolled
            # references. Without it, formal interrogation remains available but
            # deliberately degrades to suspect-only verification. The predicate is the
            # single authoritative rule in app.services.speaker_mode so the readiness
            # payload and this runtime decision cannot disagree.
            declared_mode = self.declared_mode_for_roles(enabled_roles)
            runtime.declared_recognition_mode = declared_mode

            decision_roles, decision_candidates = self._narrow_decision(
                declared_mode=declared_mode,
                margin=persisted_margin,
                threshold=runtime.speaker_threshold,
                enabled_roles=enabled_roles,
                candidates=candidates,
            )

            decision = decide_speaker(
                candidates=decision_candidates,
                enabled_roles=decision_roles,
                threshold=threshold,
                margin=0.0 if persisted_margin is None else persisted_margin,
                usable_duration_ms=max(0, end_ms - start_ms),
                overlap=bool(
                    (asr_event.details or {}).get("overlap")
                    or (speaker_event is not None and (speaker_event.details or {}).get("overlap"))
                ),
            )
            fragment = asr_repo.create_fragment(
                db,
                capture_session_id=runtime.capture_session_id,
                case_id=runtime.case_id,
                ordinal=runtime.ordinal,
                started_at_ms=start_ms,
                ended_at_ms=end_ms,
                raw_text=str(asr_event.text or ""),
                asr_confidence=asr_event.confidence,
                speaker=decision.role.value,
                speaker_id=decision.speaker_id,
                speaker_name=decision.speaker_name,
                speaker_score=decision.score,
                second_best_score=decision.second_best_score,
                speaker_threshold=decision.threshold,
                speaker_margin=persisted_margin,
                speaker_source=decision.source.value,
                voiceprint_verified=decision.voiceprint_verified,
                low_confidence=decision.low_confidence,
                model_id=str(asr_event.model_id or "paraformer"),
                model_version=self._optional_text((asr_event.details or {}).get("model_version")),
                speaker_threshold_source=threshold_source,
                speaker_model_id=(None if speaker_event is None else self._optional_text(speaker_event.model_id)),
                speaker_model_version=(
                    None
                    if speaker_event is None
                    else self._optional_text((speaker_event.details or {}).get("model_version"))
                ),
                speaker_model_fingerprint=(
                    runtime.speaker_model_fingerprint
                    if speaker_event is None
                    else self._optional_text((speaker_event.details or {}).get("model_fingerprint"))
                    or runtime.speaker_model_fingerprint
                ),
                microphone_fingerprint=runtime.microphone_fingerprint,
            )
            self._audit_speaker_decision(
                db,
                case_id=runtime.case_id,
                fragment_id=fragment.id,
                decision=decision,
                threshold_source=threshold_source,
                margin=persisted_margin,
                usable_duration_ms=max(0, end_ms - start_ms),
                decision_roles=decision_roles,
                declared_mode=declared_mode,
                asr_event=asr_event,
            )
            self._persist_compare_evidence(
                db,
                runtime=runtime,
                fragment_id=fragment.id,
                bounds=bounds,
                asr_event=asr_event,
                authoritative_event=speaker_event,
                secondary_event=compare_event,
                authoritative_decision=decision,
                authoritative_candidates=candidates,
            )
            db.commit()
            fragment_id = fragment.id
            payload = self._fragment_payload(fragment)
            payload["captureStartedAt"] = runtime.capture_started_at
            payload["thresholdSource"] = threshold_source
            payload["calibrationId"] = runtime.calibration_id
            payload["calibrationStatus"] = runtime.calibration_status
            # Task 17B-1: every published fragment carries the mode it was decided in,
            # so a narrowed operating point is visible to the client and to audit.
            payload.update(self.speaker_mode_capability(runtime))

        runtime.ordinal += 1
        self.publish_event(runtime.interrogation_session_id, "ASR_FRAGMENT", payload)
        if payload["speaker"] == "UNKNOWN":
            return fragment_id
        if self.fragment_sink is not None:
            try:
                self.fragment_sink(runtime.case_id, fragment_id)
            except Exception:
                # The ASR row is already committed. Qwen mode recovery scans
                # persisted unassigned fragments, so never fall back to legacy
                # projection or block the capture thread here.
                logger.exception("qa fragment sink failed for fragment %s", fragment_id)
            return
        try:
            with self.session_factory() as projection_db:
                InterrogationProjectionService(projection_db).process_fragment(runtime.case_id, fragment_id)
                projection_db.commit()
        except Exception:
            logger.exception("formal interrogation projection failed for fragment %s", fragment_id)

    def _persist_compare_evidence(
        self,
        db,
        *,
        runtime: _CaptureRuntime,
        fragment_id: str,
        bounds: tuple[int, int],
        asr_event: SpeechEvent,
        authoritative_event: SpeechEvent | None,
        secondary_event: SpeechEvent | None,
        authoritative_decision,
        authoritative_candidates: list[dict[str, Any]],
    ) -> None:
        coordinator = self.compare_coordinator
        if coordinator is None:
            return

        authoritative_key = runtime.authoritative_speaker_backend or coordinator.authoritative_backend
        secondary_key = runtime.secondary_speaker_backend or coordinator.secondary_backend
        primary_details = authoritative_event.details if authoritative_event is not None else (asr_event.details or {})
        primary_error = None
        if authoritative_event is None and bool((asr_event.details or {}).get("speaker_unavailable")):
            primary_error = str((asr_event.details or {}).get("speaker_error_code") or "BACKEND_UNAVAILABLE")

        primary = SpeakerBackendDiagnostic(
            backend_key=authoritative_key,
            role=authoritative_decision.role.value,
            speaker_source=authoritative_decision.source.value,
            voiceprint_verified=authoritative_decision.voiceprint_verified,
            score=authoritative_decision.score,
            second_best_score=authoritative_decision.second_best_score,
            threshold=authoritative_decision.threshold,
            margin=runtime.speaker_margin,
            calibration_id=runtime.calibration_id,
            calibration_status=runtime.calibration_status,
            model_id=None if authoritative_event is None else self._optional_text(authoritative_event.model_id),
            model_version=self._optional_text(primary_details.get("model_version")),
            model_fingerprint=(
                self._optional_text(primary_details.get("model_fingerprint"))
                or runtime.speaker_model_fingerprint
            ),
            latency_ms=self._optional_float(primary_details.get("latency_ms")),
            error_code=primary_error,
        )

        secondary_candidates: list[dict[str, Any]] = []
        secondary_calibration = runtime.secondary_calibration
        secondary_error = None
        if secondary_event is None:
            secondary_error = "BACKEND_UNAVAILABLE"
        else:
            secondary_details = secondary_event.details or {}
            if bool(secondary_details.get("speaker_unavailable")):
                secondary_error = str(secondary_details.get("speaker_error_code") or "BACKEND_UNAVAILABLE")
        if voiceprint_repo.get_suspect(db, runtime.case_id, model_key=secondary_key) is None:
            secondary_error = secondary_error or "SUSPECT_VOICEPRINT_BACKEND_REQUIRED"
        if secondary_calibration is None:
            secondary_error = secondary_error or "CALIBRATION_UNAVAILABLE"

        secondary_decision = None
        if secondary_error is None and secondary_event is not None and secondary_calibration is not None:
            case = case_repo.get(db, runtime.case_id)
            secondary_candidates, secondary_roles = self._speaker_candidates(
                db,
                case=case,
                interrogation_session_id=runtime.interrogation_session_id,
                speaker_event=secondary_event,
                backend_key=secondary_key,
            )
            secondary_decision = self._decide_with_operating_point(
                candidates=secondary_candidates,
                enabled_roles=secondary_roles,
                threshold=secondary_calibration.threshold,
                margin=secondary_calibration.margin,
                usable_duration_ms=max(0, bounds[1] - bounds[0]),
                overlap=bool(
                    (asr_event.details or {}).get("overlap")
                    or (secondary_event.details or {}).get("overlap")
                ),
            )

        if secondary_decision is None:
            threshold = (
                float(secondary_calibration.threshold)
                if secondary_calibration is not None
                else float(runtime.speaker_threshold)
            )
            margin = (
                secondary_calibration.margin
                if secondary_calibration is not None
                else None
            )
            secondary_decision = decide_speaker(
                candidates=[],
                enabled_roles={SpeakerRole.SUSPECT},
                threshold=threshold,
                margin=0.0 if margin is None else float(margin),
                usable_duration_ms=max(0, bounds[1] - bounds[0]),
                overlap=False,
            )

        secondary_details = secondary_event.details if secondary_event is not None else {}
        secondary = SpeakerBackendDiagnostic(
            backend_key=secondary_key,
            role=secondary_decision.role.value,
            speaker_source=secondary_decision.source.value,
            voiceprint_verified=secondary_decision.voiceprint_verified,
            score=secondary_decision.score,
            second_best_score=secondary_decision.second_best_score,
            threshold=secondary_decision.threshold,
            margin=(None if secondary_calibration is None else secondary_calibration.margin),
            calibration_id=(None if secondary_calibration is None else secondary_calibration.calibration_id),
            calibration_status=(None if secondary_calibration is None else secondary_calibration.status),
            model_id=None if secondary_event is None else self._optional_text(secondary_event.model_id),
            model_version=self._optional_text(secondary_details.get("model_version")),
            model_fingerprint=(
                self._optional_text(secondary_details.get("model_fingerprint"))
                or (None if secondary_calibration is None else secondary_calibration.speaker_model_fingerprint)
            ),
            latency_ms=self._optional_float(secondary_details.get("latency_ms")),
            error_code=secondary_error,
        )

        diagnostics = {primary.backend_key: primary, secondary.backend_key: secondary}
        evidence = coordinator.build_evidence(
            xvector=diagnostics["xvector"],
            eres2net_large=diagnostics["eres2net_large"],
        )
        candidate_by_backend = {
            authoritative_key: authoritative_candidates,
            secondary_key: secondary_candidates,
        }
        for item in evidence["results"]:
            key = str(item["backendKey"])
            compare_evidence_repo.create_evidence(
                db,
                fragment_id=fragment_id,
                capture_session_id=runtime.capture_session_id,
                case_id=runtime.case_id,
                backend_key=key,
                authoritative=bool(item["authoritative"]),
                available=bool(item["available"]),
                role=str(item["role"]),
                speaker_source=str(item["speakerSource"]),
                voiceprint_verified=bool(item["voiceprintVerified"]),
                score=item["score"],
                second_best_score=item["secondBestScore"],
                threshold=item["threshold"],
                margin=item["margin"],
                calibration_id=item["calibrationId"],
                calibration_status=item["calibrationStatus"],
                model_id=item["modelId"],
                model_version=item["modelVersion"],
                model_fingerprint=item["modelFingerprint"],
                latency_ms=item["latencyMs"],
                error_code=item["errorCode"],
                candidate_scores=[
                    {
                        "role": (
                            candidate["role"].value
                            if isinstance(candidate.get("role"), SpeakerRole)
                            else str(candidate.get("role"))
                        ),
                        "score": candidate.get("score"),
                    }
                    for candidate in candidate_by_backend.get(key, [])
                ],
            )

    @staticmethod
    def _decide_with_operating_point(
        *,
        candidates: list[dict[str, Any]],
        enabled_roles: set[SpeakerRole],
        threshold: float,
        margin: float | None,
        usable_duration_ms: int,
        overlap: bool,
        declared_mode: str | None = None,
    ):
        # Same single authoritative rule as the primary decision path: without a
        # calibrated margin only the suspect reference may be attributed.
        decision_roles, decision_candidates = AsrCaptureService._narrow_decision(
            declared_mode=(
                declared_mode
                if declared_mode is not None
                else AsrCaptureService.declared_mode_for_roles(enabled_roles)
            ),
            margin=margin,
            threshold=threshold,
            enabled_roles=enabled_roles,
            candidates=candidates,
        )
        return decide_speaker(
            candidates=decision_candidates,
            enabled_roles=decision_roles,
            threshold=float(threshold),
            margin=0.0 if margin is None else float(margin),
            usable_duration_ms=int(usable_duration_ms),
            overlap=bool(overlap),
        )

    @staticmethod
    def declared_mode_for_roles(enabled_roles: Iterable[SpeakerRole]) -> str:
        """The recognition mode a bound role set declares to the operator.

        Contract: ``enabled_roles`` are the references the runtime actually bound for
        this session, and it always contains :attr:`SpeakerRole.SUSPECT`
        (``_speaker_candidates`` raises unless the suspect reference exists). A set
        without it is a programming error, not a mode: the rule would declare
        ``SUSPECT_ONLY`` while ``decision_roles`` narrowed the decision set to the
        empty set. Values that are not :class:`SpeakerRole` members are ignored --
        they are not bindings, exactly as in ``narrow_decision_roles``.
        """

        roles = {role for role in enabled_roles if isinstance(role, SpeakerRole)}
        if SpeakerRole.SUSPECT not in roles:
            raise ValueError(
                "declared_mode_for_roles requires the bound suspect reference; "
                f"got {sorted(role.value for role in roles)}"
            )
        if SpeakerRole.RECORDER in roles and SpeakerRole.INTERROGATOR in roles:
            return FULL
        if SpeakerRole.INTERROGATOR in roles:
            return SUSPECT_PLUS_INTERROGATOR
        if SpeakerRole.RECORDER in roles:
            return SUSPECT_PLUS_RECORDER
        return SUSPECT_ONLY

    @staticmethod
    def _narrow_decision(
        *,
        declared_mode: str,
        margin: float | None,
        threshold: float | None,
        enabled_roles: set[SpeakerRole],
        candidates: list[dict[str, Any]],
    ) -> tuple[set[SpeakerRole], list[dict[str, Any]]]:
        """Apply the one authoritative mode rule to this fragment's references.

        The runtime behaviour is unchanged: without a calibrated margin only the
        suspect reference is compared. The predicate now comes from
        :mod:`app.services.speaker_mode`, so the UI declaration and the runtime
        enforcement cannot drift apart, and the dropped candidates are logged so the
        degradation is auditable instead of silent.
        """

        narrowed_roles, kept_candidates = narrow_decision_roles(
            declared_mode=declared_mode,
            margin=margin,
            threshold=threshold,
            enabled_roles=enabled_roles,
            candidates=candidates,
        )
        if len(kept_candidates) < len(candidates):
            detail = mode_decision_detail(
                declared_mode=declared_mode, margin=margin, threshold=threshold
            )
            logger.info(
                "speaker decision narrowed to %s (declared %s, %s): %d of %d candidate(s) kept",
                sorted(role.value for role in narrowed_roles),
                declared_mode,
                detail[MODE_REASON_KEY],
                len(kept_candidates),
                len(candidates),
            )
        return narrowed_roles, kept_candidates

    def speaker_mode_capability(self, runtime: _CaptureRuntime) -> dict[str, Any]:
        """Declared/effective recognition mode of a live capture, from the shared rule."""
        return mode_decision_detail(
            declared_mode=runtime.declared_recognition_mode,
            margin=runtime.speaker_margin,
            threshold=runtime.speaker_threshold,
        )

    @staticmethod
    def _audit_speaker_decision(
        db,
        *,
        case_id: str,
        fragment_id: str,
        decision,
        threshold_source: str,
        margin: float | None,
        usable_duration_ms: int,
        decision_roles: set[SpeakerRole],
        declared_mode: str,
        asr_event: SpeechEvent,
    ) -> None:
        if decision.role is SpeakerRole.OFFICER_FALLBACK:
            action = "ASR_SPEAKER_FALLBACK"
        elif decision.low_confidence:
            action = "ASR_SPEAKER_LOW_CONFIDENCE"
        else:
            return

        detail: dict[str, Any] = {
            "score": decision.score,
            "second_best_score": decision.second_best_score,
            "threshold": decision.threshold,
            "threshold_source": threshold_source,
            "margin": margin,
            "usable_duration_ms": int(usable_duration_ms),
            "decision_roles": sorted(role.value for role in decision_roles),
        }
        # Task 17B-1: the audit row names the mode the decision was actually made in,
        # so a narrowed operating point can never be mistaken for a full one.
        detail.update(
            mode_decision_detail(
                declared_mode=declared_mode,
                margin=margin,
                # The threshold handed to decide_speaker is never null; the missing
                # threshold channel is reported through the calibration source.
                threshold=decision.threshold,
            )
        )
        event_details = asr_event.details or {}
        if event_details.get("speaker_unavailable"):
            detail["speaker_unavailable"] = True
            error_code = event_details.get("speaker_error_code")
            if error_code:
                detail["speaker_error_code"] = str(error_code)

        audit_repo.add(
            db,
            case_id=case_id,
            action=action,
            target_type="ASR_FRAGMENT",
            target_id=fragment_id,
            after={
                "speaker": decision.role.value,
                "speaker_source": decision.source.value,
                "voiceprint_verified": decision.voiceprint_verified,
                "low_confidence": decision.low_confidence,
                "threshold_source": threshold_source,
            },
            detail=detail,
        )

    def _speaker_candidates(
        self,
        db,
        *,
        case,
        interrogation_session_id: str,
        speaker_event: SpeechEvent | None,
        backend_key: str | None = None,
    ) -> tuple[list[dict[str, Any]], set[SpeakerRole]]:
        embedding = self._normalize_vector(speaker_event.embedding if speaker_event is not None else None)
        selected_backend = str(backend_key or self.authoritative_speaker_backend).strip().lower()
        suspect = voiceprint_repo.get_suspect(
            db, case.id, model_key=selected_backend
        )
        if suspect is None:
            raise DomainError(
                "SUSPECT_VOICEPRINT_BACKEND_REQUIRED",
                f"{selected_backend} 嫌疑人声纹不可用",
                409,
                data={"speaker_backend": selected_backend},
            )

        enabled: set[SpeakerRole] = {SpeakerRole.SUSPECT}
        references: list[tuple[SpeakerRole, Any, str | None, str | None]] = [
            (SpeakerRole.SUSPECT, suspect, suspect.id, case.suspect_name),
        ]
        assignment = db.scalar(
            select(SessionVoiceAssignment).where(
                SessionVoiceAssignment.session_id == interrogation_session_id
            )
        )
        if assignment is not None:
            if selected_backend == self.authoritative_speaker_backend:
                self._append_officer_reference(
                    db,
                    references,
                    enabled,
                    SpeakerRole.INTERROGATOR,
                    assignment.interrogator_voiceprint_id,
                )
                self._append_officer_reference(
                    db,
                    references,
                    enabled,
                    SpeakerRole.RECORDER,
                    assignment.recorder_voiceprint_id,
                )
            else:
                self._append_officer_model_reference(
                    db,
                    references,
                    enabled,
                    SpeakerRole.INTERROGATOR,
                    assignment.interrogator_officer_id,
                    selected_backend,
                )
                self._append_officer_model_reference(
                    db,
                    references,
                    enabled,
                    SpeakerRole.RECORDER,
                    assignment.recorder_officer_id,
                    selected_backend,
                )

        candidates: list[dict[str, Any]] = []
        if embedding is None:
            return candidates, enabled
        for role, row, speaker_id, speaker_name in references:
            reference = self._decode_embedding(row.embedding, row.embedding_dim)
            score = self._cosine(embedding, reference)
            if score is None:
                continue
            candidates.append(
                {
                    "role": role,
                    "score": score,
                    "speaker_id": speaker_id,
                    "speaker_name": speaker_name,
                }
            )
        return candidates, enabled

    @staticmethod
    def _append_officer_model_reference(
        db,
        references: list[tuple[SpeakerRole, Any, str | None, str | None]],
        enabled: set[SpeakerRole],
        role: SpeakerRole,
        officer_id: str | None,
        model_key: str,
    ) -> None:
        if not officer_id:
            return
        officer = voiceprint_repo.get_officer(
            db,
            str(officer_id),
            model_key=model_key,
        )
        if officer is None:
            return
        enabled.add(role)
        references.append((role, officer, officer.officer_id, officer.officer_name))

    @staticmethod
    def _append_officer_reference(
        db,
        references: list[tuple[SpeakerRole, Any, str | None, str | None]],
        enabled: set[SpeakerRole],
        role: SpeakerRole,
        voiceprint_id: str | None,
    ) -> None:
        if not voiceprint_id:
            return
        officer = db.get(OfficerVoiceprint, voiceprint_id)
        if officer is None or not officer.active or officer.revoked_at is not None:
            return
        enabled.add(role)
        references.append((role, officer, officer.officer_id, officer.officer_name))

    def _bound_roles(self, db, interrogation_session_id: str) -> set[SpeakerRole]:
        """Roles the session's voice assignment enables, resolved against live profiles.

        Used once per capture start, inside the session ``start()`` already holds, to
        seed ``_CaptureRuntime.declared_recognition_mode`` so ``status()`` can report
        the declaration before the first fragment binds its own roles.
        """
        roles: set[SpeakerRole] = {SpeakerRole.SUSPECT}
        assignment = db.scalar(
            select(SessionVoiceAssignment).where(
                SessionVoiceAssignment.session_id == interrogation_session_id
            )
        )
        if assignment is None:
            return roles
        for officer_id, role in (
            (assignment.interrogator_officer_id, SpeakerRole.INTERROGATOR),
            (assignment.recorder_officer_id, SpeakerRole.RECORDER),
        ):
            if not officer_id:
                continue
            officer = voiceprint_repo.get_officer(
                db, str(officer_id), model_key=self.authoritative_speaker_backend
            )
            if officer is not None:
                roles.add(role)
        return roles

    def _resolve_calibration(self, db) -> ResolvedSpeakerCalibration:
        if self.calibration_resolver is not None:
            return self.calibration_resolver(db)
        configured_threshold = getattr(self.ai_supervisor, "speaker_accept_threshold", None)
        threshold = MODEL_BASELINE_THRESHOLD if configured_threshold is None else float(configured_threshold)
        source = str(
            getattr(
                self.ai_supervisor,
                "speaker_threshold_source",
                "MODEL_BASELINE" if configured_threshold is None else "DEVICE_CALIBRATED",
            )
        )
        margin = getattr(self.ai_supervisor, "speaker_margin", None)
        return ResolvedSpeakerCalibration(
            calibration_id=None,
            threshold=threshold,
            margin=None if margin is None else float(margin),
            source=source,
            status="NOT_CALIBRATED",
            speaker_model_fingerprint=None,
            microphone_fingerprint=None,
            speaker_backend_key=self.authoritative_speaker_backend,
        )

    def _unavailable_calibration(self) -> ResolvedSpeakerCalibration:
        return ResolvedSpeakerCalibration(
            calibration_id=None,
            threshold=MODEL_BASELINE_THRESHOLD,
            margin=None,
            source="UNAVAILABLE",
            status="UNAVAILABLE",
            speaker_model_fingerprint=None,
            microphone_fingerprint=None,
            speaker_backend_key=self.authoritative_speaker_backend,
        )

    def build_recovery_runtime(self, capture: ASRCaptureSession) -> _CaptureRuntime | None:
        if capture.interrogation_session_id is None:
            return None
        with self.session_factory() as db:
            snapshot = calibration_repo.get_session_snapshot(db, capture.id)
            roles = self._bound_roles(db, capture.interrogation_session_id)
            ordinal = int(
                db.scalar(
                    select(func.count(ASRFragment.id)).where(
                        ASRFragment.capture_session_id == capture.id
                    )
                )
                or 0
            )
        calibration = self._unavailable_calibration() if snapshot is None else ResolvedSpeakerCalibration(
            calibration_id=snapshot.calibration_id,
            threshold=snapshot.threshold,
            margin=snapshot.margin,
            source=snapshot.threshold_source,
            status=snapshot.calibration_status,
            speaker_model_fingerprint=snapshot.speaker_model_fingerprint,
            microphone_fingerprint=snapshot.microphone_fingerprint,
            speaker_backend_key=snapshot.speaker_backend_key,
        )
        runtime = _CaptureRuntime(
            case_id=capture.case_id,
            interrogation_session_id=capture.interrogation_session_id,
            capture_session_id=capture.id,
            speech_session_id=capture.id,
            speaker_threshold=float(calibration.threshold),
            speaker_margin=calibration.margin,
            threshold_source=calibration.source,
            calibration_id=calibration.calibration_id,
            calibration_status=calibration.status,
            speaker_model_fingerprint=calibration.speaker_model_fingerprint,
            microphone_fingerprint=calibration.microphone_fingerprint,
            authoritative_speaker_backend=self.authoritative_speaker_backend,
            declared_recognition_mode=self.declared_mode_for_roles(roles),
            sample_rate=self.sample_rate,
            capture_started_at=(
                iso_utc(capture.started_at)
            ),
            live_transcript_status=self._live_transcript_status(),
            speaker_backend=self.speaker_model_key,
            durable_sample_cursor=int(capture.audio_sample_count or 0),
            ordinal=ordinal,
        )
        runtime.consume_events = lambda events: self._consume_events(runtime, events)
        runtime.capture_finished_sink = lambda: self._capture_finished(runtime)
        runtime.capture_error_sink = lambda exc: self._record_runtime_error(runtime, exc)
        runtime.inference_error_sink = lambda exc: self._record_runtime_error(runtime, exc)
        return runtime

    def _resolve_secondary_calibration(self, db) -> ResolvedSpeakerCalibration:
        if self.secondary_speaker_backend is None:
            raise ValueError("secondary calibration requested outside compare mode")
        if self.secondary_calibration_resolver is not None:
            return self.secondary_calibration_resolver(db)
        configured_threshold = getattr(self.ai_supervisor, "speaker_accept_threshold", None)
        threshold = MODEL_BASELINE_THRESHOLD if configured_threshold is None else float(configured_threshold)
        margin = getattr(self.ai_supervisor, "speaker_margin", None)
        source = str(
            getattr(
                self.ai_supervisor,
                "speaker_threshold_source",
                "MODEL_BASELINE" if configured_threshold is None else "DEVICE_CALIBRATED",
            )
        )
        return ResolvedSpeakerCalibration(
            calibration_id=None,
            threshold=threshold,
            margin=None if margin is None else float(margin),
            source=source,
            status="NOT_CALIBRATED",
            speaker_model_fingerprint=None,
            microphone_fingerprint=None,
            speaker_backend_key=self.secondary_speaker_backend,
        )

    def _finish_capture_row(self, capture_session_id: str) -> None:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_session_id)
            if (
                capture is not None
                and capture.status != "STOPPED"
                and capture.recording_status != "INCOMPLETE"
                and capture.status != "FAILED"
            ):
                asr_repo.finish_capture_session(db, capture_session_id=capture_session_id)
                db.commit()

    def _safe_stop_audio(self) -> None:
        try:
            self.device_manager.stop_record()
        except Exception:
            pass

    def _safe_finalize_close(self, speech_session_id: str) -> None:
        try:
            self.ai_supervisor.finalize_speech_session(speech_session_id)
        except Exception:
            pass
        try:
            self.ai_supervisor.close_speech_session(speech_session_id)
        except Exception:
            pass

    def _any_capture_active_locked(self) -> bool:
        return any(
            runtime.thread is not None and runtime.thread.is_alive()
            for runtime in self._active.values()
        )

    def _any_preparation_active_locked(self) -> bool:
        return any(
            runtime.thread is not None and runtime.thread.is_alive()
            for runtime in self._preparation.values()
        )

    @staticmethod
    def _decode_embedding(blob: bytes, dimension: int) -> list[float] | None:
        try:
            dimension = int(dimension)
            raw = bytes(blob)
        except (TypeError, ValueError):
            return None
        if dimension <= 0 or len(raw) != dimension * _FLOAT32_BYTES:
            return None
        try:
            return [float(value) for value in struct.unpack(f"<{dimension}f", raw)]
        except struct.error:
            return None

    @staticmethod
    def _normalize_vector(value: Any) -> list[float] | None:
        if not isinstance(value, (list, tuple)) or not value:
            return None
        try:
            vector = [float(item) for item in value]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(item) for item in vector):
            return None
        norm = math.sqrt(sum(item * item for item in vector))
        if norm <= 0.0:
            return None
        return [item / norm for item in vector]

    @classmethod
    def _cosine(cls, left: list[float], right: list[float] | None) -> float | None:
        if right is None or len(left) != len(right):
            return None
        normalized_right = cls._normalize_vector(right)
        if normalized_right is None:
            return None
        score = sum(a * b for a, b in zip(left, normalized_right))
        return max(-1.0, min(1.0, float(score)))

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _fragment_payload(fragment) -> dict[str, Any]:
        return {
            "fragmentId": fragment.id,
            "captureSessionId": fragment.capture_session_id,
            "caseId": fragment.case_id,
            "ordinal": fragment.ordinal,
            "startedAtMs": fragment.started_at_ms,
            "endedAtMs": fragment.ended_at_ms,
            "rawText": fragment.raw_text,
            "editedText": fragment.edited_text,
            "asrConfidence": fragment.asr_confidence,
            "speaker": fragment.speaker,
            "speakerId": fragment.speaker_id,
            "speakerName": fragment.speaker_name,
            "speakerScore": fragment.speaker_score,
            "secondBestScore": fragment.second_best_score,
            "speakerThreshold": fragment.speaker_threshold,
            "speakerMargin": fragment.speaker_margin,
            "speakerSource": fragment.speaker_source,
            "voiceprintVerified": fragment.voiceprint_verified,
            "lowConfidence": fragment.low_confidence,
            "state": fragment.state,
            "modelId": fragment.model_id,
            "modelVersion": fragment.model_version,
        }

    def _runtime_status(
        self,
        runtime: _CaptureRuntime,
        *,
        active: bool,
        last_error: str | None,
        workflow_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "caseId": runtime.case_id,
            "active": active,
            "captureSessionId": runtime.capture_session_id,
            "interrogationSessionId": runtime.interrogation_session_id,
            "status": "CAPTURING" if active else "STOPPED",
            "sampleRate": self.sample_rate,
            "liveTranscriptStatus": runtime.live_transcript_status,
            "speakerModelKey": self.speaker_model_key,
            "speakerAuthoritativeBackend": runtime.authoritative_speaker_backend,
            "speakerSecondaryBackend": runtime.secondary_speaker_backend,
            "speakerThreshold": runtime.speaker_threshold,
            "thresholdSource": runtime.threshold_source,
            # The margin value itself, not just whether one exists: readiness must be
            # able to report the operating point this capture is really running on.
            "speakerMargin": runtime.speaker_margin,
            "speakerMarginConfigured": runtime.speaker_margin is not None,
            "calibrationId": runtime.calibration_id,
            "calibrationStatus": runtime.calibration_status,
            "lastError": last_error,
            # Task 17B-1: the mode the runtime really enforces, from the shared rule.
            **self.speaker_mode_capability(runtime),
            **(
                self._capture_workflow_status(runtime.capture_session_id)
                if workflow_status is None
                else workflow_status
            ),
        }

    def _capture_workflow_status(self, capture_id: str) -> dict[str, Any]:
        with self.session_factory() as db:
            capture = db.get(ASRCaptureSession, capture_id)
            if capture is None:
                return {}
            final_fragment_count = db.scalar(
                select(func.count(ASRFragment.id)).where(
                    ASRFragment.capture_session_id == capture_id,
                    ASRFragment.asr_idempotency_key.is_not(None),
                )
            )
            return {
                "startedAt": capture.started_at.isoformat() if capture.started_at is not None else None,
                "recordingStatus": capture.recording_status,
                "asrStatus": capture.asr_status,
                "speakerStatus": capture.speaker_status,
                "audioSampleCount": int(capture.audio_sample_count or 0),
                "asrCursorSample": int(capture.asr_cursor_sample or 0),
                "voicedMs": int(capture.voiced_ms or 0),
                "finalFragmentCount": int(final_fragment_count or 0),
            }

    def _preparation_status(self, runtime: _PreparationRuntime, *, active: bool) -> dict[str, Any]:
        return {
            "caseId": runtime.case_id,
            "active": active,
            "mode": "QUESTION_PREP",
            "captureSessionId": None,
            "interrogationSessionId": None,
            "status": "CAPTURING" if active else "STOPPED",
            "sampleRate": self.sample_rate,
            "text": "".join(runtime.text_parts),
            "lastError": runtime.last_error,
        }

    def _empty_preparation_status(self, case_id: str) -> dict[str, Any]:
        return {
            "caseId": case_id,
            "active": False,
            "mode": "QUESTION_PREP",
            "captureSessionId": None,
            "interrogationSessionId": None,
            "status": "IDLE",
            "sampleRate": self.sample_rate,
            "text": "",
            "lastError": None,
        }
