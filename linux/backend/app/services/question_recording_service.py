"""Attach a final ASR fragment to its persisted question in the same transaction."""
from sqlalchemy.orm import Session

from app.database.models import ASRCaptureSession
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo


def attach_targeted_fragment(db: Session, fragment) -> None:
    capture = db.get(ASRCaptureSession, fragment.capture_session_id)
    if capture is None or not capture.target_question_id or not str(fragment.edited_text or fragment.raw_text or '').strip():
        return
    existing = asr_repo.get_processed(db, fragment.id)
    if existing is not None and existing.action != 'RAW_ONLY':
        if existing.action == 'QUESTION_ANSWER' and existing.target_id == capture.target_question_id:
            return
        raise DomainError('ASR_FRAGMENT_ALREADY_PROCESSED', '片段已归属于其他笔录操作', 409)
    from app.services.template_workspace_service import TemplateWorkspaceService
    TemplateWorkspaceService(db).attach_case_question_answer_fragments(
        fragment.case_id, capture.target_question_id, fragment_ids=[fragment.id], draft=True,
        replace=capture.replace_answer and not capture.answer_replacement_applied,
    )
    capture.answer_replacement_applied = True
    db.flush()
