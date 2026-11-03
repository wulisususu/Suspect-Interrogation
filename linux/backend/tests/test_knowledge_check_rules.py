import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.catalog_models import KnowledgeCheckBinding, KnowledgeEntry
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import cases as case_repo


def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'check-rules.db'}")
    init_database(engine)
    return make_session_factory(engine)()


def case_with_template(db, template_id=None, *, blank=False):
    from app.services.template_catalog_service import TemplateCatalogService

    case = case_repo.create(db, {})
    TemplateCatalogService(db).select(case.id, template_id=template_id, blank=blank)
    return case


def titles(result):
    return [rule['title'] for rule in result['rules']]


def test_check_items_are_parsed_from_the_rule_section_only():
    from app.services.knowledge_checks import parse_check_items

    content = '''# 规则

- 这一行不在校验项里

## 校验项

- 锁具情况 [lock]：锁、U型锁、遥控锁
* 购买凭证: 发票，收据
- 车辆价值
-

## 说明

- 说明里的列表不是校验项
'''
    assert parse_check_items(content) == [
        {'label': '锁具情况', 'terms': ['锁', 'U型锁', '遥控锁'], 'elementKey': 'lock'},
        {'label': '购买凭证', 'terms': ['发票', '收据'], 'elementKey': None},
        {'label': '车辆价值', 'terms': ['车辆价值'], 'elementKey': None},
    ]
    assert parse_check_items('# 说明\n\n- 锁') == []


def test_binding_values_split_into_template_keys_and_case_types():
    from app.services.knowledge_checks import binding_scope, normalize_bindings

    assert binding_scope('THEFT_EBIKE_V1') == 'TEMPLATE'
    assert binding_scope('theft') == 'CASE_TYPE'
    assert binding_scope('盗窃') is None
    assert normalize_bindings([' theft ', 'THEFT_EBIKE_V1', 'theft', '']) == ['theft', 'THEFT_EBIKE_V1']
    with pytest.raises(DomainError):
        normalize_bindings(['盗窃电动车'])


def test_theft_ebike_case_loads_template_rule_before_case_type_rule_with_source(tmp_path):
    from app.services.knowledge_checks import KnowledgeCheckService

    with database(tmp_path) as db:
        case = case_with_template(db, 'theft-ebike')
        result = KnowledgeCheckService(db).rules_for_case(case.id)
        assert result['templateKey'] == 'THEFT_EBIKE_V1'
        assert result['caseType'] == 'theft'
        assert titles(result) == ['盗窃电动车笔录定稿校验', '盗窃案件财物损失核对']
        ebike, common = result['rules']
        assert ebike['matchedBy'] == {'scope': 'TEMPLATE', 'value': 'THEFT_EBIKE_V1'}
        assert common['matchedBy'] == {'scope': 'CASE_TYPE', 'value': 'theft'}
        assert ebike['sourcePath'] == 'rules/rule-theft-ebike.md'
        assert ebike['version'] == 1 and ebike['status'] == 'verified' and ebike['origin'] == 'vault'
        assert ebike['categoryName'] == '定稿校验规则'
        labels = {item['label']: item for item in ebike['items']}
        assert {'锁具情况', '购买凭证', '车辆价值'} <= set(labels)
        assert labels['锁具情况']['elementKey'] == 'lock'
        assert '发票' in labels['购买凭证']['terms']
        assert all(item['key'].startswith(ebike['entryId'] + '#') for item in ebike['items'])


def test_rules_follow_the_case_template(tmp_path):
    from app.services.knowledge_checks import KnowledgeCheckService

    with database(tmp_path) as db:
        service = KnowledgeCheckService(db)
        assert titles(service.rules_for_case(case_with_template(db, 'injury-assault').id)) == ['故意伤害笔录定稿校验']
        assert titles(service.rules_for_case(case_with_template(db, 'theft-vehicle-goods').id)) == ['盗窃案件财物损失核对']
        assert service.rules_for_case(case_with_template(db, 'traffic-simple').id)['rules'] == []
        blank = service.rules_for_case(case_with_template(db, blank=True).id)
        assert blank['rules'] == [] and blank['templateKey'] == 'BLANK_V1'
        legacy = case_repo.create(db, {})
        assert service.rules_for_case(legacy.id) == {'caseId': legacy.id, 'templateKey': None, 'caseType': None, 'rules': []}
        with pytest.raises(DomainError) as error:
            service.rules_for_case('missing-case')
        assert error.value.code == 'CASE_NOT_FOUND'


def test_fraud_template_created_in_template_management_picks_up_fraud_rule(tmp_path):
    from app.services.knowledge_checks import KnowledgeCheckService
    from app.services.template_catalog_service import TemplateCatalogService

    with database(tmp_path) as db:
        TemplateCatalogService(db).create(
            template_id='fraud-telecom', backend_key='FRAUD_TELECOM_V1',
            catalog={'title': '诈骗（电信网络）', 'category': 'other'},
            structure={'elements': [{'key': 'transfer', 'label': '转账经过'}],
                       'questions': [{'key': 'q1', 'text': '你是怎么转账的？', 'elementKey': 'transfer'}]},
        )
        case = case_with_template(db, 'fraud-telecom')
        result = KnowledgeCheckService(db).rules_for_case(case.id)
        assert titles(result) == ['电信网络诈骗笔录定稿校验']
        assert [item['label'] for item in result['rules'][0]['items']][:3] == ['转账时间', '收款账户', '资金流向']


def test_bundled_rules_seed_once_and_never_resurrect_deleted_or_load_unverified(tmp_path):
    from app.services.knowledge_checks import KnowledgeCheckService
    from app.services.knowledge_service import KnowledgeService

    with database(tmp_path) as db:
        service = KnowledgeCheckService(db)
        created = service.ensure_bundled_rules()
        assert {'rule-theft-ebike', 'rule-theft-common', 'rule-fraud-telecom', 'rule-injury-assault'} <= set(created)
        assert service.ensure_bundled_rules() == []
        ebike = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.vault_uid == 'rule-theft-ebike'))
        knowledge = KnowledgeService(db)
        assert knowledge.versions(ebike.id)[0]['action'] == 'BUNDLE_CREATE'
        assert knowledge.detail(ebike.id)['checkTemplates'] == ['THEFT_EBIKE_V1']

        knowledge.update_entry(ebike.id, {'status': 'pending'})
        assert titles({'rules': service.rules_for_template('THEFT_EBIKE_V1', 'theft')}) == ['盗窃案件财物损失核对']
        knowledge.update_entry(ebike.id, {'status': 'verified', 'active': False})
        assert titles({'rules': service.rules_for_template('THEFT_EBIKE_V1', 'theft')}) == ['盗窃案件财物损失核对']
        knowledge.delete_entry(ebike.id)
        assert service.ensure_bundled_rules() == []
        assert titles({'rules': service.rules_for_template('THEFT_EBIKE_V1', None)}) == []


def test_manual_rule_entry_binds_via_api_and_loads_for_the_case(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'check-rules-api.db'}",
                     hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as http:
        def data(response):
            body = response.json()
            assert body['ok'] is True, body
            return body['data']

        category = data(http.get('/api/v1/knowledge/categories'))[0]['id']
        entry = data(http.post('/api/v1/knowledge/entries', json={
            'title': '交通事故保险核对', 'categoryId': category,
            'content': '## 校验项\n\n- 保险公司 [insurance]：保险、保单', 'checkTemplates': ['TRAFFIC_SIMPLE_V1'],
        }))
        assert entry['checkTemplates'] == ['TRAFFIC_SIMPLE_V1']
        # 手工新建默认 pending：核实前不进入定稿校验
        preview = data(http.get('/api/v1/knowledge/check-rules', params={'templateKey': 'TRAFFIC_SIMPLE_V1'}))
        assert preview['rules'] == []
        data(http.patch(f"/api/v1/knowledge/entries/{entry['id']}", json={'status': 'verified'}))

        case_id = data(http.post('/api/v1/cases', json={}))['id']
        data(http.post(f'/api/v1/cases/{case_id}/template-selection', json={'templateId': 'traffic-simple'}))
        result = data(http.get('/api/v1/knowledge/check-rules', params={'caseId': case_id}))
        assert result['templateKey'] == 'TRAFFIC_SIMPLE_V1' and result['caseType'] == 'traffic'
        assert [rule['title'] for rule in result['rules']] == ['交通事故保险核对']
        assert result['rules'][0]['items'][0] == {
            'label': '保险公司', 'terms': ['保险', '保单'], 'elementKey': 'insurance',
            'key': f"{entry['id']}#0",
        }

        updated = data(http.patch(f"/api/v1/knowledge/entries/{entry['id']}", json={'checkTemplates': ['traffic']}))
        assert updated['checkTemplates'] == ['traffic']
        assert data(http.get('/api/v1/knowledge/check-rules', params={'caseId': case_id}))['rules'][0]['matchedBy'] == {
            'scope': 'CASE_TYPE', 'value': 'traffic'}
        bad = http.patch(f"/api/v1/knowledge/entries/{entry['id']}", json={'checkTemplates': ['交通']})
        assert bad.status_code == 400
        assert http.get('/api/v1/knowledge/check-rules', params={'caseId': 'missing'}).status_code == 404


RULE_NOTE = '''---
uid: rule-test
title: 测试校验规则
category: 定稿校验规则
kind: wiki
status: verified
templates:
{templates}
---
# 测试

## 校验项

- 现场照片：照片、拍照
'''


def test_vault_templates_frontmatter_creates_and_clears_bindings(tmp_path):
    from app.services.knowledge_service import KnowledgeService

    root = tmp_path / 'vault'
    (root / 'rules').mkdir(parents=True)
    note = root / 'rules' / 'rule-test.md'
    note.write_text(RULE_NOTE.format(templates='  - THEFT_EBIKE_V1\n  - 盗窃'), encoding='utf-8')
    with database(tmp_path) as db:
        service = KnowledgeService(db)
        report = service.import_vault(root, dry_run=False)
        assert any('盗窃' in warning for warning in report['warnings'])
        entry = db.scalar(select(KnowledgeEntry).where(KnowledgeEntry.vault_uid == 'rule-test'))
        assert service.detail(entry.id)['checkTemplates'] == ['THEFT_EBIKE_V1']

        note.write_text(RULE_NOTE.format(templates='  - injury'), encoding='utf-8')
        service.import_vault(root, dry_run=False)
        rows = list(db.scalars(select(KnowledgeCheckBinding).where(KnowledgeCheckBinding.entry_id == entry.id)))
        assert [(row.scope, row.value) for row in rows] == [('CASE_TYPE', 'injury')]
        assert service.versions(entry.id)[0]['data']['checkTemplates'] == ['injury']
