from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.ai.registry import ModelRegistry
from app.ai.settings import AISettings
from app.ai.speech.calibration import SpeakerCalibration
from app.ai.speech.client import SpeechWorkerClient
from app.ai.speech.fingerprint import fingerprint_microphone
from app.ai.supervisor import AISupervisor
from app.api.ai_runtime import router as ai_router
from app.api.asr import router as asr_router
from app.api.cases import router as cases_router
from app.api.client_context import router as client_context_router
from app.api.compat import router as compat_router
from app.api.device_events import router as device_router
from app.api.errors import install_error_handlers
from app.api.identity import router as identity_router
from app.api.interrogation import router as interrogation_router
from app.api.moss_transcription import router as moss_transcription_router
from app.api.responses import envelope
from app.api.signature import router as signature_router
from app.api.speaker_calibration import router as speaker_calibration_router
from app.api.template_workspace import router as template_workspace_router
from app.api.tls import router as tls_router
from app.api.voiceprints import router as voiceprints_router
from app.database.session import init_database, make_engine, make_session_factory
from app.hardware_gateway.linux import LinuxHardwareGateway
from app.health import capabilities_router, router as health_router
from app.request_audio_context import AudioSourceContextMiddleware
from app.runtime_settings import RuntimeSettings
from app.services.audio_capture_service import AudioCaptureService
from app.services.browser_audio_input import BrowserAudioInput
from app.services.live_speech_coordinator import LiveSpeechCoordinator
from app.services.moss_transcription_coordinator import MossTranscriptionCoordinator
from app.services.source_aware_asr_capture_service import SourceAwareAsrCaptureService
from app.services.qa_routing_coordinator import QARoutingCoordinator
from app.services.speaker_calibration_runtime import resolve_speaker_calibration
from app.services.speaker_calibration_service import (
    CurrentMicrophoneIdentity,
    CurrentSpeakerModelIdentity,
    SpeakerCalibrationService,
)
from app.websocket.browser_asr import router as browser_asr_websocket_router
from app.websocket.manager import ConnectionManager, router as websocket_router
from app.websocket.voiceprint_enrollment import router as voiceprint_enrollment_websocket_router
from hardware.base import DeviceInfo
from hardware.factory import create_device_manager


def _build_supervisor() -> AISupervisor:
    settings = AISettings.from_env()
    registry = ModelRegistry.load(settings.registry_path, settings.model_root).with_backend_overrides(
        {"asr": settings.asr_backend, "ocr": settings.ocr_backend, "llm": settings.llm_backend}
    )
    supervisor = AISupervisor(
        registry,
        mode=settings.mode,
        request_timeout=settings.request_timeout,
        idle_unload_seconds=settings.idle_unload_seconds,
        memory_budget_mb=settings.memory_budget_mb,
        speech_socket=settings.speech_socket,
        speaker_accept_threshold=settings.speaker_effective_threshold,
        speaker_margin=settings.speaker_margin,
        llamapi_base_url=settings.llamapi_base_url,
        llamapi_model_hint=settings.llamapi_model_hint,
    )
    supervisor.speaker_threshold_source = settings.speaker_threshold_source
    return supervisor


def _database_url(database_url: str | None, settings: RuntimeSettings) -> str | None:
    if database_url is not None:
        return database_url
    if "SUSPECT_DB_PATH" in os.environ:
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{settings.db_path}"
    return None


def create_app(
    database_url: str | None = None,
    hardware_gateway=None,
    hardware_manager=None,
    ai_supervisor: AISupervisor | None = None,
    runtime_settings: RuntimeSettings | None = None,
    moss_coordinator: MossTranscriptionCoordinator | None = None,
) -> FastAPI:
    settings = runtime_settings or RuntimeSettings()
    ai_settings = AISettings.from_env()
    engine = make_engine(_database_url(database_url, settings))
    init_database(engine)

    manager = hardware_manager
    if hardware_gateway is None:
        manager = manager or create_device_manager()
        hardware_gateway = LinuxHardwareGateway(manager)

    browser_audio_input = BrowserAudioInput()
    websocket_manager = ConnectionManager()
    event_loop: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}

    async def publish_hardware_event_async(payload: dict) -> None:
        await websocket_manager.broadcast_all("DEVICE_EVENT", payload)

    def publish_hardware_event(event) -> None:
        loop = event_loop["loop"]
        if loop is None or not loop.is_running():
            return
        payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
        loop.call_soon_threadsafe(lambda: asyncio.create_task(publish_hardware_event_async(payload)))

    async def publish_asr_event_async(session_id: str, event: str, payload: dict) -> None:
        await websocket_manager.broadcast(session_id, event, payload)

    def publish_asr_event(session_id: str, event: str, payload: dict) -> None:
        loop = event_loop["loop"]
        if loop is None or not loop.is_running():
            return
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(publish_asr_event_async(session_id, event, payload))
        )

    if manager is not None and manager.device_monitor is not None:
        manager.device_monitor.subscribe(publish_hardware_event)

    speech_client = SpeechWorkerClient(
        ai_settings.speech_socket,
        timeout=ai_settings.request_timeout,
    )

    def current_model_identity(backend_override: str | None = None) -> CurrentSpeakerModelIdentity:
        configured_backend = "eres2net_large"
        default_backend = configured_backend
        backend_key = str(backend_override or default_backend or "eres2net_large").strip().lower()
        if backend_key != "eres2net_large":
            backend_key = "eres2net_large"
        try:
            health = speech_client.health()
        except Exception:
            health = {}
        backend_health = None
        all_backends = health.get("speaker_backends") if isinstance(health, dict) else None
        if isinstance(all_backends, dict):
            candidate = all_backends.get(backend_key)
            if isinstance(candidate, dict):
                backend_health = candidate
        backend_health = backend_health or {}
        fingerprint = str(backend_health.get("model_fingerprint") or backend_health.get("speaker_model_fingerprint") or "UNAVAILABLE")
        model_id = str(backend_health.get("model_id") or backend_health.get("speaker_model_id") or backend_key)
        model_version_value = backend_health.get("model_version", backend_health.get("speaker_model_version"))
        return CurrentSpeakerModelIdentity(
            model_id,
            None if model_version_value is None else str(model_version_value),
            fingerprint,
            backend_key=backend_key,
        )

    def current_microphone_identity(source: str = "ALSA") -> CurrentMicrophoneIdentity:
        if str(source or "ALSA").upper() == "BROWSER":
            info = DeviceInfo(
                "audio",
                "browser-default",
                "Browser Microphone",
                source="browser-lan",
                path="browser-default",
                metadata={},
            )
            fp = fingerprint_microphone(info)
            return CurrentMicrophoneIdentity("BROWSER", fp.device_id, fp.device_name, fp.fingerprint, fp.certainty)

        audio = getattr(manager, "audio_recorder", None) if manager is not None else None
        info_fn = getattr(audio, "device_info", None)
        try:
            info = info_fn() if callable(info_fn) else None
        except Exception:
            info = None
        if not isinstance(info, DeviceInfo):
            device = str(getattr(audio, "device", None) or "default")
            info = DeviceInfo("audio", f"alsa:{device}", f"ALSA {device}", source="real", path=device, metadata={})
        fp = fingerprint_microphone(info)
        return CurrentMicrophoneIdentity("ALSA", fp.device_id, fp.device_name, fp.fingerprint, fp.certainty)

    def runtime_backend_calibration_resolver_factory(source: str, backend_key: str):
        normalized_source = str(source or "ALSA").upper()
        normalized_backend = str(backend_key or "eres2net_large").strip().lower()

        def runtime_calibration_resolver(db):
            lifecycle = SpeakerCalibrationService(
                db,
                model_provider=lambda: current_model_identity(normalized_backend),
                microphone_provider=lambda: current_microphone_identity(normalized_source),
            )
            return resolve_speaker_calibration(
                lifecycle,
                SpeakerCalibration.from_env(backend_key=normalized_backend),
            )

        return runtime_calibration_resolver

    def runtime_calibration_resolver_factory(source: str):
        configured_backend = "eres2net_large"
        primary_backend = configured_backend
        return runtime_backend_calibration_resolver_factory(
            source,
            str(primary_backend or "eres2net_large"),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        event_loop["loop"] = asyncio.get_running_loop()
        supervisor = ai_supervisor or _build_supervisor()
        app.state.ai_supervisor = supervisor
        routing_coordinator = None
        if settings.formal_routing_mode == "qwen":
            routing_coordinator = QARoutingCoordinator(
                session_factory=app.state.session_factory,
                ai_supervisor=supervisor,
                publish_event=publish_asr_event,
                idle_close_seconds=settings.qa_idle_close_seconds,
            )
            routing_coordinator.start()
        app.state.qa_routing_coordinator = routing_coordinator
        # Task 16: MOSS business poller is disabled with MOSS_ENABLED=0 and
        # then never touches the worker socket or the moss_* tables.
        if moss_coordinator is not None:
            moss_coordinator.start()
        capture_service = SourceAwareAsrCaptureService(
            session_factory=app.state.session_factory,
            device_manager=manager,
            browser_audio_input=browser_audio_input,
            ai_supervisor=supervisor,
            publish_event=publish_asr_event,
            calibration_resolver_factory=runtime_calibration_resolver_factory,
            backend_calibration_resolver_factory=runtime_backend_calibration_resolver_factory,
            fragment_sink=None if routing_coordinator is None else routing_coordinator.enqueue_fragment,
            capture_finished_sink=None if routing_coordinator is None else routing_coordinator.flush_capture,
            speaker_model_key="eres2net_large",
        )
        app.state.asr_capture_service = capture_service
        live_speech_coordinator = LiveSpeechCoordinator(
            data_dir=settings.data_dir,
            session_factory=app.state.session_factory,
            capture_service=capture_service,
            ai_supervisor=supervisor,
            min_free_bytes=settings.min_free_mb * 1024 * 1024,
        )
        app.state.live_speech_coordinator = live_speech_coordinator
        try:
            live_speech_coordinator.start()
            if manager is not None:
                manager.open_all(strict=False)
                manager.start_monitor()
            yield
        finally:
            if moss_coordinator is not None:
                moss_coordinator.shutdown()
            capture_service.shutdown()
            live_speech_coordinator.shutdown()
            if routing_coordinator is not None:
                routing_coordinator.shutdown()
            if manager is not None:
                try:
                    manager.stop_monitor()
                finally:
                    manager.close_all()
            event_loop["loop"] = None
            supervisor.shutdown()

    app = FastAPI(
        title="Linux Suspect Interrogation API",
        version="1.0.0",
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.state.runtime_settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    if moss_coordinator is None:
        moss_coordinator = MossTranscriptionCoordinator.from_settings(
            ai_settings, app.state.session_factory
        )
    app.state.moss_coordinator = moss_coordinator
    app.state.hardware_manager = manager
    app.state.hardware_gateway = hardware_gateway
    app.state.asr_capture_service = None
    app.state.live_speech_coordinator = None
    app.state.qa_routing_coordinator = None
    app.state.browser_audio_input = browser_audio_input
    app.state.speech_client = speech_client
    app.state.speaker_calibration_model_provider = current_model_identity
    # The readiness / health / asr-status surfaces must resolve the speaker operating
    # point with the same closure the capture service starts with, so a STALE DB
    # calibration cannot be bypassed by an env margin (Task 17B-1).
    app.state.speaker_calibration_resolver_factory = runtime_calibration_resolver_factory
    app.state.voiceprint_capture = (
        AudioCaptureService(
            manager,
            speech_client=speech_client,
            max_seconds=300,
            required_usable_speech_ms=60000,
        )
        if manager is not None
        else None
    )
    app.state.voiceprint_enrollment_context = {}
    app.state.websocket_manager = websocket_manager
    # REST 处理器（在线程池里跑）通过它把领域状态变更推给已连接的实时视图。
    app.state.publish_session_event = publish_asr_event

    install_error_handlers(app)
    app.add_middleware(AudioSourceContextMiddleware)
    if settings.cors_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Authorization", "Content-Type", "X-Suspect-Audio-Input"],
        )

    app.include_router(health_router)
    app.include_router(capabilities_router)
    app.include_router(tls_router)
    app.include_router(cases_router, prefix="/api/v1")
    app.include_router(identity_router, prefix="/api/v1")
    app.include_router(interrogation_router, prefix="/api/v1")
    app.include_router(template_workspace_router, prefix="/api/v1")
    app.include_router(signature_router, prefix="/api/v1")
    app.include_router(device_router, prefix="/api/v1")
    app.include_router(ai_router, prefix="/api/v1")
    app.include_router(asr_router, prefix="/api/v1")
    app.include_router(voiceprints_router, prefix="/api/v1")
    app.include_router(speaker_calibration_router, prefix="/api/v1")
    app.include_router(moss_transcription_router, prefix="/api/v1")
    app.include_router(client_context_router, prefix="/api/v1")
    app.include_router(compat_router)
    app.include_router(websocket_router)
    app.include_router(browser_asr_websocket_router)
    app.include_router(voiceprint_enrollment_websocket_router)

    @app.get("/health")
    def legacy_health():
        hardware = app.state.hardware_gateway.status()
        return envelope({"status": "ok", "platform": "linux", "hardware": hardware})

    web_dist = Path(settings.web_dist_dir)
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="webapp")

    return app


app = create_app()
