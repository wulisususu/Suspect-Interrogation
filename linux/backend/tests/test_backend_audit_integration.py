from fastapi.testclient import TestClient

from app.database.models import Case
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


def data(response):
    assert response.status_code == 200, response.text
    assert response.json()['ok'] is True
    return response.json()['data']


def test_template_switch_ensure_reorder_and_blank_remain_consistent(tmp_path):
    app = create_app(database_url=f'sqlite:///{tmp_path / "integration.db"}', hardware_gateway=MockHardwareGateway())
    client = TestClient(app)
    case_id = data(client.post('/api/v1/cases', json={}))['id']
    prefix = f'/api/v1/cases/{case_id}'
    selected = data(client.post(prefix + '/template-selection', json={'templateId': 'theft-ebike'}))
    assert selected['templateKey'] == 'THEFT_EBIKE_V1'
    selected = data(client.post(prefix + '/template-selection', json={'templateId': 'injury-assault'}))
    ensured = data(client.post(prefix + '/formal-record/ensure'))
    assert [q['id'] for q in ensured['questions']] == [q['id'] for q in selected['questions']]
    added = data(client.post(prefix + '/questions', json={'text': '还有什么伤情？', 'source': 'CASE', 'elementKey': 'injury'}))
    assert added['elementKey'] == 'injury'
    data(client.put(prefix + f'/questions/{added["id"]}/answer', json={'answerText': '手臂擦伤'}))
    facts = data(client.get(prefix + '/facts'))
    assert next(f for f in facts if f['key'] == 'injury')['status'] == 'confirmed'
    patched = data(client.patch(prefix + f'/questions/{added["id"]}', json={'elementKey': None}))
    assert patched['elementKey'] is None
    assert next(f for f in data(client.get(prefix + '/facts')) if f['key'] == 'injury')['status'] == 'pending'
    # A separate blank case must not regain legacy body elements on updates/ensure.
    blank_id = data(client.post('/api/v1/cases', json={}))['id']
    blank_prefix = f'/api/v1/cases/{blank_id}'
    data(client.post(blank_prefix + '/template-selection', json={'blank': True}))
    data(client.put(blank_prefix + '/facts/contact', json={'value': '123'}))
    blank = data(client.post(blank_prefix + '/formal-record/ensure'))
    assert len(blank['questions']) == 9
    assert all(q['sectionType'] != 'BODY' for q in blank['questions'])
    assert not {'time', 'place', 'process'}.intersection(f['key'] for f in data(client.get(blank_prefix + '/facts')))


def test_capture_api_forwards_target_and_replace_and_preserves_legacy_start(tmp_path):
    app = create_app(database_url=f'sqlite:///{tmp_path / "capture-api.db"}', hardware_gateway=MockHardwareGateway())
    calls = []
    class Capture:
        def start(self, case_id, **kwargs):
            calls.append((case_id, kwargs))
            return {'active': True, 'targetQuestionId': kwargs.get('target_question_id')}
    app.state.asr_capture_service = Capture()
    client = TestClient(app)
    endpoint = '/api/v1/cases/case/asr/capture/start'
    assert client.post(endpoint, json={'targetQuestionId': 'question', 'replace': True}).status_code == 200
    assert calls[-1] == ('case', {'target_question_id': 'question', 'replace': True})
    assert client.post(endpoint).status_code == 200
    assert calls[-1] == ('case', {})
    assert client.post(endpoint, json={'targetQuestionId': ''}).status_code == 422


def test_void_blocks_existing_mutation_routes_and_remains_visible(tmp_path):
    app = create_app(database_url=f'sqlite:///{tmp_path / "void-api.db"}', hardware_gateway=MockHardwareGateway())
    client = TestClient(app)
    case_id = data(client.post('/api/v1/cases', json={}))['id']
    prefix = f'/api/v1/cases/{case_id}'
    question = data(client.post(prefix + '/questions', json={'text': '何时？', 'source': 'CASE'}))
    data(client.post(prefix + '/void', json={'reason': '重复建档'}))
    for response in [
        client.put(prefix, json={'suspectName': '修改'}),
        client.post(prefix + '/formal-record/ensure'),
        client.put(prefix + f'/questions/{question["id"]}/answer', json={'answerText': '修改'}),
        client.post('/api/v1/identity/read', json={'case_id': case_id}),
    ]:
        assert response.status_code == 409, response.text
        assert response.json()['code'] == 'CASE_VOIDED'
    assert data(client.get(prefix))['voidReason'] == '重复建档'
    assert data(client.get('/api/v1/cases'))[0]['workflowState'] == 'VOIDED'


def test_officer_auth_covers_legacy_routes_and_failed_actions_keep_real_actor(tmp_path):
    from app.services.officer_service import OfficerService

    app = create_app(database_url=f'sqlite:///{tmp_path / "auth-integration.db"}', hardware_gateway=MockHardwareGateway())
    with app.state.session_factory() as db:
        service = OfficerService(db)
        service.provision_officer(badge_number='038291', name='张伟', unit='刑侦', password='Strong-test-pass1', is_admin=True)
        service.provision_officer(badge_number='038292', name='李明', unit='刑侦', password='Strong-test-pass2')
        db.commit()
    client = TestClient(app, base_url='https://testserver')
    for path in ['/api/v1/cases', '/api/cases', '/work/case/any']:
        assert client.get(path).status_code == 401
    assert client.post('/api/cases/create', json={}).status_code == 401
    data(client.post('/api/v1/auth/login', json={'badgeNumber': '038291', 'password': 'Strong-test-pass1'}))
    case = data(client.post('/api/v1/cases', json={'operatorId': 'forged', 'interrogatorBadgeNumber': '038291', 'recorderBadgeNumber': '038292', 'fullRecordingEnabled': False}))
    assert case['operatorId'] == '038291'
    assert case['interrogator']['badgeNumber'] == '038291'
    assert case['recorder']['badgeNumber'] == '038292'
    assert case['fullRecordingEnabled'] is False
    saved = data(client.put(f'/api/v1/cases/{case["id"]}', json={'operatorId': 'forged-update'}))
    assert saved['operatorId'] == '038291'
    failed = client.post(f'/api/v1/cases/{case["id"]}/questions', json={'text': '问题', 'source': 'CASE', 'elementKey': 'invalid'})
    assert failed.status_code == 400
    logs = data(client.get('/api/v1/audit-logs', params={'result': 'FAILURE', 'caseId': case['id']}))
    assert logs['total'] == 1
    assert logs['items'][0]['actorId'] == '038291'
    assert logs['items'][0]['actorDisplayName'] == '张伟（038291）'
    data(client.post('/api/v1/auth/lock'))
    assert client.get('/api/cases').status_code == 423
    data(client.post('/api/v1/auth/unlock'))
    assert client.get('/api/cases').status_code == 200
