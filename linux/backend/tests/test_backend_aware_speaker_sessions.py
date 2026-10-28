from __future__ import annotations

import struct
import threading
from pathlib import Path

import socket

import pytest
from sqlalchemy.orm import Session

from app.ai.speech.client import SpeechWorkerClient
from app.ai.speech.types import SpeechEventType
from app.database.models import Case, InterrogationSession, OfficerVoiceprint, SessionVoiceAssignment
from app.database.session import init_database, make_engine, make_session_factory
from app.database.voiceprint_models import SessionOfficerVoiceSnapshot
from app.domain.enums import InterrogationStage, SessionStatus
from app.domain.errors import DomainError
from app.repositories import voiceprints as voiceprint_repo
from app.runtime_settings import RuntimeSettings
from app.services.asr_capture_service import AsrCaptureService
from app.services.voiceprint_service import VoiceprintService
from speech_worker.main import SpeechWorkerServer
from speech_worker.session import SpeechSession


XVECTOR = "xvector"
ERES2NET = "eres2net_large"


def _embedding(*values: float) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _db(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'backend-aware.sqlite3'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        db.add(Case(id="CASE-1", suspect_name="张某", officer_name="李警官"))
        db.add(
            InterrogationSession(
                id="SESSION-1",
                case_id="CASE-1",
                status=SessionStatus.RUNNING.value,
                stage=InterrogationStage.STATEMENT.value,
            )
        )
        db.commit()
    return engine, factory


def _add_suspect(db: Session, model_key: str, *, dim: int = 4):
    return voiceprint_repo.enroll_suspect(
        db,
        case_id="CASE-1",
        model_key=model_key,
        embedding=_embedding(*([1.0] + [0.0] * (dim - 1))),
        embedding_dim=dim,
        model_id=f"test-{model_key}",
        model_version="v1",
        enrollment_quality="GOOD",
        usable_duration_ms=20_000,
    )


def _add_officer(db: Session, officer_id: str, model_key: str, *, dim: int = 4):
    return voiceprint_repo.enroll_officer(
        db,
        officer_id=officer_id,
        officer_name="张警官",
        model_key=model_key,
        embedding=_embedding(*([1.0] + [0.0] * (dim - 1))),
        embedding_dim=dim,
        model_id=f"test-{model_key}",
        model_version="v1",
        enrollment_quality="GOOD",
        usable_duration_ms=20_000,
    )


class NoopSpeechClient:
    pass


def test_runtime_settings_validate_selected_speaker_backend():
    assert RuntimeSettings(speaker_backend=ERES2NET).speaker_backend == ERES2NET
    with pytest.raises(ValueError, match="eres2net_large"):
        RuntimeSettings(speaker_backend="XVECTOR")
    with pytest.raises(ValueError, match="eres2net_large"):
        RuntimeSettings(speaker_backend="unknown-space")


@pytest.mark.parametrize("backend", [XVECTOR, "compare"])
def test_speech_session_rejects_non_eres2net_product_backend(backend: str):
    with pytest.raises(ValueError, match="eres2net_large"):
        SpeechSession("single-eres", 16_000, object(), speaker_backend_key=backend)


def test_readiness_uses_only_selected_model_reference(tmp_path: Path):
    engine, factory = _db(tmp_path)
    try:
        with factory() as db:
            _add_suspect(db, XVECTOR)
            db.commit()
            service = VoiceprintService(
                db,
                speech_client=NoopSpeechClient(),
                speaker_model_key=ERES2NET,
            )
            missing = service.readiness("CASE-1")
            assert missing["selectedSpeakerBackend"] == ERES2NET
            assert missing["suspectReady"] is False
            assert missing["canStart"] is False

            _add_suspect(db, ERES2NET)
            db.commit()
            ready = service.readiness("CASE-1")
            assert ready["selectedSpeakerBackend"] == ERES2NET
            assert ready["suspectReady"] is True
            assert ready["canStart"] is True
    finally:
        engine.dispose()


def test_binding_eres_session_freezes_only_eres_references(tmp_path: Path):
    engine, factory = _db(tmp_path)
    try:
        with factory() as db:
            x_suspect = _add_suspect(db, XVECTOR, dim=3)
            e_suspect = _add_suspect(db, ERES2NET, dim=4)
            _add_officer(db, "P-001", XVECTOR, dim=3)
            e_officer = _add_officer(db, "P-001", ERES2NET, dim=4)
            db.commit()

            service = VoiceprintService(
                db,
                speech_client=NoopSpeechClient(),
                speaker_model_key=ERES2NET,
            )
            result = service.bind_roles("CASE-1", "P-001", None, actor_id="op")
            assert result["selectedSpeakerBackend"] == ERES2NET

            assignment = db.query(SessionVoiceAssignment).filter_by(session_id="SESSION-1").one()
            assert assignment.suspect_voiceprint_id == e_suspect.id
            assert assignment.suspect_voiceprint_id != x_suspect.id
            snapshot = db.get(OfficerVoiceprint, assignment.interrogator_voiceprint_id)
            assert snapshot is not None
            assert snapshot.model_key == ERES2NET
            assert snapshot.model_key == e_officer.model_key
            metadata = db.query(SessionOfficerVoiceSnapshot).filter_by(
                session_id="SESSION-1", role="INTERROGATOR"
            ).one()
            assert metadata.model_key == ERES2NET
    finally:
        engine.dispose()


def test_binding_selected_backend_never_falls_back_to_xvector(tmp_path: Path):
    engine, factory = _db(tmp_path)
    try:
        with factory() as db:
            _add_suspect(db, XVECTOR)
            _add_officer(db, "P-001", XVECTOR)
            db.commit()
            service = VoiceprintService(
                db,
                speech_client=NoopSpeechClient(),
                speaker_model_key=ERES2NET,
            )
            with pytest.raises(DomainError) as exc_info:
                service.bind_roles("CASE-1", "P-001", None, actor_id="op")
            assert exc_info.value.code == "SUSPECT_VOICEPRINT_BACKEND_REQUIRED"
            assert db.query(SessionVoiceAssignment).count() == 0
    finally:
        engine.dispose()


class BackendAwareRuntime:
    def __init__(self):
        self.backends: list[str | None] = []

    def health(self):
        return {"status": "ready"}

    def vad_stream(self, pcm, sample_rate, *, cache, is_final, chunk_size_ms=200):
        del pcm, sample_rate, cache, chunk_size_ms
        return [[-1, 200]] if is_final else [[0, -1]]

    def transcribe(self, pcm, sample_rate):
        del pcm, sample_rate
        return {"text": "测试", "confidence": 1.0, "model_id": "asr"}

    def speaker_embedding(self, pcm, sample_rate, *, backend_key=None):
        del pcm, sample_rate
        self.backends.append(backend_key)
        return {
            "embedding": [1.0, 0.0, 0.0, 0.0],
            "backend_key": backend_key,
            "model_id": f"test-{backend_key}",
            "model_version": "v1",
            "model_fingerprint": "f" * 64,
        }


def _start_worker(path: Path, runtime: BackendAwareRuntime):
    server = SpeechWorkerServer(path, runtime)
    server.bind()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires an AF_UNIX socket runtime")
def test_speech_session_does_not_run_selected_speaker_backend_in_stage_one(tmp_path: Path):
    socket_path = tmp_path / "speech.sock"
    runtime = BackendAwareRuntime()
    server, thread = _start_worker(socket_path, runtime)
    try:
        client = SpeechWorkerClient(socket_path, timeout=1.0)
        opened = client.open_session("CASE-1", sample_rate=16000, speaker_backend=ERES2NET)
        assert opened["speaker_backend"] == ERES2NET
        client.push_pcm("CASE-1", b"\x01\x00" * 3200)
        events = client.finalize_session("CASE-1")
        assert any(event.type is SpeechEventType.ASR_FINAL for event in events)
        assert not any(
            event.type in {SpeechEventType.SPEAKER_RESULT, SpeechEventType.SPEAKER_COMPARE_RESULT}
            for event in events
        )
        assert runtime.backends == []
    finally:
        server.stop()
        thread.join(timeout=2.0)


class CaptureDevice:
    def start_record(self):
        pass

    def read_audio_frames(self, timeout=0.01):
        del timeout
        return b""

    def stop_record(self):
        pass


class CaptureSupervisor:
    speaker_accept_threshold = 0.7
    speaker_margin = 0.1
    speaker_threshold_source = "DEVICE_CALIBRATED"

    def __init__(self):
        self.opened: list[tuple[str, int, str]] = []

    def open_speech_session(self, session_id, *, sample_rate=16000, speaker_backend=XVECTOR):
        self.opened.append((session_id, sample_rate, speaker_backend))
        return {
            "session_id": session_id,
            "sample_rate": sample_rate,
            "speaker_backend": speaker_backend,
        }

    def finalize_speech_session(self, session_id):
        del session_id
        return []

    def close_speech_session(self, session_id):
        del session_id

    def push_speech_pcm(self, session_id, pcm):
        del session_id, pcm
        return []


def test_capture_opens_selected_speech_backend_with_or_without_reference(tmp_path: Path):
    engine, factory = _db(tmp_path)
    supervisor = CaptureSupervisor()
    try:
        with factory() as db:
            _add_suspect(db, XVECTOR)
            db.commit()

        service = AsrCaptureService(
            session_factory=factory,
            device_manager=CaptureDevice(),
            ai_supervisor=supervisor,
            publish_event=lambda *_args: None,
            speaker_model_key=ERES2NET,
            read_timeout=0.01,
        )
        # 声纹已移出办理流程：缺少选定模型的嫌疑人声纹时照常采集，
        # 且仍只打开选定的说话人后端，不回退到 xvector。
        service.start("CASE-1")
        assert supervisor.opened and supervisor.opened[-1][2] == ERES2NET
        service.stop("CASE-1")

        with factory() as db:
            suspect = _add_suspect(db, ERES2NET)
            voiceprint_repo.assign_session_roles(
                db,
                session_id="SESSION-1",
                suspect_voiceprint_id=suspect.id,
                interrogator_officer_id=None,
                recorder_officer_id=None,
                model_key=ERES2NET,
            )
            db.commit()

        started = service.start("CASE-1")
        assert started["speakerModelKey"] == ERES2NET
        assert supervisor.opened and supervisor.opened[-1][2] == ERES2NET
        service.stop("CASE-1")
    finally:
        engine.dispose()
