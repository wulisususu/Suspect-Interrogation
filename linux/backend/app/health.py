from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from .runtime_settings import RuntimeSettings
from .services.speaker_mode import SpeakerModeConfig, resolve_runtime_speaker_mode


router = APIRouter(prefix="/health", tags=["health"])
capabilities_router = APIRouter(prefix="/api/v1", tags=["runtime"])


def _result(state: str, *, required: bool, detail: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"state": state, "required": required, "detail": detail}
    payload.update(extra)
    return payload


def _storage_check(settings: RuntimeSettings) -> dict[str, Any]:
    path = Path(settings.data_dir)
    try:
        probe_root = path if path.exists() else path.parent
        if not probe_root.exists():
            return _result("ERROR", required=True, detail=f"storage parent missing: {probe_root}")
        if not os.access(probe_root, os.R_OK | os.W_OK | os.X_OK):
            return _result("ERROR", required=True, detail=f"storage not writable: {probe_root}")
        usage = shutil.disk_usage(probe_root)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < settings.min_free_mb:
            return _result(
                "LOW_SPACE",
                required=True,
                detail=f"free_mb={free_mb} below minimum={settings.min_free_mb}",
            )
        return _result("READY", required=True, detail=f"free_mb={free_mb}")
    except OSError as exc:
        return _result("ERROR", required=True, detail=f"storage check failed: {exc.__class__.__name__}")


def _database_check(settings: RuntimeSettings) -> dict[str, Any]:
    path = Path(settings.db_path)
    try:
        if not path.exists():
            parent = path.parent
            if parent.exists() and os.access(parent, os.W_OK | os.X_OK):
                return _result("READY", required=True, detail="database will be initialized on first write")
            return _result("ERROR", required=True, detail=f"database parent not writable: {parent}")
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            connection.close()
        if integrity != "ok":
            return _result("ERROR", required=True, detail="sqlite quick_check failed")
        return _result("READY", required=True, detail="sqlite quick_check=ok")
    except (OSError, sqlite3.Error) as exc:
        return _result("ERROR", required=True, detail=f"database check failed: {exc.__class__.__name__}")


def _hardware_capability() -> dict[str, Any]:
    try:
        from hardware.device_manager import DeviceManager

        manager = DeviceManager()
        configured = any(
            device is not None
            for device in (manager.idcard_reader, manager.audio_recorder, manager.signature_device)
        )
        if not configured:
            return _result("UNAVAILABLE", required=False, detail="no physical device configured")
        return _result("READY", required=False, detail="hardware manager configured")
    except Exception as exc:  # capability failure must not kill API readiness
        return _result("UNAVAILABLE", required=False, detail=f"hardware manager unavailable: {exc.__class__.__name__}")


def _ai_capability(settings: RuntimeSettings) -> dict[str, Any]:
    model_path = settings.model_path
    if model_path is None:
        return _result("NOT_INSTALLED", required=False, detail="local model asset path is not configured")

    path = Path(model_path)
    installed = path.is_file()
    if path.is_dir():
        try:
            installed = any(child.is_file() for child in path.rglob("*") if not child.name.startswith("."))
        except OSError:
            installed = False

    if not installed:
        return _result("NOT_INSTALLED", required=False, detail="local model assets are not installed")
    return _result("READY", required=False, detail="local model assets are present")


def _calibration_capability(supervisor: Any | None, app_state: Any | None = None) -> dict[str, Any]:
    """Report the device speaker calibration through the shared rule.

    Task 17B-1: this used to read ``speaker_accept_threshold``/``speaker_margin`` off
    the AI supervisor (or the env). On a device whose DB calibration went STALE the
    supervisor still advertises env values while the runtime resolves ``margin=None``
    and narrows to suspect-only, so the capability lied. The operating point now comes
    from the same resolver the capture runtime starts with; when that cannot be
    reached the capability is reported as UNVERIFIED, never as READY.
    """

    if app_state is not None:
        config = resolve_runtime_speaker_mode(app_state=app_state)
    else:
        # Request-less callers (unit probes, CLI) know nothing about the runtime.
        config = SpeakerModeConfig.from_sources([supervisor])

    if not config.verified:
        return _result(
            "UNVERIFIED",
            required=False,
            detail="speaker operating point could not be resolved against the capture runtime",
            thresholdConfigured=config.threshold_configured,
            marginConfigured=config.margin_configured,
            verified=False,
            verificationSource=config.verification_source,
        )

    configured = config.margin_configured
    return _result(
        "READY" if configured else "NOT_CONFIGURED",
        required=False,
        detail=(
            "speaker margin is calibrated; the threshold is informational"
            if configured
            else "speaker margin requires RK3588 microphone calibration"
        ),
        thresholdConfigured=config.threshold_configured,
        marginConfigured=config.margin_configured,
        verified=True,
        verificationSource=config.verification_source,
    )


def _audio_capture_capability(manager: Any | None) -> dict[str, Any]:
    if manager is None:
        return _result("UNAVAILABLE", required=False, detail="hardware manager is not active")
    recorder = getattr(manager, "audio_recorder", None)
    if recorder is None:
        return _result("UNAVAILABLE", required=False, detail="audio recorder is not configured")
    return _result("READY", required=False, detail="audio recorder is configured")


def _speech_capability(
    name: str,
    *,
    supervisor: Any | None,
    calibration: dict[str, Any],
) -> dict[str, Any]:
    if supervisor is None:
        if name == "speaker" and calibration["state"] == "NOT_CONFIGURED":
            return _result(
                "NOT_CONFIGURED",
                required=False,
                detail="speaker verification is disabled until calibration is configured",
            )
        return _result("UNAVAILABLE", required=False, detail="AI supervisor is not active")

    try:
        capability = dict((supervisor.capabilities() or {}).get(name) or {})
    except Exception as exc:
        return _result(
            "ERROR",
            required=False,
            detail=f"{name} capability check failed: {exc.__class__.__name__}",
        )

    state = str(capability.pop("state", "UNAVAILABLE"))
    detail = str(capability.pop("detail", f"{name} capability reported by AI supervisor"))
    if capability.get("speech_worker") and capability.get("speech_state") == "AVAILABLE":
        state = "AVAILABLE"
    return _result(state, required=False, detail=detail, **capability)


def readiness_snapshot(request: Request | None = None) -> dict[str, Any]:
    settings = RuntimeSettings()
    supervisor = None
    manager = None
    app_state = None
    if request is not None:
        app_state = request.app.state
        supervisor = getattr(request.app.state, "ai_supervisor", None)
        manager = getattr(request.app.state, "hardware_manager", None)

    checks = {
        "storage": _storage_check(settings),
        "database": _database_check(settings),
    }
    calibration = _calibration_capability(supervisor, app_state)
    capabilities = {
        "hardware": _hardware_capability(),
        "ai": _ai_capability(settings),
        "asr": _speech_capability("asr", supervisor=supervisor, calibration=calibration),
        "asrStreaming": _speech_capability("asrStreaming", supervisor=supervisor, calibration=calibration),
        "vad": _speech_capability("vad", supervisor=supervisor, calibration=calibration),
        "speaker": _speech_capability("speaker", supervisor=supervisor, calibration=calibration),
        "voiceprintCalibration": calibration,
        "audioCapture": _audio_capture_capability(manager),
    }
    required_ok = all(item["state"] == "READY" for item in checks.values() if item["required"])
    return {
        "status": "ready" if required_ok else "degraded",
        "checks": checks,
        "capabilities": capabilities,
    }


def _runtime_capability_state(raw: object) -> str:
    value = str(raw or "").upper()
    if value in {"READY", "AVAILABLE", "CONNECTED", "OK", "IDLE"}:
        return "AVAILABLE"
    if value in {"NOT_INSTALLED", "MISSING", "MODEL_NOT_INSTALLED"}:
        return "MODEL_NOT_INSTALLED"
    if value in {"ERROR", "LOW_SPACE"}:
        return "ERROR"
    if value == "BUSY":
        return "BUSY"
    return "NOT_CONFIGURED"


def _runtime_capability(capability_state: str, reason: str, **metadata: Any) -> dict[str, Any]:
    return {"state": capability_state, "reason": reason, "metadata": metadata}


def _device_runtime_capability(device: Any, unavailable_reason: str) -> dict[str, Any]:
    if device is None:
        return _runtime_capability("NOT_CONFIGURED", unavailable_reason)
    try:
        report = device.health().to_dict()
    except Exception as exc:
        return _runtime_capability("ERROR", f"hardware state check failed: {exc.__class__.__name__}")
    state = _runtime_capability_state(report.get("status"))
    reason = str(report.get("message") or unavailable_reason)
    return _runtime_capability(
        state,
        reason,
        healthy=bool(report.get("healthy")),
        details=dict(report.get("details") or {}),
    )


@capabilities_router.get("/capabilities")
def runtime_capabilities(request: Request) -> dict[str, Any]:
    """Expose the canonical UI capability contract from the production health state."""
    snapshot = readiness_snapshot(request)
    health = snapshot["capabilities"]
    asr = health["asr"]
    asr_streaming = health["asrStreaming"]
    asr_state = _runtime_capability_state(asr["state"])
    microphone = health["audioCapture"]
    microphone_state = _runtime_capability_state(microphone["state"])
    vad = health["vad"]
    vad_state = _runtime_capability_state(vad["state"])
    recording_state = asr_state if asr_state != "AVAILABLE" else vad_state
    recording_reason = (
        "offline ASR and VAD are ready"
        if recording_state == "AVAILABLE"
        else str((asr if asr_state != "AVAILABLE" else vad)["detail"])
    )
    supervisor = getattr(request.app.state, "ai_supervisor", None)
    try:
        ai = dict(supervisor.capabilities() if supervisor is not None else {})
    except Exception:
        ai = {}

    def model(name: str) -> dict[str, Any]:
        detail = dict(ai.get(name) or {})
        installed = detail.get("installed")
        raw_state = detail.get("state")
        state = "MODEL_NOT_INSTALLED" if installed is False else _runtime_capability_state(raw_state)
        return _runtime_capability(state, str(detail.get("detail") or f"{name} runtime capability"), **detail)

    unavailable = lambda reason: _runtime_capability("NOT_CONFIGURED", reason)
    hardware_manager = getattr(request.app.state, "hardware_manager", None)
    return {
        "identity": _device_runtime_capability(
            getattr(hardware_manager, "identity_reader", None),
            "identity reader is not configured",
        ),
        "camera": unavailable("camera is not configured"),
        "microphone": _runtime_capability(microphone_state, str(microphone["detail"]), **microphone),
        "fingerprint": unavailable("fingerprint device is not configured"),
        "signature": unavailable("signature device is not configured"),
        "recording": _runtime_capability(recording_state, recording_reason, asr=asr, vad=vad),
        "asr": _runtime_capability(asr_state, str(asr["detail"]), **asr),
        "asrStreaming": _runtime_capability(
            _runtime_capability_state(asr_streaming["state"]),
            str(asr_streaming["detail"]),
            **asr_streaming,
        ),
        "ocr": model("ocr"),
        "llm": model("llm"),
        "report": _runtime_capability(_runtime_capability_state(snapshot["checks"]["database"]["state"]), str(snapshot["checks"]["database"]["detail"])),
    }


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/ready")
def ready(request: Request) -> dict[str, Any]:
    return readiness_snapshot(request)
