from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.enums import WorkflowState
from app.domain.errors import DomainError
from app.repositories import cases as case_repo


_IMMUTABLE_WORKFLOW_STATES = frozenset(
    {
        WorkflowState.FROZEN.value,
        WorkflowState.SIGNED.value,
        WorkflowState.REPORT_GENERATED.value,
    }
)


def is_formal_record_immutable(case) -> bool:
    return str(case.workflow_state or "") in _IMMUTABLE_WORKFLOW_STATES


def assert_formal_record_mutable(db: Session, case_id: str):
    from app.services.case_management_service import assert_case_not_void

    assert_case_not_void(db, case_id)
    case = case_repo.get(db, case_id)
    if is_formal_record_immutable(case):
        raise DomainError("FORMAL_RECORD_FROZEN", "正式笔录冻结后不可修改", 409)
    return case
