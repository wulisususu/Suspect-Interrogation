from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

import pytest

from app.ai.speech.calibration import MODEL_BASELINE_THRESHOLD
from app.ai.speech.types import SpeechEvent, SpeechEventType
from app.database.models import ASRCaptureSession, ASRFragment
from app.database.session import init_database, make_engine, make_session_factory
from app.domain.enums import SessionStatus
from app.domain.errors import DomainError
from app.repositories import asr_fragments as asr_repo
from app.repositories import cases as case_repo
from app.repositories import sessions as session_repo
from app.repositories import voiceprints as voiceprint_repo
from app.services import asr_capture_service as capture_module
from app.services.asr_capture_service import AsrCaptureService
from app.services.live_speech_coordinator import LiveSpeechCoordinator
from app.services.speaker_mode import (
    DEGRADED_REASON_MARGIN_CALIBRATION_MISSING,
    SUSPECT_PLUS_INTERROGATOR,
)
from app.services.speaker_policy import SpeakerRole, decide_speaker


@pytest.fixture
def legacy_voiceprint(monkeypatch):
    """Opt in only for tests of historical speaker attribution/projection."""
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")


def _embedding(*values: float) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


class FakeDeviceManager:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.started = 0
        self.stopped = 0
        self.reads = 0
        self.exhausted = threading.Event()

    def start_record(self) -> None:
        self.started += 1

    def read_audio_frames(self, timeout: float = 0.01) -> bytes:
        self.reads += 1
        if self._chunks:
            chunk = self._chunks.pop(0)
            if not self._chunks:
                self.exhausted.set()
            return chunk
        self.exhausted.set()
        time.sleep(min(timeout, 0.005))
        return b""

    def stop_record(self) -> None:
        self.stopped += 1


class FakeSpeechSupervisor:
    def __init__(self, *, fail_on_push: bool = False):
        self.speaker_accept_threshold = 0.70
        self.speaker_margin = 0.10
        self.fail_on_push = fail_on_push
        self.opened: list[tuple[str, int]] = []
        self.pushed: list[bytes] = []
        self.finalized: list[str] = []
        self.closed: list[str] = []

    def open_speech_session(self, session_id: str, *, sample_rate: int = 16000, speaker_backend: str | None = None):
        self.opened.append((session_id, sample_rate))
        return {"session_id": session_id, "sample_rate": sample_rate}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.pushed.append(bytes(pcm))
        if self.fail_on_push:
            raise RuntimeError("simulated speech worker failure")
        if len(self.pushed) == 1:
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_START,
                    session_id=session_id,
                    start_ms=0,
                    model_id="test-vad",
                )
            ]
        if len(self.pushed) == 2:
            return [
                SpeechEvent(
                    type=SpeechEventType.VAD_END,
                    session_id=session_id,
                    start_ms=0,
                    end_ms=1200,
                    model_id="test-vad",
                ),
                SpeechEvent(
                    type=SpeechEventType.ASR_FINAL,
                    session_id=session_id,
                    start_ms=0,
                    end_ms=1200,
                    text="我是嫌疑人",
                    confidence=0.94,
                    model_id="test-paraformer",
                    details={"model_version": "asr-v1"},
                ),
                SpeechEvent(
                    type=SpeechEventType.SPEAKER_RESULT,
                    session_id=session_id,
                    start_ms=0,
                    end_ms=1200,
                    embedding=[1.0, 0.0, 0.0, 0.0],
                    model_id="test-xvector",
                    details={
                        "backend_key": "xvector",
                        "model_version": "speaker-v1",
                        "model_fingerprint": "sha256:test-xvector",
                    },
                ),
            ]
        return []

    def finalize_speech_session(self, session_id: str):
        self.finalized.append(session_id)
        return []

    def close_speech_session(self, session_id: str) -> None:
        self.closed.append(session_id)


class EventCollector:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []
        self.ready = threading.Event()

    def __call__(self, session_id: str, event: str, payload: dict) -> None:
        self.events.append((session_id, event, payload))
        self.ready.set()


def _seed_database(tmp_path: Path, *, bind_interrogator: bool = False):
    engine = make_engine(f"sqlite:///{tmp_path / 'capture.db'}")
    init_database(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        case = case_repo.create(db, {"id": "CASE-1", "suspectName": "张某", "officerName": "李警官"})
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
        officer_id = None
        if bind_interrogator:
            voiceprint_repo.enroll_officer(
                db,
                officer_id="P-001",
                officer_name="主审张警官",
                embedding=_embedding(0.0, 1.0, 0.0, 0.0),
                embedding_dim=4,
                model_id="test-xvector",
                model_version="ref-v1",
                enrollment_quality="TEST",
                usable_duration_ms=20_000,
            )
            officer_id = "P-001"
        voiceprint_repo.assign_session_roles(
            db,
            session_id=session.id,
            suspect_voiceprint_id=suspect.id,
            interrogator_officer_id=officer_id,
            recorder_officer_id=None,
        )
        db.commit()
        case_id = case.id
        session_id = session.id
    return engine, factory, case_id, session_id


def test_start_refuses_capture_below_storage_reserve_before_creating_capture(tmp_path: Path, monkeypatch):
    engine, factory, case_id, _session_id = _seed_database(tmp_path)
    device = FakeDeviceManager([])
    speech = FakeSpeechSupervisor()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=lambda *_args: None,
    )
    LiveSpeechCoordinator(
        data_dir=tmp_path / "data",
        session_factory=factory,
        capture_service=service,
        ai_supervisor=speech,
        min_free_bytes=100,
    )
    monkeypatch.setattr(
        "app.services.durable_audio_archive.shutil.disk_usage",
        lambda _path: type("Usage", (), {"free": 99})(),
    )

    with pytest.raises(DomainError) as error:
        service.start(case_id)

    assert error.value.code == "ASR_AUDIO_STORAGE_RESERVE"
    assert device.started == 0
    with factory() as db:
        assert db.query(ASRCaptureSession).count() == 0
    engine.dispose()


def _wait_until(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def test_capture_broadcasts_live_transcript_preview_without_creating_a_fragment(tmp_path: Path):
    _engine, factory, case_id, session_id = _seed_database(tmp_path)
    events = EventCollector()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager([]),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=events,
    )
    runtime = capture_module._CaptureRuntime(
        case_id=case_id,
        interrogation_session_id=session_id,
        capture_session_id="capture-preview",
        speech_session_id="speech-preview",
        speaker_threshold=0.7,
        speaker_margin=0.1,
        threshold_source="TEST",
        calibration_id=None,
        calibration_status="TEST",
        speaker_model_fingerprint=None,
        microphone_fingerprint=None,
    )

    service._consume_events(runtime, [
        SpeechEvent(
            type=SpeechEventType.ASR_PARTIAL,
            session_id=runtime.speech_session_id,
            start_ms=100,
            end_ms=1600,
            text="正在说的话",
            model_id="test-paraformer",
        )
    ])

    assert events.events == [(
        session_id,
        "ASR_PARTIAL",
        {
            "caseId": case_id,
            "captureSessionId": "capture-preview",
            "text": "正在说的话",
            "startedAtMs": 100,
            "endedAtMs": 1600,
        },
    )]
    with factory() as db:
        assert db.query(ASRFragment).count() == 0


def test_capture_pushes_each_pcm_chunk_once_persists_verified_fragment_and_broadcasts(tmp_path: Path, legacy_voiceprint):
    engine, factory, case_id, session_id = _seed_database(tmp_path)
    chunks = [b"\x01\x00" * 1600, b"\x02\x00" * 1600]
    device = FakeDeviceManager(chunks)
    speech = FakeSpeechSupervisor()
    events = EventCollector()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=events,
        sample_rate=16_000,
        read_timeout=0.01,
    )

    started = service.start(case_id)
    assert started["active"] is True
    assert started["caseId"] == case_id
    assert started["interrogationSessionId"] == session_id
    assert isinstance(started["startedAt"], str)
    assert started["startedAt"]

    _wait_until(lambda: len(speech.pushed) == 2)
    _wait_until(lambda: bool(events.events))
    stopped = service.stop(case_id)

    assert speech.pushed == chunks
    assert device.started == 1
    assert device.stopped == 1
    assert len(speech.opened) == 1
    assert speech.finalized == [speech.opened[0][0]]
    assert speech.closed == [speech.opened[0][0]]
    assert stopped["active"] is False

    with factory() as db:
        captures = list(db.query(ASRCaptureSession).all())
        fragments = list(db.query(ASRFragment).all())
        assert len(captures) == 1
        assert captures[0].status == "STOPPED"
        assert captures[0].ended_at is not None
        assert len(fragments) == 1
        fragment = fragments[0]
        assert fragment.raw_text == "我是嫌疑人"
        assert fragment.edited_text == "我是嫌疑人"
        assert fragment.state == "PENDING"
        assert fragment.speaker == "SUSPECT"
        assert fragment.speaker_source == "SPEAKER_EMBEDDING"
        assert fragment.voiceprint_verified is True
        assert fragment.low_confidence is False
        assert fragment.speaker_score == 1.0
        assert fragment.speaker_threshold == 0.70
        assert fragment.speaker_margin == 0.10
        assert fragment.asr_confidence == 0.94
        assert fragment.model_id == "test-paraformer"
        assert fragment.model_version == "asr-v1"

    audio_events = [item for item in events.events if item[1] == "AUDIO_LEVEL"]
    fragment_events = [item for item in events.events if item[1] == "ASR_FRAGMENT"]
    assert audio_events
    assert audio_events[0][2]["sampleCount"] >= 1600
    assert len(fragment_events) == 1
    event_session, event_name, payload = fragment_events[0]
    assert event_session == session_id
    assert event_name == "ASR_FRAGMENT"
    assert payload["rawText"] == "我是嫌疑人"
    assert payload["speaker"] == "SUSPECT"
    assert payload["speakerSource"] == "SPEAKER_EMBEDDING"
    assert payload["thresholdSource"] == "DEVICE_CALIBRATED"
    assert payload["voiceprintVerified"] is True
    engine.dispose()


def test_capture_rejects_paused_interrogation_session(tmp_path: Path):
    engine, factory, case_id, _ = _seed_database(tmp_path)
    with factory() as db:
        session = session_repo.active_for_case(db, case_id)
        assert session is not None
        session.status = SessionStatus.PAUSED.value
        db.commit()

    device = FakeDeviceManager([])
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=EventCollector(),
    )

    with pytest.raises(DomainError, match="当前审讯未处于进行状态") as exc:
        service.start(case_id)
    assert exc.value.code == "SESSION_NOT_RUNNING"
    assert device.started == 0
    engine.dispose()


def test_capture_without_margin_runs_suspect_only_and_preserves_uncalibrated_margin(tmp_path: Path, legacy_voiceprint):
    engine, factory, case_id, session_id = _seed_database(tmp_path)
    chunks = [b"\x01\x00" * 1600, b"\x02\x00" * 1600]
    device = FakeDeviceManager(chunks)
    speech = FakeSpeechSupervisor()
    speech.speaker_margin = None
    speech.speaker_threshold_source = "MODEL_BASELINE"
    events = EventCollector()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=events,
        sample_rate=16_000,
        read_timeout=0.01,
    )

    started = service.start(case_id)
    assert started["active"] is True
    assert started["thresholdSource"] == "MODEL_BASELINE"
    assert started["speakerMarginConfigured"] is False

    _wait_until(lambda: len(speech.pushed) == 2)
    _wait_until(lambda: bool(events.events))
    service.stop(case_id)

    with factory() as db:
        fragment = db.query(ASRFragment).one()
        assert fragment.speaker == "SUSPECT"
        assert fragment.voiceprint_verified is True
        assert fragment.speaker_threshold == 0.70
        assert fragment.speaker_margin is None

    fragment_events = [item for item in events.events if item[1] == "ASR_FRAGMENT"]
    assert len(fragment_events) == 1
    event_session, event_name, payload = fragment_events[0]
    assert event_session == session_id
    assert event_name == "ASR_FRAGMENT"
    assert payload["speaker"] == "SUSPECT"
    assert payload["speakerMargin"] is None
    assert payload["thresholdSource"] == "MODEL_BASELINE"
    engine.dispose()


def _capture_service(factory, speech: FakeSpeechSupervisor, events: EventCollector) -> AsrCaptureService:
    return AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager([]),
        ai_supervisor=speech,
        publish_event=events,
        sample_rate=16_000,
        read_timeout=0.01,
    )


def test_capture_status_declares_the_effective_mode_reported_by_the_shared_rule(tmp_path: Path, legacy_voiceprint):
    """Task 17B-1: the runtime must publish the mode it actually enforces."""
    engine, factory, case_id, _ = _seed_database(tmp_path, bind_interrogator=True)
    speech = FakeSpeechSupervisor()
    chunks = [b"\x01\x00" * 1600, b"\x02\x00" * 1600]

    configured = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager(list(chunks)),
        ai_supervisor=speech,
        publish_event=EventCollector(),
        sample_rate=16_000,
        read_timeout=0.01,
    )
    started = configured.start(case_id)
    assert started["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert started["effectiveRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert started["recognitionModeDegraded"] is False
    assert started["recognitionModeDegradedReason"] is None
    configured.stop(case_id)

    speech.speaker_margin = None
    uncalibrated = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager(list(chunks)),
        ai_supervisor=speech,
        publish_event=EventCollector(),
        sample_rate=16_000,
        read_timeout=0.01,
    )
    degraded = uncalibrated.start(case_id)
    assert degraded["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert degraded["effectiveRecognitionMode"] == "SUSPECT_ONLY"
    assert degraded["recognitionModeDegraded"] is True
    assert degraded["recognitionModeDegradedReason"] == DEGRADED_REASON_MARGIN_CALIBRATION_MISSING
    uncalibrated.stop(case_id)
    engine.dispose()


def test_without_a_margin_the_runtime_drops_unbound_officer_candidates(tmp_path: Path, legacy_voiceprint):
    """The narrowing must reuse the shared predicate (single source of truth)."""
    engine, factory, _case_id, _session_id = _seed_database(tmp_path)
    speech = FakeSpeechSupervisor()
    speech.speaker_margin = None
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=None,
        ai_supervisor=speech,
        publish_event=lambda *_args: None,
    )
    candidates = [
        {"role": SpeakerRole.SUSPECT, "score": 0.95, "speaker_id": "s", "speaker_name": "张某"},
        {"role": SpeakerRole.INTERROGATOR, "score": 0.99, "speaker_id": "P-001", "speaker_name": "张警官"},
    ]

    degraded = service._decide_with_operating_point(
        candidates=candidates,
        enabled_roles={SpeakerRole.SUSPECT, SpeakerRole.INTERROGATOR},
        threshold=0.372,
        margin=None,
        usable_duration_ms=1200,
        overlap=False,
    )
    # The higher-scoring interrogator candidate must not win without a calibrated margin.
    assert degraded.role is SpeakerRole.SUSPECT
    assert degraded.voiceprint_verified is True

    calibrated = service._decide_with_operating_point(
        candidates=candidates,
        enabled_roles={SpeakerRole.SUSPECT, SpeakerRole.INTERROGATOR},
        threshold=0.372,
        margin=0.02,
        usable_duration_ms=1200,
        overlap=False,
    )
    assert calibrated.role is SpeakerRole.INTERROGATOR
    assert calibrated.speaker_id == "P-001"
    engine.dispose()


def test_degraded_fragment_audit_records_the_shared_mode_rule(tmp_path: Path, legacy_voiceprint):
    """Task 17B-1: a narrowed operating point must leave an auditable reason."""
    import json

    from app.database.models import AuditLog

    engine, factory, case_id, _ = _seed_database(tmp_path)
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager([]),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=lambda *_args: None,
    )
    decision = decide_speaker(
        candidates=[{"role": SpeakerRole.SUSPECT, "score": 0.10, "speaker_id": "s"}],
        enabled_roles={SpeakerRole.SUSPECT},
        threshold=0.372,
        margin=0.0,
        usable_duration_ms=1200,
        overlap=False,
    )
    with factory() as db:
        service._audit_speaker_decision(
            db,
            case_id=case_id,
            fragment_id="FRAG-1",
            decision=decision,
            threshold_source="MODEL_BASELINE",
            margin=None,
            usable_duration_ms=1200,
            decision_roles={SpeakerRole.SUSPECT},
            declared_mode=SUSPECT_PLUS_INTERROGATOR,
            asr_event=SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id="SPEECH-1",
                start_ms=0,
                end_ms=1200,
                text="嗯",
            ),
        )
        db.commit()
        audit = db.query(AuditLog).filter(AuditLog.action == "ASR_SPEAKER_LOW_CONFIDENCE").one()
        detail = json.loads(audit.detail_json)

    assert detail["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert detail["effectiveRecognitionMode"] == "SUSPECT_ONLY"
    assert detail["recognitionModeDegraded"] is True
    assert detail["recognitionModeDegradedReason"] == DEGRADED_REASON_MARGIN_CALIBRATION_MISSING
    engine.dispose()


def test_inference_failure_does_not_stop_capture_and_manual_stop_finalizes_worker(tmp_path: Path):
    engine, factory, case_id, _ = _seed_database(tmp_path)
    device = FakeDeviceManager([b"\x01\x00" * 1600])
    speech = FakeSpeechSupervisor(fail_on_push=True)
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=lambda *_args: None,
        sample_rate=16_000,
        read_timeout=0.01,
    )

    service.start(case_id)
    _wait_until(lambda: service.status(case_id)["lastError"] == "simulated speech worker failure")

    assert device.started == 1
    assert device.stopped == 0
    assert service.status(case_id)["active"] is True
    service.stop(case_id)
    assert device.stopped == 1
    assert len(speech.finalized) == 1
    assert speech.closed == speech.finalized
    status = service.status(case_id)
    assert status["lastError"] == "simulated speech worker failure"

    with factory() as db:
        capture = db.query(ASRCaptureSession).one()
        assert capture.status == "STOPPED"
        assert capture.ended_at is not None
        assert db.query(ASRFragment).count() == 0
    engine.dispose()


# --- contract: declared_mode_for_roles / runtime binding roles ------------------


def test_declared_mode_for_roles_requires_the_suspect_reference():
    """The suspect reference is unconditionally bound, so a set without it is a bug.

    Making this loud is the tightening: ``decision_roles`` always contains SUSPECT, so
    a bound set that omitted it would declare one mode and enforce nothing.
    """
    import pytest

    with pytest.raises(ValueError):
        AsrCaptureService.declared_mode_for_roles({SpeakerRole.INTERROGATOR})


def test_declared_mode_for_roles_ignores_values_that_are_not_speaker_roles():
    assert AsrCaptureService.declared_mode_for_roles({SpeakerRole.SUSPECT}) == "SUSPECT_ONLY"
    # A string is not a binding, exactly like in the candidate narrowing.
    assert (
        AsrCaptureService.declared_mode_for_roles({SpeakerRole.SUSPECT, "INTERROGATOR"})
        == "SUSPECT_ONLY"
    )
    assert (
        AsrCaptureService.declared_mode_for_roles(
            {SpeakerRole.SUSPECT, SpeakerRole.INTERROGATOR}
        )
        == SUSPECT_PLUS_INTERROGATOR
    )


def test_start_seeds_the_declared_mode_without_a_second_database_session(tmp_path: Path, monkeypatch, legacy_voiceprint):
    """``start()`` must not open an extra session just to seed the declared mode."""
    engine, factory, case_id, _ = _seed_database(tmp_path, bind_interrogator=True)
    sessions: list[int] = []
    closed: list[int] = []
    original = factory

    class RecordingFactory:
        def __call__(self):
            sessions.append(len(sessions))
            session = original()
            closed.append(len(closed))
            return session

    service = AsrCaptureService(
        session_factory=RecordingFactory(),
        device_manager=FakeDeviceManager([]),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=lambda *_args: None,
        read_timeout=0.01,
    )
    started = service.start(case_id)
    try:
        assert started["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert len(sessions) == 1, "start() opened more than one session"
    finally:
        service.stop(case_id)
        engine.dispose()


# --- contract: the published ASR_FRAGMENT payload -------------------------------


def test_published_fragment_payload_carries_the_shared_mode_rule(tmp_path: Path, legacy_voiceprint):
    """Task 17B-1: every broadcast fragment names the mode it was decided in."""
    engine, factory, case_id, session_id = _seed_database(tmp_path, bind_interrogator=True)
    chunks = [b"\x01\x00" * 1600, b"\x02\x00" * 1600]

    calibrated_events = EventCollector()
    calibrated = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager(list(chunks)),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=calibrated_events,
        sample_rate=16_000,
        read_timeout=0.01,
    )
    calibrated.start(case_id)
    _wait_until(lambda: bool(calibrated_events.events))
    calibrated.stop(case_id)

    degraded_events = EventCollector()
    degraded_supervisor = FakeSpeechSupervisor()
    degraded_supervisor.speaker_margin = None
    degraded_supervisor.speaker_threshold_source = "MODEL_BASELINE"
    degraded = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager(list(chunks)),
        ai_supervisor=degraded_supervisor,
        publish_event=degraded_events,
        sample_rate=16_000,
        read_timeout=0.01,
    )
    degraded.start(case_id)
    _wait_until(lambda: bool(degraded_events.events))
    degraded.stop(case_id)

    for events, expected_mode, expected_degraded in (
        (calibrated_events, SUSPECT_PLUS_INTERROGATOR, False),
        (degraded_events, "SUSPECT_ONLY", True),
    ):
        fragment_event = next(item for item in events.events if item[1] == "ASR_FRAGMENT")
        event_session, event_name, payload = fragment_event
        assert event_session == session_id
        assert event_name == "ASR_FRAGMENT"
        assert payload["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert payload["effectiveRecognitionMode"] == expected_mode
        assert payload["recognitionModeDegraded"] is expected_degraded
        assert payload["recognitionModeDegradedReason"] == (
            DEGRADED_REASON_MARGIN_CALIBRATION_MISSING if expected_degraded else None
        )
        assert payload["speakerMargin"] == (
            None if expected_degraded else 0.10
        )
    engine.dispose()


def test_capture_starts_with_model_baseline_when_device_calibration_is_missing(tmp_path: Path, legacy_voiceprint):
    engine, factory, case_id, _ = _seed_database(tmp_path)
    device = FakeDeviceManager([])
    speech = FakeSpeechSupervisor()
    speech.speaker_accept_threshold = None
    speech.speaker_margin = None
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=lambda *_args: None,
        read_timeout=0.01,
    )

    started = service.start(case_id)
    assert started["active"] is True
    assert started["speakerThreshold"] == MODEL_BASELINE_THRESHOLD
    assert started["thresholdSource"] == "MODEL_BASELINE"
    assert started["speakerMarginConfigured"] is False
    assert device.started == 1

    service.stop(case_id)
    assert device.stopped == 1
    engine.dispose()


def test_projection_failure_keeps_raw_fragment_and_capture_loop_healthy(tmp_path: Path, monkeypatch, legacy_voiceprint):
    engine, factory, case_id, _ = _seed_database(tmp_path)
    device = FakeDeviceManager([b"\x01\x00" * 1600, b"\x02\x00" * 1600])
    speech = FakeSpeechSupervisor()
    events = EventCollector()

    class ExplodingProjection:
        calls = 0

        def __init__(self, _db):
            pass

        def process_fragment(self, _case_id: str, _fragment_id: str):
            type(self).calls += 1
            raise RuntimeError("simulated formal projection failure")

    monkeypatch.setattr(capture_module, "InterrogationProjectionService", ExplodingProjection, raising=False)
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=events,
        sample_rate=16_000,
        read_timeout=0.01,
    )

    service.start(case_id)
    _wait_until(lambda: len(speech.pushed) == 2)
    _wait_until(lambda: bool(events.events))
    stopped = service.stop(case_id)

    assert ExplodingProjection.calls == 1
    assert stopped["lastError"] is None


def test_fragment_sink_bypasses_legacy_projection_and_capture_finished_sink_flushes(tmp_path: Path, monkeypatch, legacy_voiceprint):
    engine, factory, case_id, session_id = _seed_database(tmp_path)
    device = FakeDeviceManager([b"\x01\x00" * 1600, b"\x02\x00" * 1600])
    speech = FakeSpeechSupervisor()
    events = EventCollector()
    fragments: list[tuple[str, str]] = []
    finished: list[tuple[str, str]] = []

    class ForbiddenProjection:
        calls = 0

        def __init__(self, _db):
            pass

        def process_fragment(self, _case_id: str, _fragment_id: str):
            type(self).calls += 1
            raise AssertionError("legacy projection must not run in qwen sink mode")

    monkeypatch.setattr(capture_module, "InterrogationProjectionService", ForbiddenProjection, raising=False)
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=device,
        ai_supervisor=speech,
        publish_event=events,
        fragment_sink=lambda case, fragment: fragments.append((case, fragment)),
        capture_finished_sink=lambda case, session: finished.append((case, session)),
        sample_rate=16_000,
        read_timeout=0.01,
    )

    service.start(case_id)
    _wait_until(lambda: bool(fragments))
    service.stop(case_id)

    assert ForbiddenProjection.calls == 0
    assert len(fragments) == 1
    assert fragments[0][0] == case_id
    assert finished == [(case_id, session_id)]
    engine.dispose()


def _audio_meter_runtime(tmp_path: Path, capture_id: str):
    engine, factory, case_id, session_id = _seed_database(tmp_path)
    events = EventCollector()
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager([]),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=events,
    )
    runtime = capture_module._CaptureRuntime(
        case_id=case_id,
        interrogation_session_id=session_id,
        capture_session_id=capture_id,
        speech_session_id=f"speech-{capture_id}",
        speaker_threshold=0.7,
        speaker_margin=0.1,
        threshold_source="TEST",
        calibration_id=None,
        calibration_status="TEST",
        speaker_model_fingerprint=None,
        microphone_fingerprint=None,
    )
    return engine, service, runtime, events, session_id, case_id


def test_audio_level_event_reports_metrics_from_pcm16(tmp_path: Path):
    engine, service, runtime, events, session_id, case_id = _audio_meter_runtime(tmp_path, "capture-meter")

    service._publish_audio_level(runtime, struct.pack("<hhh", 0, 3000, -4000), now=1.0)

    assert len(events.events) == 1
    event_session, event_name, payload = events.events[0]
    assert event_session == session_id
    assert event_name == "AUDIO_LEVEL"
    assert payload["caseId"] == case_id
    assert payload["captureSessionId"] == "capture-meter"
    assert payload["sampleCount"] == 3
    assert payload["sampleRate"] == 16_000
    assert payload["peak"] == 4000
    assert payload["rms"] == pytest.approx(2886.75, abs=0.01)
    engine.dispose()


def test_audio_level_event_is_throttled_and_counts_suppressed_pcm(tmp_path: Path):
    engine, service, runtime, events, _session_id, _case_id = _audio_meter_runtime(tmp_path, "capture-throttle")
    pcm = struct.pack("<hh", 1000, -1000)

    service._publish_audio_level(runtime, pcm, now=1.0)
    service._publish_audio_level(runtime, pcm, now=1.02)
    service._publish_audio_level(runtime, pcm, now=1.05)

    assert len(events.events) == 2
    assert events.events[-1][2]["sampleCount"] == 6
    engine.dispose()


def test_capture_status_reports_recording_asr_and_speaker_workflow_state(tmp_path: Path):
    engine, factory, case_id, _ = _seed_database(tmp_path)
    service = _capture_service(factory, FakeSpeechSupervisor(), EventCollector())
    started = service.start(case_id)
    service.stop(case_id)

    with factory() as db:
        capture = db.get(ASRCaptureSession, started["captureSessionId"])
        assert capture is not None
        capture.recording_status = "INCOMPLETE"
        capture.asr_status = "FINALIZING"
        capture.speaker_status = "QUEUED"
        capture.audio_sample_count = 16_000
        capture.asr_cursor_sample = 8_000
        capture.voiced_ms = 5_000
        db.commit()

    status = service.status(case_id)

    assert status["recordingStatus"] == "INCOMPLETE"
    assert status["asrStatus"] == "FINALIZING"
    assert status["speakerStatus"] == "QUEUED"
    assert status["audioSampleCount"] == 16_000
    assert status["asrCursorSample"] == 8_000
    assert status["voicedMs"] == 5_000
    assert status["finalFragmentCount"] == 0
    engine.dispose()


@pytest.mark.parametrize("use_sink", [True, False])
def test_unknown_asr_final_is_published_without_projection_or_sink(tmp_path: Path, monkeypatch, use_sink: bool):
    engine, factory, case_id, session_id = _seed_database(tmp_path)
    with factory() as db:
        capture = asr_repo.create_capture_session(
            db,
            case_id=case_id,
            interrogation_session_id=session_id,
            sample_rate=16_000,
        )
        capture_id = capture.id
        db.commit()

    events = EventCollector()
    enqueued: list[tuple[str, str]] = []
    service = AsrCaptureService(
        session_factory=factory,
        device_manager=FakeDeviceManager([]),
        ai_supervisor=FakeSpeechSupervisor(),
        publish_event=events,
        fragment_sink=(lambda case, fragment: enqueued.append((case, fragment))) if use_sink else None,
    )

    class ForbiddenProjection:
        calls = 0

        def __init__(self, _db):
            pass

        def process_fragment(self, _case_id, _fragment_id):
            type(self).calls += 1
            raise AssertionError("UNKNOWN transcript rows must wait for speaker resolution")

    monkeypatch.setattr(capture_module, "InterrogationProjectionService", ForbiddenProjection, raising=False)
    runtime = capture_module._CaptureRuntime(
        case_id=case_id,
        interrogation_session_id=session_id,
        capture_session_id=capture_id,
        speech_session_id=capture_id,
        speaker_threshold=0.7,
        speaker_margin=0.1,
        threshold_source="TEST",
        calibration_id=None,
        calibration_status="UNAVAILABLE",
        speaker_model_fingerprint=None,
        microphone_fingerprint=None,
    )
    fragment_id = service._persist_asr_only_fragment(
        runtime,
        SpeechEvent(
            type=SpeechEventType.ASR_FINAL,
            session_id=capture_id,
            start_ms=0,
            end_ms=1000,
            text="暂不区分说话人",
            confidence=0.9,
            model_id="test-asr",
            details={"model_version": "v1"},
        ),
    )

    assert events.events[0][1] == "ASR_FRAGMENT"
    assert events.events[0][2]["fragmentId"] == fragment_id
    assert enqueued == []
    assert ForbiddenProjection.calls == 0
    with factory() as db:
        persisted = db.get(ASRFragment, fragment_id)
        assert persisted is not None
        assert persisted.speaker == "UNKNOWN"
    engine.dispose()
