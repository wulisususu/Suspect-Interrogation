from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database.models import ProcessedSpeechFragment
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import question_rounds as rounds_repo
from app.repositories import recognition_evidence as evidence_repo
from app.repositories import template_questions as question_repo
from app.services.formal_record_policy import assert_formal_record_mutable
from app.services.question_matching import (
    QuestionCandidate,
    QuestionMatchStatus,
    is_question_utterance,
    match_question,
)
from app.services.serializers import pending_question_dict, question_round_dict
from app.services.template_workspace_service import TemplateWorkspaceService


_OFFICER_SPEAKERS = {"INTERROGATOR", "RECORDER", "OFFICER_FALLBACK"}
_ALLOWED_ROUND_MODES = {"APPEND_EXISTING", "NEW_ROUND"}


def _json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


class InterrogationProjectionService:
    """Legacy deterministic regex projection compatibility path.

    Production ASR capture reaches this service only when
    ``formal_routing_mode == 'legacy'`` (AsrCaptureService has no Qwen fragment
    sink). The explicit ``/speech-fragments/{id}/process`` API also keeps this
    path available for rollback/manual compatibility. Qwen mode must not invoke
    it in parallel with QARoutingCoordinator, otherwise one raw fragment could
    produce two formal projections.
    """

    def __init__(self, db: Session):
        self.db = db

    def process_fragment(self, case_id: str, fragment_id: str) -> dict:
        fragment = asr_repo.get_fragment(self.db, fragment_id)
        if fragment.case_id != case_id:
            raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
        processed = asr_repo.get_processed(self.db, fragment_id)
        speaker = str(fragment.speaker or "UNKNOWN")
        may_retry_unknown = bool(
            processed is not None
            and processed.action == "RAW_ONLY"
            and speaker != "UNKNOWN"
            and self._was_previously_unknown(fragment_id)
        )
        if processed is not None and not may_retry_unknown:
            return self._processed_result(processed)
        assert_formal_record_mutable(self.db, case_id)
        capture = asr_repo.get_capture_session(self.db, fragment.capture_session_id)
        session_id = capture.interrogation_session_id
        text = str(fragment.edited_text or fragment.raw_text or "").strip()
        if not session_id or not text:
            return self._record_processed(fragment.id, case_id, "RAW_ONLY", None, existing=processed)
        if speaker == "UNKNOWN":
            return self._record_processed(fragment.id, case_id, "RAW_ONLY", None, existing=processed)
        if speaker == "SUSPECT":
            pending = rounds_repo.active_pending(self.db, case_id, session_id)
            if pending is not None:
                rounds_repo.append_pending_answer(self.db, pending, text, fragment.id)
                return self._record_processed(fragment.id, case_id, "PENDING_BUFFER", pending.id, existing=processed)
            active = rounds_repo.active_round(self.db, case_id, session_id)
            if active is not None:
                rounds_repo.append_round_answer(self.db, active, text, [fragment.id])
                question = question_repo.get_case(self.db, case_id, active.case_question_id)
                question_repo.set_canonical_answer(
                    self.db,
                    question,
                    answer_text=active.answer_text,
                    first_asked_at=active.started_at,
                )
                return self._record_processed(fragment.id, case_id, "ROUND_APPEND", active.id, existing=processed)
            return self._record_processed(fragment.id, case_id, "RAW_ONLY", None, existing=processed)
        if speaker not in _OFFICER_SPEAKERS:
            return self._record_processed(fragment.id, case_id, "RAW_ONLY", None, existing=processed)
        if not is_question_utterance(text):
            return self._record_processed(fragment.id, case_id, "RAW_ONLY", None, existing=processed)

        rounds_repo.defer_active_pending(self.db, case_id, session_id)
        rounds_repo.close_active(self.db, case_id, session_id)
        matched = match_question(text, self._question_candidates(case_id))
        if matched.status is QuestionMatchStatus.MATCHED:
            question_id = matched.matched_question_ids[0]
            prior = rounds_repo.list_for_question(self.db, case_id, question_id)
            if prior:
                pending = rounds_repo.create_pending(
                    self.db,
                    case_id=case_id,
                    session_id=session_id,
                    officer_fragment_id=fragment.id,
                    question_text=text,
                    match_status="MATCHED_EXISTING",
                    candidate_question_ids=[question_id],
                )
                return self._record_processed(fragment.id, case_id, "PENDING", pending.id, existing=processed)
            round_row = rounds_repo.create_round(
                self.db,
                case_id=case_id,
                session_id=session_id,
                case_question_id=question_id,
                actual_question_text=text,
                officer_fragment_id=fragment.id,
            )
            return self._record_processed(fragment.id, case_id, "ROUND_OPEN", round_row.id, existing=processed)

        pending = rounds_repo.create_pending(
            self.db,
            case_id=case_id,
            session_id=session_id,
            officer_fragment_id=fragment.id,
            question_text=text,
            match_status="AMBIGUOUS" if matched.status is QuestionMatchStatus.AMBIGUOUS else "UNMATCHED",
            candidate_question_ids=list(matched.matched_question_ids),
        )
        return self._record_processed(fragment.id, case_id, "PENDING", pending.id, existing=processed)

    def add_pending_as_question(self, pending_id: str, *, after_question_id: str | None = None) -> dict:
        pending = self._pending_for_action(pending_id, allow_deferred=True)
        assert_formal_record_mutable(self.db, pending.case_id)
        is_deferred = pending.status == "DEFERRED"
        after_id = after_question_id or self._last_formal_question_id(pending.case_id, pending.session_id)
        created = TemplateWorkspaceService(self.db).add_case_question(
            pending.case_id,
            text=pending.question_text,
            source="LIVE",
            after_question_id=after_id,
        )
        round_row = rounds_repo.create_round(
            self.db,
            case_id=pending.case_id,
            session_id=pending.session_id,
            case_question_id=created["id"],
            actual_question_text=pending.question_text,
            officer_fragment_id=pending.officer_fragment_id,
            answer_text=pending.buffered_answer_text,
            answer_fragment_ids=_json_list(pending.buffered_fragment_ids_json),
            status="CLOSED" if is_deferred else "ACTIVE",
        )
        pending.status = "ADDED"
        self.db.flush()
        return question_round_dict(round_row)

    def link_pending(self, pending_id: str, case_question_id: str, *, round_mode: str) -> dict:
        pending = self._pending_for_action(pending_id, allow_deferred=True)
        assert_formal_record_mutable(self.db, pending.case_id)
        is_deferred = pending.status == "DEFERRED"
        mode = str(round_mode or "").upper()
        if mode not in _ALLOWED_ROUND_MODES:
            raise DomainError("INVALID_ROUND_MODE", "轮次处理方式无效", 400)
        question_repo.get_case(self.db, pending.case_id, case_question_id)
        if pending.session_id and not is_deferred:
            rounds_repo.close_active(self.db, pending.case_id, pending.session_id)
        if mode == "APPEND_EXISTING":
            round_row = rounds_repo.latest_for_question(self.db, pending.case_id, case_question_id)
            if round_row is None:
                raise DomainError("QUESTION_ROUND_NOT_FOUND", "没有可追加的历史问答轮次", 409)
            rounds_repo.append_round_answer(
                self.db,
                round_row,
                pending.buffered_answer_text,
                _json_list(pending.buffered_fragment_ids_json),
            )
            if not is_deferred:
                round_row.status = "ACTIVE"
                round_row.ended_at = None
                self.db.flush()
        else:
            round_row = rounds_repo.create_round(
                self.db,
                case_id=pending.case_id,
                session_id=pending.session_id,
                case_question_id=case_question_id,
                actual_question_text=pending.question_text,
                officer_fragment_id=pending.officer_fragment_id,
                answer_text=pending.buffered_answer_text,
                answer_fragment_ids=_json_list(pending.buffered_fragment_ids_json),
                status="CLOSED" if is_deferred else "ACTIVE",
            )
        pending.status = "LINKED"
        self.db.flush()
        return question_round_dict(round_row)

    def ignore_pending(self, pending_id: str) -> dict:
        pending = self._pending_for_action(pending_id, allow_deferred=True)
        assert_formal_record_mutable(self.db, pending.case_id)
        pending.status = "IGNORED"
        self.db.flush()
        return pending_question_dict(pending)

    def update_round_answer(self, round_id: str, *, answer_text: str) -> dict:
        round_row = rounds_repo.get_round(self.db, round_id)
        assert_formal_record_mutable(self.db, round_row.case_id)
        round_row.answer_text = str(answer_text or "").strip()
        self.db.flush()
        return question_round_dict(round_row)

    def reassociate_round(
        self,
        round_id: str,
        *,
        case_question_id: str | None,
        new_question_text: str | None = None,
    ) -> dict:
        round_row = rounds_repo.get_round(self.db, round_id)
        assert_formal_record_mutable(self.db, round_row.case_id)
        if case_question_id is None and not str(new_question_text or "").strip():
            round_row.status = "DETACHED"
            round_row.ended_at = datetime.now(timezone.utc)
            self.db.flush()
            return question_round_dict(round_row)
        if new_question_text is not None and str(new_question_text).strip():
            created = TemplateWorkspaceService(self.db).add_case_question(
                round_row.case_id,
                text=str(new_question_text).strip(),
                source="LIVE",
                after_question_id=round_row.case_question_id,
            )
            destination_id = created["id"]
        elif case_question_id is not None:
            question_repo.get_case(self.db, round_row.case_id, case_question_id)
            destination_id = case_question_id
        else:
            raise DomainError("REASSOCIATE_TARGET_REQUIRED", "必须选择目标问题或创建新问题", 400)
        if destination_id != round_row.case_question_id:
            destination_round_no = rounds_repo.next_round_no(self.db, destination_id)
            round_row.case_question_id = destination_id
            round_row.round_no = destination_round_no
            self.db.flush()
        return question_round_dict(round_row)

    def _pending_for_action(self, pending_id: str, *, allow_deferred: bool = False):
        pending = rounds_repo.get_pending(self.db, pending_id)
        if pending.status == "PENDING":
            return pending
        if allow_deferred and pending.status == "DEFERRED":
            return pending
        raise DomainError("PENDING_QUESTION_RESOLVED", "该待处理问题已经处理", 409)

    def _last_formal_question_id(self, case_id: str, session_id: str | None) -> str | None:
        rows = rounds_repo.list_for_case(self.db, case_id)
        if session_id is not None:
            rows = [row for row in rows if row.session_id == session_id]
        return rows[-1].case_question_id if rows else None

    def _question_candidates(self, case_id: str) -> list[QuestionCandidate]:
        result: list[QuestionCandidate] = []
        for row in question_repo.list_case(self.db, case_id):
            patterns = _json_list(row.regex_patterns_json)
            patterns.extend(f"^{re.escape(alias)}$" for alias in _json_list(row.aliases_json))
            result.append(QuestionCandidate(id=row.id, text=row.text, patterns=tuple(patterns)))
        return result

    def _record_processed(
        self,
        fragment_id: str,
        case_id: str,
        action: str,
        target_id: str | None,
        *,
        existing: ProcessedSpeechFragment | None = None,
    ) -> dict:
        if existing is None:
            row = asr_repo.mark_processed(
                self.db,
                fragment_id=fragment_id,
                case_id=case_id,
                action=action,
                target_id=target_id,
            )
        else:
            existing.action = action
            existing.target_id = target_id
            self.db.flush()
            row = existing
        return self._processed_result(row)

    def _was_previously_unknown(self, fragment_id: str) -> bool:
        evidence = evidence_repo.get_evidence(self.db, fragment_id)
        if evidence is not None and evidence.ai_speaker == "UNKNOWN":
            return True
        revisions = evidence_repo.list_revisions(self.db, fragment_id)
        return bool(revisions and revisions[-1].before_speaker == "UNKNOWN")

    def _processed_result(self, processed: ProcessedSpeechFragment) -> dict:
        if processed.action in {"QUESTION_ANSWER", "LIVE_QUESTION"} and processed.target_id:
            return {"status": processed.action, "questionId": processed.target_id}
        if processed.action == "RAW_ONLY":
            return {"status": "RAW_ONLY"}
        if processed.action in {"ROUND_OPEN", "ROUND_APPEND"} and processed.target_id:
            round_row = rounds_repo.get_round(self.db, processed.target_id)
            return {
                "status": "MATCHED" if processed.action == "ROUND_OPEN" else "ROUND_APPEND",
                "round": question_round_dict(round_row),
            }
        if processed.action in {"PENDING", "PENDING_BUFFER"} and processed.target_id:
            pending = rounds_repo.get_pending(self.db, processed.target_id)
            if processed.action == "PENDING_BUFFER":
                return {"status": "PENDING_BUFFER", "pendingQuestion": pending_question_dict(pending)}
            return {
                "status": pending.match_status,
                "candidateQuestionIds": _json_list(pending.candidate_question_ids_json),
                "pendingQuestion": pending_question_dict(pending),
            }
        raise DomainError("INVALID_PROJECTION_STATE", "正式笔录投影状态无效", 500)
