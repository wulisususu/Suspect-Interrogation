from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.auth.context import Actor, actor_context
from app.domain.errors import DomainError
from test_recording_service import environment, recorded


def api_app(environment):
    from app.api.recordings import router
    factory, archive = environment
    app = FastAPI()
    app.state.session_factory = factory
    app.state.recording_archive = archive
    app.include_router(router, prefix='/api/v1')

    @app.middleware('http')
    async def test_actor(request: Request, call_next):
        badge = request.headers.get('x-test-actor')
        token = actor_context.set(Actor(badge, '测试民警', '单位', badge == 'admin') if badge else None)
        try:
            return await call_next(request)
        finally:
            actor_context.reset(token)

    @app.exception_handler(DomainError)
    async def domain_error(_request, error):
        return JSONResponse(status_code=error.status_code, content={'ok': False, 'code': error.code, 'message': error.message, 'data': None})
    return app


def test_recording_routes_require_auth_and_download_real_wav(environment):
    from app.services.recording_service import RecordingService
    qid = recorded(environment)
    factory, archive = environment
    with factory() as db:
        RecordingService(db, archive).finalize_original('capture-1')
        db.commit()
    with TestClient(api_app(environment)) as client:
        base = '/api/v1/cases/case-1/recordings'
        assert client.get(base).status_code == 401
        listed = client.get(base, headers={'x-test-actor': 'officer'}).json()
        assert listed['ok'] is True
        assert listed['data']['originals'][0]['sha256']
        audio_url = listed['data']['questions'][0]['audioUrl']
        response = client.get(audio_url, headers={'x-test-actor': 'officer'})
        assert response.status_code == 200
        assert response.headers['content-type'] == 'audio/wav'
        assert response.content[:4] == b'RIFF'
        assert response.content[44:] == b'\x02\x00' * 16000 + b'\x03\x00' * 16000
        full = base + '/originals/capture-1/audio'
        assert client.get(full, params={'reason': '核对'}, headers={'x-test-actor': 'officer'}).status_code == 403
        assert client.get(full, params={'reason': '核对'}, headers={'x-test-actor': 'admin'}).status_code == 200
        assert client.get(full, headers={'x-test-actor': 'admin'}).status_code == 422
        assert client.get(audio_url.replace('case-1', 'case-2'), headers={'x-test-actor': 'admin'}).status_code == 404


def test_recording_option_contract(environment):
    with TestClient(api_app(environment)) as client:
        url = '/api/v1/cases/case-1/recording-options'
        assert client.patch(url, json={'fullRecordingEnabled': False}).status_code == 401
        response = client.patch(url, json={'fullRecordingEnabled': False}, headers={'x-test-actor': 'officer'})
        assert response.json()['data']['fullRecordingEnabled'] is False
        assert client.get(url, headers={'x-test-actor': 'officer'}).json()['data']['fullRecordingEnabled'] is False
        assert client.patch(url, json={'fullRecordingEnabled': 'false'}, headers={'x-test-actor': 'officer'}).status_code == 422
