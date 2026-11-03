from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database.catalog_models import KnowledgeSuggestionFeedback
from app.database.models import AuditLog, CaseQuestion
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import cases as case_repo
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_suggestions import KnowledgeSuggestionService, parse_suggestions
from app.services.template_catalog_service import TemplateCatalogService
from app.services.template_workspace_service import TemplateWorkspaceService


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'suggestions.db'}")
    init_database(engine)
    with make_session_factory(engine)() as session:
        yield session
    engine.dispose()


def theft_case(db):
    case = case_repo.create(db, {})
    TemplateCatalogService(db).select(case.id, template_id='theft-ebike', blank=False)
    db.flush()
    return case.id


def body_question(db, case_id, element_key):
    return db.scalar(select(CaseQuestion).where(
        CaseQuestion.case_id == case_id, CaseQuestion.element_key == element_key, CaseQuestion.section_type == 'BODY'))


def feedback_rows(db, case_id=None):
    statement = select(func.count()).select_from(KnowledgeSuggestionFeedback)
    if case_id:
        statement = statement.where(KnowledgeSuggestionFeedback.case_id == case_id)
    return db.scalar(statement)


def test_suggestion_lines_carry_an_optional_element_tag():
    content = '# 要点\n\n## 建议问法\n\n- [lock] 停车时车上用了什么锁？\n- 你是怎么记住这个时间的？\n\n## 其他\n- 不算'
    assert parse_suggestions(content) == [('lock', '停车时车上用了什么锁？'), (None, '你是怎么记住这个时间的？')]
    # 旧的 draft-questions 也不会把标记带进问法文字
    assert KnowledgeService._suggestion_lines(content) == ['停车时车上用了什么锁？', '你是怎么记住这个时间的？']


def test_unconfirmed_element_gets_reviewed_follow_ups_and_confirmed_one_does_not(db):
    case_id = theft_case(db)
    lock = body_question(db, case_id, 'lock')
    result = KnowledgeSuggestionService(db).recommend(case_id, question_id=lock.id)
    assert result['templateTitle'] == '盗窃（电动车）'
    assert result['focus']['elementKey'] == 'lock' and result['focus']['statusText'] == '尚未确认'
    first = result['suggestions'][0]
    assert first['elementKey'] == 'lock' and first['entryTitle'] == '盗窃电动车追问要点'
    assert first['entryVersion'] == 1 and first['sourceRef']

    # 回答写进正本后，锁具要素确认，不再推荐锁具追问
    TemplateWorkspaceService(db).upsert_case_question_answer(case_id, lock.id, answer_text='用的是 U 型锁，锁在车轮上。')
    db.flush()
    result = KnowledgeSuggestionService(db).recommend(case_id, question_id=lock.id)
    assert result['focus']['elementKey'] != 'lock'
    assert all(item['elementKey'] != 'lock' for item in result['suggestions'])


def test_adopting_creates_one_live_draft_question_after_the_element_and_never_a_formal_answer(db):
    case_id = theft_case(db)
    lock = body_question(db, case_id, 'lock')
    service = KnowledgeSuggestionService(db)
    suggestion = service.recommend(case_id, question_id=lock.id, actor_id='038291')['suggestions'][0]
    adopted = service.feedback(case_id, suggestion['key'], 'ADOPTED', actor_id='038291')
    again = service.feedback(case_id, suggestion['key'], 'ADOPTED', actor_id='038291')
    assert again['createdQuestionId'] == adopted['createdQuestionId']

    created = db.get(CaseQuestion, adopted['createdQuestionId'])
    assert (created.source, created.section_type, created.element_key) == ('LIVE', 'BODY', 'lock')
    assert created.text == suggestion['text'] and created.formal_answer_text == ''
    body = list(db.scalars(select(CaseQuestion.id).where(
        CaseQuestion.case_id == case_id, CaseQuestion.section_type == 'BODY', CaseQuestion.active.is_(True))
        .order_by(CaseQuestion.sort_order)))
    assert body[body.index(lock.id) + 1] == created.id
    assert db.scalar(select(func.count()).select_from(CaseQuestion).where(CaseQuestion.text == suggestion['text'])) == 1
    actions = list(db.scalars(select(AuditLog.action).where(AuditLog.action.like('KNOWLEDGE_SUGGESTION_%'))))
    assert actions == ['KNOWLEDGE_SUGGESTION_ADOPT']
    with pytest.raises(DomainError) as error:
        service.feedback(case_id, suggestion['key'], 'NOT_APPLICABLE')
    assert error.value.code == 'SUGGESTION_ALREADY_ADOPTED'


def test_not_applicable_is_persisted_and_repeated_views_or_clicks_count_once(db):
    case_id = theft_case(db)
    lock = body_question(db, case_id, 'lock')
    service = KnowledgeSuggestionService(db)
    shown = service.recommend(case_id, question_id=lock.id)['suggestions']
    for _ in range(3):
        service.recommend(case_id, question_id=lock.id)
    assert feedback_rows(db, case_id) == len(shown)

    dismissed = shown[0]
    service.feedback(case_id, dismissed['key'], 'NOT_APPLICABLE', actor_id='038291')
    service.feedback(case_id, dismissed['key'], 'NOT_APPLICABLE', actor_id='038291')
    assert dismissed['key'] not in {item['key'] for item in service.recommend(case_id, question_id=lock.id)['suggestions']}
    usage = service.usage_by_entry()[dismissed['entryId']]
    assert usage['notApplicable'] == 1 and usage['adopted'] == 0
    per_text = {item['text']: item for item in service.entry_usage(dismissed['entryId'])}
    assert per_text[dismissed['text']]['notApplicable'] == 1


def test_feedback_is_scoped_to_its_case_and_usage_counts_cases_not_clicks(db):
    first, second = theft_case(db), theft_case(db)
    service = KnowledgeSuggestionService(db)
    shown = service.recommend(first, question_id=body_question(db, first, 'lock').id)['suggestions'][0]
    with pytest.raises(DomainError) as error:
        service.feedback(second, shown['key'], 'ADOPTED')
    assert error.value.code == 'SUGGESTION_NOT_FOUND'
    assert db.scalar(select(func.count()).select_from(CaseQuestion).where(
        CaseQuestion.case_id == second, CaseQuestion.source == 'LIVE')) == 0

    service.feedback(first, shown['key'], 'ADOPTED')
    again = service.recommend(second, question_id=body_question(db, second, 'lock').id)['suggestions']
    same = next(item for item in again if item['key'] == shown['key'])
    # 另一个案件只看到汇总次数，看不到第一个案件的任何内容
    assert same['usage'] == {'shown': 1, 'adopted': 1, 'notApplicable': 0}
    per_text = {item['text']: item for item in service.entry_usage(shown['entryId'])}
    assert (per_text[shown['text']]['shown'], per_text[shown['text']]['adopted']) == (2, 1)


def test_only_verified_entries_in_force_are_recommended(db):
    case_id = theft_case(db)
    service = KnowledgeSuggestionService(db)
    entry_id = service.recommend(case_id)['suggestions'][0]['entryId']
    knowledge = KnowledgeService(db)
    knowledge.update_entry(entry_id, {'status': 'pending'})
    assert all(item['entryId'] != entry_id for item in service.recommend(case_id)['suggestions'])
    knowledge.update_entry(entry_id, {'status': 'verified', 'effectiveUntil': (date.today() - timedelta(days=1)).isoformat()})
    assert all(item['entryId'] != entry_id for item in service.recommend(case_id)['suggestions'])


def test_api_round_trip(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'api.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as http:
        case_id = http.post('/api/v1/cases', json={'suspectName': '王某'}).json()['data']['id']
        assert http.post(f'/api/v1/cases/{case_id}/template-selection', json={'templateId': 'theft-ebike'}).json()['ok']
        recommended = http.post('/api/v1/knowledge/suggestions', json={'caseId': case_id}).json()
        assert recommended['ok'], recommended
        suggestion = recommended['data']['suggestions'][0]
        adopted = http.post('/api/v1/knowledge/suggestions/feedback',
                            json={'caseId': case_id, 'key': suggestion['key'], 'action': 'ADOPTED'}).json()
        assert adopted['ok'] and adopted['data']['createdQuestionId']
        assert http.post('/api/v1/knowledge/suggestions/feedback',
                         json={'caseId': case_id, 'key': suggestion['key'], 'action': 'MAYBE'}).status_code == 422
        usage = http.get('/api/v1/knowledge/usage').json()['data']
        assert usage[suggestion['entryId']]['adopted'] == 1
