from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.speech.fingerprint import fingerprint_microphone
from app.api.deps import get_db, require_admin
from app.api.responses import envelope
from app.domain.errors import DomainError
from app.services.speaker_calibration_service import (
    CurrentMicrophoneIdentity,
    CurrentSpeakerModelIdentity,
    SpeakerCalibrationService,
)
from hardware.base import DeviceInfo


router = APIRouter(prefix="/speaker-calibration", tags=["speaker-calibration"])
SpeakerBackendKey = Literal["eres2net_large"]


class RecomputeBody(BaseModel):
    actor_id: str | None = None


def _model_provider(request: Request, backend: SpeakerBackendKey | None = None):
    injected = getattr(request.app.state, "speaker_calibration_model_provider", None)
    if callable(injected):
        if backend is None:
            return injected

        def injected_provider() -> CurrentSpeakerModelIdentity:
            try:
                identity = injected(backend)
            except TypeError:
                identity = injected()
            actual = str(getattr(identity, "backend_key", "eres2net_large") or "eres2net_large").strip().lower()
            if actual != backend:
                raise DomainError(
                    "SPEAKER_MODEL_BACKEND_MISMATCH",
                    "校准模型提供器返回了错误的声纹后端",
                    503,
                    data={"requestedBackend": backend, "actualBackend": actual},
                )
            return identity

        return injected_provider

    selected = str(backend or "eres2net_large").strip().lower()

    def provide() -> CurrentSpeakerModelIdentity:
        client = getattr(request.app.state, "speech_client", None)
        if client is None:
            raise DomainError("SPEAKER_MODEL_UNAVAILABLE", "声纹运行时未配置", 503)
        health = client.health()
        backends = health.get("speaker_backends") if isinstance(health, dict) else None
        backend_health = backends.get(selected) if isinstance(backends, dict) else None
        backend_health = backend_health or {}
        fingerprint = backend_health.get("model_fingerprint") or backend_health.get("speaker_model_fingerprint")
        if not fingerprint:
            raise DomainError(
                "SPEAKER_MODEL_FINGERPRINT_UNAVAILABLE",
                f"当前 {selected} 模型指纹不可用",
                503,
            )
        return CurrentSpeakerModelIdentity(
            str(backend_health.get("model_id") or backend_health.get("speaker_model_id") or selected),
            None
            if backend_health.get("model_version", backend_health.get("speaker_model_version")) is None
            else str(backend_health.get("model_version", backend_health.get("speaker_model_version"))),
            str(fingerprint),
            backend_key=selected,
        )

    return provide


def _microphone_provider(request: Request):
    injected = getattr(request.app.state, "speaker_calibration_microphone_provider", None)
    if callable(injected):
        return injected

    def provide() -> CurrentMicrophoneIdentity:
        manager = getattr(request.app.state, "hardware_manager", None)
        audio = getattr(manager, "audio_recorder", None) if manager is not None else None
        info_fn = getattr(audio, "device_info", None)
        try:
            info = info_fn() if callable(info_fn) else None
        except Exception:
            info = None
        if not isinstance(info, DeviceInfo):
            device = str(getattr(audio, "device", None) or "default")
            info = DeviceInfo("audio", f"alsa:{device}", f"ALSA {device}", source="real", path=device, metadata={})
        identity = fingerprint_microphone(info)
        return CurrentMicrophoneIdentity(
            "ALSA",
            identity.device_id,
            identity.device_name,
            identity.fingerprint,
            identity.certainty,
        )

    return provide


def _service(
    request: Request,
    db: Session,
    backend: SpeakerBackendKey | None = None,
) -> SpeakerCalibrationService:
    return SpeakerCalibrationService(
        db,
        model_provider=_model_provider(request, backend),
        microphone_provider=_microphone_provider(request),
    )


@router.get("/status")
def calibration_status(
    request: Request,
    backend: SpeakerBackendKey | None = Query(None),
    db: Session = Depends(get_db),
):
    return envelope(_service(request, db, backend).status())


@router.get("/history")
def calibration_history(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    backend: SpeakerBackendKey | None = Query(None),
    db: Session = Depends(get_db),
):
    return envelope(_service(request, db, backend).history(limit=limit))


@router.post("/recompute", dependencies=[Depends(require_admin)])
def recompute_calibration(
    request: Request,
    body: RecomputeBody | None = None,
    backend: SpeakerBackendKey | None = Query(None),
    db: Session = Depends(get_db),
):
    return envelope(
        _service(request, db, backend).recompute(actor_id=body.actor_id if body else None),
        "设备声纹校准已重新计算",
    )
