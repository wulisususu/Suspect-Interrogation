import pytest
from sqlalchemy.orm import Session

from app.database.models import Case, CaseQuestion
from app.database.session import init_database, make_engine
from app.domain.errors import DomainError
from app.services.case_service import CaseService


@pytest.fixture
def validation(tmp_path):
    from app.database import case_management_models  # noqa:F401
    from app.services.record_validation_service import RecordValidationService
    engine=make_engine(f"sqlite:///{tmp_path/'validation.db'}")
    init_database(engine)
    with Session(engine,expire_on_commit=False) as db:
        cid=CaseService(db).create({"suspectName":"被询问人"})["id"]
        db.add(CaseQuestion(id="q1",case_id=cid,source="CASE",text="什么品牌？",sort_order=10,
                            section_type="BODY",formal_answer_text="雅笛电动车"));db.commit()
        yield db,cid,RecordValidationService(db,homophones={"雅笛":["雅迪"]})
    engine.dispose()


def test_timeline_requires_evidence_and_reports_conflict(validation):
    db,cid,service=validation
    assert service.check_timeline(cid)["status"] == "UNAVAILABLE"
    service.add_timeline_evidence(cid,kind="EVENT",at="2026-10-28T10:00:00+08:00",source="当事人确认")
    service.add_timeline_evidence(cid,kind="REPORT",at="2026-10-28T09:00:00+08:00",source="民警登记")
    db.commit()
    result=service.check_timeline(cid)
    assert result["status"] == "CONFLICT"
    assert len(result["conflicts"]) == 1
    assert {x["kind"] for x in result["evidence"]} == {"EVENT","REPORT"}


def test_timeline_timezone_normalization_and_consistent_result(validation):
    db,cid,service=validation
    service.add_timeline_evidence(cid,kind="EVENT",at="2026-10-28T10:00:00+08:00",source="确认")
    service.add_timeline_evidence(cid,kind="REPORT",at="2026-10-28T03:00:00+00:00",source="确认")
    db.commit()
    assert service.check_timeline(cid)["status"] == "CONSISTENT"


def test_timeline_rejects_naive_time_and_unknown_kind(validation):
    _,cid,service=validation
    for kind,at in [("EVENT","2026-10-28T10:00:00"),("FAKE","2026-10-28T10:00:00Z")]:
        with pytest.raises(DomainError):service.add_timeline_evidence(cid,kind=kind,at=at,source="确认")


def test_candidate_accept_applies_only_matching_revision_and_is_idempotent(validation):
    db,cid,service=validation
    first=service.corrections(cid)
    assert first["configured"] is True and first["pending"] == 1
    candidate=first["items"][0]
    assert candidate["original"] == "雅笛" and candidate["suggestion"] == "雅迪"
    result=service.resolve_correction(cid,candidate["id"],action="ACCEPT",actor_id="a1")
    db.commit()
    assert result["status"] == "ACCEPTED"
    assert db.get(CaseQuestion,"q1").formal_answer_text == "雅迪电动车"
    assert service.resolve_correction(cid,candidate["id"],action="ACCEPT")["status"] == "ACCEPTED"
    assert service.corrections(cid)["pending"] == 0


def test_ignored_correction_preserves_answer(validation):
    db,cid,service=validation
    candidate=service.corrections(cid)["items"][0]
    service.resolve_correction(cid,candidate["id"],action="IGNORE")
    assert db.get(CaseQuestion,"q1").formal_answer_text == "雅笛电动车"
    assert service.corrections(cid)["pending"] == 0


def test_stale_or_other_case_candidate_cannot_rewrite_answer(validation):
    db,cid,service=validation
    candidate=service.corrections(cid)["items"][0]
    other=CaseService(db).create({"suspectName":"另案"})["id"]
    with pytest.raises(DomainError) as exc:service.resolve_correction(other,candidate["id"],action="ACCEPT")
    assert exc.value.status_code == 404
    db.get(CaseQuestion,"q1").formal_answer_text="民警已修订";db.commit()
    with pytest.raises(DomainError) as exc:service.resolve_correction(cid,candidate["id"],action="ACCEPT")
    assert exc.value.code == "CORRECTION_STALE"
    assert db.get(CaseQuestion,"q1").formal_answer_text == "民警已修订"


def test_frozen_document_cannot_create_or_resolve_corrections(validation):
    db,cid,service=validation
    candidate=service.corrections(cid)["items"][0]
    db.get(Case,cid).workflow_state="FROZEN";db.commit()
    with pytest.raises(DomainError):service.resolve_correction(cid,candidate["id"],action="ACCEPT")
    assert db.get(CaseQuestion,"q1").formal_answer_text == "雅笛电动车"


def test_no_dictionary_reports_unavailable_without_invented_suggestions(validation):
    db,cid,_=validation
    from app.services.record_validation_service import RecordValidationService
    result=RecordValidationService(db,homophones={}).corrections(cid)
    assert result["configured"] is False and result["items"] == []
