from __future__ import annotations

import json
import struct
from pathlib import Path
import pytest

from app.ai.speech.types import SpeechEvent, SpeechEventType
from app.database.models import ASRFragment, AuditLog
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.asr_capture_service import AsrCaptureService, _CaptureRuntime


@pytest.fixture(autouse=True)
def legacy_speaker_enabled(monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")


def _embedding(*values: float) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


class _Supervisor:
    speaker_accept_threshold = 0.70
    speaker_margin = 0.10


class _Device:
    pass


def _service_and_runtime(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fail-safe.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-FS", "suspectName": "张某", "officerName": "李警官"})
        session = session_repo.create(db, case.id)
        suspect = voiceprint_repo.enroll_suspect(
            db,
            case_id=case.id,
            embedding=_embedding(1.0, 0.0, 0.0, 0.0),
            embedding_dim=4,
            model_id="test-xvector",
            model_version="ref-v1",
            enrollment_quality="TEST",
            usable_duration_ms=20_000,
        )
        voiceprint_repo.assign_session_roles(
            db,
            session_id=session.id,
            suspect_voiceprint_id=suspect.id,
            interrogator_officer_id=None,
            recorder_officer_id=None,
        )
        capture = asr_repo.create_capture_session(
            db,
            case_id=case.id,
            interrogation_session_id=session.id,
            sample_rate=16_000,
        )
        db.commit()
        runtime = _CaptureRuntime(
            case_id=case.id,
            interrogation_session_id=session.id,
            capture_session_id=capture.id,
            speech_session_id=capture.id,
            speaker_threshold=0.70,
            speaker_margin=0.10,
            threshold_source="DEVICE_CALIBRATED",
            calibration_id=None,
            calibration_status="NOT_CALIBRATED",
            speaker_model_fingerprint=None,
            microphone_fingerprint=None,
        )

    service = AsrCaptureService(
        session_factory=factory,
        device_manager=_Device(),
        ai_supervisor=_Supervisor(),
        publish_event=lambda *_args: None,
    )
    return engine, factory, service, runtime


def _asr_event() -> SpeechEvent:
    return SpeechEvent(
        type=SpeechEventType.ASR_FINAL,
        session_id="speech",
        start_ms=0,
        end_ms=1200,
        text="这是有效转写",
        confidence=0.91,
        model_id="test-paraformer",
    )


def test_missing_xvector_result_preserves_asr_as_unknown_and_audits_low_confidence(tmp_path: Path):
    engine, factory, service, runtime = _service_and_runtime(tmp_path)
    service._consume_events(runtime, [_asr_event()])

    with factory() as db:
        fragment = db.query(ASRFragment).one()
        assert fragment.raw_text == "这是有效转写"
        assert fragment.speaker == "UNKNOWN"
        assert fragment.speaker_source == "UNASSIGNED"
        assert fragment.voiceprint_verified is False
        assert fragment.low_confidence is True

        audit = db.query(AuditLog).filter(AuditLog.action == "ASR_SPEAKER_LOW_CONFIDENCE").one()
        assert audit.target_id == fragment.id
        serialized = " ".join((audit.before_json, audit.after_json, audit.detail_json)).lower()
        assert "embedding" not in serialized
        assert "pcm" not in serialized
        assert "audio" not in serialized
    engine.dispose()


def test_suspect_only_nonmatch_stays_pending_for_manual_confirmation(tmp_path: Path):
    engine, factory, service, runtime = _service_and_runtime(tmp_path)
    speaker = SpeechEvent(
        type=SpeechEventType.SPEAKER_RESULT,
        session_id="speech",
        start_ms=0,
        end_ms=1200,
        embedding=[0.0, 1.0, 0.0, 0.0],
        model_id="test-xvector",
    )
    service._consume_events(runtime, [_asr_event(), speaker])

    with factory() as db:
        fragment = db.query(ASRFragment).one()
        assert fragment.speaker == "UNKNOWN"
        assert fragment.speaker_source == "UNASSIGNED"
        assert fragment.voiceprint_verified is False
        assert fragment.low_confidence is True

        audit = db.query(AuditLog).filter(AuditLog.action == "ASR_SPEAKER_LOW_CONFIDENCE").one()
        assert audit.target_id == fragment.id
        after = json.loads(audit.after_json)
        assert after["speaker"] == "UNKNOWN"
        assert after["speaker_source"] == "UNASSIGNED"
        serialized = " ".join((audit.before_json, audit.after_json, audit.detail_json)).lower()
        assert "embedding" not in serialized
        assert "pcm" not in serialized
        assert "audio" not in serialized
    engine.dispose()
