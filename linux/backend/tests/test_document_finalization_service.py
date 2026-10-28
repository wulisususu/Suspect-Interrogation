from pathlib import Path

import pytest

from app.database.models import (
    ASRCaptureSession,
    ASRFragment,
    Case,
    CaseQuestion,
    DocumentSnapshot,
    InterrogationSession,
    Message,
    QAUnit,
    QuestionRound,
)
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.enums import SessionStatus, WorkflowState
from app.domain.errors import DomainError
from app.services.document_finalization_service import DocumentFinalizationService


class FakeCaptureService:
    def __init__(self, events: list[str]):
        self.active = True
        self.events = events

    def status(self, _case_id: str) -> dict:
        return {"active": self.active}

    def stop(self, _case_id: str) -> dict:
        self.events.append("capture-stop")
        self.active = False
        return {"active": False}


class FakeRoutingCoordinator:
    def __init__(self, events: list[str]):
        self.events = events

    def drain_capture(self, case_id: str, session_id: str, *, timeout: float) -> None:
        self.events.append(f"routing-drain:{case_id}:{session_id}")


def seed(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'finalize.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = Case(id="CASE-FINALIZE", workflow_state=WorkflowState.QUESTIONING.value)
        session = InterrogationSession(
            id="SESSION-FINALIZE",
            case_id=case.id,
            status=SessionStatus.RUNNING.value,
            stage="IDENTITY",
        )
        db.add_all([case, session])
        db.commit()
    return engine, factory, case.id, session.id


def test_finalize_stops_capture_drains_routing_then_finishes_and_freezes(tmp_path: Path):
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        state = DocumentFinalizationService(
            db,
            capture_service=FakeCaptureService(events),
            routing_coordinator=FakeRoutingCoordinator(events),
        ).finalize(case_id, actor_id="officer-1")

        assert state["status"] == "FROZEN"
        assert events == ["capture-stop", f"routing-drain:{case_id}:{session_id}"]
        assert db.get(Case, case_id).workflow_state == WorkflowState.FROZEN.value
        assert db.get(InterrogationSession, session_id).status == SessionStatus.COMPLETED.value
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 1

        retry_events: list[str] = []
        retried = DocumentFinalizationService(
            db,
            capture_service=FakeCaptureService(retry_events),
            routing_coordinator=FakeRoutingCoordinator(retry_events),
        ).finalize(case_id, actor_id="officer-1")
        assert retried == state
        assert retry_events == []
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 1
    engine.dispose()


def test_finalize_refuses_to_freeze_unresolved_routing_work(tmp_path: Path):
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        db.add(QAUnit(
            id="QA-REVIEW",
            case_id=case_id,
            session_id=session_id,
            status="NEEDS_REVIEW",
            raw_question_text="你从哪里拿的刀？",
            raw_answer_text="从厨房。",
        ))
        db.commit()

        with pytest.raises(DomainError) as exc:
            DocumentFinalizationService(
                db,
                capture_service=FakeCaptureService(events),
                routing_coordinator=FakeRoutingCoordinator(events),
            ).finalize(case_id)
        assert exc.value.code == "FORMAL_RECORD_REVIEW_REQUIRED"
        assert db.get(Case, case_id).workflow_state == WorkflowState.QUESTIONING.value
        assert db.get(InterrogationSession, session_id).status == SessionStatus.RUNNING.value
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 0
    engine.dispose()


def test_finalize_refuses_to_freeze_incomplete_audio_archive(tmp_path: Path):
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        db.add(ASRCaptureSession(
            id="CAPTURE-INCOMPLETE",
            case_id=case_id,
            interrogation_session_id=session_id,
            status="FAILED",
            sample_rate=16000,
            recording_status="INCOMPLETE",
            asr_status="COMPLETE",
            speaker_status="COMPLETE",
        ))
        db.commit()

        with pytest.raises(DomainError) as exc:
            DocumentFinalizationService(
                db,
                capture_service=FakeCaptureService(events),
                routing_coordinator=FakeRoutingCoordinator(events),
            ).finalize(case_id)

        assert exc.value.code == "AUDIO_ARCHIVE_INCOMPLETE"
        assert "录音" in exc.value.message
        assert db.get(Case, case_id).workflow_state == WorkflowState.QUESTIONING.value
        assert db.get(InterrogationSession, session_id).status == SessionStatus.RUNNING.value
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 0
    engine.dispose()


def test_finalize_refuses_to_freeze_unresolved_transcript_fragment(tmp_path: Path):
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        db.add(ASRCaptureSession(
            id="CAPTURE-COMPLETE",
            case_id=case_id,
            interrogation_session_id=session_id,
            status="COMPLETE",
            sample_rate=16000,
            recording_status="COMPLETE",
            asr_status="COMPLETE",
            speaker_status="NEEDS_REVIEW",
        ))
        db.add(ASRFragment(
            id="FRAGMENT-REVIEW",
            capture_session_id="CAPTURE-COMPLETE",
            case_id=case_id,
            ordinal=0,
            started_at_ms=0,
            ended_at_ms=1000,
            raw_text="待确认内容",
            edited_text="待确认内容",
            speaker="UNKNOWN",
            speaker_source="PENDING_ANALYSIS",
            voiceprint_verified=False,
            low_confidence=False,
            state="PENDING",
            model_id="test-model",
        ))
        db.commit()

        with pytest.raises(DomainError) as exc:
            DocumentFinalizationService(
                db,
                capture_service=FakeCaptureService(events),
                routing_coordinator=FakeRoutingCoordinator(events),
            ).finalize(case_id)

        assert exc.value.code == "ASR_FRAGMENT_REVIEW_REQUIRED"
        assert "确认" in exc.value.message and "丢弃" in exc.value.message
        assert db.get(Case, case_id).workflow_state == WorkflowState.QUESTIONING.value
        assert db.get(InterrogationSession, session_id).status == SessionStatus.RUNNING.value
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 0
    engine.dispose()


@pytest.mark.parametrize("fragment_state", ["DISCARDED", "SUPERSEDED", "CONFIRMED"])
def test_finalize_accepts_explicitly_resolved_transcript_fragments(tmp_path: Path, fragment_state: str):
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        db.add(ASRCaptureSession(
            id="CAPTURE-RESOLVED",
            case_id=case_id,
            interrogation_session_id=session_id,
            status="COMPLETE",
            sample_rate=16000,
            recording_status="COMPLETE",
            asr_status="COMPLETE",
            speaker_status="COMPLETE",
        ))
        confirmed_message_id = None
        if fragment_state == "CONFIRMED":
            confirmed_message_id = "MESSAGE-CONFIRMED"
            db.add(Message(
                id=confirmed_message_id,
                case_id=case_id,
                session_id=session_id,
                seq=1,
                speaker="SUSPECT",
                text="已确认内容",
            ))
            db.flush()
        db.add(ASRFragment(
            id="FRAGMENT-RESOLVED",
            capture_session_id="CAPTURE-RESOLVED",
            case_id=case_id,
            ordinal=0,
            started_at_ms=0,
            ended_at_ms=1000,
            raw_text="已处置内容",
            edited_text="已处置内容",
            speaker="SUSPECT",
            speaker_source="MANUAL",
            voiceprint_verified=False,
            low_confidence=False,
            state=fragment_state,
            model_id="test-model",
            confirmed_message_id=confirmed_message_id,
        ))
        db.commit()

        result = DocumentFinalizationService(
            db,
            capture_service=FakeCaptureService(events),
            routing_coordinator=FakeRoutingCoordinator(events),
        ).finalize(case_id)

        assert result["status"] == "FROZEN"
        assert db.query(DocumentSnapshot).filter_by(case_id=case_id).count() == 1
    engine.dispose()


def test_finalize_accepts_unknown_speaker_fragment_attached_to_a_question(tmp_path: Path):
    """逐题录音：没有声纹的片段说话人为 UNKNOWN，挂到题目回答后即视为已处理。"""
    engine, factory, case_id, session_id = seed(tmp_path)
    events: list[str] = []
    with factory() as db:
        db.add(ASRCaptureSession(
            id="CAPTURE-CARD",
            case_id=case_id,
            interrogation_session_id=session_id,
            status="COMPLETE",
            sample_rate=16000,
            recording_status="COMPLETE",
            asr_status="COMPLETE",
            speaker_status="COMPLETE",
        ))
        for ordinal, fragment_id in enumerate(("FRAGMENT-CARD", "FRAGMENT-LOOSE")):
            db.add(ASRFragment(
                id=fragment_id,
                capture_session_id="CAPTURE-CARD",
                case_id=case_id,
                ordinal=ordinal,
                started_at_ms=ordinal * 1000,
                ended_at_ms=ordinal * 1000 + 800,
                raw_text="锁了，锁在柱子上。",
                edited_text="锁了，锁在柱子上。",
                speaker="UNKNOWN",
                speaker_source="UNASSIGNED",
                voiceprint_verified=False,
                low_confidence=False,
                state="PENDING",
                model_id="test-model",
            ))
        db.add(CaseQuestion(id="Q-CARD", case_id=case_id, source="CASE", text="车辆当时锁了吗？", sort_order=1))
        db.flush()
        db.add(QuestionRound(
            id="ROUND-CARD",
            case_id=case_id,
            session_id=session_id,
            case_question_id="Q-CARD",
            round_no=1,
            actual_question_text="车辆当时锁了吗？",
            answer_text="锁了，锁在柱子上。",
            answer_fragment_ids_json='["FRAGMENT-CARD"]',
            status="CLOSED",
        ))
        db.commit()

        service = DocumentFinalizationService(
            db,
            capture_service=FakeCaptureService(events),
            routing_coordinator=FakeRoutingCoordinator(events),
        )
        with pytest.raises(DomainError) as exc:
            service.finalize(case_id)
        assert exc.value.code == "ASR_FRAGMENT_REVIEW_REQUIRED"
        assert exc.value.data == {"fragment_ids": ["FRAGMENT-LOOSE"]}

        db.get(ASRFragment, "FRAGMENT-LOOSE").state = "DISCARDED"
        db.commit()
        result = DocumentFinalizationService(
            db,
            capture_service=FakeCaptureService(events),
            routing_coordinator=FakeRoutingCoordinator(events),
        ).finalize(case_id)
        assert result["status"] == "FROZEN"
    engine.dispose()
