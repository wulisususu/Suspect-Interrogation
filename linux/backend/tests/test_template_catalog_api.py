from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


def client_app(tmp_path):
    from app.api.template_catalog import router as template_router
    from app.api.knowledge import router as knowledge_router

    app = create_app(database_url=f"sqlite:///{tmp_path / 'catalog-api.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    paths = {route.path for route in app.routes}
    if '/api/v1/templates/catalog' not in paths:
        app.include_router(template_router, prefix='/api/v1')
    if '/api/v1/knowledge/entries' not in paths:
        app.include_router(knowledge_router, prefix='/api/v1')
    return app


def data(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['ok'] is True
    return body['data']


def test_catalog_selection_version_and_disabled_contract(tmp_path):
    app = client_app(tmp_path)
    with TestClient(app) as client:
        catalog = data(client.get('/api/v1/templates/catalog'))
        assert len(catalog) == 6
        case = data(client.post('/api/v1/cases', json={'operatorId': 'test'}))
        selected = data(client.post(f"/api/v1/cases/{case['id']}/template-selection", json={'templateId': 'theft-ebike'}))
        assert selected['templateKey'] == 'THEFT_EBIKE_V1'
        assert len([q for q in selected['questions'] if q['sectionType'] == 'BODY']) == 6
        original = data(client.get(f"/api/v1/cases/{case['id']}/template-selection"))
        template = data(client.get('/api/v1/templates/theft-ebike'))
        updated = data(client.post('/api/v1/templates/theft-ebike/versions', json={'structure': template['structure'], 'catalog': {'learnedCount': 3}}))
        assert updated['version'] == 2
        assert updated['learning'] == '已学习 3 份'
        assert data(client.get(f"/api/v1/cases/{case['id']}/template-selection")) == original
        assert len(data(client.get('/api/v1/templates/theft-ebike/versions'))) == 2
        data(client.patch('/api/v1/templates/theft-ebike', json={'active': False}))
        assert len(data(client.get('/api/v1/templates/catalog'))) == 5


def test_create_template_and_reject_bad_element_link(tmp_path):
    with TestClient(client_app(tmp_path)) as client:
        body = dict(id='new-template', backendKey='CUSTOM_V1', catalog={'title': '新模板', 'category': 'other'}, structure={'elements': [{'key': 'reason', 'label': '案由'}], 'questions': [{'key': 'q1', 'text': '案由？', 'elementKey': 'reason'}], 'topics': [{'key': 'basic', 'title': '基本信息', 'fields': [{'key': 'name', 'label': '姓名', 'type': 'text'}]}]})
        created = data(client.post('/api/v1/templates', json=body))
        assert created['structure']['topics'][0]['fields'][0]['key'] == 'name'
        invalid = {**body, 'id': 'invalid-template', 'backendKey': 'INVALID_V1', 'structure': {'elements': [], 'questions': [{'key': 'q1', 'text': '问？', 'elementKey': 'reason'}]}}
        response = client.post('/api/v1/templates', json=invalid)
        assert response.status_code == 400
        assert response.json()['code'] == 'INVALID_TEMPLATE_STRUCTURE'
        assert client.get('/api/v1/templates/invalid-template').status_code == 404


def test_knowledge_endpoints_preserve_history_and_exclude_disabled_guidance(tmp_path):
    with TestClient(client_app(tmp_path)) as client:
        category = data(client.post('/api/v1/knowledge/categories', json={'name': '案件专名'}))
        entry = data(client.post('/api/v1/knowledge/entries', json={'title': '凤凰路', 'categoryId': category['id'], 'content': '路名核对', 'keywords': ['凤凰路']}))
        assert len(data(client.get('/api/v1/knowledge/guidance'))) == 1
        data(client.patch(f"/api/v1/knowledge/entries/{entry['id']}", json={'active': False}))
        assert data(client.get('/api/v1/knowledge/guidance')) == []
        assert data(client.get(f"/api/v1/knowledge/entries?categoryId={category['id']}"))[0]['active'] is False
        data(client.delete(f"/api/v1/knowledge/entries/{entry['id']}"))
        assert client.get(f"/api/v1/knowledge/entries/{entry['id']}").status_code == 404
        assert [x['action'] for x in data(client.get(f"/api/v1/knowledge/entries/{entry['id']}/versions"))] == ['DELETE', 'UPDATE', 'CREATE']
