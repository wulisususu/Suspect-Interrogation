from __future__ import annotations

import struct
import time
from pathlib import Path

import pytest

from app.ai.speech.calibration import MODEL_BASELINE_THRESHOLD, SpeakerCalibration
from app.database.session import init_database, make_engine, make_session_factory
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services.asr_capture_service import AsrCaptureService


class SilentDevice:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start_record(self) -> None:
        self.started += 1

    def read_audio_frames(self, timeout: float = 0.01) -> bytes:
        time.sleep(min(timeout, 0.005))
        return b""

    def stop_record(self) -> None:
        self.stopped += 1


class BaselineSpeechSupervisor:
    speaker_accept_threshold = MODEL_BASELINE_THRESHOLD
    speaker_threshold_source = "MODEL_BASELINE"
    speaker_margin = None

    def open_speech_session(self, session_id: str, *, sample_rate: int = 16000, speaker_backend: str | None = None):
        return {"session_id": session_id, "sample_rate": sample_rate}

    def push_speech_pcm(self, _session_id: str, _pcm: bytes):
        return []

    def finalize_speech_session(self, _session_id: str):
        return []

    def close_speech_session(self, _session_id: str) -> None:
        return None


def _seed_case(tmp_path: Path, *, with_suspect_voiceprint: bool):
    engine = make_engine(f"sqlite:///{tmp_path / 'baseline.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(
            db,
            {"id": "CASE-BASELINE", "suspectName": "张某", "officerName": "李警官"},
        )
        session_repo.create(db, case.id)
        if with_suspect_voiceprint:
            voiceprint_repo.enroll_suspect(
                db,
                case_id=case.id,
                embedding=struct.pack("<4f", 1.0, 0.0, 0.0, 0.0),
                embedding_dim=4,
                model_id="eres2net_large",
                model_version="test",
                enrollment_quality="TEST",
                usable_duration_ms=20_000,
            )
        db.commit()
    return engine, factory, case.id


def test_missing_device_calibration_uses_model_baseline_threshold(monkeypatch):
    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_BASELINE_THRESHOLD", raising=False)

    calibration = SpeakerCalibration.from_env()

    assert calibration.accept_threshold is None
    assert calibration.margin is None
    assert calibration.effective_threshold == pytest.approx(MODEL_BASELINE_THRESHOLD)
    assert calibration.threshold_source == "MODEL_BASELINE"
    assert calibration.device_calibrated is False


def test_device_threshold_overrides_baseline_and_reports_calibrated_source(monkeypatch):
    monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", "0.76")
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)

    calibration = SpeakerCalibration.from_env()

    assert calibration.effective_threshold == pytest.approx(0.76)
    assert calibration.threshold_source == "DEVICE_CALIBRATED"
    assert calibration.device_calibrated is True
    assert calibration.margin is None


def test_formal_capture_starts_with_suspect_voiceprint_and_baseline_threshold_without_margin(tmp_path: Path):
    engine, factory, case_id = _seed_case(tmp_path, with_suspect_voiceprint=True)
    device = SilentDevice()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=BaselineSpeechSupervisor(),
        publish_event=lambda *_args: None,
        read_timeout=0.01,
    )

    try:
        started = service.start(case_id)
        assert started["active"] is True
        assert device.started == 1
    finally:
        service.stop(case_id)
        engine.dispose()


def test_formal_capture_starts_without_suspect_voiceprint(tmp_path: Path):
    engine, factory, case_id = _seed_case(tmp_path, with_suspect_voiceprint=False)
    device = SilentDevice()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=BaselineSpeechSupervisor(),
        publish_event=lambda *_args: None,
        read_timeout=0.01,
    )

    try:
        started = service.start(case_id)
        assert started["active"] is True
        assert device.started == 1
    finally:
        service.stop(case_id)
        engine.dispose()
