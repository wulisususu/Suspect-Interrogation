"""Maintain template coverage from canonical answers, never from ASR drafts."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import CaseQuestion, Fact
from app.domain.errors import DomainError

DEFAULT_ELEMENT_KEYS = frozenset({'time', 'place', 'motive', 'method', 'process', 'evidence', 'after'})


def validate_element_key(db: Session, case_id: str, value: str | None) -> str | None:
    if value is None:
        return None
    key = str(value).strip()
    from app.services.template_catalog_service import get_case_elements
    elements = get_case_elements(db, case_id)
    allowed = {item['key'] for item in elements} if elements is not None else DEFAULT_ELEMENT_KEYS
    if key not in allowed:
        raise DomainError('INVALID_ELEMENT_KEY', '要素不属于本案模板', 400)
    return key


def sync_element_coverage(db: Session, case_id: str, key: str | None) -> None:
    if not key:
        return
    fact = db.scalar(select(Fact).where(Fact.case_id == case_id, Fact.fact_key == key))
    if fact is None:
        return
    answers = [str(value).strip() for value in db.scalars(
        select(CaseQuestion.formal_answer_text).where(
            CaseQuestion.case_id == case_id, CaseQuestion.element_key == key,
            CaseQuestion.active.is_(True), CaseQuestion.section_type == 'BODY',
        ).order_by(CaseQuestion.sort_order, CaseQuestion.id)
    ) if str(value or '').strip()]
    fact.status = 'confirmed' if answers else 'pending'
    fact.value = '\n'.join(answers)
    db.flush()
