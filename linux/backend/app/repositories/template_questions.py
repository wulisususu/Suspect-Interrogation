from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import CaseQuestion, StandardQuestion
from app.domain.errors import DomainError


def list_standard(db: Session, category: str | None = None) -> list[StandardQuestion]:
    stmt = select(StandardQuestion).where(StandardQuestion.active.is_(True))
    if category:
        stmt = stmt.where(StandardQuestion.category == category)
    stmt = stmt.order_by(StandardQuestion.sort_order.asc(), StandardQuestion.created_at.asc())
    return list(db.scalars(stmt))


def get_standard(db: Session, question_id: str) -> StandardQuestion:
    row = db.get(StandardQuestion, question_id)
    if row is None or not row.active:
        raise DomainError("STANDARD_QUESTION_NOT_FOUND", "标准问题不存在", 404)
    return row


def next_standard_sort_order(db: Session) -> int:
    current = db.scalar(select(func.coalesce(func.max(StandardQuestion.sort_order), 0))) or 0
    return int(current) + 10


def create_standard(db: Session, *, text: str, category: str, regex_patterns_json: str, aliases_json: str) -> StandardQuestion:
    row = StandardQuestion(
        id=str(uuid4()), text=text, category=category, regex_patterns_json=regex_patterns_json,
        aliases_json=aliases_json, sort_order=next_standard_sort_order(db), active=True,
    )
    db.add(row)
    db.flush()
    return row


def list_case(db: Session, case_id: str) -> list[CaseQuestion]:
    stmt = (
        select(CaseQuestion)
        .where(CaseQuestion.case_id == case_id, CaseQuestion.active.is_(True))
        .order_by(CaseQuestion.sort_order.asc(), CaseQuestion.created_at.asc())
    )
    return list(db.scalars(stmt))


def get_case(db: Session, case_id: str, question_id: str) -> CaseQuestion:
    row = db.scalar(select(CaseQuestion).where(
        CaseQuestion.id == question_id, CaseQuestion.case_id == case_id, CaseQuestion.active.is_(True),
    ))
    if row is None:
        raise DomainError("CASE_QUESTION_NOT_FOUND", "本案问题不存在", 404)
    return row


def next_case_sort_order(db: Session, case_id: str) -> int:
    current = db.scalar(select(func.coalesce(func.max(CaseQuestion.sort_order), 0)).where(CaseQuestion.case_id == case_id)) or 0
    return int(current) + 10


def create_case(
    db: Session, *, case_id: str, source: str, text: str, standard_question_id: str | None,
    regex_patterns_json: str, aliases_json: str, section_type: str = "BODY",
    template_key: str | None = None, template_item_key: str | None = None, locked: bool = False,
    element_key: str | None = None,
) -> CaseQuestion:
    row = CaseQuestion(
        id=str(uuid4()), case_id=case_id, source=source, standard_question_id=standard_question_id, text=text,
        regex_patterns_json=regex_patterns_json, aliases_json=aliases_json, section_type=section_type,
        template_key=template_key, template_item_key=template_item_key, locked=locked,
        element_key=element_key,
        sort_order=next_case_sort_order(db, case_id), active=True,
    )
    db.add(row)
    db.flush()
    return row


def set_canonical_answer(
    db: Session,
    row: CaseQuestion,
    *,
    answer_text: str,
    first_asked_at: datetime | None = None,
) -> CaseQuestion:
    row.formal_answer_text = str(answer_text or "").strip()
    if row.first_asked_at is None and first_asked_at is not None:
        row.first_asked_at = first_asked_at
    db.flush()
    from app.services.question_element_service import sync_element_coverage
    sync_element_coverage(db, row.case_id, row.element_key)
    return row
