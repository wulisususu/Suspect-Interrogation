from __future__ import annotations

import struct
import time
import pytest

from app.database.session import init_database, make_engine, make_session_factory
from app.database.voiceprint_models import SessionSpeakerCalibrationSnapshot
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import speaker_calibrations as calibration_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.asr_capture_service import AsrCaptureService
from app.services.speaker_calibration_runtime import ResolvedSpeakerCalibration


@pytest.fixture(autouse=True)
def legacy_calibration_enabled(monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")


class IdleDevice:
    def start_record(self): pass
    def stop_record(self): pass
    def read_audio_frames(self, timeout=0.01):
        time.sleep(min(timeout, 0.003)); return b""


class IdleSupervisor:
    speaker_accept_threshold = 0.70
    speaker_margin = None
    speaker_threshold_source = "MODEL_BASELINE"
    def open_speech_session(self, session_id, sample_rate=16000, speaker_backend=None): return {}
    def push_speech_pcm(self, session_id, pcm): return []
    def finalize_speech_session(self, session_id): return []
    def close_speech_session(self, session_id): return None


def test_formal_capture_snapshots_resolved_calibration_once(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'snapshot.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-CAL", "suspectName": "张某", "officerName": "李警官"})
        session = session_repo.create(db, case.id)
        suspect = voiceprint_repo.enroll_suspect(
            db, case_id=case.id, embedding=struct.pack("<3f", 1.0, 0.0, 0.0), embedding_dim=3,
            model_id="eres2net", model_version="v1", enrollment_quality="GOOD", usable_duration_ms=20_000,
        )
        voiceprint_repo.assign_session_roles(
            db, session_id=session.id, suspect_voiceprint_id=suspect.id,
            interrogator_officer_id=None, recorder_officer_id=None,
        )
        calibration = calibration_repo.create_calibration(
            db,
            status_at_creation="VALID",
            threshold=0.81,
            margin=0.08,
            far=0.0,
            frr=0.0,
            eer=0.0,
            eer_threshold=0.81,
            eer_far=0.0,
            eer_frr=0.0,
            genuine_trial_count=9,
            impostor_trial_count=18,
            officer_count=3,
            sample_count=9,
            corpus_digest="c" * 64,
            algorithm_version="speaker-calibration-v1",
            speaker_model_id="eres2net",
            speaker_model_version="v1",
            speaker_model_fingerprint="a" * 64,
            audio_source="ALSA",
            microphone_id="hw:1,0",
            microphone_name="USB Mic",
            microphone_fingerprint="b" * 64,
            microphone_fingerprint_certainty="STRONG",
        )
        db.commit()
        calibration_id = calibration.id

    current = {"threshold": 0.81}
    def resolver(_db):
        return ResolvedSpeakerCalibration(
            calibration_id=calibration_id, threshold=current["threshold"], margin=0.08,
            source="DEVICE_CALIBRATED", status="VALID",
            speaker_model_fingerprint="a" * 64, microphone_fingerprint="b" * 64,
        )

    service = AsrCaptureService(
        session_factory=factory, device_manager=IdleDevice(), ai_supervisor=IdleSupervisor(),
        publish_event=lambda *_args: None, read_timeout=0.01, calibration_resolver=resolver,
    )
    started = service.start("CASE-CAL")
    assert started["speakerThreshold"] == 0.81
    assert started["calibrationId"] == calibration_id

    current["threshold"] = 0.93
    active = service.status("CASE-CAL")
    assert active["speakerThreshold"] == 0.81

    with factory() as db:
        snapshot = db.query(SessionSpeakerCalibrationSnapshot).one()
        assert snapshot.calibration_id == calibration_id
        assert snapshot.threshold == 0.81
        assert snapshot.margin == 0.08
        assert snapshot.threshold_source == "DEVICE_CALIBRATED"
        assert snapshot.calibration_status == "VALID"
        assert snapshot.speaker_model_fingerprint == "a" * 64
        assert snapshot.microphone_fingerprint == "b" * 64

    service.stop("CASE-CAL")
    engine.dispose()
