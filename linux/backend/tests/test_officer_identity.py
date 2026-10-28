from datetime import datetime, timedelta, timezone
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.errors import install_error_handlers
from app.database.models import AuditLog, Case
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.services.document_service import DocumentService


PNG = 'data:image/png;base64,' + base64.b64encode(bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c63606060f80f00010401005fe5c34b0000000049454e44ae426082'
)).decode()


@pytest.fixture
def identity(tmp_path):
    from app.database import officer_models  # noqa: F401
    from app.services.officer_service import OfficerService
    factory = make_session_factory(make_engine(f"sqlite:///{tmp_path / 'identity.db'}"))
    init_database(factory.kw['bind'])
    now = [datetime(2026, 10, 28, 4, 0, tzinfo=timezone.utc)]
    with factory() as db:
        db.add(Case(id='CASE-A', suspect_name='甲', officer_name='旧姓名'))
        db.add(Case(id='CASE-B', suspect_name='乙', officer_name='旧姓名'))
        service = OfficerService(db, now=lambda: now[0])
        service.provision_officer(badge_number='038291', name='张伟', unit='刑侦', password='a-secure-password', is_admin=True)
        service.provision_officer(badge_number='036612', name='刘敏', unit='刑侦', password='another-password')
        db.commit()
    return factory, now


def test_roster_password_hash_and_no_default_secret(identity):
    from app.database.officer_models import Officer
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        items = service.list_officers()
        assert {x['badgeNumber'] for x in items} == {'038291', '036612'}
        assert all('password' not in str(x).lower() for x in items)
        assert db.get(Officer, '038291').password_hash != 'a-secure-password'
        with pytest.raises(DomainError, match='至少'):
            service.provision_officer(badge_number='000001', name='弱密码', unit='刑侦', password='123')
        with pytest.raises(DomainError):
            service.provision_officer(badge_number='038291', name='重复', unit='刑侦', password='valid-password')


def test_session_lock_exemption_expiry_and_token_tampering(identity):
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        result = service.login('038291', 'a-secure-password')
        token = result['token']
        assert result['exemptionRemainingSeconds'] == 600
        assert service.authenticate(token).badge_number == '038291'
        service.lock(token)
        with pytest.raises(DomainError) as error:
            service.authenticate(token)
        assert error.value.code == 'AUTH_SESSION_LOCKED'
        assert service.session_status(token)['locked'] is True
        service.unlock(token)
        assert service.authenticate(token).name == '张伟'
        service.lock(token)
        now[0] += timedelta(seconds=601)
        assert service.session_status(token)['exemptionRemainingSeconds'] == 0
        with pytest.raises(DomainError) as error:
            service.unlock(token)
        assert error.value.code == 'AUTH_REAUTHENTICATION_REQUIRED'
        service.unlock(token, password='a-secure-password')
        assert service.session_status(token)['exemptionRemainingSeconds'] == 600
        with pytest.raises(DomainError):
            service.authenticate(token + 'tampered')
        service.logout(token)
        with pytest.raises(DomainError):
            service.authenticate(token)


def test_disable_officer_revokes_session_and_cannot_disable_last_admin(identity):
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        token = service.login('036612', 'another-password')['token']
        service.update_officer('036612', enabled=False)
        with pytest.raises(DomainError):
            service.authenticate(token)
        assert [x['badgeNumber'] for x in service.list_officers(active_only=True)] == ['038291']
        with pytest.raises(DomainError) as error:
            service.update_officer('038291', enabled=False)
        assert error.value.code == 'LAST_ADMIN_REQUIRED'


def test_case_roles_store_badges_and_reject_disabled_or_frozen_bindings(identity):
    from app.database.officer_models import CaseOfficerBinding
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        result = service.bind_case_officers('CASE-A', interrogator_badge_number='038291', recorder_badge_number='036612')
        assert result['interrogator']['displayName'] == '张伟（038291）'
        assert result['recorder']['unit'] == '刑侦'
        assert db.get(CaseOfficerBinding, 'CASE-A').recorder_badge_number == '036612'
        assert db.get(Case, 'CASE-A').officer_name == '张伟'
        assert service.case_officers('CASE-B')['interrogator'] is None
        service.update_officer('036612', enabled=False)
        with pytest.raises(DomainError):
            service.bind_case_officers('CASE-B', interrogator_badge_number='036612', recorder_badge_number=None)
        db.get(Case, 'CASE-A').workflow_state = 'FROZEN'
        with pytest.raises(DomainError) as error:
            service.bind_case_officers('CASE-A', interrogator_badge_number='038291', recorder_badge_number=None)
        assert error.value.code == 'FORMAL_RECORD_FROZEN'


def test_signature_versions_disable_and_application_snapshot_are_immutable(identity):
    from app.database.officer_models import OfficerSignatureUse
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        service.bind_case_officers('CASE-A', interrogator_badge_number='038291', recorder_badge_number='036612')
        first = service.save_signature('038291', image_data=PNG, actor_id='038291')
        second = service.save_signature('038291', image_data=PNG, actor_id='038291')
        assert first['version'] == 1 and second['version'] == 2
        assert service.list_signatures('038291')[0]['id'] == second['id']
        db.get(Case, 'CASE-A').workflow_state = 'SUMMARY'
        DocumentService(db).freeze('CASE-A', commit=False)
        # DocumentService uses its own transaction but must copy the stored image.
        result = service.apply_signature('CASE-A', second['id'], actor_id='038291')
        assert result['signerName'] == '张伟'
        assert result['imageData'] == PNG
        use = db.scalar(select(OfficerSignatureUse).where(OfficerSignatureUse.case_id == 'CASE-A'))
        assert use.officer_signature_id == second['id']
        assert use.actor_id == '038291'
        service.set_signature_enabled(second['id'], False, actor_id='038291')
        assert service.signature_uses('038291')[0]['caseId'] == 'CASE-A'
        assert DocumentService(db).signing_state('CASE-A')['signatures'][0]['imageDataUrl'] == PNG
        with pytest.raises(DomainError) as error:
            service.apply_signature('CASE-B', second['id'], actor_id='038291')
        assert error.value.code == 'OFFICER_SIGNATURE_DISABLED'


@pytest.mark.parametrize('value', ['not-png', 'data:image/png;base64,AAAA', PNG[:-8]])
def test_signature_rejects_invalid_or_truncated_images(identity, value):
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db, pytest.raises(DomainError) as error:
        OfficerService(db, now=lambda: now[0]).save_signature('038291', image_data=value, actor_id='038291')
    assert error.value.code == 'INVALID_SIGNATURE_IMAGE'


def make_api(factory, required=None):
    from app.api.officers import router
    from app.auth.middleware import OfficerAuthMiddleware
    app = FastAPI()
    app.state.session_factory = factory
    install_error_handlers(app)
    app.include_router(router, prefix='/api/v1')
    app.add_middleware(OfficerAuthMiddleware, session_factory=factory, required=required)

    @app.get('/api/v1/protected')
    def protected():
        from app.auth.context import current_actor_id
        return {'actorId': current_actor_id()}

    return app


def test_auth_api_enforces_sessions_and_context_ignores_client_actor(identity):
    factory, now = identity
    with TestClient(make_api(factory)) as client:
        assert client.get('/api/v1/protected').status_code == 401
        logged = client.post('/api/v1/auth/login', json={'badgeNumber': '038291', 'password': 'a-secure-password'})
        assert logged.status_code == 200, logged.text
        assert 'httponly' in logged.headers['set-cookie'].lower()
        assert client.get('/api/v1/protected', headers={'X-Actor-Id': 'fake'}).json()['actorId'] == '038291'
        assert client.post('/api/v1/auth/lock').status_code == 200
        assert client.get('/api/v1/officers').status_code == 423
        assert client.get('/api/v1/auth/session').json()['data']['locked'] is True
        assert client.post('/api/v1/auth/unlock', json={}).status_code == 200
        assert client.get('/api/v1/officers').status_code == 200
        assert client.post('/api/v1/auth/logout').status_code == 200
        assert client.get('/api/v1/protected').status_code == 401


def test_unprovisioned_auth_is_explicit_and_cannot_bootstrap_over_http(tmp_path):
    from app.database import officer_models  # noqa: F401
    engine = make_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    init_database(engine)
    with TestClient(make_api(make_session_factory(engine))) as client:
        status = client.get('/api/v1/auth/session').json()['data']
        assert status['configured'] is False and status['required'] is False
        assert client.get('/api/v1/protected').status_code == 200
        assert client.post('/api/v1/officers', json={'badgeNumber': 'bad', 'name': '冒名', 'password': 'valid-password'}).status_code == 401


def test_regular_officer_cannot_manage_roster_or_other_signature(identity):
    factory, now = identity
    with TestClient(make_api(factory)) as client:
        client.post('/api/v1/auth/login', json={'badgeNumber': '036612', 'password': 'another-password'})
        assert client.post('/api/v1/officers', json={'badgeNumber': '000001', 'name': '新人', 'password': 'valid-password'}).status_code == 403
        assert client.post('/api/v1/officers/038291/signatures', json={'imageData': PNG}).status_code == 403


def test_invalid_cookie_does_not_block_login_or_static_app(identity):
    factory, now = identity
    app = make_api(factory)
    @app.get('/')
    def home():
        return {'app': True}
    with TestClient(app) as client:
        client.cookies.set('suspect_officer_session', 'expired-or-tampered')
        assert client.get('/').status_code == 200
        assert client.post('/api/v1/auth/login', json={'badgeNumber': '038291', 'password': 'a-secure-password'}).status_code == 200


def test_sessions_expire_and_wrong_password_is_throttled_persistently(identity):
    from app.database.officer_models import OfficerSession
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        token = service.login('038291', 'a-secure-password')['token']
        stored = db.scalar(select(OfficerSession))
        assert stored.token_hash != token
        now[0] += timedelta(hours=8)
        with pytest.raises(DomainError) as error:
            service.authenticate(token)
        assert error.value.code == 'AUTH_SESSION_REQUIRED'
        for _ in range(5):
            with pytest.raises(DomainError) as error:
                service.login('038291', 'wrong-password')
            assert error.value.code == 'AUTH_INVALID_CREDENTIALS'
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        with pytest.raises(DomainError) as error:
            service.login('038291', 'a-secure-password')
        assert error.value.code == 'AUTH_RATE_LIMITED'
        now[0] += timedelta(seconds=61)
        assert service.login('038291', 'a-secure-password')['authenticated'] is True


def test_signature_application_and_use_record_roll_back_together(identity):
    from app.database.models import SignatureRecord
    from app.database.officer_models import OfficerSignatureUse
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        service.bind_case_officers('CASE-A', interrogator_badge_number='038291', recorder_badge_number=None)
        signature = service.save_signature('038291', image_data=PNG, actor_id='038291')
        db.get(Case, 'CASE-A').workflow_state = 'SUMMARY'
        DocumentService(db).freeze('CASE-A')
        service.apply_signature('CASE-A', signature['id'], actor_id='038291')
        db.rollback()
    with factory() as db:
        assert db.scalar(select(SignatureRecord).where(SignatureRecord.case_id == 'CASE-A')) is None
        assert db.scalar(select(OfficerSignatureUse).where(OfficerSignatureUse.case_id == 'CASE-A')) is None


def test_disabled_admin_account_cannot_be_used_by_existing_session(identity):
    from app.services.officer_service import OfficerService
    factory, now = identity
    with factory() as db:
        service = OfficerService(db, now=lambda: now[0])
        service.provision_officer(badge_number='000002', name='管理员二', password='second-admin-password', is_admin=True)
        token = service.login('038291', 'a-secure-password')['token']
        service.update_officer('038291', enabled=False)
        with pytest.raises(DomainError):
            service.authenticate(token)


def test_explicit_auth_required_without_provisioning_fails_closed(tmp_path):
    from app.database import officer_models  # noqa: F401
    engine = make_engine(f"sqlite:///{tmp_path / 'required.db'}")
    init_database(engine)
    with TestClient(make_api(make_session_factory(engine), required=True)) as client:
        assert client.get('/api/v1/protected').status_code == 401
        assert client.get('/api/v1/auth/session').json()['data']['required'] is True
