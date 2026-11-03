import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.database.catalog_models import KnowledgeEntry, KnowledgeExperienceCandidate, KnowledgeExperienceSource
from app.database.models import AuditLog, CaseQuestion, Person
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import cases as case_repo
from app.services.knowledge_experience import KnowledgeExperienceService, insert_suggestion_line, mask_question
from app.services.knowledge_suggestions import KnowledgeSuggestionService, parse_suggestions
from app.services.template_catalog_service import TemplateCatalogService
from app.services.template_workspace_service import TemplateWorkspaceService


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'experience.db'}")
    init_database(engine)
    with make_session_factory(engine)() as session:
        yield session
    engine.dispose()


def theft_case(db, *, suspect='张三'):
    case = case_repo.create(db, {})
    case.suspect_name = suspect
    TemplateCatalogService(db).select(case.id, template_id='theft-ebike', blank=False)
    db.flush()
    return case.id


def ask(db, case_id, text, *, answer='回答内容', element_key=None):
    """民警在问话中自己补充一题并得到回答。"""
    workspace = TemplateWorkspaceService(db)
    created = workspace.add_case_question(case_id, text=text, source='LIVE', element_key=element_key)
    if answer:
        workspace.upsert_case_question_answer(case_id, created['id'], answer_text=answer)
    db.flush()
    return created['id']


def close(db, case_id, state='FROZEN'):
    case_repo.get(db, case_id).workflow_state = state
    db.flush()


def pending(db):
    return KnowledgeExperienceService(db).overview(status='PENDING')['candidates']


def test_masking_replaces_case_specific_details_but_keeps_the_question():
    masked, rules = mask_question(
        '张三，你3月5日晚上8点把浙A12345的车停在文三路12号，手机13812345678，车值2000元吗？',
        names=['张三'], addresses=[])
    assert masked == '某某，你当天晚上那个时间把某车牌的车停在某地址，手机某号码，车值若干元吗？'
    assert rules == ['人名', '电话', '车牌', '日期', '时刻', '金额', '门牌']
    assert mask_question('你当时用的是什么锁？') == ('你当时用的是什么锁？', [])
    masked, rules = mask_question('你住在杭州市西湖区某街道100号吗', addresses=['杭州市西湖区某街道100号'])
    assert masked == '你住在某地址吗' and rules == ['地址']


def test_suggestion_line_goes_to_the_end_of_the_section():
    content = '# 标题\n\n## 建议问法\n\n- [lock] 甲？\n- 乙？\n\n## 其他\n\n- 不算\n'
    updated = insert_suggestion_line(content, '- [time_place] 丙？')
    assert parse_suggestions(updated) == [('lock', '甲？'), (None, '乙？'), ('time_place', '丙？')]
    assert insert_suggestion_line('# 标题\n\n正文', '- 丁？').endswith('## 建议问法\n\n- 丁？\n')


def test_only_officer_added_questions_from_closed_cases_are_harvested(db):
    open_case = theft_case(db)
    ask(db, open_case, '你停车的时候旁边有没有充电桩？')                     # 未结案：不提炼

    closed = theft_case(db)
    asked = ask(db, closed, '张三，你停车时旁边有没有其他电动车？', element_key='witness')
    ask(db, closed, '还没问的一题内容比较长', answer='')                      # 没问过：不提炼
    ask(db, closed, '当时锁了吗？')                                          # 与模板原题相同：不提炼
    ask(db, closed, '停车时车上用了什么锁？')                                # 知识库已有问法：不提炼
    lock = db.scalar(select(CaseQuestion).where(CaseQuestion.case_id == closed, CaseQuestion.element_key == 'lock',
                                                CaseQuestion.section_type == 'BODY', CaseQuestion.source != 'LIVE'))
    suggestion = KnowledgeSuggestionService(db).recommend(closed, question_id=lock.id)['suggestions'][-1]
    KnowledgeSuggestionService(db).feedback(closed, suggestion['key'], 'ADOPTED')   # 采纳推荐生成的题：不提炼
    close(db, closed)

    voided = theft_case(db)
    ask(db, voided, '作废案件里补问的问题？')
    close(db, voided)
    case_repo.get(db, voided).document_status = 'VOIDED'
    db.flush()

    service = KnowledgeExperienceService(db)
    assert service.harvest() == {'scannedCases': 1, 'addedSources': 1, 'newCandidates': 1}
    assert service.harvest() == {'scannedCases': 1, 'addedSources': 0, 'newCandidates': 0}   # 可重复执行

    [candidate] = pending(db)
    assert candidate['proposedText'] == '某某，你停车时旁边有没有其他电动车？'
    assert candidate['maskRules'] == ['人名']
    assert (candidate['scopeKey'], candidate['scopeTitle']) == ('THEFT_EBIKE_V1', '盗窃（电动车）')
    assert (candidate['elementKey'], candidate['elementLabel']) == ('witness', '可疑对象与目击情况')
    assert candidate['sources'] == [{'caseId': closed, 'questionId': asked,
                                     'originalText': '张三，你停车时旁边有没有其他电动车？',
                                     'harvestedAt': candidate['sources'][0]['harvestedAt']}]
    # 只存问题，不存回答
    assert '回答内容' not in str(candidate)


def test_same_question_in_several_cases_merges_into_one_candidate(db):
    for suspect in ('张三', '李四', '王五'):
        case_id = theft_case(db, suspect=suspect)
        ask(db, case_id, f'{suspect}，你停车时旁边有没有其他电动车？')
        close(db, case_id, 'SIGNED')
    KnowledgeExperienceService(db).harvest()
    [candidate] = pending(db)
    assert candidate['caseCount'] == 3 and len(candidate['sources']) == 3
    assert db.scalar(select(func.count()).select_from(KnowledgeExperienceCandidate)) == 1


def test_approval_publishes_a_reviewed_entry_version_used_by_the_next_case(db):
    closed = theft_case(db)
    ask(db, closed, '张三，你停车时旁边有没有其他电动车？')
    close(db, closed)
    service = KnowledgeExperienceService(db)
    service.harvest()
    [candidate] = pending(db)

    with pytest.raises(DomainError) as error:
        service.approve(candidate['id'], text='问', element_key='witness')
    assert error.value.code == 'INVALID_EXPERIENCE_TEXT'
    with pytest.raises(DomainError) as error:
        service.approve(candidate['id'], text='你停车时旁边有没有其他电动车？', element_key='nope')
    assert error.value.code == 'INVALID_EXPERIENCE_ELEMENT'

    result = service.approve(candidate['id'], text='你停车时旁边有没有其他电动车？', element_key='witness',
                             note='去掉称呼', actor_id='038291')
    entry = db.get(KnowledgeEntry, result['entry']['id'])
    assert (entry.status, entry.origin, entry.category_id, entry.current_version) == ('verified', 'manual', 'questioning', 1)
    assert entry.title == '办案经验问法 · 盗窃（电动车）'
    assert parse_suggestions(entry.content) == [('witness', '你停车时旁边有没有其他电动车？')]
    assert result['entry']['checkTemplates'] == ['THEFT_EBIKE_V1']
    assert result['candidate']['status'] == 'APPROVED' and result['candidate']['publishedVersion'] == 1
    with pytest.raises(DomainError) as error:
        service.approve(candidate['id'], text='你停车时旁边有没有其他电动车？')
    assert error.value.code == 'EXPERIENCE_ALREADY_APPROVED'

    # 下一个同类案件：目击要素未确认时，推荐里出现这条经审核的问法
    next_case = theft_case(db, suspect='赵六')
    witness = db.scalar(select(CaseQuestion).where(CaseQuestion.case_id == next_case, CaseQuestion.element_key == 'witness'))
    texts = [item['text'] for item in KnowledgeSuggestionService(db).recommend(next_case, question_id=witness.id, limit=6)['suggestions']]
    assert '你停车时旁边有没有其他电动车？' in texts

    # 第二条通过：追加到同一条目，版本 +1
    second = theft_case(db, suspect='孙七')
    ask(db, second, '车停好以后你去了哪里，离开多久？')
    close(db, second)
    service.harvest()
    [candidate] = pending(db)
    result = service.approve(candidate['id'], text=candidate['proposedText'], element_key='last_seen')
    assert result['entry']['id'] == entry.id and result['entry']['version'] == 2
    assert [text for _key, text in parse_suggestions(db.get(KnowledgeEntry, entry.id).content)] == [
        '你停车时旁边有没有其他电动车？', '车停好以后你去了哪里，离开多久？']
    # 已发布的问法再出现时不会再变成候选
    third = theft_case(db, suspect='周八')
    ask(db, third, '你停车时旁边有没有其他电动车')
    close(db, third)
    assert service.harvest()['newCandidates'] == 0 and pending(db) == []

    actions = list(db.scalars(select(AuditLog.action).where(AuditLog.action.like('KNOWLEDGE_EXPERIENCE_%'))))
    assert actions.count('KNOWLEDGE_EXPERIENCE_APPROVE') == 2


def test_rejected_candidates_stay_rejected_when_seen_again(db):
    first = theft_case(db)
    ask(db, first, '你平时喜欢在哪里吃饭？')
    close(db, first)
    service = KnowledgeExperienceService(db)
    service.harvest()
    [candidate] = pending(db)
    rejected = service.reject(candidate['id'], note='与案件无关', actor_id='038291')
    assert rejected['status'] == 'REJECTED' and rejected['reviewNote'] == '与案件无关'

    again = theft_case(db, suspect='李四')
    ask(db, again, '你平时喜欢在哪里吃饭')
    close(db, again)
    assert service.harvest()['newCandidates'] == 0
    assert pending(db) == []
    [row] = service.overview(status='REJECTED')['candidates']
    assert row['caseCount'] == 2
    assert db.scalar(select(func.count()).select_from(KnowledgeEntry).where(KnowledgeEntry.title.like('办案经验问法%'))) == 0


def test_overview_reports_elements_left_unconfirmed_at_close(db):
    for suspect in ('张三', '李四'):
        case_id = theft_case(db, suspect=suspect)
        lock = db.scalar(select(CaseQuestion).where(CaseQuestion.case_id == case_id, CaseQuestion.element_key == 'lock'))
        if suspect == '张三':
            TemplateWorkspaceService(db).upsert_case_question_answer(case_id, lock.id, answer_text='U 型锁')
        close(db, case_id)
    [scope] = KnowledgeExperienceService(db).overview()['scopes']
    assert scope['closedCases'] == 2 and scope['templateKey'] == 'THEFT_EBIKE_V1'
    gaps = {gap['elementKey']: gap['cases'] for gap in scope['gaps']}
    assert gaps['lock'] == 1 and gaps['vehicle'] == 2


def test_person_names_and_addresses_from_the_case_are_masked(db):
    case_id = theft_case(db, suspect='待录入')
    db.add(Person(id='p1', case_id=case_id, role='suspect', name='欧阳明', id_number='x', address='城南新村7幢'))
    ask(db, case_id, '欧阳明，你那天回城南新村7幢了吗？')
    close(db, case_id)
    KnowledgeExperienceService(db).harvest()
    [candidate] = pending(db)
    assert candidate['proposedText'] == '某某，你那天回某地址了吗？'
    assert db.scalar(select(KnowledgeExperienceSource.original_text)) == '欧阳明，你那天回城南新村7幢了吗？'


def test_experience_api_round_trip(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'api.db'}", hardware_gateway=MockHardwareGateway())
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            case_id = theft_case(db)
            ask(db, case_id, '张三，你停车时旁边有没有其他电动车？')
            close(db, case_id)
            db.commit()
        harvested = client.post('/api/v1/knowledge/experience/harvest').json()['data']
        assert harvested['newCandidates'] == 1
        overview = client.get('/api/v1/knowledge/experience', params={'status': 'PENDING'}).json()['data']
        assert overview['counts']['PENDING'] == 1
        candidate = overview['candidates'][0]
        bad = client.post(f"/api/v1/knowledge/experience/{candidate['id']}/approve", json={'text': ''})
        assert bad.status_code == 422
        approved = client.post(f"/api/v1/knowledge/experience/{candidate['id']}/approve",
                               json={'text': '你停车时旁边有没有其他电动车？', 'elementKey': 'witness'})
        assert approved.status_code == 200 and approved.json()['data']['entry']['status'] == 'verified'
        conflict = client.post(f"/api/v1/knowledge/experience/{candidate['id']}/reject", json={'note': 'x'})
        assert conflict.status_code == 409
        assert client.get('/api/v1/knowledge/experience', params={'status': 'bogus'}).status_code == 400
        assert client.post('/api/v1/knowledge/experience/nope/reject', json={}).status_code == 404
