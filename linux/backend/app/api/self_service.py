from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.services.self_service import SelfServiceService


router = APIRouter(tags=['self-service'])


class SelfServiceEventRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    kind: Literal['IDENTITY_CONFIRM', 'ANSWER_CONFIRM', 'ANSWER_UNCONFIRM', 'HANDOVER']
    question_id: str | None = Field(default=None, alias='questionId', max_length=64)


@router.get('/cases/{case_id}/self-service')
def get_self_service_state(case_id: str, db: Session = Depends(get_db)):
    return envelope(SelfServiceService(db).state(case_id))


@router.post('/cases/{case_id}/self-service/events')
def record_self_service_event(case_id: str, body: SelfServiceEventRequest, db: Session = Depends(get_db)):
    result = SelfServiceService(db).record(case_id, body.kind, body.question_id)
    db.commit()
    return envelope(result, '已记录本人确认')
