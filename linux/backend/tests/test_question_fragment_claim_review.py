import pytest

from app.domain.errors import DomainError
from app.database.models import QuestionRound
from app.repositories import asr_fragments as asr_repo
from app.services.template_workspace_service import TemplateWorkspaceService
from test_question_recording_ownership import db, fragment, question


@pytest.mark.parametrize('action', ['QUESTION_ANSWER', 'LIVE_QUESTION'])
def test_owned_sources_cannot_be_confirmed_discarded_or_bulk_applied_through_legacy_api(db, action):
    from app.api.asr import _confirm_one, apply_fragments, discard_fragment, FragmentBatchRequest
    from app.services.interrogation_projection_service import InterrogationProjectionService

    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '已归属内容')
    asr_repo.mark_processed(db, fragment_id=source.id, case_id='CASE-OWN', action=action, target_id=q['id'])
    db.commit()
    for operation in [lambda: _confirm_one(db, case_id='CASE-OWN', fragment_id=source.id, actor_id=None),
                      lambda: discard_fragment('CASE-OWN', source.id, db=db)]:
        with pytest.raises(DomainError) as exc:
            operation()
        assert exc.value.code == 'ASR_FRAGMENT_ALREADY_PROCESSED'
    assert apply_fragments('CASE-OWN', FragmentBatchRequest(), db=db)['confirmedCount'] == 0
    assert source.state == 'PENDING'
    projected = InterrogationProjectionService(db).process_fragment('CASE-OWN', source.id)
    assert projected == {'status': action, 'questionId': q['id']}


def test_manual_answer_attachment_claims_source_and_rejects_other_uses(db):
    service = TemplateWorkspaceService(db)
    q1, q2 = question(db), question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '回答内容')
    service.attach_case_question_answer_fragments('CASE-OWN', q1['id'], fragment_ids=[source.id], draft=True)
    claim = asr_repo.get_processed(db, source.id)
    assert claim is not None
    assert (claim.action, claim.target_id) == ('QUESTION_ANSWER', q1['id'])
    with pytest.raises(DomainError) as error:
        service.attach_case_question_answer_fragments('CASE-OWN', q2['id'], fragment_ids=[source.id], draft=True)
    assert error.value.code == 'ASR_FRAGMENT_ALREADY_PROCESSED'
    with pytest.raises(DomainError):
        service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[source.id])


@pytest.mark.parametrize('state', ['DISCARDED', 'SUPERSEDED', 'CONFIRMED'])
def test_unclaimed_nonusable_answer_sources_are_rejected(db, state):
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '不应写入')
    source.state = state
    db.flush()
    with pytest.raises(DomainError) as error:
        service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[source.id], draft=True)
    assert error.value.code == 'ASR_FRAGMENT_ALREADY_PROCESSED'


def test_answer_retry_replace_and_raw_only_upgrade_are_idempotent(db):
    service = TemplateWorkspaceService(db)
    q = question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    first, second = fragment(db, capture, 0, '第一段'), fragment(db, capture, 1, '第二段')
    asr_repo.mark_processed(db, fragment_id=first.id, case_id='CASE-OWN', action='RAW_ONLY')
    for replace in (True, False, True):
        result = service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[first.id, second.id], draft=True, replace=replace)
        assert result['answerText'].replace(' ', '') == '第一段第二段'
        assert result['answerFragmentIds'] == [first.id, second.id]
    assert asr_repo.get_processed(db, first.id).action == 'QUESTION_ANSWER'
    # Automatic targeted attachment and the frontend's later aggregate call share ownership.
    targeted = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000, target_question_id=q['id'], replace=True)
    a, b = fragment(db, targeted, 0, '重录一'), fragment(db, targeted, 1, '重录二')
    result = service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[a.id, b.id], draft=True, replace=True)
    assert result['answerText'].replace(' ', '') == '重录一重录二'
    assert result['answerFragmentIds'] == [a.id, b.id]


def test_single_and_multi_question_apis_share_claims_in_both_directions(db):
    service = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    first, second = fragment(db, capture, 0, '第一个问题？'), fragment(db, capture, 1, '第二个问题？')
    first.speaker = second.speaker = 'INTERROGATOR'
    db.flush()
    multi = service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[first.id])
    single_retry = service.create_live_question_from_fragment('CASE-OWN', fragment_id=first.id)
    assert single_retry['question']['id'] == multi['question']['id']
    single = service.create_live_question_from_fragment('CASE-OWN', fragment_id=second.id)
    multi_retry = service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[second.id])
    assert multi_retry['question']['id'] == single['question']['id']
    assert len(service.workspace('CASE-OWN')['questions']) == 2
    assert asr_repo.get_processed(db, second.id).action == 'LIVE_QUESTION'


def test_single_question_creation_rejects_discarded_source(db):
    service = TemplateWorkspaceService(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '已经丢弃的问题？')
    source.speaker, source.state = 'INTERROGATOR', 'DISCARDED'
    db.flush()
    with pytest.raises(DomainError) as error:
        service.create_live_question_from_fragment('CASE-OWN', fragment_id=source.id)
    assert error.value.code == 'ASR_FRAGMENT_ALREADY_PROCESSED'


def test_legacy_answer_round_without_claim_preserves_same_question_ownership(db):
    service = TemplateWorkspaceService(db)
    q1, q2 = question(db), question(db)
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '历史回答')
    db.add(QuestionRound(id='legacy-answer', case_id='CASE-OWN', case_question_id=q1['id'], round_no=1,
        actual_question_text='历史问题', answer_text='历史回答', answer_fragment_ids_json=f'["{source.id}"]', status='CLOSED'))
    db.flush()
    with pytest.raises(DomainError):
        service.attach_case_question_answer_fragments('CASE-OWN', q2['id'], fragment_ids=[source.id], draft=True)
    with pytest.raises(DomainError):
        service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[source.id])
    source.speaker = 'INTERROGATOR'
    with pytest.raises(DomainError):
        service.create_live_question_from_fragment('CASE-OWN', fragment_id=source.id)
    result = service.attach_case_question_answer_fragments('CASE-OWN', q1['id'], fragment_ids=[source.id], draft=True)
    assert result['answerText'] == '历史回答'
    assert asr_repo.get_processed(db, source.id).target_id == q1['id']


@pytest.mark.parametrize('other_case, status', [(False, 'DETACHED'), (True, 'CLOSED')])
def test_legacy_detached_or_foreign_round_cannot_be_reclaimed(db, other_case, status):
    service = TemplateWorkspaceService(db)
    q = question(db)
    other_question = service.add_case_question('CASE-OTHER', text='其他问题', source='CASE') if other_case else q
    capture = asr_repo.create_capture_session(db, case_id='CASE-OWN', interrogation_session_id=None, sample_rate=16000)
    source = fragment(db, capture, 0, '已有归属')
    db.add(QuestionRound(id='legacy-invalid', case_id='CASE-OTHER' if other_case else 'CASE-OWN', case_question_id=other_question['id'], round_no=1,
        actual_question_text='问题', answer_fragment_ids_json=f'["{source.id}"]', status=status))
    db.flush()
    with pytest.raises(DomainError):
        service.attach_case_question_answer_fragments('CASE-OWN', q['id'], fragment_ids=[source.id], draft=True)
    with pytest.raises(DomainError):
        service.create_live_question_from_fragments('CASE-OWN', fragment_ids=[source.id])
