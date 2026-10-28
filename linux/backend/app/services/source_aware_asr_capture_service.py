from __future__ import annotations

import threading
from typing import Any, Callable

from app.domain.errors import DomainError
from app.request_audio_context import current_request_audio_source, normalize_audio_source
from app.services.asr_capture_service import AsrCaptureService


CalibrationResolverFactory = Callable[[str], Callable[[Any], Any] | None]
BackendCalibrationResolverFactory = Callable[[str, str], Callable[[Any], Any] | None]


class SourceAwareAsrCaptureService:
    """Route each ASR capture to ALSA or the LAN browser input.

    ``AsrCaptureService`` intentionally owns one concrete input for the complete
    lifetime of a capture thread. This coordinator keeps that invariant while
    selecting the concrete service per HTTP start request. Formal interrogation
    and question-preparation dictation therefore share one source policy without
    mutating a process-global device pointer while a worker thread is running.
    """

    def __init__(
        self,
        *,
        session_factory,
        device_manager: Any | None,
        browser_audio_input: Any | None,
        ai_supervisor: Any,
        publish_event,
        sample_rate: int = 16_000,
        read_timeout: float = 0.2,
        calibration_resolver_factory: CalibrationResolverFactory | None = None,
        backend_calibration_resolver_factory: BackendCalibrationResolverFactory | None = None,
        fragment_sink: Callable[[str, str], None] | None = None,
        capture_finished_sink: Callable[[str, str], None] | None = None,
        speaker_model_key: str = "eres2net_large",
        speaker_authoritative_backend: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.device_manager = device_manager
        self.browser_audio_input = browser_audio_input
        self.ai_supervisor = ai_supervisor
        self.publish_event = publish_event
        self.sample_rate = int(sample_rate)
        self.read_timeout = float(read_timeout)
        self.fragment_sink = fragment_sink
        self.capture_finished_sink = capture_finished_sink
        self.calibration_resolver_factory = calibration_resolver_factory
        self.backend_calibration_resolver_factory = backend_calibration_resolver_factory
        self.speaker_model_key = str(speaker_model_key or "eres2net_large").strip().lower()
        if self.speaker_model_key != "eres2net_large":
            raise ValueError("speaker_model_key must be eres2net_large")
        self.speaker_authoritative_backend = (
            None
            if speaker_authoritative_backend is None
            else str(speaker_authoritative_backend).strip().lower()
        )
        self._lock = threading.RLock()
        self._capture_sources: dict[str, str] = {}
        self._preparation_source: tuple[str, str] | None = None
        self._services: dict[str, AsrCaptureService] = {}
        self._live_speech_coordinator: Any | None = None

        self._inputs = {
            "ALSA": device_manager,
            "BROWSER": browser_audio_input,
        }
        for source, audio_input in self._inputs.items():
            if audio_input is None:
                continue
            self._services[source] = self._build_service(
                source,
                audio_input,
                self.speaker_model_key,
                self.speaker_authoritative_backend,
            )

        if not self._services:
            raise ValueError("at least one ASR audio input must be configured")
        self._default_service = self._services.get("ALSA") or next(iter(self._services.values()))

    def set_live_speech_coordinator(self, coordinator: Any) -> None:
        self._live_speech_coordinator = coordinator
        for service in self._services.values():
            service.set_live_speech_coordinator(coordinator)

    def build_recovery_runtime(self, capture):
        return self._default_service.build_recovery_runtime(capture)

    def build_browser_recovery_runtime(self, capture):
        browser_service = self._services.get("BROWSER")
        return None if browser_service is None else browser_service.build_recovery_runtime(capture)

    def resume_browser_capture(self, runtime) -> None:
        browser_service = self._services.get("BROWSER")
        if browser_service is None:
            raise DomainError("BROWSER_AUDIO_UNAVAILABLE", "浏览器音频输入未配置", 503)
        browser_service.resume_browser_capture(runtime)
        with self._lock:
            self._capture_sources[runtime.case_id] = "BROWSER"

    def ingest_browser_frame(
        self,
        case_id: str,
        capture_id: str,
        source_sequence: int,
        start_sample: int,
        pcm: bytes,
    ) -> dict[str, int]:
        case_id = str(case_id).strip()
        with self._lock:
            source = self._capture_sources.get(case_id)
        if source == "BROWSER":
            return self._services[source].ingest_browser_frame(
                case_id, capture_id, source_sequence, start_sample, pcm
            )
        if source is not None:
            raise RuntimeError("active capture does not use browser audio")
        if self._live_speech_coordinator is None:
            raise RuntimeError("durable browser audio ingress is unavailable")
        return self._live_speech_coordinator.replay_browser_frame(
            case_id=case_id,
            capture_id=capture_id,
            source_sequence=source_sequence,
            start_sample=start_sample,
            pcm=pcm,
        )

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

    def mark_browser_capture_incomplete(self, case_id: str, capture_id: str, reason: str) -> bool:
        case_id = str(case_id).strip()
        with self._lock:
            source = self._capture_sources.get(case_id)
        if source == "BROWSER":
            return self._services[source].mark_browser_capture_incomplete(case_id, capture_id, reason)
        if self._live_speech_coordinator is None:
            raise RuntimeError("durable browser audio ingress is unavailable")
        return self._live_speech_coordinator.mark_browser_capture_incomplete(case_id, capture_id, reason)

    def _build_service(
        self,
        source: str,
        audio_input: Any,
        mode: str,
        authoritative_backend: str | None,
    ) -> AsrCaptureService:
        resolver = (
            self.calibration_resolver_factory(source)
            if self.calibration_resolver_factory is not None
            else None
        )
        secondary_resolver = None
        primary_backend = "eres2net_large"
        if self.backend_calibration_resolver_factory is not None:
            resolver = self.backend_calibration_resolver_factory(source, primary_backend)
        return AsrCaptureService(
            session_factory=self.session_factory,
            device_manager=audio_input,
            ai_supervisor=self.ai_supervisor,
            publish_event=self.publish_event,
            sample_rate=self.sample_rate,
            read_timeout=self.read_timeout,
            calibration_resolver=resolver,
            secondary_calibration_resolver=secondary_resolver,
            fragment_sink=self.fragment_sink,
            capture_finished_sink=self.capture_finished_sink,
            speaker_model_key=mode,
            speaker_authoritative_backend=authoritative_backend,
        )

    def _source(self, source: str | None = None) -> str:
        selected = normalize_audio_source(source) or current_request_audio_source("ALSA")
        if selected not in self._services:
            if selected == "BROWSER":
                raise DomainError(
                    "BROWSER_AUDIO_UNAVAILABLE",
                    "浏览器音频输入未配置，不能启动局域网浏览器录音",
                    503,
                )
            raise DomainError("AUDIO_DEVICE_NOT_CONFIGURED", "Linux ALSA 录音设备未配置", 503)
        return selected

    def _prune_capture_if_stopped(self, case_id: str) -> None:
        with self._lock:
            source = self._capture_sources.get(case_id)
        if source is None:
            return
        try:
            active = bool(self._services[source].status(case_id).get("active"))
        except Exception:
            return
        if not active:
            with self._lock:
                if self._capture_sources.get(case_id) == source:
                    self._capture_sources.pop(case_id, None)

    def start(self, case_id: str, source: str | None = None, *, target_question_id: str | None = None, replace: bool = False) -> dict[str, Any]:
        selected = self._source(source)
        with self._lock:
            for active_case in list(self._capture_sources):
                self._prune_capture_if_stopped(active_case)
            if self._capture_sources:
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "正式审讯录音正在占用麦克风", 409)
            if self._preparation_source is not None:
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "准备阶段语音输入正在占用麦克风", 409)
            ownership = {"target_question_id": target_question_id, "replace": replace} if target_question_id is not None or replace else {}
            result = self._services[selected].start(case_id, **ownership)
            if selected == "BROWSER" and self._live_speech_coordinator is not None:
                try:
                    self._live_speech_coordinator.register_browser_capture(
                        str(result.get("captureSessionId") or "")
                    )
                except Exception:
                    self._services[selected].stop(case_id)
                    raise
            self._capture_sources[str(case_id)] = selected
        payload = dict(result)
        payload["source"] = selected
        return payload

    def stop(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            source = self._capture_sources.get(case_id)
        if source is None:
            return self.status(case_id)
        try:
            result = self._services[source].stop(case_id)
        finally:
            with self._lock:
                if self._capture_sources.get(case_id) == source:
                    self._capture_sources.pop(case_id, None)
        payload = dict(result)
        payload["source"] = source
        return payload

    def status(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            source = self._capture_sources.get(case_id)
        if source is None:
            result = dict(self._default_service.status(case_id))
            coordinator = self._live_speech_coordinator
            capture_id = result.get("captureSessionId")
            if (
                coordinator is not None
                and capture_id
                and coordinator.has_browser_frame_receipt(case_id, str(capture_id))
            ):
                result["source"] = "BROWSER"
            return result
        result = dict(self._services[source].status(case_id))
        result["source"] = source
        if not result.get("active"):
            with self._lock:
                if self._capture_sources.get(case_id) == source:
                    self._capture_sources.pop(case_id, None)
        return result

    def start_preparation(self, case_id: str, source: str | None = None) -> dict[str, Any]:
        selected = self._source(source)
        with self._lock:
            for active_case in list(self._capture_sources):
                self._prune_capture_if_stopped(active_case)
            if self._capture_sources:
                raise DomainError("ASR_AUDIO_RESOURCE_BUSY", "正式审讯录音正在占用麦克风", 409)
            if self._preparation_source is not None:
                raise DomainError("ASR_PREPARATION_ALREADY_ACTIVE", "已有准备阶段语音输入正在进行", 409)
            result = self._services[selected].start_preparation(case_id)
            self._preparation_source = (str(case_id), selected)
        payload = dict(result)
        payload["source"] = selected
        return payload

    def stop_preparation(self, case_id: str) -> dict[str, Any]:
        case_id = str(case_id).strip()
        with self._lock:
            current = self._preparation_source
        if current is None or current[0] != case_id:
            result = self._default_service.stop_preparation(case_id)
            return dict(result)
        source = current[1]
        try:
            result = self._services[source].stop_preparation(case_id)
        finally:
            with self._lock:
                if self._preparation_source == current:
                    self._preparation_source = None
        payload = dict(result)
        payload["source"] = source
        return payload

    def shutdown(self) -> None:
        for service in self._services.values():
            try:
                service.shutdown()
            except Exception:
                pass
        with self._lock:
            self._capture_sources.clear()
            self._preparation_source = None
