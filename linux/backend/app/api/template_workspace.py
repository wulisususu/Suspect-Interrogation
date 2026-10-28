from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.responses import envelope
from app.api.schemas import (
    CaseQuestionCreateRequest,
    CaseQuestionUpdateRequest,
    FragmentAnswerRequest,
    LiveQuestionFragmentRequest,
    LiveQuestionFragmentsRequest,
    PendingAddRequest,
    PendingLinkRequest,
    QuestionReorderRequest,
    QAUnitResolutionRequest,
    RoundReassociateRequest,
    RoundUpdateRequest,
    SaveQuestionToLibraryRequest,
)
from app.domain.errors import DomainError
from app.repositories import qa_units as qa_repo
from app.repositories import question_rounds as round_repo
from app.services.formal_record_routing_service import FormalRecordRoutingService
from app.services.interrogation_projection_service import InterrogationProjectionService
from app.services.template_workspace_service import TemplateWorkspaceService


router = APIRouter(tags=["template-workspace"])


def _pending_for_case(db: Session, case_id: str, pending_id: str):
    row = round_repo.get_pending(db, pending_id)
    if row.case_id != case_id:
        raise DomainError("PENDING_QUESTION_NOT_FOUND", "待处理问题不存在", 404)
    return row


def _round_for_case(db: Session, case_id: str, round_id: str):
    row = round_repo.get_round(db, round_id)
    if row.case_id != case_id:
        raise DomainError("QUESTION_ROUND_NOT_FOUND", "问答轮次不存在", 404)
    return row


def _qa_unit_for_case(db: Session, case_id: str, qa_unit_id: str):
    row = qa_repo.get(db, qa_unit_id)
    if row.case_id != case_id:
        raise DomainError("QA_UNIT_NOT_FOUND", "问答单元不存在", 404)
    return row


@router.get("/cases/{case_id}/template-workspace")
def get_template_workspace(case_id: str, db: Session = Depends(get_db)):
    return envelope(TemplateWorkspaceService(db).workspace(case_id))


@router.get("/question-library")
def get_question_library(category: str | None = Query(None), db: Session = Depends(get_db)):
    return envelope(TemplateWorkspaceService(db).list_library(category))


@router.post("/cases/{case_id}/questions")
def create_case_question(case_id: str, body: CaseQuestionCreateRequest, db: Session = Depends(get_db)):
    service = TemplateWorkspaceService(db)
    result = service.add_case_question(
        case_id,
        text=body.text,
        source=body.source,
        standard_question_id=body.standard_question_id,
        regex_patterns=body.regex_patterns,
        after_question_id=body.after_question_id,
        element_key=body.element_key,
    )
    db.commit()
    return envelope(result, "问题已加入本案笔录")


@router.post("/cases/{case_id}/questions/from-fragment")
def create_live_question_from_fragment(case_id: str, body: LiveQuestionFragmentRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).create_live_question_from_fragment(
        case_id,
        fragment_id=body.fragment_id,
        after_question_id=body.after_question_id,
    )
    db.commit()
    return envelope(result, "实时问题已加入正式笔录")


@router.patch("/cases/{case_id}/questions/{question_id}")
def update_case_question(case_id: str, question_id: str, body: CaseQuestionUpdateRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).update_case_question(
        case_id,
        question_id,
        text=body.text,
        regex_patterns=body.regex_patterns,
        **({"element_key": body.element_key} if "element_key" in body.model_fields_set else {}),
    )
    db.commit()
    return envelope(result, "问题已更新")


@router.post("/cases/{case_id}/questions/from-fragments")
def create_live_question_from_fragments(case_id: str, body: LiveQuestionFragmentsRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).create_live_question_from_fragments(
        case_id, fragment_ids=body.fragment_ids, after_question_id=body.after_question_id,
    )
    db.commit()
    return envelope(result, "语音问题已加入笔录，原片段已标记为已处理")


@router.put("/cases/{case_id}/questions/{question_id}/answer")
def upsert_case_question_answer(case_id: str, question_id: str, body: RoundUpdateRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).upsert_case_question_answer(
        case_id,
        question_id,
        answer_text=body.answer_text,
    )
    db.commit()
    return envelope(result, "正式回答已保存")


@router.post("/cases/{case_id}/questions/{question_id}/answer-fragments")
def attach_case_question_answer_fragments(case_id: str, question_id: str, body: FragmentAnswerRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).attach_case_question_answer_fragments(
        case_id,
        question_id,
        fragment_ids=body.fragment_ids,
        draft=body.draft,
        replace=body.replace,
    )
    db.commit()
    return envelope(result, "语音片段已转为待摘入回答" if body.draft else "语音片段已录入正式回答")


@router.post("/cases/{case_id}/questions/reorder")
def reorder_case_questions(case_id: str, body: QuestionReorderRequest, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).reorder(case_id, body.question_ids)
    db.commit()
    return envelope(result, "问题顺序已更新")


@router.post("/cases/{case_id}/speech-fragments/{fragment_id}/process")
def process_speech_fragment(case_id: str, fragment_id: str, db: Session = Depends(get_db)):
    result = InterrogationProjectionService(db).process_fragment(case_id, fragment_id)
    db.commit()
    return envelope(result)


@router.post("/cases/{case_id}/qa-units/{qa_unit_id}/resolve")
def resolve_qa_unit(case_id: str, qa_unit_id: str, body: QAUnitResolutionRequest, db: Session = Depends(get_db)):
    _qa_unit_for_case(db, case_id, qa_unit_id)
    result = FormalRecordRoutingService(db).resolve_manual(
        qa_unit_id,
        action=body.action,
        case_question_id=body.case_question_id,
        formal_question=body.formal_question,
        formal_answer=body.formal_answer,
    )
    db.commit()
    return envelope(result, "待处理问答已人工确认")


@router.post("/cases/{case_id}/qa-units/{qa_unit_id}/rollback")
def rollback_qa_unit(case_id: str, qa_unit_id: str, db: Session = Depends(get_db)):
    _qa_unit_for_case(db, case_id, qa_unit_id)
    result = FormalRecordRoutingService(db).rollback_qa_unit(qa_unit_id)
    db.commit()
    return envelope(result, "本次匹配已回退")


@router.post("/cases/{case_id}/pending-questions/{pending_id}/add")
def add_pending_question(case_id: str, pending_id: str, body: PendingAddRequest | None = None, db: Session = Depends(get_db)):
    _pending_for_case(db, case_id, pending_id)
    result = InterrogationProjectionService(db).add_pending_as_question(
        pending_id,
        after_question_id=body.after_question_id if body is not None else None,
    )
    db.commit()
    return envelope(result, "现场问题已加入正式笔录")


@router.post("/cases/{case_id}/pending-questions/{pending_id}/link")
def link_pending_question(case_id: str, pending_id: str, body: PendingLinkRequest, db: Session = Depends(get_db)):
    _pending_for_case(db, case_id, pending_id)
    result = InterrogationProjectionService(db).link_pending(
        pending_id,
        body.case_question_id,
        round_mode=body.round_mode,
    )
    db.commit()
    return envelope(result, "待处理问题已关联")


@router.post("/cases/{case_id}/pending-questions/{pending_id}/ignore")
def ignore_pending_question(case_id: str, pending_id: str, db: Session = Depends(get_db)):
    _pending_for_case(db, case_id, pending_id)
    result = InterrogationProjectionService(db).ignore_pending(pending_id)
    db.commit()
    return envelope(result, "该问题仅保留在原始对话")


@router.post("/cases/{case_id}/rounds/{round_id}/reassociate")
def reassociate_round(case_id: str, round_id: str, body: RoundReassociateRequest, db: Session = Depends(get_db)):
    _round_for_case(db, case_id, round_id)
    result = InterrogationProjectionService(db).reassociate_round(
        round_id,
        case_question_id=body.case_question_id,
        new_question_text=body.new_question_text,
    )
    db.commit()
    return envelope(result, "问答轮次已重新关联")


@router.patch("/cases/{case_id}/rounds/{round_id}")
def update_round(case_id: str, round_id: str, body: RoundUpdateRequest, db: Session = Depends(get_db)):
    _round_for_case(db, case_id, round_id)
    result = InterrogationProjectionService(db).update_round_answer(round_id, answer_text=body.answer_text)
    db.commit()
    return envelope(result, "正式回答已修订")


@router.post("/cases/{case_id}/questions/{question_id}/save-to-library")
def save_question_to_library(case_id: str, question_id: str, body: SaveQuestionToLibraryRequest | None = None, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).save_to_library(
        case_id,
        question_id,
        body.category if body is not None else "通用",
    )
    db.commit()
    return envelope(result, "问题已保存到常用问题库")


@router.post("/cases/{case_id}/formal-record/ensure")
def ensure_formal_record(case_id: str, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).ensure_formal_record(case_id, template_key="SUSPECT_INQUIRY_V1")
    db.commit()
    return envelope(result, "正式询问笔录模板已就绪")


@router.delete("/cases/{case_id}/questions/{question_id}")
def deactivate_case_question(case_id: str, question_id: str, db: Session = Depends(get_db)):
    result = TemplateWorkspaceService(db).deactivate_case_question(case_id, question_id)
    db.commit()
    return envelope(result, "动态问题已从正式笔录移出")
