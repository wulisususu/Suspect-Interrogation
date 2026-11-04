from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import AuditLog, CaseQuestion, QuestionRound
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import cases as case_repo
from app.services.self_service import SelfServiceService
from app.services.template_catalog_service import TemplateCatalogService


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'self-service.db'}")
    init_database(engine)
    with make_session_factory(engine)() as session:
        yield session
    engine.dispose()


def theft_case(db):
    case = case_repo.create(db, {})
    case.suspect_name = '王某某'
    TemplateCatalogService(db).select(case.id, template_id='theft-ebike', blank=False)
    db.flush()
    return case.id


def body_questions(db, case_id):
    return list(db.scalars(select(CaseQuestion).where(CaseQuestion.case_id == case_id, CaseQuestion.section_type == 'BODY',
                                                      CaseQuestion.active.is_(True)).order_by(CaseQuestion.sort_order)))


def draft_answer(db, question, text, round_no=1):
    """当事人自助回答：转写结果作为待摘入草稿挂在题目上，不进正本。"""
    db.add(QuestionRound(id=str(uuid4()), case_id=question.case_id, case_question_id=question.id, round_no=round_no,
                         actual_question_text=question.text, answer_text=text))
    db.flush()


def test_identity_answer_and_handover_confirmations_are_audited(db):
    case_id = theft_case(db)
    lock = body_questions(db, case_id)[2]
    service = SelfServiceService(db)
    assert service.state(case_id) == {'caseId': case_id, 'identityConfirmedAt': None, 'handedOverAt': None, 'confirmedAnswers': []}

    assert service.record(case_id, 'IDENTITY_CONFIRM')['identityConfirmedAt']
    with pytest.raises(DomainError) as error:
        service.record(case_id, 'ANSWER_CONFIRM', lock.id)
    assert error.value.code == 'SELF_SERVICE_NO_ANSWER'

    draft_answer(db, lock, '我那天是锁了的，就锁在单元门口那个柱子上')
    state = service.record(case_id, 'ANSWER_CONFIRM', lock.id)
    assert [item['questionId'] for item in state['confirmedAnswers']] == [lock.id]
    assert lock.formal_answer_text == ''                      # 本人确认不代替民警摘入正本
    assert service.record(case_id, 'ANSWER_UNCONFIRM', lock.id)['confirmedAnswers'] == []
    service.record(case_id, 'ANSWER_CONFIRM', lock.id)
    assert service.record(case_id, 'HANDOVER')['handedOverAt']

    actions = [row.action for row in db.scalars(select(AuditLog).where(AuditLog.case_id == case_id, AuditLog.action.like('SELF_SERVICE_%'))
                                                   .order_by(AuditLog.created_at))]
    assert actions == ['SELF_SERVICE_IDENTITY_CONFIRM', 'SELF_SERVICE_ANSWER_CONFIRM', 'SELF_SERVICE_ANSWER_UNCONFIRM',
                       'SELF_SERVICE_ANSWER_CONFIRM', 'SELF_SERVICE_HANDOVER']
    confirm = db.scalar(select(AuditLog).where(AuditLog.action == 'SELF_SERVICE_ANSWER_CONFIRM'))
    assert '单元门口' in confirm.after_json


def test_re_recorded_answer_needs_a_fresh_confirmation(db):
    case_id = theft_case(db)
    question = body_questions(db, case_id)[0]
    draft_answer(db, question, '晚上七点二十分发现车不见了')
    service = SelfServiceService(db)
    service.record(case_id, 'ANSWER_CONFIRM', question.id)
    draft_answer(db, question, '是早上七点二十分发现的', round_no=2)
    assert service.state(case_id)['confirmedAnswers'] == []
    # 民警把同一段话摘入正本后，本人的确认仍然有效
    service.record(case_id, 'ANSWER_CONFIRM', question.id)
    question.formal_answer_text = '是早上七点二十分发现的'
    db.flush()
    assert len(service.state(case_id)['confirmedAnswers']) == 1


def test_frozen_case_and_foreign_question_are_rejected(db):
    case_id = theft_case(db)
    other = theft_case(db)
    service = SelfServiceService(db)
    with pytest.raises(DomainError) as error:
        service.record(case_id, 'ANSWER_CONFIRM', body_questions(db, other)[0].id)
    assert error.value.code == 'CASE_QUESTION_NOT_FOUND'
    with pytest.raises(DomainError) as error:
        service.record(case_id, 'SOMETHING_ELSE')
    assert error.value.code == 'INVALID_SELF_SERVICE_EVENT'
    case_repo.get(db, case_id).workflow_state = 'FROZEN'
    db.flush()
    with pytest.raises(DomainError) as error:
        service.record(case_id, 'IDENTITY_CONFIRM')
    assert error.value.code == 'FORMAL_RECORD_FROZEN'


def test_self_service_api_round_trip(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'api.db'}", hardware_gateway=MockHardwareGateway())
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            case_id = theft_case(db)
            question = body_questions(db, case_id)[1]
            draft_answer(db, question, '雅迪，深蓝色')
            question_id = question.id
            db.commit()
        assert client.get(f'/api/v1/cases/{case_id}/self-service').json()['data']['confirmedAnswers'] == []
        response = client.post(f'/api/v1/cases/{case_id}/self-service/events', json={'kind': 'ANSWER_CONFIRM', 'questionId': question_id})
        assert response.status_code == 200
        assert response.json()['data']['confirmedAnswers'][0]['questionId'] == question_id
        assert client.post(f'/api/v1/cases/{case_id}/self-service/events', json={'kind': 'NOPE'}).status_code == 422
        assert client.get('/api/v1/cases/missing/self-service').status_code == 404
