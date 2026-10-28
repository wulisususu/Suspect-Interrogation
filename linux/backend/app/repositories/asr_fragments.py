from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.database.models import (
    ASRCaptureSession,
    ASRFragment,
    ASRFragmentLineage,
    Message,
    ProcessedSpeechFragment,
    QAUnitFragment,
)
from app.database.recognition_models import (
    ASRRecognitionEvidence,
    ASRRecognitionRevision,
    ASRSpeakerAnalysisResult,
)
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import recognition_evidence as evidence_repo
from app.repositories import speaker_calibrations as calibration_repo
from app.services.speaker_policy import SpeakerDecision


def create_capture_session(db: Session, *, case_id: str, interrogation_session_id: str | None, sample_rate: int,
                           target_question_id: str | None = None, replace: bool = False) -> ASRCaptureSession:
    if sample_rate <= 0:
        raise DomainError("INVALID_SAMPLE_RATE", "采样率必须大于 0", 400)
    from app.services.formal_record_policy import assert_formal_record_mutable

    assert_formal_record_mutable(db, case_id)
    if target_question_id is not None:
        from app.repositories import template_questions
        template_questions.get_case(db, case_id, target_question_id)
    item = ASRCaptureSession(
        id=str(uuid4()), case_id=case_id, interrogation_session_id=interrogation_session_id,
        status="CAPTURING", sample_rate=sample_rate, started_at=datetime.now(timezone.utc), ended_at=None,
        target_question_id=target_question_id, replace_answer=replace, answer_replacement_applied=False,
    )
    db.add(item)
    db.flush()
    from app.services.recording_service import snapshot_capture_options

    snapshot_capture_options(db, item.id)
    return item


def get_capture_session(db: Session, capture_session_id: str) -> ASRCaptureSession:
    item = db.get(ASRCaptureSession, capture_session_id)
    if item is None:
        raise DomainError("ASR_CAPTURE_NOT_FOUND", "ASR 采集会话不存在", 404)
    return item


def finish_capture_session(db: Session, *, capture_session_id: str) -> ASRCaptureSession:
    item = get_capture_session(db, capture_session_id)
    item.status = "STOPPED"
    item.ended_at = datetime.now(timezone.utc)
    db.flush()
    return item


def get_fragment(db: Session, fragment_id: str) -> ASRFragment:
    item = db.get(ASRFragment, fragment_id)
    if item is None:
        raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
    return item


def list_fragments(db: Session, *, capture_session_id: str) -> list[ASRFragment]:
    stmt = (
        select(ASRFragment)
        .where(ASRFragment.capture_session_id == capture_session_id)
        .order_by(
            ASRFragment.started_at_ms.asc(),
            ASRFragment.ended_at_ms.asc(),
            ASRFragment.ordinal.asc(),
            ASRFragment.id.asc(),
        )
    )
    return list(db.scalars(stmt))


def list_for_capture(db: Session, capture_id: str) -> list[ASRFragment]:
    return list_fragments(db, capture_session_id=capture_id)


def asr_final_idempotency_key(
    capture_session_id: str,
    start_sample: int,
    end_sample: int,
    model_version: str | None,
) -> str:
    key = "\0".join(
        (
            str(capture_session_id),
            str(int(start_sample)),
            str(int(end_sample)),
            "" if model_version is None else str(model_version),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_or_update_asr_only_fragment(
    db: Session,
    *,
    capture_session_id: str,
    case_id: str,
    started_at_ms: int,
    ended_at_ms: int,
    raw_text: str,
    asr_confidence: float | None,
    model_id: str,
    model_version: str | None,
    idempotency_key: str,
) -> tuple[ASRFragment, bool]:
    existing = db.scalar(
        select(ASRFragment).where(ASRFragment.asr_idempotency_key == idempotency_key)
    )
    text = str(raw_text or "")
    if existing is not None:
        if existing.state == "PENDING" and existing.speaker_source == "PENDING_ANALYSIS":
            if existing.edited_text == existing.raw_text:
                existing.edited_text = text
            existing.raw_text = text
            existing.asr_confidence = asr_confidence
            existing.started_at_ms = started_at_ms
            existing.ended_at_ms = ended_at_ms
            existing.model_id = model_id
            existing.model_version = model_version
            db.flush()
        from app.services.question_recording_service import attach_targeted_fragment
        attach_targeted_fragment(db, existing)
        return existing, False

    max_ordinal = db.scalar(
        select(func.max(ASRFragment.ordinal)).where(
            ASRFragment.capture_session_id == capture_session_id
        )
    )
    ordinal = int(max_ordinal) + 1 if max_ordinal is not None else 0
    item = ASRFragment(
        id=str(uuid4()),
        capture_session_id=capture_session_id,
        case_id=case_id,
        ordinal=ordinal,
        started_at_ms=started_at_ms,
        ended_at_ms=ended_at_ms,
        raw_text=text,
        edited_text=text,
        asr_confidence=asr_confidence,
        speaker="UNKNOWN",
        speaker_id=None,
        speaker_name=None,
        speaker_score=None,
        second_best_score=None,
        speaker_threshold=None,
        speaker_margin=None,
        speaker_source="PENDING_ANALYSIS",
        voiceprint_verified=False,
        low_confidence=False,
        state="PENDING",
        model_id=model_id,
        model_version=model_version,
        asr_idempotency_key=idempotency_key,
        confirmed_message_id=None,
    )
    db.add(item)
    db.flush()

    evidence_repo.create_evidence(
        db,
        fragment_id=item.id,
        capture_session_id=capture_session_id,
        case_id=case_id,
        ai_speaker="UNKNOWN",
        speaker_id=None,
        speaker_name=None,
        speaker_source="PENDING_ANALYSIS",
        score=None,
        second_best_score=None,
        threshold=None,
        margin=None,
        threshold_source=None,
        voiceprint_verified=False,
        low_confidence=False,
        asr_model_id=model_id,
        asr_model_version=model_version,
        speaker_model_id=None,
        speaker_model_version=None,
        speaker_model_fingerprint=None,
        microphone_fingerprint=None,
        calibration_id=None,
        calibration_status=None,
    )
    from app.services.question_recording_service import attach_targeted_fragment
    attach_targeted_fragment(db, item)
    return item, True


def get_processed(db: Session, fragment_id: str) -> ProcessedSpeechFragment | None:
    return db.get(ProcessedSpeechFragment, fragment_id)


def mark_processed(db: Session, *, fragment_id: str, case_id: str, action: str, target_id: str | None = None) -> ProcessedSpeechFragment:
    item = ProcessedSpeechFragment(fragment_id=fragment_id, case_id=case_id, action=action, target_id=target_id)
    db.add(item)
    db.flush()
    return item


def create_fragment(
    db: Session,
    *,
    capture_session_id: str,
    case_id: str,
    ordinal: int,
    started_at_ms: int,
    ended_at_ms: int,
    raw_text: str,
    speaker: str,
    speaker_source: str,
    voiceprint_verified: bool,
    low_confidence: bool,
    model_id: str,
    asr_confidence: float | None = None,
    speaker_id: str | None = None,
    speaker_name: str | None = None,
    speaker_score: float | None = None,
    second_best_score: float | None = None,
    speaker_threshold: float | None = None,
    speaker_margin: float | None = None,
    model_version: str | None = None,
    speaker_threshold_source: str | None = None,
    speaker_model_id: str | None = None,
    speaker_model_version: str | None = None,
    speaker_model_fingerprint: str | None = None,
    microphone_fingerprint: str | None = None,
) -> ASRFragment:
    if ordinal < 0 or started_at_ms < 0 or ended_at_ms < started_at_ms:
        raise DomainError("INVALID_ASR_FRAGMENT_RANGE", "ASR 片段序号或时间范围无效", 400)
    text = str(raw_text or "")
    item = ASRFragment(
        id=str(uuid4()), capture_session_id=capture_session_id, case_id=case_id, ordinal=ordinal,
        started_at_ms=started_at_ms, ended_at_ms=ended_at_ms, raw_text=text, edited_text=text,
        asr_confidence=asr_confidence, speaker=speaker, speaker_id=speaker_id, speaker_name=speaker_name,
        speaker_score=speaker_score, second_best_score=second_best_score, speaker_threshold=speaker_threshold,
        speaker_margin=speaker_margin, speaker_source=speaker_source, voiceprint_verified=voiceprint_verified,
        low_confidence=low_confidence, state="PENDING", model_id=model_id, model_version=model_version,
        confirmed_message_id=None,
    )
    db.add(item)
    db.flush()

    snapshot = calibration_repo.get_session_snapshot(db, capture_session_id)
    threshold_source = speaker_threshold_source or (snapshot.threshold_source if snapshot is not None else None)
    if speaker_model_fingerprint is None and snapshot is not None:
        speaker_model_fingerprint = snapshot.speaker_model_fingerprint
    if microphone_fingerprint is None and snapshot is not None:
        microphone_fingerprint = snapshot.microphone_fingerprint
    speaker_model_id = speaker_model_id or "eres2net_large"
    speaker_model_version = speaker_model_version or os.environ.get("SUSPECT_XVECTOR_MODEL_VERSION", "local")

    evidence_repo.create_evidence(
        db,
        fragment_id=item.id,
        capture_session_id=capture_session_id,
        case_id=case_id,
        ai_speaker=item.speaker,
        speaker_id=item.speaker_id,
        speaker_name=item.speaker_name,
        speaker_source=item.speaker_source,
        score=item.speaker_score,
        second_best_score=item.second_best_score,
        threshold=item.speaker_threshold,
        margin=item.speaker_margin,
        threshold_source=threshold_source,
        voiceprint_verified=item.voiceprint_verified,
        low_confidence=item.low_confidence,
        asr_model_id=item.model_id,
        asr_model_version=item.model_version,
        speaker_model_id=speaker_model_id,
        speaker_model_version=speaker_model_version,
        speaker_model_fingerprint=speaker_model_fingerprint,
        microphone_fingerprint=microphone_fingerprint,
        calibration_id=None if snapshot is None else snapshot.calibration_id,
        calibration_status=None if snapshot is None else snapshot.calibration_status,
    )

    # Keep the cross-cutting audit event for operational traceability. The
    # authoritative immutable recognition evidence now lives in its own table.
    audit_repo.add(
        db,
        case_id=case_id,
        action="ASR_SPEAKER_DECISION",
        target_type="ASR_FRAGMENT",
        target_id=item.id,
        after={
            "speaker": item.speaker,
            "speaker_id": item.speaker_id,
            "speaker_name": item.speaker_name,
            "speaker_source": item.speaker_source,
            "voiceprint_verified": item.voiceprint_verified,
            "low_confidence": item.low_confidence,
        },
        detail={
            "score": item.speaker_score,
            "second_best_score": item.second_best_score,
            "threshold": item.speaker_threshold,
            "margin": item.speaker_margin,
            "threshold_source": threshold_source,
            "asr_model_id": item.model_id,
            "asr_model_version": item.model_version,
            "speaker_model_id": speaker_model_id,
            "speaker_model_version": speaker_model_version,
            "speaker_model_fingerprint": speaker_model_fingerprint,
            "microphone_fingerprint": microphone_fingerprint,
            "calibration_id": None if snapshot is None else snapshot.calibration_id,
            "calibration_status": None if snapshot is None else snapshot.calibration_status,
        },
    )
    from app.services.question_recording_service import attach_targeted_fragment
    attach_targeted_fragment(db, item)
    return item


def update_fragment(
    db: Session,
    *,
    fragment_id: str,
    edited_text: str,
    speaker: str,
    speaker_id: str | None,
    speaker_name: str | None,
    speaker_source: str,
    voiceprint_verified: bool,
    low_confidence: bool,
    actor_id: str | None = None,
    reason: str | None = None,
) -> ASRFragment:
    item = get_fragment(db, fragment_id)
    if item.state == "CONFIRMED":
        raise DomainError("ASR_FRAGMENT_ALREADY_CONFIRMED", "已确认的 ASR 片段不能直接修改", 409)
    before_speaker = item.speaker
    before_text = item.edited_text
    after_text = str(edited_text or "")
    evidence_repo.append_revision(
        db,
        fragment_id=item.id,
        case_id=item.case_id,
        before_speaker=before_speaker,
        after_speaker=speaker,
        before_text=before_text,
        after_text=after_text,
        actor_id=actor_id,
        reason=reason,
    )
    item.edited_text = after_text
    item.speaker = speaker
    item.speaker_id = speaker_id
    item.speaker_name = speaker_name
    item.speaker_source = speaker_source
    item.voiceprint_verified = voiceprint_verified
    item.low_confidence = low_confidence
    item.state = "EDITED"
    db.flush()
    return item


def confirm_fragment(db: Session, *, fragment_id: str, message_id: str) -> ASRFragment:
    item = get_fragment(db, fragment_id)
    if db.get(Message, message_id) is None:
        raise DomainError("QA_NOT_FOUND", "正式问答记录不存在", 404)
    item.confirmed_message_id = message_id
    item.state = "CONFIRMED"
    db.flush()
    return item


def create_speaker_analysis_result(
    db: Session,
    *,
    analysis_job_id: str,
    fragment_id: str,
    decision: SpeakerDecision,
    threshold_source: str,
    calibration_id: str | None,
    calibration_status: str | None,
    overlap: bool,
    usable_duration_ms: int,
    model_id: str | None,
    model_version: str | None,
    model_fingerprint: str | None,
    microphone_fingerprint: str | None,
) -> ASRSpeakerAnalysisResult:
    row = ASRSpeakerAnalysisResult(
        id=str(uuid4()),
        analysis_job_id=analysis_job_id,
        fragment_id=fragment_id,
        role=decision.role.value,
        speaker_id=decision.speaker_id,
        speaker_name=decision.speaker_name,
        speaker_source=decision.source.value,
        score=decision.score,
        second_best_score=decision.second_best_score,
        threshold=decision.threshold,
        margin=decision.margin,
        threshold_source=threshold_source,
        calibration_id=calibration_id,
        calibration_status=calibration_status,
        voiceprint_verified=decision.voiceprint_verified,
        low_confidence=decision.low_confidence,
        overlap=bool(overlap),
        usable_duration_ms=max(0, int(usable_duration_ms)),
        model_id=model_id,
        model_version=model_version,
        model_fingerprint=model_fingerprint,
        microphone_fingerprint=microphone_fingerprint,
    )
    db.add(row)
    db.flush()
    return row


def add_fragment_lineage(
    db: Session,
    *,
    analysis_job_id: str,
    parent_fragment_id: str,
    child_fragment_id: str,
) -> ASRFragmentLineage:
    row = ASRFragmentLineage(
        id=str(uuid4()),
        analysis_job_id=analysis_job_id,
        parent_fragment_id=parent_fragment_id,
        child_fragment_id=child_fragment_id,
        relation="SUPERSEDES",
    )
    db.add(row)
    db.flush()
    return row


def list_unassigned_for_session(
    db: Session,
    case_id: str,
    session_id: str,
    *,
    limit: int = 256,
) -> list[ASRFragment]:
    stmt = (
        select(ASRFragment)
        .join(ASRCaptureSession, ASRCaptureSession.id == ASRFragment.capture_session_id)
        .where(
            ASRFragment.case_id == case_id,
            ASRCaptureSession.interrogation_session_id == session_id,
            *_qwen_route_eligibility_filters(),
        )
        .order_by(
            ASRCaptureSession.started_at.asc(),
            ASRCaptureSession.id.asc(),
            ASRFragment.started_at_ms.asc(),
            ASRFragment.ended_at_ms.asc(),
            ASRFragment.ordinal.asc(),
            ASRFragment.id.asc(),
        )
        .limit(max(1, min(int(limit), 4096)))
    )
    return list(db.scalars(stmt))


def list_unassigned_session_pairs(
    db: Session,
    *,
    case_ids: list[str] | None = None,
) -> list[tuple[str, str]]:
    stmt = (
        select(ASRCaptureSession.case_id, ASRCaptureSession.interrogation_session_id)
        .join(ASRFragment, ASRFragment.capture_session_id == ASRCaptureSession.id)
        .where(
            ASRCaptureSession.interrogation_session_id.is_not(None),
            *_qwen_route_eligibility_filters(),
        )
        .distinct()
    )
    if case_ids:
        stmt = stmt.where(ASRCaptureSession.case_id.in_(case_ids))
    return [
        (str(case_id), str(session_id))
        for case_id, session_id in db.execute(stmt)
        if session_id is not None
    ]


def is_qwen_route_eligible(db: Session, case_id: str, fragment_id: str) -> bool:
    return db.scalar(
        select(ASRFragment.id)
        .where(
            ASRFragment.id == fragment_id,
            ASRFragment.case_id == case_id,
            *_qwen_route_eligibility_filters(),
        )
        .limit(1)
    ) is not None


def _qwen_route_eligibility_filters():
    assigned = select(QAUnitFragment.fragment_id).where(QAUnitFragment.fragment_id == ASRFragment.id)
    originally_unknown = or_(
        select(ASRRecognitionEvidence.fragment_id).where(
            ASRRecognitionEvidence.fragment_id == ASRFragment.id,
            ASRRecognitionEvidence.ai_speaker == "UNKNOWN",
        ).correlate(ASRFragment).exists(),
        select(ASRRecognitionRevision.fragment_id).where(
            ASRRecognitionRevision.fragment_id == ASRFragment.id,
            ASRRecognitionRevision.before_speaker == "UNKNOWN",
        ).correlate(ASRFragment).exists(),
    )
    previously_projected = select(ProcessedSpeechFragment.fragment_id).where(
        ProcessedSpeechFragment.fragment_id == ASRFragment.id,
        or_(
            ProcessedSpeechFragment.action != "RAW_ONLY",
            and_(ProcessedSpeechFragment.action == "RAW_ONLY", ~originally_unknown),
        ),
    )
    usable_text = func.trim(func.coalesce(func.nullif(ASRFragment.edited_text, ""), ASRFragment.raw_text, ""))
    return (
        ASRFragment.speaker.in_(("INTERROGATOR", "RECORDER", "OFFICER_FALLBACK", "SUSPECT")),
        ASRFragment.state.in_(("PENDING", "EDITED")),
        usable_text != "",
        ~assigned.exists(),
        ~previously_projected.exists(),
    )
