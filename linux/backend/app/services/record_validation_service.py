from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.base import utc_now
from app.database.case_management_models import AnswerCorrection, RecordTimelineEvidence
from app.database.models import CaseQuestion, InterrogationSession
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.repositories import cases as case_repo
from app.services.formal_record_answer_service import FormalRecordAnswerService
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.serializers import iso_utc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def configured_homophones() -> dict[str, list[str]]:
    """Explicit operator-maintained lexicon; an absent lexicon is not a passed check."""
    raw = os.environ.get("SUSPECT_HOMOPHONE_CANDIDATES_JSON", "{}")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise DomainError("CORRECTION_LEXICON_INVALID", "纠错词典配置无效", 503) from exc
    if not isinstance(value, dict) or len(value) > 10000:
        raise DomainError("CORRECTION_LEXICON_INVALID", "纠错词典配置无效", 503)
    result = {}
    for key, words in value.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 256 or not isinstance(words, list):
            raise DomainError("CORRECTION_LEXICON_INVALID", "纠错词典配置无效", 503)
        if any(not isinstance(word, str) or not word.strip() or len(word) > 256 for word in words):
            raise DomainError("CORRECTION_LEXICON_INVALID", "纠错词典配置无效", 503)
        result[key] = list(dict.fromkeys(word for word in words if word != key))
    return result


class RecordValidationService:
    def __init__(self, db: Session, *, homophones: dict[str, list[str]] | None = None):
        self.db = db
        self.homophones = configured_homophones() if homophones is None else homophones

    def add_timeline_evidence(self, case_id: str, *, kind: str, at: str, source: str,
                              actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        assert_formal_record_mutable(self.db, case_id)
        if kind not in {"EVENT", "REPORT", "QUESTIONING"}:
            raise DomainError("INVALID_TIMELINE_KIND", "无效的时间线证据类型", 400)
        try:
            parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timezone required")
        except (ValueError, TypeError, AttributeError) as exc:
            raise DomainError("INVALID_TIMELINE_TIME", "时间必须是带时区的ISO日期时间", 400) from exc
        if not source.strip() or len(source) > 256:
            raise DomainError("TIMELINE_SOURCE_REQUIRED", "请填写不超过256字的时间证据来源", 400)
        row = RecordTimelineEvidence(id=str(uuid4()), case_id=case_id, kind=kind,
                                     occurred_at=parsed.astimezone(timezone.utc), source=source.strip(), actor_id=actor_id)
        self.db.add(row)
        self.db.flush()
        result = {"id": row.id, "kind": kind, "at": iso_utc(row.occurred_at), "source": row.source}
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="TIMELINE_EVIDENCE_ADD",
                       target_type="TIMELINE_EVIDENCE", target_id=row.id, after=result)
        return result

    def check_timeline(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        items = [{"id": row.id, "kind": row.kind, "at": iso_utc(row.occurred_at), "source": row.source}
                 for row in self.db.scalars(select(RecordTimelineEvidence).where(
                     RecordTimelineEvidence.case_id == case_id).order_by(RecordTimelineEvidence.created_at, RecordTimelineEvidence.id))]
        for row in self.db.scalars(select(InterrogationSession).where(
                InterrogationSession.case_id == case_id, InterrogationSession.started_at.is_not(None))):
            items.append({"id": row.id, "kind": "QUESTIONING", "at": iso_utc(row.started_at), "source": "询问开始记录"})
        by_kind = {kind: [item for item in items if item["kind"] == kind] for kind in ["EVENT", "REPORT", "QUESTIONING"]}
        present = [kind for kind, evidence in by_kind.items() if evidence]
        conflicts = []
        for index, first in enumerate(present):
            for second in present[index+1:]:
                latest = max(by_kind[first], key=lambda x: x["at"])
                earliest = min(by_kind[second], key=lambda x: x["at"])
                if latest["at"] > earliest["at"]:
                    conflicts.append({"earlierKind": first, "laterKind": second,
                                      "earlierEvidenceId": latest["id"], "laterEvidenceId": earliest["id"]})
        status = "UNAVAILABLE" if len(present) < 2 else ("CONFLICT" if conflicts else "CONSISTENT")
        return {"status": status, "evidence": items, "conflicts": conflicts,
                "message": "至少需要两类有来源的时间证据" if status == "UNAVAILABLE" else "仅提示时间先后关系，不自动改写笔录"}

    def corrections(self, case_id: str, *, scan: bool = True) -> dict:
        if scan:
            begin_sqlite_immediate(self.db)
            assert_formal_record_mutable(self.db, case_id)
        else:
            case_repo.get(self.db, case_id)
        questions = list(self.db.scalars(select(CaseQuestion).where(
            CaseQuestion.case_id == case_id, CaseQuestion.active.is_(True))))
        by_id = {row.id: row for row in questions}
        candidates = list(self.db.scalars(select(AnswerCorrection).where(AnswerCorrection.case_id == case_id)
                                         .order_by(AnswerCorrection.created_at, AnswerCorrection.id)))
        existing = {(row.question_id, row.answer_hash, row.start_index, row.original, row.suggestion) for row in candidates}
        if scan:
            for question in questions:
                answer = question.formal_answer_text or ""
                answer_hash = _digest(answer)
                for original, words in self.homophones.items():
                    offset = 0
                    while original and (position := answer.find(original, offset)) >= 0:
                        for suggestion in words:
                            identity = (question.id, answer_hash, position, original, suggestion)
                            if identity in existing:
                                continue
                            row = AnswerCorrection(id=str(uuid4()), case_id=case_id, question_id=question.id,
                                                   answer_hash=answer_hash, start_index=position, original=original,
                                                   suggestion=suggestion, source="CONFIGURED_LEXICON", status="PENDING")
                            self.db.add(row)
                            candidates.append(row)
                            existing.add(identity)
                        offset = position + len(original)
            self.db.flush()
        items = []
        for row in candidates:
            payload = self._correction_payload(row)
            question = by_id.get(row.question_id)
            if row.status == "PENDING" and (question is None or _digest(question.formal_answer_text or "") != row.answer_hash):
                payload["status"] = "STALE"
            items.append(payload)
        return {"configured": bool(self.homophones), "items": items,
                "pending": sum(x["status"] == "PENDING" for x in items)}

    def resolve_correction(self, case_id: str, correction_id: str, *, action: str,
                           actor_id: str | None = None) -> dict:
        begin_sqlite_immediate(self.db)
        assert_formal_record_mutable(self.db, case_id)
        row = self.db.get(AnswerCorrection, correction_id)
        if row is None or row.case_id != case_id:
            raise DomainError("CORRECTION_NOT_FOUND", "纠错候选不存在", 404)
        if action not in {"ACCEPT", "IGNORE"}:
            raise DomainError("INVALID_CORRECTION_ACTION", "请选择采纳或忽略", 400)
        wanted_status = "ACCEPTED" if action == "ACCEPT" else "IGNORED"
        if row.status != "PENDING":
            if row.status == wanted_status:
                return self._correction_payload(row)
            raise DomainError("CORRECTION_ALREADY_RESOLVED", "纠错候选已处理", 409)
        question = self.db.get(CaseQuestion, row.question_id)
        if question is None or not question.active or question.case_id != case_id:
            raise DomainError("CASE_QUESTION_NOT_FOUND", "本案问题不存在", 404)
        previous = question.formal_answer_text or ""
        if _digest(previous) != row.answer_hash:
            raise DomainError("CORRECTION_STALE", "回答已修订，请重新生成纠错候选", 409)
        revised = previous
        if action == "ACCEPT":
            revised = previous[:row.start_index] + row.suggestion + previous[row.start_index+len(row.original):]
            FormalRecordAnswerService(self.db).upsert(case_id, question.id, answer_text=revised)
        row.status = wanted_status
        row.resolved_at = utc_now()
        row.resolved_by = actor_id
        self.db.flush()
        audit_repo.add(self.db, case_id=case_id, actor_id=actor_id, action="ANSWER_CORRECTION_"+action,
                       target_type="CASE_QUESTION", target_id=question.id,
                       before={"answerText": previous}, after={"answerText": revised},
                       detail={"correctionId": row.id, "original": row.original, "suggestion": row.suggestion,
                               "source": row.source, "result": "SUCCESS"})
        return self._correction_payload(row)

    @staticmethod
    def _correction_payload(row: AnswerCorrection) -> dict:
        return {"id": row.id, "caseId": row.case_id, "questionId": row.question_id,
                "original": row.original, "suggestion": row.suggestion, "startIndex": row.start_index,
                "source": row.source, "status": row.status, "createdAt": iso_utc(row.created_at),
                "resolvedAt": iso_utc(row.resolved_at), "resolvedBy": row.resolved_by}
