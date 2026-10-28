from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.base import utc_now
from app.database.case_management_models import CaseManagement
from app.database.models import ASRCaptureSession, ASRFragment, AuditLog, CaseQuestion, InterrogationSession
from app.database.officer_models import Officer
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.repositories import template_questions as question_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import audit_dict, case_dict, iso_utc


INTERRUPTION_REASONS = frozenset({"POWER_RECOVERY", "PARTY_LEFT", "NETWORK_INTERRUPTED", "FINALIZATION_INTERRUPTED"})
_COMPLETED = frozenset({"FROZEN", "SIGNED", "REPORT_GENERATED"})
_SYSTEM_PREFIXES = ("ASR_", "SPEAKER_", "VOICEPRINT_", "SESSION_VOICE_", "SUSPECT_VOICEPRINT_")


def assert_case_not_void(db: Session, case_id: str):
    case = case_repo.get(db, case_id)
    if case.workflow_state == "VOIDED" or case.document_status == "VOIDED":
        raise DomainError("CASE_VOIDED", "已作废笔录不可继续办理", 409)
    return case


def case_management_fields(db: Session, case_id: str) -> dict:
    row = db.get(CaseManagement, case_id)
    question = db.get(CaseQuestion, row.stopped_question_id) if row and row.stopped_question_id else None
    number = None
    if question is not None and question.active:
        number = db.scalar(select(func.count()).select_from(CaseQuestion).where(
            CaseQuestion.case_id == case_id, CaseQuestion.active.is_(True), CaseQuestion.sort_order <= question.sort_order,
        ))
    return {
        "interruptionReason": row.interruption_reason if row else None,
        "interruptionDetail": row.interruption_detail if row else None,
        "interruptedAt": iso_utc(row.interrupted_at) if row else None,
        "stoppedQuestionId": row.stopped_question_id if row else None,
        "stoppedQuestionNumber": number,
        "stoppedQuestionText": question.text if question is not None else None,
        "voidReason": row.void_reason if row else None,
        "voidedAt": iso_utc(row.voided_at) if row else None,
        "voidedBy": row.voided_by if row else None,
    }


def _json(raw: str) -> dict:
    try:
        result = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return result if isinstance(result, dict) else {}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class CaseManagementService:
    def __init__(self, db: Session):
        self.db = db

    def case_fields(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        return case_management_fields(self.db, case_id)

    def _management(self, case_id: str) -> CaseManagement:
        row = self.db.get(CaseManagement, case_id)
        if row is None:
            row = CaseManagement(case_id=case_id)
            self.db.add(row)
        return row

    def interrupt(self, case_id: str, *, reason: str, question_id: str | None = None,
                  detail: str = "", actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        assert_case_not_void(self.db, case_id)
        case = assert_formal_record_mutable(self.db, case_id)
        if reason not in INTERRUPTION_REASONS:
            raise DomainError("INVALID_INTERRUPTION_REASON", "无效的中断事由", 400)
        if len(detail) > 1000:
            raise DomainError("INTERRUPTION_DETAIL_TOO_LONG", "中断说明不能超过1000字", 400)
        if question_id:
            question_repo.get_case(self.db, case_id, question_id)
        row = self._management(case_id)
        row.interruption_reason = reason
        row.interruption_detail = detail.strip() or None
        row.interrupted_at = utc_now()
        row.stopped_question_id = question_id
        case.updated_at = utc_now()
        self.db.flush()
        result = self.case_fields(case_id)
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="CASE_INTERRUPTED",
                       target_type="CASE", target_id=case_id, detail=result)
        return result

    def void(self, case_id: str, *, reason: str, actor_id: str | None = None) -> dict:
        clean = str(reason or "").strip()
        if not clean:
            raise DomainError("VOID_REASON_REQUIRED", "作废必须填写原因", 400)
        if len(clean) > 1000:
            raise DomainError("VOID_REASON_TOO_LONG", "作废原因不能超过1000字", 400)
        begin_sqlite_immediate(self.db)
        case = case_repo.get(self.db, case_id)
        existing = self.db.get(CaseManagement, case_id)
        if case.workflow_state == "VOIDED":
            if existing and existing.void_reason == clean:
                return {**case_dict(case), **self.case_fields(case_id)}
            raise DomainError("CASE_ALREADY_VOIDED", "笔录已作废，原因不可改写", 409)
        if case.workflow_state in _COMPLETED or case.document_status in {"ARCHIVED", "SIGNED", "FROZEN", "LOCKED"}:
            raise DomainError("CASE_VOID_NOT_ALLOWED", "仅未完成或待定稿笔录可以作废", 409)
        active_capture = self.db.scalar(select(ASRCaptureSession.id).where(
            ASRCaptureSession.case_id == case_id,
            ASRCaptureSession.status.in_(["CAPTURING", "RUNNING", "STARTING", "RECORDING", "STOPPING", "FINALIZING"]),
        ).limit(1))
        if active_capture:
            raise DomainError("ASR_CAPTURE_ACTIVE", "请先停止并保存录音，再作废笔录", 409)
        before = case_dict(case)
        row = self._management(case_id)
        row.void_reason = clean
        row.voided_at = utc_now()
        row.voided_by = actor_id
        case.workflow_state = "VOIDED"
        case.document_status = "VOIDED"
        for session in self.db.scalars(select(InterrogationSession).where(
                InterrogationSession.case_id == case_id, InterrogationSession.status != "COMPLETED")):
            session.status = "COMPLETED"
            session.ended_at = utc_now()
        self.db.flush()
        result = {**case_dict(case), **self.case_fields(case_id)}
        audit_repo.add(self.db, case_id=case_id, action="CASE_VOID", actor_id=actor_id,
                       target_type="CASE", target_id=case_id, before=before, after=result,
                       detail={"reason": clean, "result": "SUCCESS"})
        return result

    def query_audit(self, *, keyword: str | None = None, created_from: datetime | None = None,
                    created_to: datetime | None = None, action: str | None = None,
                    actor_id: str | None = None, result: str | None = None, category: str | None = None,
                    case_id: str | None = None, page: int = 1, page_size: int = 50) -> dict:
        if page < 1 or not 1 <= page_size <= 200:
            raise DomainError("INVALID_PAGINATION", "分页参数无效", 400)
        start, end = _utc(created_from), _utc(created_to)
        if start and end and start > end:
            raise DomainError("INVALID_DATE_RANGE", "开始时间不能晚于结束时间", 400)
        if result and result not in {"SUCCESS", "FAILURE", "UNKNOWN"}:
            raise DomainError("INVALID_AUDIT_RESULT", "无效的操作结果", 400)
        if category and category not in {"SYSTEM", "BUSINESS"}:
            raise DomainError("INVALID_AUDIT_CATEGORY", "无效的日志分类", 400)
        stmt = select(AuditLog)
        filters = []
        if case_id: filters.append(AuditLog.case_id == case_id)
        if action: filters.append(AuditLog.action == action)
        if actor_id: filters.append(AuditLog.actor_id == actor_id)
        if start: filters.append(AuditLog.created_at >= start)
        if end: filters.append(AuditLog.created_at <= end)
        system = or_(*(AuditLog.action.startswith(prefix, autoescape=True) for prefix in _SYSTEM_PREFIXES))
        if category: filters.append(system if category == "SYSTEM" else ~system)
        if keyword and keyword.strip():
            stmt = stmt.outerjoin(Officer, Officer.badge_number == AuditLog.actor_id)
            term = keyword.strip()
            fields = [AuditLog.case_id, AuditLog.actor_id, AuditLog.action, AuditLog.target_type,
                      AuditLog.target_id, AuditLog.detail_json, AuditLog.before_json, AuditLog.after_json,
                      Officer.name, Officer.badge_number]
            filters.append(or_(*(column.contains(term, autoescape=True) for column in fields)))
        # Metadata is JSON but loaded in SQL via SQLite JSON extraction, preserving real pagination.
        stored_result = func.coalesce(func.json_extract(AuditLog.detail_json, "$.result"), "UNKNOWN")
        if result: filters.append(stored_result == result)
        stmt = stmt.where(*filters)
        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                               .offset((page-1)*page_size).limit(page_size))
        return {"items": [self._audit_payload(row) for row in rows], "total": total,
                "page": page, "pageSize": page_size}

    def _audit_payload(self, row: AuditLog) -> dict:
        data = audit_dict(row)
        detail = _json(row.detail_json)
        actor_name = str(detail.get("actorDisplayName") or row.actor_id or "系统自动")
        if row.actor_id:
            # Lazy import avoids coupling historical core models to officer provisioning.
            officer = self.db.get(Officer, row.actor_id)
            if officer is not None:
                actor_name = f"{officer.name}（{officer.badge_number}）"
        summary = detail.get("objectSummary")
        if not summary and row.target_type in {"CASE_QUESTION", "QUESTION"}:
            question = self.db.get(CaseQuestion, row.target_id)
            if question is not None and question.case_id == row.case_id:
                summary = f"问题：{question.text[:100]}"
        if not summary and row.target_type == "ASR_FRAGMENT":
            fragment = self.db.get(ASRFragment, row.target_id)
            if fragment is not None and fragment.case_id == row.case_id:
                summary = f"语音片段 {fragment.started_at_ms/1000:.1f}–{fragment.ended_at_ms/1000:.1f}秒"
        if not summary:
            summary = " · ".join(str(x) for x in [row.target_type, row.target_id] if x)
        return {**data, "caseId": row.case_id, "actorDisplayName": actor_name,
                "objectSummary": summary, "result": detail.get("result", "UNKNOWN"),
                "category": "SYSTEM" if row.action.startswith(_SYSTEM_PREFIXES) else "BUSINESS"}
