from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_hardware
from app.api.responses import envelope
from app.auth.context import current_actor_id
from app.domain.errors import DomainError
from app.services.document_mark_service import DocumentMarkService

router = APIRouter(tags=['document-fingerprint'])


@router.get('/cases/{case_id}/document/fingerprint')
def get_fingerprint(case_id: str, db: Session = Depends(get_db), hardware=Depends(get_hardware)):
    return envelope(DocumentMarkService(db, hardware).get(case_id))


@router.post('/cases/{case_id}/document/fingerprint')
def capture_fingerprint(case_id: str, db: Session = Depends(get_db), hardware=Depends(get_hardware)):
    if not current_actor_id():
        raise DomainError('AUTH_SESSION_REQUIRED', '请先验证民警身份再采集指纹', 401)
    result = DocumentMarkService(db, hardware).capture(case_id)
    db.commit()
    return envelope(result, '指纹已写入文末热区')
