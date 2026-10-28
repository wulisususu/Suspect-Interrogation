from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import qa_units as qa_repo
from app.repositories import question_rounds as round_repo
from app.repositories import template_questions as question_repo
from app.services.formal_record_answer_service import FormalRecordAnswerService
from app.services.formal_record_policy import assert_formal_record_mutable, is_formal_record_immutable
from app.services.serializers import case_question_dict, pending_question_dict, qa_unit_dict, question_round_dict, standard_question_dict

_ALLOWED_SOURCES = {"STANDARD", "CASE", "LIVE"}
_OFFICER_FRAGMENT_SPEAKERS = {"INTERROGATOR", "RECORDER", "OFFICER_FALLBACK"}

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


class TemplateWorkspaceService:
    def __init__(self, db: Session):
        self.db = db

    def _assert_case_mutable(self, case_id: str):
        return assert_formal_record_mutable(self.db, case_id)

    def workspace(self, case_id: str) -> dict:
        case_repo.get(self.db, case_id)
        rows = question_repo.list_case(self.db, case_id)
        rounds = round_repo.list_for_case(self.db, case_id)
        rounds_by_question: dict[str, list] = {}
        for row in rounds:
            rounds_by_question.setdefault(row.case_question_id, []).append(row)
        template_key = next((row.template_key for row in rows if row.template_key), None)
        return {
            "caseId": case_id,
            "templateKey": template_key,
            "questions": [case_question_dict(row, rounds=rounds_by_question.get(row.id, [])) for row in rows],
            "rounds": [question_round_dict(row) for row in rounds],
            "pendingQuestions": [pending_question_dict(row) for row in round_repo.list_pending_for_case(self.db, case_id)],
            "qaUnits": [qa_unit_dict(row) for row in qa_repo.list_for_case(self.db, case_id)],
        }

    def ensure_formal_record(self, case_id: str, *, template_key: str = "SUSPECT_INQUIRY_V1") -> dict:
        case = case_repo.get(self.db, case_id)
        template = _FORMAL_RECORD_TEMPLATES.get(template_key)
        if template is None:
            raise DomainError("FORMAL_RECORD_TEMPLATE_NOT_FOUND", "正式笔录模板不存在", 404)
        rows = question_repo.list_case(self.db, case_id)
        # The frontend calls ensure on page load. Historical frozen/signed records
        # must remain byte-for-byte stable and must never be retrofitted merely by viewing them.
        if is_formal_record_immutable(case):
            return self.workspace(case_id)
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
        self._assert_case_mutable(case_id)
        fragment = asr_repo.get_fragment(self.db, fragment_id)
        if fragment.case_id != case_id:
            raise DomainError("ASR_FRAGMENT_NOT_FOUND", "ASR 临时片段不存在", 404)
        if str(fragment.speaker or "UNKNOWN") not in _OFFICER_FRAGMENT_SPEAKERS:
            raise DomainError("LIVE_QUESTION_OFFICER_FRAGMENT_REQUIRED", "只有主审或记录民警的提问片段可以新建动态问题", 400)

        existing_round = round_repo.find_for_officer_fragment(
            self.db,
            case_id=case_id,
            fragment_id=fragment.id,
        )
        if existing_round is not None:
            question = question_repo.get_case(self.db, case_id, existing_round.case_question_id)
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
        return {
            "question": case_question_dict(question, rounds=[round_row]),
            "round": question_round_dict(round_row),
        }

    def update_case_question(self, case_id: str, question_id: str, *, text: str | None = None, regex_patterns: list[str] | None = None) -> dict:
        self._assert_case_mutable(case_id)
        row = question_repo.get_case(self.db, case_id, question_id)
        if row.locked and (text is not None or regex_patterns is not None):
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
        self.db.flush()
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

        if not draft:
            question_repo.set_canonical_answer(
                self.db,
                question,
                answer_text=round_row.answer_text,
                first_asked_at=round_row.started_at,
            )
        return question_round_dict(round_row)

    def deactivate_case_question(self, case_id: str, question_id: str) -> dict:
        self._assert_case_mutable(case_id)
        row = question_repo.get_case(self.db, case_id, question_id)
        if row.locked or row.section_type != "BODY":
            raise DomainError("FIXED_QUESTION_LOCKED", "固定笔录问题不可移除", 409)
        row.active = False
        # Keep its historical sort_order. Active queries simply omit this row, so
        # compacting the remaining sequence is unnecessary and would make the
        # inactive row collide with the (case_id, sort_order) uniqueness constraint.
        self.db.flush()
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
        template = _FORMAL_RECORD_TEMPLATES[template_key]
        item_rank = {key: index for section in ("OPENING", "CLOSING") for index, (key, _) in enumerate(template[section])}
        opening = sorted([row for row in rows if row.section_type == "OPENING"], key=lambda row: item_rank.get(row.template_item_key, 999))
        closing = sorted([row for row in rows if row.section_type == "CLOSING"], key=lambda row: item_rank.get(row.template_item_key, 999))
        body = body_order if body_order is not None else [row for row in rows if row.section_type == "BODY"]
        self._apply_order(opening + list(body) + closing)

    def _apply_order(self, rows: list) -> None:
        for index, row in enumerate(rows, start=1):
            row.sort_order = -(index * 10)
        self.db.flush()
        for index, row in enumerate(rows, start=1):
            row.sort_order = index * 10
        self.db.flush()
