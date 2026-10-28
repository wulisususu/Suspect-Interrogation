from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.api.schemas import FormalRequest
from app.services.case_management_service import CaseManagementService
from app.services.record_validation_service import RecordValidationService


router = APIRouter(tags=["case-management"])


class InterruptionRequest(FormalRequest):
    reason: str
    question_id: str | None = Field(None, alias="questionId")
    detail: str = Field("", max_length=1000)


class VoidRequest(FormalRequest):
    reason: str = Field(min_length=1, max_length=1000)


class TimelineEvidenceRequest(FormalRequest):
    kind: str
    at: str
    source: str = Field(min_length=1, max_length=256)


class CorrectionResolutionRequest(FormalRequest):
    action: str


def _actor_id() -> str | None:
    from app.auth.context import current_actor_id
    return current_actor_id()


@router.post("/cases/{case_id}/interruption")
def record_interruption(case_id: str, body: InterruptionRequest, db: Session = Depends(get_db)):
    result = CaseManagementService(db).interrupt(case_id, reason=body.reason,
        question_id=body.question_id, detail=body.detail, actor_id=_actor_id())
    db.commit()
    return envelope(result, "中断位置已保存")


@router.get("/cases/{case_id}/management")
def get_case_management(case_id: str, db: Session = Depends(get_db)):
    return envelope(CaseManagementService(db).case_fields(case_id))


@router.post("/cases/{case_id}/void")
def void_case(case_id: str, body: VoidRequest, db: Session = Depends(get_db)):
    result = CaseManagementService(db).void(case_id, reason=body.reason, actor_id=_actor_id())
    db.commit()
    return envelope(result, "笔录已作废，原记录保留")


@router.get("/audit-logs")
def query_audit(keyword: str | None = None, created_from: datetime | None = Query(None, alias="createdFrom"),
                created_to: datetime | None = Query(None, alias="createdTo"), action: str | None = None,
                actor_id: str | None = Query(None, alias="actorId"), result: str | None = None,
                category: str | None = None, case_id: str | None = Query(None, alias="caseId"),
                page: int = Query(1, ge=1), page_size: int = Query(50, alias="pageSize", ge=1, le=200),
                db: Session = Depends(get_db)):
    return envelope(CaseManagementService(db).query_audit(keyword=keyword, created_from=created_from,
        created_to=created_to, action=action, actor_id=actor_id, result=result, category=category,
        case_id=case_id, page=page, page_size=page_size))


@router.post("/cases/{case_id}/timeline-evidence")
def add_timeline_evidence(case_id: str, body: TimelineEvidenceRequest, db: Session = Depends(get_db)):
    result = RecordValidationService(db).add_timeline_evidence(case_id, kind=body.kind, at=body.at,
                                                            source=body.source, actor_id=_actor_id())
    db.commit()
    return envelope(result, "时间证据已记录")


@router.get("/cases/{case_id}/validation")
def get_record_validation(case_id: str, db: Session = Depends(get_db)):
    service = RecordValidationService(db)
    return envelope({"timeline": service.check_timeline(case_id), "homophones": service.corrections(case_id, scan=False)})


@router.post("/cases/{case_id}/corrections/scan")
def scan_answer_corrections(case_id: str, db: Session = Depends(get_db)):
    result = RecordValidationService(db).corrections(case_id)
    db.commit()
    return envelope(result)


@router.post("/cases/{case_id}/corrections/{correction_id}/resolve")
def resolve_answer_correction(case_id: str, correction_id: str, body: CorrectionResolutionRequest,
                              db: Session = Depends(get_db)):
    result = RecordValidationService(db).resolve_correction(case_id, correction_id,
                                                          action=body.action, actor_id=_actor_id())
    db.commit()
    return envelope(result, "纠错处理已留痕")
