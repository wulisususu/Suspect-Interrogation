from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.api.schemas import ActorRequest, DocumentSignRequest, SignatureRequest
from app.domain.errors import DomainError
from app.services.document_finalization_service import DocumentFinalizationService
from app.services.document_service import DocumentService

router = APIRouter(tags=["documents"])


@router.get("/cases/{case_id}/document")
def document_signing_state(case_id: str, db: Session = Depends(get_db)):
    return envelope(DocumentService(db).signing_state(case_id))


@router.get("/cases/{case_id}/document/status")
def document_status(case_id: str, db: Session = Depends(get_db)):
    return envelope(DocumentService(db).status(case_id))


@router.post("/cases/{case_id}/document/freeze")
def freeze_document(
    case_id: str,
    request: Request,
    body: ActorRequest | None = None,
    db: Session = Depends(get_db),
):
    return _finalize_document(case_id, request, body, db, success_message="笔录已冻结")


@router.post("/cases/{case_id}/document/finalize")
def finalize_document(
    case_id: str,
    request: Request,
    body: ActorRequest | None = None,
    db: Session = Depends(get_db),
):
    return _finalize_document(case_id, request, body, db, success_message="审讯已结束，笔录已冻结")


def _finalize_document(
    case_id: str,
    request: Request,
    body: ActorRequest | None,
    db: Session,
    *,
    success_message: str,
):
    capture_service = getattr(request.app.state, "asr_capture_service", None)
    if capture_service is None:
        raise DomainError("ASR_CAPTURE_UNAVAILABLE", "语音采集服务未配置，不能结束并冻结笔录", 503)
    speech_coordinator = getattr(request.app.state, "live_speech_coordinator", None)
    if speech_coordinator is None:
        raise DomainError("ASR_PROCESSING_UNAVAILABLE", "语音处理服务未配置，不能结束并冻结笔录", 503)
    actor_id = body.actor_id if body else None
    try:
        result = DocumentFinalizationService(
            db,
            capture_service=capture_service,
            routing_coordinator=getattr(request.app.state, "qa_routing_coordinator", None),
            speech_coordinator=speech_coordinator,
        ).finalize(case_id, actor_id)
    except DomainError as exc:
        db.rollback()
        from sqlalchemy import select
        from app.database.models import ASRCaptureSession
        from app.services.case_management_service import CaseManagementService

        if exc.code not in {"CASE_VOIDED", "CASE_NOT_FOUND"}:
            with request.app.state.session_factory() as interruption_db:
                capture = interruption_db.scalar(select(ASRCaptureSession).where(ASRCaptureSession.case_id == case_id)
                                                 .order_by(ASRCaptureSession.started_at.desc()).limit(1))
                try:
                    CaseManagementService(interruption_db).interrupt(
                        case_id, reason="FINALIZATION_INTERRUPTED", actor_id=actor_id,
                        question_id=capture.target_question_id if capture else None, detail=exc.code,
                    )
                    interruption_db.commit()
                except DomainError:
                    interruption_db.rollback()
        raise
    return envelope(result, success_message)


@router.post("/cases/{case_id}/document/sign")
def sign_document(case_id: str, body: DocumentSignRequest, db: Session = Depends(get_db)):
    return envelope(
        DocumentService(db).sign(
            case_id,
            signer_role=body.signer_role,
            signer_name=body.signer_name,
            image_data=body.image_data,
            strokes_json=body.strokes_json,
            actor_id=body.actor_id,
        ),
        "签名已保存",
    )


@router.get("/cases/{case_id}/signatures")
def list_signatures(case_id: str, db: Session = Depends(get_db)):
    return envelope(DocumentService(db).list_signatures(case_id))


@router.post("/cases/{case_id}/signatures")
def create_signature(case_id: str, body: SignatureRequest, db: Session = Depends(get_db)):
    return envelope(
        DocumentService(db).sign(
            case_id,
            signer_role=body.signer_role,
            signer_name=body.signer_name,
            image_data=body.image_data,
            strokes_json=body.strokes_json,
            actor_id=body.actor_id,
        ),
        "签名已保存",
    )


@router.post("/cases/{case_id}/report/generated")
def report_generated(case_id: str, body: ActorRequest | None = None, db: Session = Depends(get_db)):
    actor_id = body.actor_id if body else None
    return envelope(DocumentService(db).mark_report_generated(case_id, actor_id), "报告状态已更新")
