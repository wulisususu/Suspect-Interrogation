from app.database.models import Case, CaseQuestion
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.enums import WorkflowState
from app.services.knowledge_matching import normalize, similar_question
from app.services.knowledge_service import KnowledgeService

TIME_NOTE = '''# 案发时间核对要点

询问案发时间时，先让当事人用自己的话讲一遍。

## 建议问法

- 这件事是哪一天、大概几点发生的？
- 你是怎么记住这个时间的？有没有看过手机、监控或者付款记录？
'''


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'guidance.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def entry(service, title, content='正文', keywords=(), status='verified'):
    category = service.categories()[0]['id']
    return service.create_entry(title=title, category_id=category, content=content, keywords=list(keywords), status=status)


def test_colloquial_phrasing_is_normalized_to_concepts():
    assert {'时间', '转账', '资金'} <= normalize('钱是什么时候转出去的？').concepts
    # 最长匹配：「付款记录」是凭证，「多少钱」是价值，不被拆成转账 / 资金
    assert normalize('有没有付款记录').concepts == {'凭证'}
    assert normalize('车值多少钱').concepts == {'价值'}
    assert similar_question('这件事是哪一天、大概几点发生的？', '这件事是哪一天，大概几点发生的')
    assert not similar_question('这件事是哪一天、大概几点发生的？', '车辆当时锁了吗？')


def test_guidance_understands_different_wording_and_skips_unrelated(tmp_path):
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        transfer = entry(service, '转账时间与资金流向核对', keywords=['资金流向'])
        entry(service, '电子签名与捺印取证规范', keywords=['签名', '捺印'])
        matches = service.guidance_for(text='钱是什么时候转出去的', limit=5)
        assert [item['id'] for item in matches] == [transfer['id']]
        assert any(reason.startswith('标题相关') for reason in matches[0]['matchReasons'])


def test_answer_text_feeds_retrieval_and_pending_entries_stay_hidden(tmp_path):
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        db.add(Case(id='case-1', workflow_state=WorkflowState.CASE_CREATED.value))
        db.add(CaseQuestion(id='q-1', case_id='case-1', source='LIVE', text='后来呢？', sort_order=1))
        db.flush()
        lock = entry(service, '防盗锁具核对', keywords=['车锁'])
        entry(service, '未审核的锁具说明', keywords=['车锁'], status='pending')
        assert service.guidance_for(case_id='case-1', question_id='q-1') == []
        matches = service.guidance_for(case_id='case-1', question_id='q-1', text='锁了，我平时上下班都锁好的')
        assert [item['id'] for item in matches] == [lock['id']]


def test_draft_questions_skip_questions_already_in_the_case(tmp_path):
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        entry(service, '案发时间核对要点', content=TIME_NOTE, keywords=['案发时间', '几点'])
        db.add(Case(id='case-1', workflow_state=WorkflowState.CASE_CREATED.value))
        db.add(CaseQuestion(id='q-1', case_id='case-1', source='TEMPLATE', text='这件事是哪一天，大概几点发生的？', sort_order=1))
        db.flush()
        drafts = service.draft_questions(case_id='case-1', question_id='q-1', limit=3)
        assert [item['text'] for item in drafts] == ['你是怎么记住这个时间的？有没有看过手机、监控或者付款记录？']
        assert drafts[0]['entryTitle'] == '案发时间核对要点'
        assert service.guidance_for(case_id='case-1', question_id='q-1')[0]['snippet'] == '询问案发时间时，先让当事人用自己的话讲一遍。'
