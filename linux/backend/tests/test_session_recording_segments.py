import hashlib
import json
import struct
import wave
from datetime import timedelta

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.context import Actor, actor_context
from app.database.base import utc_now
from app.database.models import AuditLog, Case
from app.database.recording_models import SessionRecordingSegment
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.enums import WorkflowState
from app.domain.errors import DomainError
from app.services.recording_service import RecordingService
from app.services.session_recording_service import SessionRecordingStore
from app.services.session_service import SessionService


@pytest.fixture
def env(tmp_path):
    import app.database.recording_models  # noqa: F401
    engine = make_engine(f"sqlite:///{tmp_path / 'segments.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(Case(id='case-1', workflow_state=WorkflowState.CASE_CREATED.value))
        db.commit()
    yield factory, SessionRecordingStore(tmp_path / 'data', factory)
    engine.dispose()


def segments(factory):
    with factory() as db:
        return [(row.ordinal, row.status, row.end_reason) for row in db.scalars(
            select(SessionRecordingSegment).order_by(SessionRecordingSegment.ordinal))]


def frame(sequence, start, samples, value=1):
    return struct.pack('<IQ', sequence, start) + struct.pack('<h', value) * samples


def test_each_start_or_resume_until_pause_or_finish_is_its_own_segment(env):
    factory, _store = env
    with factory() as db:
        started = SessionService(db).start('case-1', 'op')
    assert started['recordingSegment']['ordinal'] == 1
    with factory() as db:
        paused = SessionService(db).pause('case-1', 'op')
    assert paused['recordingSegment'] is None
    assert segments(factory) == [(1, 'CLOSING', 'PAUSED')]
    with factory() as db:
        resumed = SessionService(db).resume('case-1', 'op')
    assert resumed['recordingSegment']['ordinal'] == 2
    with factory() as db:
        SessionService(db).finish('case-1', 'op')
    assert segments(factory) == [(1, 'CLOSING', 'PAUSED'), (2, 'CLOSING', 'FINISHED')]
    with factory() as db:
        actions = list(db.scalars(select(AuditLog.action).where(AuditLog.action.like('RECORDING_SEGMENT_%')).order_by(AuditLog.created_at)))
    assert actions == ['RECORDING_SEGMENT_START', 'RECORDING_SEGMENT_STOP'] * 2


def test_disabled_full_recording_opens_no_segment(env):
    factory, store = env
    with factory() as db:
        RecordingService(db, None, store).set_options('case-1', False)
        db.commit()
    with factory() as db:
        assert SessionService(db).start('case-1', 'op')['recordingSegment'] is None
    assert segments(factory) == []


def test_frames_are_idempotent_gaps_are_recorded_not_filled_and_pause_saves_one_wav(env):
    factory, store = env
    with factory() as db:
        segment_id = SessionService(db).start('case-1', 'op')['recordingSegment']['id']
    assert store.attach('case-1', segment_id, fresh=True) == {'status': 'RECORDING', 'clientSampleEnd': 0, 'nextSequence': 1}
    assert store.ingest('case-1', segment_id, 1, 0, b'\x01\x00' * 16000)['durableSampleEnd'] == 16000
    # 重连后同一录音器补发已落盘的帧：确认但不重复写。
    assert store.ingest('case-1', segment_id, 1, 0, b'\x01\x00' * 16000)['ackSequence'] == 1
    # 浏览器缓存溢出丢了半秒：不补静音，只记缺口。
    store.ingest('case-1', segment_id, 3, 24000, b'\x02\x00' * 8000)
    # 刷新页面后新录音器从服务端给的位置接着录，墙钟缺口记入 gaps。
    with factory() as db:
        db.get(SessionRecordingSegment, segment_id).last_frame_at = utc_now() - timedelta(seconds=3)
        db.commit()
    resumed = store.attach('case-1', segment_id, fresh=True)
    assert resumed['clientSampleEnd'] == 32000 and resumed['nextSequence'] == 4
    store.ingest('case-1', segment_id, 4, 32000, b'\x03\x00' * 16000)
    with factory() as db:
        SessionService(db).pause('case-1', 'op')
    result = store.finalize('case-1', segment_id, client_confirmed=True)
    assert result['status'] == 'COMPLETE' and result['durationMs'] == 2500
    with factory() as db:
        row = db.get(SessionRecordingSegment, segment_id)
        gaps = json.loads(row.gaps_json)
        path = store.wav_path(row)
        assert row.client_finalized is True
        assert row.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [(gap['atMs'], gap['reason']) for gap in gaps] == [(1000, 'BROWSER_BUFFER_DROPPED'), (1500, 'BROWSER_RESTARTED')]
    assert gaps[0]['missingMs'] == 500 and gaps[1]['missingMs'] >= 3000
    with wave.open(str(path)) as wav:
        assert (wav.getframerate(), wav.getnframes()) == (16000, 40000)
    assert not (path.parent / 'audio.pcm').exists()
    with pytest.raises(DomainError):
        store.ingest('case-1', segment_id, 10, 48000, b'\x01\x00' * 10)


def test_crash_tail_beyond_committed_samples_is_discarded(env):
    factory, store = env
    with factory() as db:
        segment_id = SessionService(db).start('case-1', 'op')['recordingSegment']['id']
    store.ingest('case-1', segment_id, 1, 0, b'\x01\x00' * 100)
    with factory() as db:
        pcm = store.segment_dir('case-1', segment_id) / 'audio.pcm'
    with open(pcm, 'ab') as stream:
        stream.write(b'\x7f\x7f' * 50)  # 写入后、提交前断电留下的尾巴
    store.ingest('case-1', segment_id, 2, 100, b'\x02\x00' * 100)
    assert pcm.read_bytes() == b'\x01\x00' * 100 + b'\x02\x00' * 100


def test_sweep_saves_segments_the_browser_never_confirmed(env):
    factory, store = env
    with factory() as db:
        first = SessionService(db).start('case-1', 'op')['recordingSegment']['id']
    store.ingest('case-1', first, 1, 0, b'\x01\x00' * 1600)
    with factory() as db:
        SessionService(db).pause('case-1', 'op')
    assert store.sweep() == 0  # 宽限期内等浏览器送完尾音
    assert store.sweep(force=True) == 1
    with factory() as db:
        row = db.get(SessionRecordingSegment, first)
        assert (row.status, row.client_finalized) == ('COMPLETE', False)
    # 询问已不在进行中（例如作废、断电）却还挂着 RECORDING 的段也会被收尾。
    with factory() as db:
        second = SessionService(db).resume('case-1', 'op')['recordingSegment']['id']
        from app.database.models import InterrogationSession
        db.scalar(select(InterrogationSession)).status = 'COMPLETED'
        db.commit()
    assert store.sweep(force=True) == 1
    with factory() as db:
        row = db.get(SessionRecordingSegment, second)
        assert (row.status, row.end_reason) == ('EMPTY', 'SESSION_NOT_RUNNING')


def recording_app(factory, store):
    from app.api.recordings import router
    from app.websocket.session_recording import router as ws_router
    app = FastAPI()
    app.state.session_factory = factory
    app.state.session_recording_store = store
    app.include_router(router, prefix='/api/v1')
    app.include_router(ws_router)

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


def test_browser_stream_and_admin_only_playback_with_reason(env):
    factory, store = env
    with factory() as db:
        segment_id = SessionService(db).start('case-1', 'op')['recordingSegment']['id']
    with TestClient(recording_app(factory, store)) as client:
        url = f'/ws/recording/cases/case-1/segments/{segment_id}'
        with client.websocket_connect(url) as socket:
            socket.send_text(json.dumps({'type': 'segment_open', 'fresh': True}))
            assert socket.receive_json() == {'type': 'segment_opened', 'status': 'RECORDING', 'clientSampleEnd': 0, 'nextSequence': 1}
            socket.send_bytes(frame(1, 0, 8000))
            assert socket.receive_json() == {'type': 'ack', 'ackSequence': 1, 'durableSampleEnd': 8000}
            socket.send_bytes(frame(2, 8000, 8000))
            assert socket.receive_json()['durableSampleEnd'] == 16000
            with factory() as db:
                SessionService(db).pause('case-1', 'op')
            socket.send_text(json.dumps({'type': 'segment_finalize'}))
            ack = socket.receive_json()
            assert ack['type'] == 'segment_finalize_ack' and ack['status'] == 'COMPLETE' and ack['durationMs'] == 1000

        listed = client.get('/api/v1/cases/case-1/recordings', headers={'x-test-actor': 'officer'}).json()['data']
        assert [(s['ordinal'], s['status'], s['durationMs'], s['tailConfirmed']) for s in listed['segments']] == [(1, 'COMPLETE', 1000, True)]
        assert listed['segments'][0]['filename'].startswith('第1次询问-')
        audio = f'/api/v1/cases/case-1/recordings/segments/{segment_id}/audio'
        assert client.get(audio, params={'reason': '核对'}, headers={'x-test-actor': 'officer'}).status_code == 403
        assert client.get(audio, headers={'x-test-actor': 'admin'}).status_code == 422
        response = client.get(audio, params={'reason': '核对笔录时间'}, headers={'x-test-actor': 'admin'})
        assert response.status_code == 200 and response.headers['content-type'] == 'audio/wav'
        assert hashlib.sha256(response.content).hexdigest() == listed['segments'][0]['sha256']
        # 已保存的段不再接收音频
        with client.websocket_connect(url) as socket:
            socket.send_text(json.dumps({'type': 'segment_open', 'fresh': True}))
            assert socket.receive_json()['status'] == 'COMPLETE'
    with factory() as db:
        access = db.scalar(select(AuditLog).where(AuditLog.action == 'RECORDING_ORIGINAL_ACCESS'))
        assert access.target_type == 'RECORDING_SEGMENT'
        assert json.loads(access.detail_json)['reason'] == '核对笔录时间'


def test_full_recording_switch_is_locked_while_a_segment_records(env):
    factory, store = env
    with factory() as db:
        SessionService(db).start('case-1', 'op')
    with factory() as db, pytest.raises(DomainError) as error:
        RecordingService(db, None, store).set_options('case-1', False)
    assert error.value.code == 'RECORDING_IN_PROGRESS'
