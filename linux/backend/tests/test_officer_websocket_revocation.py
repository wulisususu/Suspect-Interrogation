from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.officers import router
from app.auth.middleware import OfficerAuthMiddleware
from app.database.officer_models import Officer, OfficerSession
from app.database.session import init_database, make_engine, make_session_factory
from app.services.officer_service import OfficerService


@pytest.mark.parametrize('revoke', ['lock', 'logout', 'disable', 'expiry'])
def test_existing_websocket_rechecks_session_before_accepting_more_data(tmp_path, revoke):
    engine = make_engine(f'sqlite:///{tmp_path / "ws-auth.db"}')
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        OfficerService(db).provision_officer(badge_number='038291', name='测试民警', password='Strong-test-pass1', is_admin=True)
        db.commit()
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(router, prefix='/api/v1')
    # lock/logout go through the API and bump the revocation epoch, so they must
    # be seen immediately even with the production recheck interval; direct
    # database edits rely on the periodic recheck, forced to every frame here.
    interval = 5.0 if revoke in {'lock', 'logout'} else 0.0
    app.add_middleware(OfficerAuthMiddleware, session_factory=factory, recheck_interval=interval)
    @app.websocket('/ws/echo')
    async def echo(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_text(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
    client = TestClient(app, base_url='https://testserver')
    assert client.post('/api/v1/auth/login', json={'badgeNumber': '038291', 'password': 'Strong-test-pass1'}).status_code == 200
    with client.websocket_connect('wss://testserver/ws/echo') as ws:
        ws.send_text('before')
        assert ws.receive_text() == 'before'
        if revoke in {'lock', 'logout'}:
            assert client.post(f'/api/v1/auth/{revoke}').status_code == 200
        else:
            with factory() as db:
                if revoke == 'disable':
                    db.get(Officer, '038291').enabled = False
                else:
                    db.query(OfficerSession).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                db.commit()
        ws.send_text('after')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == (4403 if revoke == 'lock' else 4401)
    engine.dispose()


def test_websocket_does_not_reauthenticate_every_frame_until_interval_or_revocation(tmp_path):
    from app.auth.context import bump_session_revocation

    engine = make_engine(f'sqlite:///{tmp_path / "ws-throttle.db"}')
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        OfficerService(db).provision_officer(badge_number='038291', name='测试民警', password='Strong-test-pass1', is_admin=True)
        db.commit()
    app = FastAPI()
    app.state.session_factory = factory
    app.include_router(router, prefix='/api/v1')
    app.add_middleware(OfficerAuthMiddleware, session_factory=factory, recheck_interval=3600)

    @app.websocket('/ws/echo')
    async def echo(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                await websocket.send_text(await websocket.receive_text())
        except WebSocketDisconnect:
            pass
    client = TestClient(app, base_url='https://testserver')
    assert client.post('/api/v1/auth/login', json={'badgeNumber': '038291', 'password': 'Strong-test-pass1'}).status_code == 200
    with client.websocket_connect('wss://testserver/ws/echo') as ws:
        with factory() as db:
            db.query(OfficerSession).one().expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        # Within the interval frames flow without a database round trip.
        for index in range(20):
            ws.send_text(str(index))
            assert ws.receive_text() == str(index)
        bump_session_revocation()
        ws.send_text('after-bump')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 4401
    engine.dispose()
