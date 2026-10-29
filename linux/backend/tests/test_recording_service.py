import hashlib
import json
import wave

import pytest
from sqlalchemy import select

from app.auth.context import Actor, actor_context
from app.database.models import ASRCaptureSession, ASRFragment, AuditLog, Case, QuestionRound
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.errors import DomainError
from app.services.durable_audio_archive import DurableAudioArchive
from app.services.template_catalog_service import TemplateCatalogService


def test_recording_checksum_works_on_board_python_without_file_digest(tmp_path, monkeypatch):
    from app.services.recording_service import RecordingService

    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    source = tmp_path / 'audio-evidence.bin'
    content = b'preserved-audio-evidence' * 65536
    source.write_bytes(content)
    assert RecordingService._digest(source) == hashlib.sha256(content).hexdigest()


@pytest.fixture
def environment(tmp_path):
    import app.database.recording_models
    engine = make_engine(f"sqlite:///{tmp_path / 'recordings.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    archive = DurableAudioArchive(tmp_path / 'data', factory)
    with factory() as db:
        db.add(Case(id='case-1'))
        db.add(Case(id='case-2'))
        db.commit()
    yield factory, archive
    engine.dispose()


def recorded(environment, *, enabled=True, target=True):
    from app.services.recording_service import RecordingService, snapshot_capture_options
    factory, archive = environment
    with factory() as db:
        selected = TemplateCatalogService(db).select('case-1', template_id='theft-ebike')
        qid = next(q['id'] for q in selected['questions'] if q['sectionType'] == 'BODY')
        RecordingService(db, archive).set_options('case-1', enabled)
        db.add(ASRCaptureSession(id='capture-1', case_id='case-1', status='RUNNING', sample_rate=16000, target_question_id=qid if target else None))
        db.flush()
        snapshot_capture_options(db, 'capture-1')
        db.commit()
    archive.open_capture('capture-1', case_id='case-1')
    archive.append('capture-1', b'\x02\x00' * 16000)
    archive.append('capture-1', b'\x03\x00' * 16000)
    archive.finalize_capture('capture-1')
    with factory() as db:
        db.get(ASRCaptureSession, 'capture-1').status = 'STOPPED'
        db.commit()
    return qid


def test_full_option_is_persistent_frozen_and_capture_guarded(environment):
    from app.services.recording_service import RecordingService
    factory, archive = environment
    with factory() as db:
        service = RecordingService(db, archive)
        assert service.options('case-1')['fullRecordingEnabled'] is True
        assert service.set_options('case-1', False)['fullRecordingEnabled'] is False
        db.commit()
        db.add(ASRCaptureSession(id='running', case_id='case-1', status='RUNNING', sample_rate=16000, recording_status='CAPTURING'))
        db.flush()
        with pytest.raises(DomainError, match='采集'):
            service.set_options('case-1', True)
        db.get(ASRCaptureSession, 'running').recording_status = 'COMPLETE'
        db.get(ASRCaptureSession, 'running').status = 'STOPPED'
        db.get(Case, 'case-1').workflow_state = 'FROZEN'
        with pytest.raises(DomainError) as error:
            service.set_options('case-1', True)
        assert error.value.code == 'FORMAL_RECORD_FROZEN'


def test_disabled_capture_never_generates_full_original_but_question_audio_exists(environment):
    from app.services.recording_service import RecordingService
    qid = recorded(environment, enabled=False)
    factory, archive = environment
    token = actor_context.set(Actor('001', '民警', '单位', True))
    try:
        with factory() as db:
            service = RecordingService(db, archive)
            service.set_options('case-1', True)
            db.commit()
            assert service.finalize_original('capture-1') is None
            listed = service.list_recordings('case-1')
            assert listed['originals'] == []
            segment = listed['questions'][0]
            assert segment['questionId'] == qid
            assert segment['questionNumber'] == 7
            assert segment['durationMs'] == 2000
            path = service.question_audio('case-1', qid, 'capture-1')
            with wave.open(str(path), 'rb') as wav:
                assert wav.getnframes() == 32000
                assert wav.readframes(32000) == b'\x02\x00' * 16000 + b'\x03\x00' * 16000
    finally:
        actor_context.reset(token)


def test_full_original_requires_admin_reason_and_integrity_and_is_audited(environment):
    from app.services.recording_service import RecordingService
    recorded(environment)
    factory, archive = environment
    with factory() as db:
        service = RecordingService(db, archive)
        metadata = service.finalize_original('capture-1')
        assert metadata['durationMs'] == 2000
        db.commit()
        with pytest.raises(DomainError) as error:
            service.original_audio('case-1', 'capture-1', reason='核对原始录音')
        assert error.value.status_code == 401
        token = actor_context.set(Actor('002', '普通民警', '单位', False))
        try:
            with pytest.raises(DomainError) as error:
                service.original_audio('case-1', 'capture-1', reason='核对原始录音')
            assert error.value.status_code == 403
        finally:
            actor_context.reset(token)
        token = actor_context.set(Actor('001', '管理员', '单位', True))
        try:
            with pytest.raises(DomainError):
                service.original_audio('case-1', 'capture-1', reason=' ')
            path = service.original_audio('case-1', 'capture-1', reason='核对原始录音')
            assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata['sha256']
            db.commit()
            log = db.scalar(select(AuditLog).where(AuditLog.action == 'RECORDING_ORIGINAL_ACCESS'))
            assert log.actor_id == '001'
            assert json.loads(log.detail_json)['reason'] == '核对原始录音'
            path.write_bytes(b'tampered')
            with pytest.raises(DomainError) as error:
                service.original_audio('case-1', 'capture-1', reason='核对')
            assert error.value.code == 'RECORDING_INTEGRITY_ERROR'
        finally:
            actor_context.reset(token)


def test_legacy_round_fragments_are_real_ranges_and_foreign_case_is_rejected(environment):
    from app.services.recording_service import RecordingService
    qid = recorded(environment, target=False)
    factory, archive = environment
    with factory() as db:
        db.add(ASRFragment(id='frag-1', capture_session_id='capture-1', case_id='case-1', ordinal=1, started_at_ms=1000, ended_at_ms=2000, raw_text='回答', edited_text='回答', speaker='SUSPECT', speaker_source='TEST', state='CONFIRMED', model_id='test'))
        db.add(QuestionRound(id='round-1', case_id='case-1', case_question_id=qid, round_no=1, actual_question_text='问题', answer_fragment_ids_json='["frag-1"]', status='CLOSED'))
        db.commit()
        token = actor_context.set(Actor('001', '民警', '单位', False))
        try:
            service = RecordingService(db, archive)
            metadata = service.list_recordings('case-1')['questions'][0]
            assert metadata['fragmentId'] == 'frag-1'
            assert metadata['startMs'] == 1000
            assert metadata['durationMs'] == 1000
            path = service.question_audio('case-1', qid, 'capture-1', fragment_id='frag-1')
            with wave.open(str(path), 'rb') as wav:
                assert wav.readframes(16000) == b'\x03\x00' * 16000
            with pytest.raises(DomainError) as error:
                service.question_audio('case-2', qid, 'capture-1', fragment_id='frag-1')
            assert error.value.status_code == 404
        finally:
            actor_context.reset(token)


def test_corrupt_source_is_never_served(environment):
    from app.services.recording_service import RecordingService
    qid = recorded(environment, enabled=False)
    factory, archive = environment
    (archive.data_dir / 'audio/case-1/capture-1/segment-000000.wav').write_bytes(b'corrupt')
    token = actor_context.set(Actor('001', '民警', '单位', True))
    try:
        with factory() as db:
            with pytest.raises(DomainError) as error:
                RecordingService(db, archive).question_audio('case-1', qid, 'capture-1')
            assert error.value.code == 'RECORDING_INTEGRITY_ERROR'
    finally:
        actor_context.reset(token)
