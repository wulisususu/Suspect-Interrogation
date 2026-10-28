from __future__ import annotations

import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database.models import ASRCaptureSession, ASRFragment, ProcessedSpeechFragment, QuestionRound
from app.database.session import begin_sqlite_immediate
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import qa_units as qa_repo
from app.repositories import question_rounds as round_repo
from app.repositories import template_questions as question_repo
from app.services.formal_record_answer_service import FormalRecordAnswerService
from app.services.formal_record_policy import assert_formal_record_mutable, is_formal_record_immutable
from app.services.serializers import case_question_dict, iso_utc, pending_question_dict, qa_unit_dict, question_round_dict, standard_question_dict
from app.services.question_element_service import sync_element_coverage, validate_element_key

_ALLOWED_SOURCES = {"STANDARD", "CASE", "LIVE"}
_OFFICER_FRAGMENT_SPEAKERS = {"INTERROGATOR", "RECORDER", "OFFICER_FALLBACK"}
_UNSET = object()

# Wording is transcribed from the supplied Nantong Chongchuan inquiry-record samples.
# The key is versioned so later legal/template changes never rewrite frozen historical records.
_FORMAL_RECORD_TEMPLATES = {
    "SUSPECT_INQUIRY_V1": {
        "OPENING": [
            ("opening-rights", "我们是南通市公安局崇川分局的民警，现依法对你进行询问，根据有关法律规定，对我们的提问你应当如实回答，对与本案无关的问题，你有拒绝回答的权利。听清楚没有？"),
            ("opening-reason", "你因何事来公安机关？"),
            ("opening-notice", "这是《行政案件权利义务告知书》，交给你阅读。如果你不识字，我们可以向你宣读。"),
            ("opening-notice-confirm", "你看清楚了吗？有什么要求？"),
            ("opening-recusal", "你是否申请回避？"),
            ("opening-basic-info", "你的基本情况？"),
        ],
        "CLOSING": [
            ("closing-supplement", "你还有什么要补充的？"),
            ("closing-truth", "你以上说的是否属实？"),
            ("closing-review-sign", "以上笔录你仔细阅看，若无误则签字捺印？"),
        ],
    },
}

_TEMPLATE_QUESTION_ALIASES = {
    "opening-reason": [
        "你应何时来公安机关",
        "你因什么事来公安机关",
        "你为什么来公安机关",
        "你为何来公安机关",
    ],
    "opening-notice": [
        "这是行政案件权利义务告知书交给你阅读",
        "这是行政案件权利义务告知书交给你看",
    ],
    "opening-notice-confirm": [
        "你看清楚了吗有什么要求",
    ],
}


def _clean_text(value: str, *, code: str = "EMPTY_QUESTION") -> str:
    clean = str(value or "").strip()
    if not clean:
        raise DomainError(code, "问题内容不能为空", 400)
    return clean


def _clean_list(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def _load_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in value if str(item).strip()] if isinstance(value, list) else []


def _assert_round_fragment_ownership(db: Session, case_id: str, fragment_id: str, *, purpose: str, question_id: str | None = None) -> bool:
    """Honor legacy round evidence even when no processed claim was recorded."""
    candidates = db.scalars(select(QuestionRound).where(or_(
        QuestionRound.officer_fragment_id == fragment_id,
        QuestionRound.answer_fragment_ids_json.contains(json.dumps(fragment_id), autoescape=True),
    )))
    owned = False
    for row in candidates:
        is_question = row.officer_fragment_id == fragment_id
        is_answer = fragment_id in _load_list(row.answer_fragment_ids_json)
        if not is_question and not is_answer:
            continue
        if (row.case_id != case_id or row.status == "DETACHED" or row.case_question_id != question_id
                or (purpose == "QUESTION_ANSWER" and is_question)
                or (purpose == "LIVE_QUESTION" and is_answer)):
            raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "片段已有问答归属或已解除关联，不能重复使用", 409)
        owned = True
    return owned


class TemplateWorkspaceService:
    def __init__(self, db: Session):
        self.db = db

    def _assert_case_mutable(self, case_id: str):
        return assert_formal_record_mutable(self.db, case_id)

    def workspace(self, case_id: str) -> dict:
        from app.services.template_catalog_service import get_case_snapshot

        case_repo.get(self.db, case_id)
        snapshot = get_case_snapshot(self.db, case_id)
        rows = question_repo.list_case(self.db, case_id)
        rounds = round_repo.list_for_case(self.db, case_id)
        rounds_by_question: dict[str, list] = {}
        for row in rounds:
            rounds_by_question.setdefault(row.case_question_id, []).append(row)
        template_key = next((row.template_key for row in rows if row.template_key), None)
        return {
            "caseId": case_id,
            "templateKey": template_key,
            "templateSelection": None if snapshot is None else {
                "templateKey": snapshot.template_key,
                "blank": snapshot.blank,
                "snapshot": json.loads(snapshot.snapshot_json),
            },
            "questions": [case_question_dict(row, rounds=rounds_by_question.get(row.id, [])) for row in rows],
            "rounds": [question_round_dict(row) for row in rounds],
            "pendingQuestions": [pending_question_dict(row) for row in round_repo.list_pending_for_case(self.db, case_id)],
            "qaUnits": [qa_unit_dict(row) for row in qa_repo.list_for_case(self.db, case_id)],
        }

    def ensure_formal_record(self, case_id: str, *, template_key: str = "SUSPECT_INQUIRY_V1") -> dict:
        from app.services.template_catalog_service import get_case_snapshot

        case = case_repo.get(self.db, case_id)
        # A selected version is already copied into this case. Page-load ensure
        # must neither add legacy questions nor rewrite its structure.
        if get_case_snapshot(self.db, case_id) is not None:
            return self.workspace(case_id)
        template = _FORMAL_RECORD_TEMPLATES.get(template_key)
        if template is None:
            raise DomainError("FORMAL_RECORD_TEMPLATE_NOT_FOUND", "正式笔录模板不存在", 404)
        rows = question_repo.list_case(self.db, case_id)
        # The frontend calls ensure on page load. Historical frozen/signed records
        # must remain byte-for-byte stable and must never be retrofitted merely by viewing them.
        if is_formal_record_immutable(case):
            return self.workspace(case_id)
        self._assert_case_mutable(case_id)
        existing_keys = {row.template_item_key for row in rows if row.template_key == template_key}
        for section in ("OPENING", "CLOSING"):
            for item_key, text in template[section]:
                if item_key in existing_keys:
                    continue
                question_repo.create_case(
                    self.db, case_id=case_id, source="CASE", text=text, standard_question_id=None,
                    regex_patterns_json="[]", aliases_json=json.dumps(_TEMPLATE_QUESTION_ALIASES.get(item_key, []), ensure_ascii=False), section_type=section,
                    template_key=template_key, template_item_key=item_key, locked=True,
                )
        self._apply_section_order(question_repo.list_case(self.db, case_id), template_key=template_key)
        return self.workspace(case_id)

    def list_library(self, category: str | None = None) -> list[dict]:
        return [standard_question_dict(row) for row in question_repo.list_standard(self.db, category)]

    def add_case_question(
        self, case_id: str, *, text: str, source: str, standard_question_id: str | None = None,
        regex_patterns: list[str] | None = None, after_question_id: str | None = None,
        element_key: str | None = None,
    ) -> dict:
        self._assert_case_mutable(case_id)
        normalized_source = str(source or "").strip().upper()
        if normalized_source not in _ALLOWED_SOURCES:
            raise DomainError("INVALID_QUESTION_SOURCE", "无效的问题来源", 400)
        if standard_question_id is not None:
            question_repo.get_standard(self.db, standard_question_id)
        row = question_repo.create_case(
            self.db, case_id=case_id, source=normalized_source, text=_clean_text(text),
            standard_question_id=standard_question_id, regex_patterns_json=json.dumps(_clean_list(regex_patterns), ensure_ascii=False),
            aliases_json="[]", section_type="BODY", locked=False,
            element_key=validate_element_key(self.db, case_id, element_key),
        )
        rows = question_repo.list_case(self.db, case_id)
        template_key = next((item.template_key for item in rows if item.template_key), None)
        if template_key:
            body = [item for item in rows if item.section_type == "BODY" and item.id != row.id]
            insert_at = len(body)
            if after_question_id is not None:
                after = next((item for item in rows if item.id == after_question_id), None)
                if after is None:
                    raise DomainError("CASE_QUESTION_NOT_FOUND", "插入位置对应的问题不存在", 404)
                if after.section_type == "BODY":
                    insert_at = body.index(after) + 1
                elif after.section_type == "OPENING":
                    insert_at = 0
                else:
                    raise DomainError("FIXED_SECTION_BOUNDARY", "动态问题不能插入固定结尾之后", 409)
            body.insert(insert_at, row)
            fixed = [item for item in rows if item.section_type != "BODY"]
            self._apply_section_order(fixed + body, template_key=template_key, body_order=body)
        elif after_question_id is not None:
            other = [item for item in rows if item.id != row.id]
            after = next((item for item in other if item.id == after_question_id), None)
            if after is None:
                raise DomainError("CASE_QUESTION_NOT_FOUND", "插入位置对应的问题不存在", 404)
            index = other.index(after) + 1
            other.insert(index, row)
            self._apply_order(other)
        return case_question_dict(row, rounds=[])

    def create_live_question_from_fragment(
        self,
        case_id: str,
        *,
        fragment_id: str,
        after_question_id: str | None = None,
    ) -> dict:
        begin_sqlite_immediate(self.db)
        self._assert_case_mutable(case_id)
        fragment = asr_repo.get_fragment(self.db, fragment_id)
        if fragment.case_id != case_id:
            raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
        claim = asr_repo.get_processed(self.db, fragment.id)
        existing_round = round_repo.find_for_officer_fragment(self.db, case_id=case_id, fragment_id=fragment.id)
        owner_id = claim.target_id if claim is not None and claim.action == "LIVE_QUESTION" else (
            existing_round.case_question_id if existing_round is not None else None)
        _assert_round_fragment_ownership(self.db, case_id, fragment.id, purpose="LIVE_QUESTION", question_id=owner_id)
        if claim is not None and claim.action not in {"RAW_ONLY", "LIVE_QUESTION"}:
            raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "片段已归属于其他笔录操作", 409)
        if claim is not None and claim.action == "LIVE_QUESTION":
            question = question_repo.get_case(self.db, case_id, claim.target_id)
            rounds = round_repo.list_for_question(self.db, case_id, question.id)
            round_row = next((row for row in rounds if row.officer_fragment_id == fragment.id), None)
            return {"question": case_question_dict(question, rounds=rounds),
                    "round": None if round_row is None else question_round_dict(round_row)}
        if existing_round is None and (fragment.state not in {"PENDING", "EDITED"} or fragment.confirmed_message_id):
            raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "片段已处理或不再可用", 409)
        if str(fragment.speaker or "UNKNOWN") not in _OFFICER_FRAGMENT_SPEAKERS:
            raise DomainError("LIVE_QUESTION_OFFICER_FRAGMENT_REQUIRED", "只有主审或记录民警的提问片段可以新建动态问题", 400)

        if existing_round is not None:
            question = question_repo.get_case(self.db, case_id, existing_round.case_question_id)
            if claim is not None:
                claim.action, claim.target_id = "LIVE_QUESTION", question.id
            else:
                asr_repo.mark_processed(self.db, fragment_id=fragment.id, case_id=case_id,
                                        action="LIVE_QUESTION", target_id=question.id)
            self.db.flush()
            return {
                "question": case_question_dict(question, rounds=[existing_round]),
                "round": question_round_dict(existing_round),
            }

        text = str(fragment.edited_text or fragment.raw_text or "").strip()
        if not text:
            raise DomainError("ASR_FRAGMENT_EMPTY", "所选语音片段没有可录入的文字", 400)
        capture = asr_repo.get_capture_session(self.db, fragment.capture_session_id)
        session_id = capture.interrogation_session_id
        pending = round_repo.find_pending_for_officer_fragment(
            self.db,
            case_id=case_id,
            fragment_id=fragment.id,
        )
        if pending is not None:
            text = pending.question_text
            session_id = pending.session_id or session_id
            buffered_answer = pending.buffered_answer_text
            buffered_fragment_ids = _load_list(pending.buffered_fragment_ids_json)
            round_status = "CLOSED" if pending.status == "DEFERRED" else "ACTIVE"
        else:
            buffered_answer = ""
            buffered_fragment_ids = []
            round_status = "ACTIVE" if session_id else "CLOSED"

        if session_id and pending is None:
            round_repo.defer_active_pending(self.db, case_id, session_id)
            round_repo.close_active(self.db, case_id, session_id)

        created = self.add_case_question(
            case_id,
            text=text,
            source="LIVE",
            after_question_id=after_question_id,
        )
        round_row = round_repo.create_round(
            self.db,
            case_id=case_id,
            session_id=session_id,
            case_question_id=created["id"],
            actual_question_text=text,
            officer_fragment_id=fragment.id,
            answer_text=buffered_answer,
            answer_fragment_ids=buffered_fragment_ids,
            status=round_status,
        )
        if pending is not None:
            pending.status = "ADDED"
        question = question_repo.get_case(self.db, case_id, created["id"])
        question_repo.set_canonical_answer(
            self.db,
            question,
            answer_text=round_row.answer_text,
            first_asked_at=round_row.started_at,
        )
        if claim is not None:
            claim.action, claim.target_id = "LIVE_QUESTION", question.id
        else:
            asr_repo.mark_processed(self.db, fragment_id=fragment.id, case_id=case_id,
                                    action="LIVE_QUESTION", target_id=question.id)
        self.db.flush()
        return {
            "question": case_question_dict(question, rounds=[round_row]),
            "round": question_round_dict(round_row),
        }

    def update_case_question(self, case_id: str, question_id: str, *, text: str | None = None, regex_patterns: list[str] | None = None, element_key=_UNSET) -> dict:
        self._assert_case_mutable(case_id)
        row = question_repo.get_case(self.db, case_id, question_id)
        if row.locked and (text is not None or regex_patterns is not None or element_key is not _UNSET):
            raise DomainError("FIXED_QUESTION_LOCKED", "固定笔录问题不可修改", 409)
        if text is not None:
            clean = _clean_text(text)
            if clean != row.text:
                aliases = _load_list(row.aliases_json)
                if row.text not in aliases:
                    aliases.append(row.text)
                row.aliases_json = json.dumps([alias for alias in aliases if alias != clean], ensure_ascii=False)
                row.text = clean
        if regex_patterns is not None:
            row.regex_patterns_json = json.dumps(_clean_list(regex_patterns), ensure_ascii=False)
        old_key = row.element_key
        if element_key is not _UNSET:
            row.element_key = validate_element_key(self.db, case_id, element_key)
        self.db.flush()
        if old_key != row.element_key:
            sync_element_coverage(self.db, case_id, old_key)
            sync_element_coverage(self.db, case_id, row.element_key)
        return case_question_dict(row, rounds=round_repo.list_for_question(self.db, case_id, row.id))

    def upsert_case_question_answer(self, case_id: str, question_id: str, *, answer_text: str) -> dict:
        return FormalRecordAnswerService(self.db).upsert(case_id, question_id, answer_text=answer_text)

    def attach_case_question_answer_fragments(
        self,
        case_id: str,
        question_id: str,
        *,
        fragment_ids: list[str],
        draft: bool = False,
        replace: bool = False,
    ) -> dict:
        """Attach ASR fragments as the answer of one question.

        ``draft`` keeps the text on the question's round only (待摘入), so the officer
        can edit it before it is written into the formal record; ``replace`` starts the
        round answer over (重录这题) instead of appending to it.
        """
        begin_sqlite_immediate(self.db)
        self._assert_case_mutable(case_id)
        question = question_repo.get_case(self.db, case_id, question_id)
        requested_ids: list[str] = []
        for value in fragment_ids:
            fragment_id = str(value or "").strip()
            if fragment_id and fragment_id not in requested_ids:
                requested_ids.append(fragment_id)
        if not requested_ids:
            raise DomainError("ASR_FRAGMENT_REQUIRED", "至少选择一个语音片段", 400)

        fragments: list[tuple[str, str, str]] = []
        for fragment_id in requested_ids:
            fragment = asr_repo.get_fragment(self.db, fragment_id)
            if fragment.case_id != case_id:
                raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
            claim = asr_repo.get_processed(self.db, fragment.id)
            capture = asr_repo.get_capture_session(self.db, fragment.capture_session_id)
            if capture.case_id != case_id:
                raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
            legacy_owned = _assert_round_fragment_ownership(self.db, case_id, fragment.id,
                purpose="QUESTION_ANSWER", question_id=question_id)
            if (fragment.state not in {"PENDING", "EDITED"} and not (legacy_owned and fragment.state == "CONFIRMED")) or (fragment.confirmed_message_id and not legacy_owned):
                raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "片段已处理或不再可用", 409)
            if (claim is not None and claim.action != "RAW_ONLY" and
                    not (claim.action == "QUESTION_ANSWER" and claim.target_id == question_id)) or (
                    capture.target_question_id is not None and capture.target_question_id != question_id):
                raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "片段已归属于其他题目或笔录操作", 409)
            text = str(fragment.edited_text or fragment.raw_text or "").strip()
            if text:
                fragments.append((fragment.id, text, fragment.capture_session_id))
        if not fragments:
            raise DomainError("ASR_FRAGMENT_EMPTY", "所选语音片段没有可录入的文字", 400)

        round_row = round_repo.latest_for_question(self.db, case_id, question_id)
        if round_row is not None and replace:
            # 重录：旧草稿片段标为丢弃（行保留可追溯），不再挡住定稿冻结。
            for old_id in _load_list(round_row.answer_fragment_ids_json):
                if old_id in requested_ids:
                    continue
                old = asr_repo.get_fragment(self.db, old_id)
                if old.case_id == case_id and old.state not in ("CONFIRMED", "SUPERSEDED"):
                    old.state = "DISCARDED"
            round_repo.reset_round_answer(self.db, round_row)
        existing_ids = set(_load_list(round_row.answer_fragment_ids_json)) if round_row is not None else set()
        new_fragments = [item for item in fragments if item[0] not in existing_ids]
        if round_row is None:
            capture = asr_repo.get_capture_session(self.db, fragments[0][2])
            round_row = round_repo.create_round(
                self.db,
                case_id=case_id,
                session_id=capture.interrogation_session_id,
                case_question_id=question_id,
                actual_question_text=question.text,
                officer_fragment_id=None,
                answer_text="".join(item[1] for item in new_fragments),
                answer_fragment_ids=[item[0] for item in new_fragments],
                status="CLOSED",
            )
        elif new_fragments:
            round_repo.append_round_answer(
                self.db,
                round_row,
                "".join(item[1] for item in new_fragments),
                [item[0] for item in new_fragments],
            )

        for fragment_id, _text, _capture_id in fragments:
            claim = asr_repo.get_processed(self.db, fragment_id)
            if claim is None:
                asr_repo.mark_processed(self.db, fragment_id=fragment_id, case_id=case_id,
                                        action="QUESTION_ANSWER", target_id=question_id)
            else:
                claim.action, claim.target_id = "QUESTION_ANSWER", question_id
        self.db.flush()

        if not draft:
            question_repo.set_canonical_answer(
                self.db,
                question,
                answer_text=round_row.answer_text,
                first_asked_at=round_row.started_at,
            )
        return question_round_dict(round_row)

    def create_live_question_from_fragments(
        self, case_id: str, *, fragment_ids: list[str], after_question_id: str | None = None,
    ) -> dict:
        begin_sqlite_immediate(self.db)
        self._assert_case_mutable(case_id)
        ids = _clean_list(fragment_ids)
        if not ids:
            raise DomainError("ASR_FRAGMENT_REQUIRED", "至少选择一个语音片段", 400)
        fragments = []
        claims = []
        for fragment_id in ids:
            fragment = asr_repo.get_fragment(self.db, fragment_id)
            if fragment.case_id != case_id:
                raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
            claim = asr_repo.get_processed(self.db, fragment_id)
            _assert_round_fragment_ownership(self.db, case_id, fragment_id, purpose="LIVE_QUESTION",
                question_id=claim.target_id if claim is not None and claim.action == "LIVE_QUESTION" else None)
            fragments.append(fragment)
            claims.append(claim)
        consumed = [row for row in claims if row is not None and row.action != "RAW_ONLY"]
        if consumed:
            targets = {row.target_id for row in consumed}
            if len(consumed) == len(ids) and len(targets) == 1 and all(row.action == "LIVE_QUESTION" for row in consumed):
                target_id = next(iter(targets))
                claimed_ids = set(self.db.scalars(select(ProcessedSpeechFragment.fragment_id).where(
                    ProcessedSpeechFragment.case_id == case_id,
                    ProcessedSpeechFragment.action == "LIVE_QUESTION",
                    ProcessedSpeechFragment.target_id == target_id,
                )))
                if claimed_ids == set(ids):
                    return {"question": case_question_dict(question_repo.get_case(self.db, case_id, target_id)), "fragmentIds": ids}
            raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "语音片段已用于其他笔录操作", 409)
        for fragment in fragments:
            if fragment.state not in {"PENDING", "EDITED"} or fragment.confirmed_message_id:
                raise DomainError("ASR_FRAGMENT_ALREADY_PROCESSED", "语音片段已处理或不再可用", 409)
        captures = {row.id: row for row in self.db.scalars(select(ASRCaptureSession).where(
            ASRCaptureSession.id.in_({row.capture_session_id for row in fragments}),
        ))}
        fragments.sort(key=lambda row: (iso_utc(captures[row.capture_session_id].started_at), row.capture_session_id,
                                       row.started_at_ms, row.ended_at_ms, row.ordinal, row.id))
        text = "".join(str(row.edited_text or row.raw_text or "").strip() for row in fragments)
        if not text:
            raise DomainError("ASR_FRAGMENT_EMPTY", "所选语音片段没有可录入的文字", 400)
        # Validate the insertion point before allocating any question or claim.
        if after_question_id is not None:
            after = question_repo.get_case(self.db, case_id, after_question_id)
            if after.section_type == "CLOSING":
                raise DomainError("FIXED_SECTION_BOUNDARY", "动态问题不能插入固定结尾之后", 409)
        with self.db.begin_nested():
            created = self.add_case_question(case_id, text=text, source="LIVE", after_question_id=after_question_id)
            for fragment, claim in zip([asr_repo.get_fragment(self.db, value) for value in ids], claims):
                if claim is not None:
                    claim.action, claim.target_id = "LIVE_QUESTION", created["id"]
                else:
                    asr_repo.mark_processed(self.db, fragment_id=fragment.id, case_id=case_id,
                                            action="LIVE_QUESTION", target_id=created["id"])
            self.db.flush()
        return {"question": created, "fragmentIds": [row.id for row in fragments]}

    def deactivate_case_question(self, case_id: str, question_id: str) -> dict:
        begin_sqlite_immediate(self.db)
        self._assert_case_mutable(case_id)
        row = question_repo.get_case(self.db, case_id, question_id)
        if row.locked or row.section_type != "BODY":
            raise DomainError("FIXED_QUESTION_LOCKED", "固定笔录问题不可移除", 409)
        unresolved_capture = self.db.scalar(select(ASRCaptureSession.id).where(
            ASRCaptureSession.case_id == case_id,
            ASRCaptureSession.target_question_id == question_id,
            or_(ASRCaptureSession.status == "CAPTURING", ASRCaptureSession.recording_status == "INCOMPLETE",
                ASRCaptureSession.asr_status != "COMPLETE"),
        ).limit(1))
        if unresolved_capture is not None:
            raise DomainError("QUESTION_RECORDING_ACTIVE", "该题仍在录音或转写处理中，请处理完成后再移除", 409)
        row.active = False
        # Keep its historical sort_order. Active queries simply omit this row, so
        # compacting the remaining sequence is unnecessary and would make the
        # inactive row collide with the (case_id, sort_order) uniqueness constraint.
        self.db.flush()
        sync_element_coverage(self.db, case_id, row.element_key)
        result = case_question_dict(row, rounds=round_repo.list_for_question(self.db, case_id, row.id))
        result["active"] = False
        return result

    def reorder(self, case_id: str, ordered_ids: list[str]) -> list[dict]:
        self._assert_case_mutable(case_id)
        rows = question_repo.list_case(self.db, case_id)
        template_key = next((row.template_key for row in rows if row.template_key), None)
        supplied = [str(value) for value in ordered_ids]
        if len(supplied) != len(set(supplied)):
            raise DomainError("INVALID_QUESTION_ORDER", "问题排序不能重复", 400)
        if template_key:
            body = [row for row in rows if row.section_type == "BODY"]
            expected = {row.id for row in body}
            if set(supplied) != expected:
                raise DomainError("INVALID_QUESTION_ORDER", "正式笔录只能对案件动态问题排序", 400)
            by_id = {row.id: row for row in body}
            body_order = [by_id[row_id] for row_id in supplied]
            self._apply_section_order(rows, template_key=template_key, body_order=body_order)
        else:
            expected = {row.id for row in rows}
            if set(supplied) != expected:
                raise DomainError("INVALID_QUESTION_ORDER", "问题排序必须包含本案全部问题且不能重复", 400)
            by_id = {row.id: row for row in rows}
            self._apply_order([by_id[row_id] for row_id in supplied])
        return [case_question_dict(row, rounds=round_repo.list_for_question(self.db, case_id, row.id)) for row in question_repo.list_case(self.db, case_id)]

    def apply_actual_body_order(self, case_id: str) -> list[dict]:
        self._assert_case_mutable(case_id)
        rows = question_repo.list_case(self.db, case_id)
        body = [row for row in rows if row.section_type == "BODY"]
        asked = sorted(
            [row for row in body if row.first_asked_at is not None],
            key=lambda row: (row.first_asked_at, row.sort_order),
        )
        unasked = sorted(
            [row for row in body if row.first_asked_at is None],
            key=lambda row: row.sort_order,
        )
        body_order = asked + unasked
        template_key = next((row.template_key for row in rows if row.template_key), None)
        if template_key:
            self._apply_section_order(rows, template_key=template_key, body_order=body_order)
        else:
            non_body = [row for row in rows if row.section_type != "BODY"]
            self._apply_order(non_body + body_order)
        return [
            case_question_dict(row, rounds=round_repo.list_for_question(self.db, case_id, row.id))
            for row in question_repo.list_case(self.db, case_id)
        ]

    def save_to_library(self, case_id: str, question_id: str, category: str) -> dict:
        self._assert_case_mutable(case_id)
        row = question_repo.get_case(self.db, case_id, question_id)
        if row.locked:
            raise DomainError("FIXED_QUESTION_LOCKED", "固定模板问题无需保存到常用问题库", 409)
        standard = question_repo.create_standard(
            self.db, text=row.text, category=str(category or "通用").strip() or "通用",
            regex_patterns_json=row.regex_patterns_json or "[]", aliases_json=row.aliases_json or "[]",
        )
        row.standard_question_id = standard.id
        self.db.flush()
        return standard_question_dict(standard)

    def _apply_section_order(self, rows: list, *, template_key: str, body_order: list | None = None) -> None:
        template = _FORMAL_RECORD_TEMPLATES.get(template_key, _FORMAL_RECORD_TEMPLATES["SUSPECT_INQUIRY_V1"])
        item_rank = {key: index for section in ("OPENING", "CLOSING") for index, (key, _) in enumerate(template[section])}
        opening = sorted([row for row in rows if row.section_type == "OPENING"], key=lambda row: item_rank.get(row.template_item_key, 999))
        closing = sorted([row for row in rows if row.section_type == "CLOSING"], key=lambda row: item_rank.get(row.template_item_key, 999))
        body = body_order if body_order is not None else [row for row in rows if row.section_type == "BODY"]
        self._apply_order(opening + list(body) + closing)

    def _apply_order(self, rows: list) -> None:
        if not rows:
            return
        from app.database.models import CaseQuestion

        # Inactive questions remain as evidence, and share the same unique order
        # constraint. Reassign their positions along with the visible questions.
        all_rows = list(self.db.scalars(select(CaseQuestion).where(CaseQuestion.case_id == rows[0].case_id)))
        visible_ids = {row.id for row in rows}
        inactive = [row for row in all_rows if row.id not in visible_ids]
        ordered = rows + sorted(inactive, key=lambda row: (row.sort_order, row.id))
        low = min([row.sort_order for row in all_rows] + [0]) - (len(ordered) + 1) * 10
        for index, row in enumerate(ordered, start=1):
            row.sort_order = low - index * 10
        self.db.flush()
        for index, row in enumerate(ordered, start=1):
            row.sort_order = index * 10
        self.db.flush()
