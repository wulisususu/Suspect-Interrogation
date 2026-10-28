import json
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ASRCaptureSession, Case, CaseQuestion, Fact, ProcessedSpeechFragment, QuestionRound
from app.database.session import init_database, make_engine
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import facts as fact_repo
from app.services.template_workspace_service import TemplateWorkspaceService


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'question-ownership.db'}")
    init_database(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([Case(id='CASE-OWN'), Case(id='CASE-OTHER')])
        session.flush()
        fact_repo.seed_defaults(session, 'CASE-OWN')
        session.commit()
        yield session
    engine.dispose()


def question(db, element='time'):
    return TemplateWorkspaceService(db).add_case_question('CASE-OWN', text='何时到达？', source='CASE', element_key=element)


def fact_status(db, key):
    return db.scalar(select(Fact.status).where(Fact.case_id == 'CASE-OWN', Fact.fact_key == key))


def fragment(db, capture, ordinal, text):
    return asr_repo.create_or_update_asr_only_fragment(
        db, capture_session_id=capture.id, case_id=capture.case_id,
        started_at_ms=ordinal * 1000, ended_at_ms=ordinal * 1000 + 900,
        raw_text=text, asr_confidence=0.9, model_id='test-asr', model_version='1',
        idempotency_key=f'{capture.id}:{ordinal}',
    )[0]


def test_element_coverage_uses_all_active_canonical_answers(db):
    svc = TemplateWorkspaceService(db)
    first, second = question(db), question(db)
    assert first['elementKey'] == 'time'
    svc.upsert_case_question_answer('CASE-OWN', first['id'], answer_text='今天七点')
    svc.upsert_case_question_answer('CASE-OWN', second['id'], answer_text='七点十分离开')
    assert fact_status(db, 'time') == 'confirmed'
    svc.upsert_case_question_answer('CASE-OWN', first['id'], answer_text='')
    assert fact_status(db, 'time') == 'confirmed'
    svc.upsert_case_question_answer('CASE-OWN', second['id'], answer_text='  ')
    assert fact_status(db, 'time') == 'pending'


def test_reassigning_element_and_deactivating_refreshes_old_and_new_coverage(db):
    svc = TemplateWorkspaceService(db)
    q = question(db)
    svc.upsert_case_question_answer('CASE-OWN', q['id'], answer_text='今天七点')
    svc.update_case_question('CASE-OWN', q['id'], element_key='place')
    assert fact_status(db, 'time') == 'pending'
    assert fact_status(db, 'place') == 'confirmed'
    svc.deactivate_case_question('CASE-OWN', q['id'])
    assert fact_status(db, 'place') == 'pending'


def test_unknown_and_fixed_element_associations_are_rejected(db):
    svc = TemplateWorkspaceService(db)
    with pytest.raises(DomainError):
        question(db, 'not-in-template')
    fixed = svc.ensure_formal_record('CASE-OWN')['questions'][0]
    with pytest.raises(DomainError):
        svc.update_case_question('CASE-OWN', fixed['id'], element_key='time')
    assert all(q['elementKey'] is None for q in svc.workspace('CASE-OWN')['questions'] if q['locked'])


def test_multiple_capture_batches_sort_after_sqlite_datetime_roundtrip(db):
    first = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    first.started_at = datetime(2026, 10, 28, 1, tzinfo=timezone.utc)
    before = fragment(db, first, 0, '前半句')
    db.commit()
    db.expire(first, ['started_at'])  # SQLite reload is naive UTC, new captures are aware UTC.
    second = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    second.started_at = datetime(2026, 10, 28, 1, tzinfo=timezone.utc) + timedelta(seconds=1)
    after = fragment(db, second, 0, '后半句？')
    result = TemplateWorkspaceService(db).create_live_question_from_fragments('CASE-OWN', fragment_ids=[after.id, before.id])
    assert result['question']['text'] == '前半句后半句？'
    assert result['fragmentIds'] == [before.id, after.id]


def test_recording_target_cannot_be_removed_before_capture_and_transcription_settle(db):
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None,
                                             sample_rate=16000, target_question_id=q['id'])
    for status, recording, asr in [('CAPTURING', 'CAPTURING', 'PENDING'), ('STOPPED', 'COMPLETE', 'FINALIZING')]:
        capture.status, capture.recording_status, capture.asr_status = status, recording, asr
        db.flush()
        with pytest.raises(DomainError) as exc:
            service.deactivate_case_question('CASE-OWN', q['id'])
        assert exc.value.code == 'QUESTION_RECORDING_ACTIVE'
        assert db.get(CaseQuestion, q['id']).active is True
    capture.status, capture.recording_status, capture.asr_status = 'STOPPED', 'COMPLETE', 'COMPLETE'
    db.flush()
    assert service.deactivate_case_question('CASE-OWN', q['id'])['active'] is False


def test_targeted_capture_owns_fragments_durably_as_draft_and_replaces_only_once(db):
    svc = TemplateWorkspaceService(db)
    q = question(db)
    svc.upsert_case_question_answer('CASE-OWN', q['id'], answer_text='原正式回答')
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None,
        sample_rate=16000, target_question_id=q['id'], replace=True)
    a = fragment(db, capture, 0, '新回答第一段')
    db.commit()
    db.expire_all()
    b = fragment(db, capture, 1, '第二段')
    fragment(db, capture, 1, '第二段')
    db.commit()
    current = svc.workspace('CASE-OWN')['questions'][0]
    assert current['formalAnswerText'] == '原正式回答'
    latest = current['rounds'][-1]
    assert latest['answerText'] == '新回答第一段 第二段'
    assert json.loads(db.get(QuestionRound, latest['id']).answer_fragment_ids_json) == [a.id, b.id]
    saved = db.get(ASRCaptureSession, capture.id)
    assert saved.target_question_id == q['id']
    assert saved.answer_replacement_applied is True


def test_capture_target_must_be_active_same_case_and_mutable(db):
    q = question(db)
    with pytest.raises(DomainError):
        asr_repo.create_capture_session(db, case_id='CASE-OTHER', interrogation_session_id=None,
            sample_rate=16000, target_question_id=q['id'])
    db.get(Case, 'CASE-OWN').workflow_state = 'FROZEN'
    db.flush()
    with pytest.raises(DomainError):
        asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None,
            sample_rate=16000, target_question_id=q['id'])


def test_multi_fragment_question_is_ordered_atomic_and_idempotent(db):
    svc = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    a, b = fragment(db, capture, 0, '你什么时候'), fragment(db, capture, 1, '到现场的？')
    result = svc.create_live_question_from_fragments('CASE-OWN', fragment_ids=[b.id, a.id, a.id])
    repeated = svc.create_live_question_from_fragments('CASE-OWN', fragment_ids=[a.id, b.id])
    assert result['question']['text'] == '你什么时候到现场的？'
    assert repeated['question']['id'] == result['question']['id']
    assert len(svc.workspace('CASE-OWN')['questions']) == 1
    processed = list(db.scalars(select(ProcessedSpeechFragment)))
    assert {x.fragment_id for x in processed} == {a.id, b.id}
    assert {x.target_id for x in processed} == {result['question']['id']}
    with pytest.raises(DomainError):
        svc.create_live_question_from_fragments('CASE-OWN', fragment_ids=[a.id])


def test_multi_fragment_validation_leaves_no_partial_question_or_processing(db):
    svc = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    other = asr_repo.create_capture_session(db, case_id='CASE-OTHER', interrogation_session_id=None, sample_rate=16000)
    a, b = fragment(db, capture, 0, '哪一天？'), fragment(db, other, 0, '别的案件')
    with pytest.raises(DomainError):
        svc.create_live_question_from_fragments('CASE-OWN', fragment_ids=[a.id, b.id])
    assert svc.workspace('CASE-OWN')['questions'] == []
    assert list(db.scalars(select(ProcessedSpeechFragment))) == []
