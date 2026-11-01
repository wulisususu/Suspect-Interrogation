from datetime import datetime, timedelta, timezone

import pytest

from app.database.officer_models import Officer, OfficerSession
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.services.officer_service import OfficerService, SESSION_HOURS, SESSION_MAX_HOURS


class Clock:
    def __init__(self):
        self.value = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'login.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        OfficerService(db).provision_officer(badge_number='038291', name='测试民警', password='Strong-test-pass1', is_admin=True)
        db.commit()
    yield factory
    engine.dispose()


def _fail(service):
    with pytest.raises(DomainError) as exc:
        service.login('038291', 'wrong-password-123')
    return exc.value.code


def test_lockout_backs_off_and_does_not_hand_out_fresh_attempts(factory):
    clock = Clock()
    with factory() as db:
        service = OfficerService(db, now=clock)
        assert [_fail(service) for _ in range(5)] == ['AUTH_INVALID_CREDENTIALS'] * 5
        assert _fail(service) == 'AUTH_RATE_LIMITED'
        clock.value += timedelta(minutes=1, seconds=1)
        # The sixth wrong password doubles the block instead of resetting to five tries.
        assert _fail(service) == 'AUTH_INVALID_CREDENTIALS'
        officer = db.get(Officer, '038291')
        assert officer.failed_login_count == 6
        blocked = officer.login_blocked_until.replace(tzinfo=timezone.utc)
        assert blocked - clock.value == timedelta(minutes=2)
        clock.value = blocked + timedelta(seconds=1)
        service.login('038291', 'Strong-test-pass1')
        assert db.get(Officer, '038291').failed_login_count == 0


def test_unknown_badge_is_rejected_like_a_wrong_password(factory):
    with factory() as db:
        with pytest.raises(DomainError) as exc:
            OfficerService(db).login('999999', 'whatever-password')
        assert exc.value.code == 'AUTH_INVALID_CREDENTIALS'


def test_login_purges_expired_sessions(factory):
    clock = Clock()
    with factory() as db:
        service = OfficerService(db, now=clock)
        service.login('038291', 'Strong-test-pass1')
        db.commit()
        clock.value += timedelta(hours=SESSION_HOURS + 1)
        service.login('038291', 'Strong-test-pass1')
        db.commit()
        assert db.query(OfficerSession).count() == 1


def test_in_use_session_slides_forward_up_to_the_absolute_limit(factory):
    clock = Clock()
    with factory() as db:
        service = OfficerService(db, now=clock)
        token = service.login('038291', 'Strong-test-pass1')['token']
        db.commit()
        clock.value += timedelta(hours=SESSION_HOURS - 1)
        service.authenticate(token, renew=True)
        row = db.query(OfficerSession).one()
        assert row.expires_at.replace(tzinfo=timezone.utc) == clock.value + timedelta(hours=SESSION_HOURS)
        # Keep using it right up to the absolute limit, then it must end.
        while clock.value < datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc) + timedelta(hours=SESSION_MAX_HOURS):
            service.authenticate(token, renew=True)
            clock.value += timedelta(hours=3)
        with pytest.raises(DomainError) as exc:
            service.authenticate(token, renew=True)
        assert exc.value.code == 'AUTH_SESSION_REQUIRED'
