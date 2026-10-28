from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditLog, Case, CaseQuestion, InterrogationSession
from app.database.session import init_database, make_engine
from app.domain.errors import DomainError
from app.repositories import audit as audit_repo
from app.services.case_service import CaseService


@pytest.fixture
def managed(tmp_path):
    from app.database import case_management_models  # noqa: F401
    from app.services.case_management_service import CaseManagementService
    engine = make_engine(f"sqlite:///{tmp_path / 'management.db'}")
    init_database(engine)
    with Session(engine, expire_on_commit=False) as db:
        case_id = CaseService(db).create({"suspectName": "被询问人", "officerName": "测试警官"})["id"]
        yield db, case_id, CaseManagementService(db)
    engine.dispose()


def question(db, case_id, qid="q1", text="时间？", answer="今天上午", order=10):
    row = CaseQuestion(id=qid, case_id=case_id, source="CASE", text=text, sort_order=order,
                       formal_answer_text=answer, section_type="BODY")
    db.add(row); db.commit()
    return row


def test_interruption_persists_reason_and_question_position(managed):
    db, cid, service = managed
    question(db, cid)
    result = service.interrupt(cid, reason="PARTY_LEFT", question_id="q1", detail="当事人暂离")
    db.commit(); db.expire_all()
    assert result["interruptionReason"] == "PARTY_LEFT"
    assert service.case_fields(cid)["stoppedQuestionId"] == "q1"
    assert service.case_fields(cid)["stoppedQuestionNumber"] == 1
    assert service.case_fields(cid)["stoppedQuestionText"] == "时间？"
    assert service.case_fields(cid)["interruptedAt"].endswith("+00:00")
    assert service.case_fields(cid)["interruptionDetail"] == "当事人暂离"


def test_interruption_rejects_cross_case_question_without_writing(managed):
    db, cid, service = managed
    other = CaseService(db).create({"suspectName": "另案"})["id"]
    question(db, other)
    with pytest.raises(DomainError) as exc:
        service.interrupt(cid, reason="NETWORK_INTERRUPTED", question_id="q1")
    assert exc.value.status_code == 404
    assert service.case_fields(cid)["interruptionReason"] is None


def test_interruption_rejects_unknown_reason(managed):
    _, cid, service = managed
    with pytest.raises(DomainError) as exc:
        service.interrupt(cid, reason="made-up")
    assert exc.value.code == "INVALID_INTERRUPTION_REASON"


def test_void_requires_reason_and_preserves_case_and_audit(managed):
    db, cid, service = managed
    with pytest.raises(DomainError) as exc:
        service.void(cid, reason=" ")
    assert exc.value.code == "VOID_REASON_REQUIRED"
    result = service.void(cid, reason="模板选择错误", actor_id="officer-a")
    db.commit(); db.expire_all()
    assert result["documentStatus"] == "VOIDED"
    assert db.get(Case, cid) is not None
    assert db.get(Case, cid).workflow_state == "VOIDED"
    logs = list(db.scalars(select(AuditLog).where(AuditLog.case_id == cid, AuditLog.action == "CASE_VOID")))
    assert len(logs) == 1
    assert service.case_fields(cid)["voidReason"] == "模板选择错误"
    service.void(cid, reason="模板选择错误", actor_id="officer-a")
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "CASE_VOID")))) == 1


@pytest.mark.parametrize("state", ["FROZEN", "SIGNED", "REPORT_GENERATED"])
def test_void_rejects_completed_records(managed, state):
    db, cid, service = managed
    db.get(Case, cid).workflow_state = state; db.commit()
    with pytest.raises(DomainError) as exc:
        service.void(cid, reason="更正")
    assert exc.value.code == "CASE_VOID_NOT_ALLOWED"
    assert db.get(Case, cid).workflow_state == state


def test_void_closes_running_session_and_rejects_future_edits(managed):
    db, cid, service = managed
    db.add(InterrogationSession(id="session-void",case_id=cid,status="RUNNING",stage="STATEMENT")); db.commit()
    service.void(cid, reason="重复建案"); db.commit()
    assert db.get(InterrogationSession, "session-void").status == "COMPLETED"
    from app.services.case_management_service import assert_case_not_void
    with pytest.raises(DomainError) as exc:
        assert_case_not_void(db, cid)
    assert exc.value.code == "CASE_VOIDED"


def test_audit_global_filters_pagination_results_and_keyword_escape(managed):
    db, cid, service = managed
    other = CaseService(db).create({"suspectName": "另一案"})["id"]
    audit_repo.add(db, case_id=cid, action="EXPORT", actor_id="a1", target_type="CASE", target_id=cid,
                   detail={"objectSummary": "百分比100%", "result": "SUCCESS"})
    audit_repo.add(db, case_id=other, action="EXPORT", actor_id="a2", target_type="CASE", target_id=other,
                   detail={"objectSummary": "文件生成失败", "result": "FAILURE"})
    db.commit()
    all_exports = service.query_audit(action="EXPORT", page=1, page_size=1)
    assert all_exports["total"] == 2
    assert len(all_exports["items"]) == 1
    assert service.query_audit(action="EXPORT", actor_id="a1")["total"] == 1
    assert service.query_audit(keyword="100%")["total"] == 1
    failure = service.query_audit(result="FAILURE")["items"]
    assert len(failure) == 1 and failure[0]["actorDisplayName"] == "a2"
    assert failure[0]["objectSummary"] == "文件生成失败"
    assert service.query_audit(created_from=datetime.now(timezone.utc)+timedelta(days=1))["total"] == 0


def test_audit_system_events_are_filterable_without_deletion(managed):
    db, cid, service = managed
    audit_repo.add(db, case_id=cid, action="ASR_SPEAKER_DECISION")
    db.commit()
    result = service.query_audit(category="SYSTEM")
    assert result["total"] == 1
    assert result["items"][0]["actorDisplayName"] == "系统自动"
    assert service.query_audit(category="BUSINESS")["total"] >= 1
    assert len(list(db.scalars(select(AuditLog).where(AuditLog.action == "ASR_SPEAKER_DECISION")))) == 1


def test_audit_fragment_summary_uses_question_or_fragment_context(managed):
    db, cid, service = managed
    question(db, cid, text="何时到现场？")
    audit_repo.add(db, case_id=cid, action="QUESTION_UPDATE", target_type="CASE_QUESTION", target_id="q1")
    db.commit()
    row = service.query_audit(action="QUESTION_UPDATE")["items"][0]
    assert "何时到现场" in row["objectSummary"]
    assert row["caseId"] == cid


def test_audit_invalid_date_interval_and_page_rejected(managed):
    _, _, service = managed
    now = datetime.now(timezone.utc)
    for kwargs in [{"page": 0},{"page_size": 201},{"created_from":now,"created_to":now-timedelta(days=1)}]:
        with pytest.raises(DomainError): service.query_audit(**kwargs)


def test_audit_uses_authenticated_actor_instead_of_client_actor(managed):
    from app.auth.context import Actor, actor_context
    db, cid, service = managed
    token = actor_context.set(Actor("038291", "张伟", "刑侦", False))
    try:
        row = audit_repo.add(db, case_id=cid, action="EXPORT", actor_id="spoofed")
        db.commit()
    finally:
        actor_context.reset(token)
    assert row.actor_id == "038291"
    result = service.query_audit(action="EXPORT")["items"][0]
    assert result["actorDisplayName"] == "张伟（038291）"
    assert result["result"] == "SUCCESS"


def test_void_rejects_capturing_audio_without_mutation(managed):
    from app.database.models import ASRCaptureSession
    db, cid, service = managed
    db.add(ASRCaptureSession(id="capturing", case_id=cid, status="CAPTURING", sample_rate=16000))
    db.commit()
    with pytest.raises(DomainError) as exc:
        service.void(cid, reason="重复建案")
    assert exc.value.code == "ASR_CAPTURE_ACTIVE"
    assert db.get(Case, cid).workflow_state != "VOIDED"


def test_audit_keyword_can_find_historical_actor_by_roster_name(managed):
    from app.database.officer_models import Officer
    db, cid, service = managed
    db.add(Officer(badge_number="038291",name="张伟",unit="刑侦",password_hash="not-a-login-hash"))
    audit_repo.add(db,case_id=cid,action="EXPORT",actor_id="038291")
    db.commit()
    found=service.query_audit(keyword="张伟")
    assert found["total"] == 1
    assert found["items"][0]["actorDisplayName"] == "张伟（038291）"
