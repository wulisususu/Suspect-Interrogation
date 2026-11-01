from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.errors import AIError, ResourceBusyError
from app.ai.speech.fingerprint import fingerprint_microphone
from app.api.deps import get_db, require_admin
from app.api.responses import envelope
from app.domain.errors import DomainError
from app.services.officer_voiceprint_library import OfficerVoiceprintLibraryService
from app.services.speaker_mode import SpeakerModeConfig, resolve_runtime_speaker_mode
from app.services.voiceprint_service import VoiceprintService
from hardware.base import DeviceInfo


router = APIRouter(tags=["voiceprints"])


VoiceprintAudioSource = Literal["ALSA", "BROWSER"]


class ActorBody(BaseModel):
    actor_id: str | None = None


class EnrollmentStartBody(ActorBody):
    source: VoiceprintAudioSource = "ALSA"


class EnrollmentCancelBody(BaseModel):
    capture_id: str = Field(min_length=1, max_length=128)


class OfficerEnrollmentStartBody(ActorBody):
    officer_name: str = Field(min_length=1, max_length=128)
    source: VoiceprintAudioSource = "ALSA"


class OfficerSampleDisableBody(ActorBody):
    reason: str | None = Field(default=None, max_length=512)


class VoiceRoleAssignmentBody(ActorBody):
    interrogator_officer_id: str | None = Field(default=None, max_length=128)
    recorder_officer_id: str | None = Field(default=None, max_length=128)


def _speech_client(request: Request):
    client = getattr(request.app.state, "speech_client", None)
    if client is None:
        raise DomainError("SPEECH_RUNTIME_UNAVAILABLE", "离线语音运行时未配置", 503)
    return client


def _capture_service(request: Request):
    capture = getattr(request.app.state, "voiceprint_capture", None)
    if capture is None:
        raise DomainError("AUDIO_DEVICE_NOT_CONFIGURED", "声纹录音设备未配置", 503)
    return capture


def make_voiceprint_service(request: Request, db: Session) -> VoiceprintService:
    settings = getattr(request.app.state, "runtime_settings", None)
    speaker_model_key = getattr(settings, "speaker_backend", "xvector")
    speaker_authoritative_backend = getattr(settings, "speaker_authoritative_backend", None)
    return VoiceprintService(
        db,
        speech_client=_speech_client(request),
        speaker_model_key=speaker_model_key,
        speaker_authoritative_backend=speaker_authoritative_backend,
    )


def _service(request: Request, db: Session) -> VoiceprintService:
    return make_voiceprint_service(request, db)


def _speaker_mode_config(request: Request, case_id: str, db: Session) -> SpeakerModeConfig:
    """Resolve the runtime speaker operating point the readiness payload must report.

    The resolution order lives in :func:`app.services.speaker_mode.resolve_runtime_speaker_mode`
    because ``/health/ready``, ``/api/v1/asr/status`` and ``/api/v1/capabilities`` need
    the same answer. It asks the live capture (by case id), then the device-calibration
    resolver the capture service was built with, and only then the AI supervisor or
    process settings -- the latter reported as *unverified* rather than as "not
    degraded", which is what let the UI advertise a mode the runtime never enforced.
    """

    return resolve_runtime_speaker_mode(app_state=request.app.state, case_id=case_id, db=db)


def _officer_library(request: Request, db: Session) -> OfficerVoiceprintLibraryService:
    return OfficerVoiceprintLibraryService(db, speech_client=_speech_client(request))


def _context(request: Request) -> dict[str, Any]:
    context = getattr(request.app.state, "voiceprint_enrollment_context", None)
    if context is None:
        context = {}
        request.app.state.voiceprint_enrollment_context = context
    return context


def _set_context(request: Request, *, kind: str, subject_id: str, **extra: Any) -> None:
    context = _context(request)
    context.clear()
    context.update({"kind": kind, "subject_id": subject_id, **extra})


def _clear_context(request: Request, *, kind: str, subject_id: str) -> dict[str, Any]:
    context = dict(_context(request))
    if context.get("kind") != kind or context.get("subject_id") != subject_id:
        raise DomainError("CAPTURE_SUBJECT_MISMATCH", "当前声纹录音上下文不匹配", 409)
    _context(request).clear()
    return context


def _raise_ai_error(exc: AIError) -> None:
    status = 409 if isinstance(exc, ResourceBusyError) else 503
    raise DomainError(exc.code, exc.message, status, data=exc.details) from exc


def _capture_device_metadata(request: Request, source: str) -> tuple[str, str, str, str]:
    normalized = str(source or "ALSA").upper()
    if normalized == "BROWSER":
        info = DeviceInfo(
            "audio",
            "browser-default",
            "Windows Browser Microphone",
            source="browser-test",
            path="browser-default",
            metadata={},
        )
        identity = fingerprint_microphone(info)
        return identity.device_id, identity.device_name, identity.fingerprint, identity.certainty

    manager = getattr(request.app.state, "hardware_manager", None)
    audio = getattr(manager, "audio_recorder", None) if manager is not None else None
    info_fn = getattr(audio, "device_info", None)
    if callable(info_fn):
        try:
            info = info_fn()
        except Exception:
            info = None
    else:
        info = None
    if not isinstance(info, DeviceInfo):
        device = str(getattr(audio, "device", None) or getattr(audio, "device_name", None) or "alsa-default")
        name = str(getattr(audio, "device_name", None) or getattr(audio, "name", None) or "Linux ALSA Microphone")
        info = DeviceInfo("audio", f"alsa:{device}", name, source="real", path=device, metadata={})
    identity = fingerprint_microphone(info)
    return identity.device_id, identity.device_name, identity.fingerprint, identity.certainty


@router.get("/cases/{case_id}/voiceprints/readiness")
def readiness(case_id: str, request: Request, db: Session = Depends(get_db)):
    return envelope(
        _service(request, db).readiness(
            case_id, speaker_mode=_speaker_mode_config(request, case_id, db)
        )
    )


@router.get("/cases/{case_id}/voiceprints/role-draft")
def get_role_draft(case_id: str, request: Request, db: Session = Depends(get_db)):
    return envelope(_service(request, db).get_role_draft(case_id))


@router.put("/cases/{case_id}/voiceprints/role-draft")
def save_role_draft(
    case_id: str,
    body: VoiceRoleAssignmentBody,
    request: Request,
    db: Session = Depends(get_db),
):
    return envelope(
        _service(request, db).save_role_draft(
            case_id,
            body.interrogator_officer_id,
            body.recorder_officer_id,
            actor_id=body.actor_id,
        ),
        "案件级民警角色草稿已保存",
    )


@router.get("/voiceprints/enrollment/status")
def enrollment_status(request: Request):
    return envelope(_capture_service(request).status())


@router.post("/voiceprints/enrollment/cancel")
def cancel_enrollment(request: Request, body: EnrollmentCancelBody):
    context = dict(_context(request))
    if context.get("capture_id") != body.capture_id:
        raise DomainError("CAPTURE_ID_MISMATCH", "声纹录音会话已失效，请重新开始", 409)
    result = _capture_service(request).cancel(body.capture_id)
    _context(request).clear()
    return envelope(result, "声纹录音已取消")


@router.post("/cases/{case_id}/voiceprints/suspect/enrollment/start")
def start_suspect_enrollment(
    case_id: str,
    request: Request,
    body: EnrollmentStartBody | None = None,
    db: Session = Depends(get_db),
):
    _service(request, db).readiness(case_id)
    source = body.source if body else "ALSA"
    result = _capture_service(request).start("suspect", case_id, source=source)
    _set_context(
        request,
        kind="suspect",
        subject_id=case_id,
        capture_id=result.get("captureId"),
        source=result.get("source") or source,
    )
    return envelope(result, "嫌疑人声纹录音已开始")


@router.post("/cases/{case_id}/voiceprints/suspect/enrollment/stop")
def stop_suspect_enrollment(
    case_id: str,
    request: Request,
    body: ActorBody | None = None,
    db: Session = Depends(get_db),
):
    context = dict(_context(request))
    if context.get("kind") != "suspect" or context.get("subject_id") != case_id:
        raise DomainError("CAPTURE_SUBJECT_MISMATCH", "当前嫌疑人声纹录音上下文不匹配", 409)
    pcm = _capture_service(request).stop("suspect", case_id)
    _clear_context(request, kind="suspect", subject_id=case_id)
    try:
        result = _service(request, db).enroll_suspect(
            case_id,
            pcm,
            actor_id=body.actor_id if body else None,
        )
    except AIError as exc:
        _raise_ai_error(exc)
    return envelope(result, "嫌疑人声纹已注册")


@router.get("/officer-voiceprints")
def list_officer_voiceprints(
    request: Request,
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
):
    return envelope(_officer_library(request, db).list_profiles(active_only=active_only))


@router.get("/officer-voiceprints/{officer_id}")
def get_officer_voiceprint(
    officer_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    return envelope(_officer_library(request, db).get_profile(officer_id))


@router.post("/officer-voiceprints/{officer_id}/enrollment/start")
def start_officer_enrollment(
    officer_id: str,
    body: OfficerEnrollmentStartBody,
    request: Request,
    db: Session = Depends(get_db),
):
    _officer_library(request, db)
    result = _capture_service(request).start("officer", officer_id, source=body.source)
    _set_context(
        request,
        kind="officer",
        subject_id=officer_id,
        officer_name=body.officer_name.strip(),
        capture_id=result.get("captureId"),
        source=result.get("source") or body.source,
    )
    return envelope(result, "民警声纹录音已开始")


@router.post("/officer-voiceprints/{officer_id}/enrollment/stop")
def stop_officer_enrollment(
    officer_id: str,
    request: Request,
    body: ActorBody | None = None,
    db: Session = Depends(get_db),
):
    context = dict(_context(request))
    if context.get("kind") != "officer" or context.get("subject_id") != officer_id:
        raise DomainError("CAPTURE_SUBJECT_MISMATCH", "当前民警声纹录音上下文不匹配", 409)
    officer_name = str(context.get("officer_name") or "").strip()
    if not officer_name:
        raise DomainError("OFFICER_IDENTITY_REQUIRED", "民警姓名不能为空", 400)
    source = str(context.get("source") or "ALSA").upper()
    device_id, device_name, microphone_fingerprint, microphone_certainty = _capture_device_metadata(request, source)
    pcm = _capture_service(request).stop("officer", officer_id)
    _clear_context(request, kind="officer", subject_id=officer_id)
    try:
        result = _officer_library(request, db).add_sample(
            officer_id,
            officer_name,
            pcm,
            actor_id=body.actor_id if body else None,
            audio_source=source,
            device_id=device_id,
            device_name=device_name,
            microphone_fingerprint=microphone_fingerprint,
            microphone_fingerprint_certainty=microphone_certainty,
        )
    except AIError as exc:
        _raise_ai_error(exc)
    return envelope(result, "民警声纹样本已添加")


@router.delete("/officer-voiceprints/{officer_id}/samples/{sample_id}", dependencies=[Depends(require_admin)])
def disable_officer_voiceprint_sample(
    officer_id: str,
    sample_id: str,
    request: Request,
    body: OfficerSampleDisableBody | None = None,
    db: Session = Depends(get_db),
):
    return envelope(
        _officer_library(request, db).disable_sample(
            officer_id,
            sample_id,
            reason=body.reason if body else None,
            actor_id=body.actor_id if body else None,
        ),
        "民警声纹样本已停用并重新聚合",
    )


@router.delete("/officer-voiceprints/{officer_id}", dependencies=[Depends(require_admin)])
def revoke_officer_voiceprint(
    officer_id: str,
    request: Request,
    actor_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return envelope(
        _officer_library(request, db).revoke_profile(officer_id, actor_id=actor_id),
        "民警声纹档案已停用",
    )


@router.put("/cases/{case_id}/voiceprints/assignments")
def assign_voice_roles(
    case_id: str,
    body: VoiceRoleAssignmentBody,
    request: Request,
    db: Session = Depends(get_db),
):
    return envelope(
        _service(request, db).bind_roles(
            case_id,
            body.interrogator_officer_id,
            body.recorder_officer_id,
            actor_id=body.actor_id,
        ),
        "审讯声纹角色已绑定",
    )
