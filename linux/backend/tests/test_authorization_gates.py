import base64

from fastapi.testclient import TestClient

from app.database.models import ASRCaptureSession, ASRFragment, CaseQuestion, QAUnit, QAUnitFragment, QuestionRound
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.services.officer_service import OfficerService


PNG = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082'
)).decode()


def data(response):
    body = response.json()
    assert body['ok'] is True, body
    return body['data']


def make_app(tmp_path):
    app = create_app(database_url=f'sqlite:///{tmp_path / "gates.db"}', hardware_gateway=MockHardwareGateway())
    with app.state.session_factory() as db:
        service = OfficerService(db)
        service.provision_officer(badge_number='038291', name='张伟', password='Strong-test-pass1', is_admin=True)
        service.provision_officer(badge_number='038292', name='李明', password='Strong-test-pass2')
        service.provision_officer(badge_number='038293', name='王强', password='Strong-test-pass3')
        db.commit()
    return app


def login(app, badge, password):
    client = TestClient(app, base_url='https://testserver')
    data(client.post('/api/v1/auth/login', json={'badgeNumber': badge, 'password': password}))
    return client


def test_roster_administration_requires_an_administrator(tmp_path):
    app = make_app(tmp_path)
    officer = login(app, '038292', 'Strong-test-pass2')
    admin = login(app, '038291', 'Strong-test-pass1')

    gated = [
        ('post', '/api/v1/templates', {'templateId': 'x', 'backendKey': 'X_V1', 'catalog': {}, 'structure': {}}),
        ('patch', '/api/v1/templates/any', {'active': False}),
        ('post', '/api/v1/knowledge/categories', {'name': '新分类'}),
        ('post', '/api/v1/knowledge/import', {'dryRun': True}),
        ('post', '/api/v1/knowledge/term-corrections', {'wrong': '甲', 'right': '乙'}),
        ('get', '/api/v1/audit-logs', None),
    ]
    for method, path, body in gated:
        response = getattr(officer, method)(path, **({'json': body} if body is not None else {}))
        assert response.status_code == 403, (path, response.json())
        assert response.json()['code'] == 'AUTH_ADMIN_REQUIRED'

    assert data(admin.post('/api/v1/knowledge/categories', json={'name': '新分类'}))['name'] == '新分类'
    assert 'items' in data(admin.get('/api/v1/audit-logs'))

    # A single case's trail stays readable to any officer.
    case = data(officer.post('/api/v1/cases', json={'interrogatorBadgeNumber': '038292', 'recorderBadgeNumber': '038293'}))
    assert 'items' in data(officer.get('/api/v1/audit-logs', params={'caseId': case['id']}))


def test_only_the_case_officers_or_an_administrator_may_void(tmp_path):
    app = make_app(tmp_path)
    interrogator = login(app, '038292', 'Strong-test-pass2')
    admin = login(app, '038291', 'Strong-test-pass1')
    case = data(interrogator.post('/api/v1/cases', json={'interrogatorBadgeNumber': '038292'}))

    outsider = login(app, '038293', 'Strong-test-pass3')
    refused = outsider.post(f'/api/v1/cases/{case["id"]}/void', json={'reason': '误建'})
    assert refused.status_code == 403
    assert refused.json()['code'] == 'CASE_VOID_FORBIDDEN'

    assert data(interrogator.post(f'/api/v1/cases/{case["id"]}/void', json={'reason': '误建'}))['workflowState'] == 'VOIDED'
    other = data(interrogator.post('/api/v1/cases', json={'interrogatorBadgeNumber': '038292'}))
    assert data(admin.post(f'/api/v1/cases/{other["id"]}/void', json={'reason': '重复'}))['workflowState'] == 'VOIDED'


def test_saved_signature_images_are_only_returned_to_their_owner(tmp_path):
    app = make_app(tmp_path)
    owner = login(app, '038292', 'Strong-test-pass2')
    data(owner.post('/api/v1/officers/038292/signatures', json={'imageData': PNG}))

    assert data(owner.get('/api/v1/officers/038292/signatures'))[0]['imageData'] == PNG
    for badge, password in [('038293', 'Strong-test-pass3'), ('038291', 'Strong-test-pass1')]:
        listed = data(login(app, badge, password).get('/api/v1/officers/038292/signatures'))
        assert listed[0]['imageData'] is None
        assert listed[0]['version'] == 1


def test_fragments_backing_a_formal_round_cannot_be_discarded_or_duplicated(tmp_path):
    app = make_app(tmp_path)
    client = login(app, '038291', 'Strong-test-pass1')
    case = data(client.post('/api/v1/cases', json={}))
    data(client.post('/api/v1/identity/confirm', json={'case_id': case['id'], 'name': '测试对象'}))
    data(client.post(f'/api/v1/cases/{case["id"]}/session/start', json={}))
    with app.state.session_factory() as db:
        db.add(ASRCaptureSession(id='CAP', case_id=case['id'], status='COMPLETE', sample_rate=16000,
                                 recording_status='COMPLETE', asr_status='COMPLETE', speaker_status='COMPLETE'))
        for ordinal, (fragment_id, speaker) in enumerate([('F-Q', 'INTERROGATOR'), ('F-A', 'SUSPECT'), ('F-FREE', 'SUSPECT')]):
            db.add(ASRFragment(id=fragment_id, capture_session_id='CAP', case_id=case['id'], ordinal=ordinal,
                               started_at_ms=ordinal * 1000, ended_at_ms=ordinal * 1000 + 500, raw_text='文本',
                               edited_text='文本', speaker=speaker, speaker_source='SPEAKER_EMBEDDING',
                               voiceprint_verified=True, low_confidence=False, state='PENDING', model_id='m'))
        db.add(CaseQuestion(id='Q', case_id=case['id'], source='CASE', text='问题？', sort_order=1))
        db.add(QAUnit(id='QA', case_id=case['id'], status='APPLIED', raw_question_text='问题？', raw_answer_text='文本'))
        db.flush()
        db.add_all([QAUnitFragment(qa_unit_id='QA', fragment_id='F-Q', role='QUESTION', position=0),
                    QAUnitFragment(qa_unit_id='QA', fragment_id='F-A', role='ANSWER', position=1)])
        db.add(QuestionRound(id='R', case_id=case['id'], case_question_id='Q', round_no=1, actual_question_text='问题？',
                             officer_fragment_id='F-Q', answer_text='文本', answer_fragment_ids_json='["F-A"]', status='CLOSED'))
        db.commit()

    for fragment_id in ('F-Q', 'F-A'):
        for action in ('discard', 'confirm'):
            response = client.post(f'/api/v1/cases/{case["id"]}/asr/fragments/{fragment_id}/{action}')
            assert response.status_code == 409, (fragment_id, action)
            assert response.json()['code'] == 'ASR_FRAGMENT_IN_FORMAL_RECORD'
    # "Apply all" skips round evidence instead of failing on it.
    response = client.post(f'/api/v1/cases/{case["id"]}/asr/fragments/apply', json={'fragment_ids': []})
    assert response.status_code == 200, response.json()
    applied = response.json()
    assert [item['fragmentId'] for item in applied['fragments']] == ['F-FREE']
