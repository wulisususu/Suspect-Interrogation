from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.database.session import begin_sqlite_immediate
from app.database.models import ASRCaptureSession, ASRFragment, ASRFragmentLineage
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.services.serializers import iso_utc
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import recognition_evidence as evidence_repo
from app.services.message_service import MessageService
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.speaker_mode import resolve_runtime_speaker_mode
from app.services.speaker_policy import SpeakerRole, SpeakerSource
from app.websocket.publisher import publish_recording_state


router = APIRouter(tags=["asr"])


class FragmentUpdateRequest(BaseModel):
    edited_text: str = ""
    speaker: str
    actor_id: str | None = None
    reason: str | None = None


class FragmentBatchRequest(BaseModel):
    fragment_ids: list[str] = Field(default_factory=list)
    actor_id: str | None = None


def _supervisor(request: Request):
    return request.app.state.ai_supervisor


def _capture_service(request: Request):
    service = getattr(request.app.state, "asr_capture_service", None)
    if service is None:
        raise DomainError("ASR_CAPTURE_UNAVAILABLE", "连续语音采集服务未配置", 503)
    return service


def _fragment_for_case(db: Session, case_id: str, fragment_id: str) -> ASRFragment:
    case_repo.get(db, case_id)
    fragment = asr_repo.get_fragment(db, fragment_id)
    if fragment.case_id != case_id:
        raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
    return fragment


def _fragment_payload(
    fragment: ASRFragment,
    db: Session | None = None,
    *,
    capture_started_at=None,
) -> dict[str, Any]:
    payload = {
        "fragmentId": fragment.id,
        "captureSessionId": fragment.capture_session_id,
        "caseId": fragment.case_id,
        "ordinal": fragment.ordinal,
        "captureStartedAt": (
            iso_utc(capture_started_at)
            if capture_started_at is not None
            else None
        ),
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
        "confirmedMessageId": fragment.confirmed_message_id,
        "createdAt": iso_utc(fragment.created_at),
        "updatedAt": iso_utc(fragment.updated_at),
    }
    if db is not None:
        if capture_started_at is None:
            capture = db.get(ASRCaptureSession, fragment.capture_session_id)
            if capture is not None:
                payload["captureStartedAt"] = iso_utc(capture.started_at)
        payload["recognitionEvidence"] = evidence_repo.evidence_payload(evidence_repo.get_evidence(db, fragment.id))
        payload["recognitionRevisions"] = [
            evidence_repo.revision_payload(row) for row in evidence_repo.list_revisions(db, fragment.id)
        ]
        lineage = db.scalars(
            select(ASRFragmentLineage)
            .where(
                or_(
                    ASRFragmentLineage.parent_fragment_id == fragment.id,
                    ASRFragmentLineage.child_fragment_id == fragment.id,
                )
            )
            .order_by(ASRFragmentLineage.created_at.asc(), ASRFragmentLineage.id.asc())
        )
        payload["lineage"] = [
            {
                "analysisJobId": row.analysis_job_id,
                "parentFragmentId": row.parent_fragment_id,
                "childFragmentId": row.child_fragment_id,
                "relation": row.relation,
            }
            for row in lineage
        ]
    return payload


def _asr_status(request: Request) -> dict[str, Any]:
    supervisor = _supervisor(request)
    health = supervisor.health()
    capabilities = supervisor.capabilities()
    speech = health.get("speech") or {}
    # Task 17B-1: the calibration flag used to be read straight off the supervisor,
    # which is not where a calibration-configured runtime reads from. It now comes
    # from the shared rule, resolved with the capture service's own resolver, and is
    # reported as unverified when that resolver cannot be reached.
    config = resolve_runtime_speaker_mode(app_state=request.app.state)
    ready = speech.get("state") == "READY" and capabilities.get("asr", {}).get("state") not in {"ERROR", "NOT_CONFIGURED"}
    return {
        "state": "AVAILABLE" if ready else "ERROR",
        "speech": speech,
        "capabilities": {
            "asr": capabilities.get("asr"),
            "asrStreaming": capabilities.get("asrStreaming"),
            "vad": capabilities.get("vad"),
            "speaker": capabilities.get("speaker"),
        },
        "calibration": {
            # The margin is the only channel the runtime narrows on, so it is the only
            # one that makes the device "configured"; the threshold is informational.
            "configured": bool(config.verified and config.margin_configured),
            "verified": config.verified,
            "verificationSource": config.verification_source,
            "threshold": config.threshold,
            "margin": config.margin,
            "thresholdSource": config.threshold_source,
        },
    }


def _official_message_speaker(role: str) -> str:
    try:
        normalized = SpeakerRole(str(role))
    except ValueError as exc:
        raise DomainError("INVALID_SPEAKER_ROLE", "ASR 片段包含无效的说话人角色", 409) from exc
    if normalized is SpeakerRole.SUSPECT:
        return "嫌疑人"
    if normalized in {SpeakerRole.INTERROGATOR, SpeakerRole.RECORDER, SpeakerRole.OFFICER_FALLBACK}:
        return "民警"
    raise DomainError("ASR_SPEAKER_CONFIRMATION_REQUIRED", "说话人尚未确认，请先人工指定嫌疑人或民警角色后再写入正式笔录", 409)


@router.get("/asr/status")
def asr_status(request: Request):
    return _asr_status(request)


@router.post("/asr/start")
def asr_start(request: Request):
    status = _asr_status(request)
    if status["state"] != "AVAILABLE":
        raise DomainError("ASR_NOT_READY", "离线语音运行时尚未就绪", 503, status)
    return status


@router.post("/asr/stop")
def asr_stop(request: Request):
    _capture_service(request).shutdown()
    status = _asr_status(request)
    status["capturesStopped"] = True
    return status


@router.get("/cases/{case_id}/asr/capture")
def capture_status(case_id: str, request: Request):
    return _capture_service(request).status(case_id)


@router.post("/cases/{case_id}/asr/capture/start")
def capture_start(case_id: str, request: Request):
    status = _capture_service(request).start(case_id)
    publish_recording_state(request.app.state, case_id, status)
    return status


@router.post("/cases/{case_id}/asr/capture/stop")
def capture_stop(case_id: str, request: Request):
    status = _capture_service(request).stop(case_id)
    publish_recording_state(request.app.state, case_id, status)
    return status


@router.post("/cases/{case_id}/asr/question-preparation/start")
def question_preparation_start(case_id: str, request: Request):
    status = _asr_status(request)
    if status["state"] != "AVAILABLE":
        raise DomainError("ASR_NOT_READY", "离线语音运行时尚未就绪", 503, status)
    return _capture_service(request).start_preparation(case_id)


@router.post("/cases/{case_id}/asr/question-preparation/stop")
def question_preparation_stop(case_id: str, request: Request):
    return _capture_service(request).stop_preparation(case_id)


@router.get("/cases/{case_id}/asr/fragments")
def list_fragments(
    case_id: str,
    include_confirmed: bool = Query(False),
    include_superseded: bool = Query(False),
    db: Session = Depends(get_db),
):
    case_repo.get(db, case_id)
    stmt = (
        select(ASRFragment, ASRCaptureSession.started_at)
        .join(ASRCaptureSession, ASRCaptureSession.id == ASRFragment.capture_session_id)
        .where(ASRFragment.case_id == case_id, ASRFragment.state != "DISCARDED")
    )
    if not include_confirmed:
        stmt = stmt.where(ASRFragment.state != "CONFIRMED")
    if not include_superseded:
        stmt = stmt.where(ASRFragment.state != "SUPERSEDED")
    stmt = stmt.order_by(
        ASRCaptureSession.started_at.asc(),
        ASRCaptureSession.id.asc(),
        ASRFragment.started_at_ms.asc(),
        ASRFragment.ended_at_ms.asc(),
        ASRFragment.ordinal.asc(),
        ASRFragment.id.asc(),
    )
    return [
        _fragment_payload(fragment, db, capture_started_at=capture_started_at)
        for fragment, capture_started_at in db.execute(stmt)
    ]


@router.put("/cases/{case_id}/asr/fragments/{fragment_id}")
def update_fragment(
    case_id: str,
    fragment_id: str,
    body: FragmentUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    fragment = _fragment_for_case(db, case_id, fragment_id)
    assert_formal_record_mutable(db, case_id)
    if fragment.state == "DISCARDED":
        raise DomainError("ASR_FRAGMENT_DISCARDED", "已丢弃的 ASR 片段不能修改", 409)
    if fragment.state == "SUPERSEDED":
        raise DomainError("ASR_FRAGMENT_SUPERSEDED", "已被替换的 ASR 片段不能修改", 409)
    try:
        role = SpeakerRole(str(body.speaker))
    except ValueError as exc:
        raise DomainError("INVALID_SPEAKER_ROLE", "无效的说话人角色", 400) from exc

    speaker_changed = role.value != fragment.speaker
    resolving_unknown = fragment.speaker == SpeakerRole.UNKNOWN.value and role is not SpeakerRole.UNKNOWN
    before = {
        "edited_text": fragment.edited_text,
        "speaker": fragment.speaker,
        "speaker_id": fragment.speaker_id,
        "speaker_name": fragment.speaker_name,
        "speaker_source": fragment.speaker_source,
        "voiceprint_verified": fragment.voiceprint_verified,
        "low_confidence": fragment.low_confidence,
    }
    row = asr_repo.update_fragment(
        db,
        fragment_id=fragment_id,
        edited_text=body.edited_text,
        speaker=role.value,
        speaker_id=None if speaker_changed else fragment.speaker_id,
        speaker_name=None if speaker_changed else fragment.speaker_name,
        speaker_source=(SpeakerSource.MANUAL.value if speaker_changed else fragment.speaker_source),
        voiceprint_verified=False if speaker_changed else fragment.voiceprint_verified,
        low_confidence=(role is SpeakerRole.UNKNOWN if speaker_changed else fragment.low_confidence),
        actor_id=body.actor_id,
        reason=body.reason,
    )
    audit_repo.add(
        db,
        case_id=case_id,
        actor_id=body.actor_id,
        action="ASR_FRAGMENT_UPDATE",
        target_type="ASR_FRAGMENT",
        target_id=row.id,
        before=before,
        after={
            "edited_text": row.edited_text,
            "speaker": row.speaker,
            "speaker_id": row.speaker_id,
            "speaker_name": row.speaker_name,
            "speaker_source": row.speaker_source,
            "voiceprint_verified": row.voiceprint_verified,
            "low_confidence": row.low_confidence,
        },
        detail={"raw_text_unchanged": True, "speaker_changed": speaker_changed, "reason": body.reason},
    )
    db.commit()
    if resolving_unknown:
        capture_service = getattr(request.app.state, "asr_capture_service", None)
        fragment_sink = getattr(capture_service, "fragment_sink", None)
        if fragment_sink is not None:
            fragment_sink(case_id, row.id)
        else:
            from app.services.interrogation_projection_service import InterrogationProjectionService

            InterrogationProjectionService(db).process_fragment(case_id, row.id)
            db.commit()
    return _fragment_payload(row, db)


def _confirm_one(db: Session, *, case_id: str, fragment_id: str, actor_id: str | None, commit: bool = True) -> tuple[ASRFragment, bool]:
    begin_sqlite_immediate(db)
    fragment = _fragment_for_case(db, case_id, fragment_id)
    assert_formal_record_mutable(db, case_id)
    if fragment.state == "DISCARDED":
        raise DomainError("ASR_FRAGMENT_DISCARDED", "已丢弃的 ASR 片段不能确认", 409)
    if fragment.state == "SUPERSEDED":
        raise DomainError("ASR_FRAGMENT_SUPERSEDED", "已被替换的 ASR 片段不能确认", 409)
    if fragment.state == "CONFIRMED":
        return fragment, False
    official_speaker = _official_message_speaker(fragment.speaker)
    message = MessageService(db).create(case_id, text=fragment.edited_text, speaker=official_speaker, actor_id=actor_id, commit=False)
    row = asr_repo.confirm_fragment(db, fragment_id=fragment.id, message_id=message["id"])
    audit_repo.add(
        db, case_id=case_id, actor_id=actor_id, action="ASR_FRAGMENT_CONFIRM",
        target_type="ASR_FRAGMENT", target_id=row.id,
        after={"message_id": message["id"], "speaker": row.speaker, "official_speaker": official_speaker, "text": row.edited_text},
        detail={"raw_text": row.raw_text},
    )
    if commit:
        db.commit()
    return row, True


@router.post("/cases/{case_id}/asr/fragments/{fragment_id}/confirm")
def confirm_fragment(case_id: str, fragment_id: str, db: Session = Depends(get_db)):
    row, _ = _confirm_one(db, case_id=case_id, fragment_id=fragment_id, actor_id=None)
    return _fragment_payload(row, db)


def _confirm_batch(db: Session, *, case_id: str, fragment_ids: list[str], actor_id: str | None) -> dict[str, Any]:
    begin_sqlite_immediate(db)
    assert_formal_record_mutable(db, case_id)
    unique_ids = list(dict.fromkeys(str(item).strip() for item in fragment_ids if str(item).strip()))
    confirmed = 0
    rows: list[ASRFragment] = []
    for fragment_id in unique_ids:
        row, created = _confirm_one(db, case_id=case_id, fragment_id=fragment_id, actor_id=actor_id, commit=False)
        rows.append(row)
        confirmed += int(created)
    db.commit()
    return {"confirmedCount": confirmed, "fragments": [_fragment_payload(row, db) for row in rows]}


@router.post("/cases/{case_id}/asr/fragments/confirm")
def confirm_fragments(case_id: str, body: FragmentBatchRequest, db: Session = Depends(get_db)):
    return _confirm_batch(db, case_id=case_id, fragment_ids=body.fragment_ids, actor_id=body.actor_id)


@router.post("/cases/{case_id}/asr/fragments/apply")
def apply_fragments(case_id: str, body: FragmentBatchRequest, db: Session = Depends(get_db)):
    begin_sqlite_immediate(db)
    fragment_ids = list(body.fragment_ids)
    if not fragment_ids:
        fragment_ids = list(db.scalars(select(ASRFragment.id).where(ASRFragment.case_id == case_id, ASRFragment.state.in_(["PENDING", "EDITED"])).order_by(ASRFragment.created_at.asc(), ASRFragment.ordinal.asc())))
    return _confirm_batch(db, case_id=case_id, fragment_ids=fragment_ids, actor_id=body.actor_id)


@router.post("/cases/{case_id}/asr/fragments/{fragment_id}/discard")
def discard_fragment(case_id: str, fragment_id: str, db: Session = Depends(get_db)):
    fragment = _fragment_for_case(db, case_id, fragment_id)
    assert_formal_record_mutable(db, case_id)
    if fragment.state == "SUPERSEDED":
        raise DomainError("ASR_FRAGMENT_SUPERSEDED", "已被替换的 ASR 片段不能丢弃", 409)
    if fragment.state == "CONFIRMED":
        raise DomainError("ASR_FRAGMENT_ALREADY_CONFIRMED", "已确认的 ASR 片段不能丢弃", 409)
    if fragment.state != "DISCARDED":
        before = {"state": fragment.state}
        fragment.state = "DISCARDED"
        audit_repo.add(db, case_id=case_id, actor_id=None, action="ASR_FRAGMENT_DISCARD", target_type="ASR_FRAGMENT", target_id=fragment.id, before=before, after={"state": "DISCARDED"})
        db.commit()
    return _fragment_payload(fragment, db)
