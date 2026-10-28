"""Task 17B-1 acceptance: the effective speaker mode is one provable rule.

Two sides must agree for every device configuration:

* ``VoiceprintService.readiness()["effectiveRecognitionMode"]`` -- what the operator
  is told will happen.
* ``AsrCaptureService`` -- the roles the runtime actually lets through when it
  attributes a fragment.

The regression this guards: a deployment without a calibrated margin silently ran
suspect-only while the UI still advertised "suspect + interrogating officer".
"""

import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai.speech.calibration import MODEL_BASELINE_THRESHOLD
from app.database.models import Case
from app.database.session import init_database, make_engine, make_session_factory
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app
from app.repositories import sessions as session_repo
from app.repositories import speaker_calibrations as calibration_repo
from app.services.asr_capture_service import AsrCaptureService
from app.services.speaker_mode import (
    DEGRADED_REASON_MARGIN_CALIBRATION_MISSING,
    SUSPECT_ONLY,
    SUSPECT_PLUS_INTERROGATOR,
    VERIFICATION_DEVICE_CALIBRATION,
    SpeakerModeConfig,
)
from app.services.speaker_policy import SpeakerRole
from app.services.voiceprint_service import VoiceprintService


SAMPLE_RATE = 16000
GOOD_SEGMENTS = [[0, 20000], [21000, 41000], [42000, 62000]]
GOOD_EMBEDDINGS = [
    [1.0, 0.0, 0.0],
    [0.99, 0.1, 0.0],
    [0.98, -0.1, 0.0],
]


@pytest.fixture(autouse=True)
def legacy_speaker_modes_enabled(monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")


def pcm16(duration_ms: int = 62000, sample: int = 1200) -> bytes:
    samples = duration_ms * SAMPLE_RATE // 1000
    return struct.pack(f"<{samples}h", *([sample] * samples))


class FakeSpeechClient:
    def __init__(self):
        self.embedding_calls = 0

    def speech_segments(self, pcm: bytes, sample_rate: int = SAMPLE_RATE):
        return [list(item) for item in GOOD_SEGMENTS]

    def extract_embedding(self, pcm: bytes, sample_rate: int = SAMPLE_RATE):
        vector = GOOD_EMBEDDINGS[self.embedding_calls % len(GOOD_EMBEDDINGS)]
        self.embedding_calls += 1
        return {
            "embedding": vector,
            "backend_key": "eres2net_large",
            "model_id": "eres2net_large",
            "model_version": "17b1-test",
        }


class FakeCaptureService:
    """Mirrors the parts of AsrCaptureService the readiness route consults."""

    def __init__(self):
        self.active: tuple[str, str] | None = None

    def start(self, kind: str, subject_id: str, source: str = "ALSA"):
        self.active = (kind, subject_id)
        return {
            "active": True,
            "kind": kind,
            "subjectId": subject_id,
            "captureId": "CAP-FAKE-1",
            "source": source,
            "sampleRate": SAMPLE_RATE,
            "capturedBytes": 0,
            "maxBytes": SAMPLE_RATE * 2 * 30,
            "complete": False,
        }

    def stop(self, kind: str, subject_id: str):
        self.active = None
        return pcm16()

    def status(self, case_id: str | None = None):
        return {"active": False, "caseId": case_id}


class FakeSupervisor:
    def __init__(self, *, margin: float | None, threshold: float | None = 0.372):
        self.speaker_margin = margin
        self.speaker_accept_threshold = threshold
        self.speaker_threshold_source = (
            "DEVICE_CALIBRATED" if threshold is not None else "MODEL_BASELINE"
        )
        self.opened: list[str] = []
        self.pushed: list[bytes] = []

    def open_speech_session(self, session_id: str, *, sample_rate: int = SAMPLE_RATE, speaker_backend=None):
        self.opened.append(session_id)
        return {"session_id": session_id, "sample_rate": sample_rate}

    def push_speech_pcm(self, session_id: str, pcm: bytes):
        self.pushed.append(bytes(pcm))
        return []

    def finalize_speech_session(self, session_id: str):
        return []

    def close_speech_session(self, session_id: str) -> None:
        pass

    def shutdown(self) -> None:
        pass


class FakeDeviceManager:
    """Idle microphone: the capture loop only ever reads silence."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start_record(self) -> None:
        self.started += 1

    def read_audio_frames(self, timeout: float = 0.01) -> bytes:
        import time

        time.sleep(min(timeout, 0.005))
        return b""

    def stop_record(self) -> None:
        self.stopped += 1


class CaseIdOnlyCaptureService:
    """Mirrors ``SourceAwareAsrCaptureService.status(self, case_id: str)``.

    ``case_id`` is a *required* positional parameter, exactly like production. A
    caller that invokes ``status()`` with no argument gets a ``TypeError``, so this
    fake can never hide the no-argument call the readiness route used to make.
    """

    def __init__(self, payload: dict | None = None) -> None:
        self.payload = dict(payload or {})
        self.calls: list[str] = []

    def status(self, case_id: str) -> dict:
        self.calls.append(case_id)
        payload = dict(self.payload)
        payload.setdefault("caseId", case_id)
        return payload


def _insert_stale_calibration(database_url: str) -> None:
    """A real device calibration row whose fingerprints no longer match.

    This is the review's divergence reproducer: once DB calibration history exists,
    ``resolve_speaker_calibration`` refuses to fall back to env values, so a STALE
    lifecycle state resolves to ``MODEL_BASELINE`` with ``margin=None``.
    """
    engine = make_engine(database_url)
    try:
        factory = make_session_factory(engine)
        with factory() as db:
            calibration_repo.create_calibration(
                db,
                status_at_creation="VALID",
                threshold=0.55,
                margin=0.09,
                far=0.01,
                frr=0.02,
                eer=0.015,
                eer_threshold=0.55,
                eer_far=0.01,
                eer_frr=0.02,
                genuine_trial_count=40,
                impostor_trial_count=40,
                officer_count=3,
                sample_count=9,
                corpus_digest="stale-corpus",
                algorithm_version="speaker-calibration-v1",
                speaker_backend_key="eres2net_large",
                speaker_model_id="eres2net_large",
                speaker_model_version="retired-model",
                speaker_model_fingerprint="f" * 64,
                audio_source="ALSA",
                microphone_id="retired-mic",
                microphone_name="retired mic",
                microphone_fingerprint="e" * 64,
                microphone_fingerprint_certainty="HIGH",
            )
            db.commit()
    finally:
        engine.dispose()


def _app(tmp_path: Path, monkeypatch, supervisor, *, db_name: str = "degradation-api.sqlite3"):
    """App whose lifespan builds the given supervisor (the real one owns the margins)."""
    monkeypatch.setattr("app.main._build_supervisor", lambda: supervisor)
    app = create_app(
        database_url=f"sqlite:///{tmp_path / db_name}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    app.state.speech_client = FakeSpeechClient()
    app.state.voiceprint_capture = FakeCaptureService()
    return app


def _calibrated(
    margin: float | None,
    threshold: float | None = 0.372,
    *,
    verification_source: str = VERIFICATION_DEVICE_CALIBRATION,
) -> SpeakerModeConfig:
    return SpeakerModeConfig(
        margin=margin,
        threshold=threshold,
        threshold_source="DEVICE_CALIBRATED" if threshold is not None else "MODEL_BASELINE",
        verification_source=verification_source,
    )


def _bound_case(tmp_path: Path, name: str):
    """Case with an enrolled suspect + interrogator officer bound to an active session."""
    engine = make_engine(f"sqlite:///{tmp_path / name}")
    init_database(engine)
    db = Session(engine)
    db.add(Case(id="CASE-1", officer_name="测试警官"))
    db.commit()
    service = VoiceprintService(db, speech_client=FakeSpeechClient())
    service.enroll_suspect("CASE-1", pcm16(), actor_id="op")
    service.speech_client = FakeSpeechClient()
    service.enroll_officer("P-001", "主审张警官", pcm16(), actor_id="admin")
    session_repo.create(db, "CASE-1")
    db.commit()
    service.bind_roles("CASE-1", "P-001", None, actor_id="op")
    return engine, db


def test_readiness_is_unverified_when_the_live_capture_status_cannot_be_read(tmp_path: Path, monkeypatch):
    """A capture whose status raised may be running on a frozen snapshot.

    The device resolver then describes the *next* capture, not the running one, so the
    answer must be "unverified" rather than an authoritative "not degraded".
    """
    monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", "0.55")
    monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", "0.08")
    app = _app(tmp_path, monkeypatch, FakeSupervisor(margin=0.08), db_name="status-failure.sqlite3")

    class ExplodingStatus:
        def status(self, case_id: str):
            raise RuntimeError("simulated capture status failure")

    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        app.state.asr_capture_service = ExplodingStatus()
        data = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    assert data["recognitionModeVerified"] is False
    assert data["recognitionModeVerificationSource"] == "UNVERIFIED"
    assert data["effectiveRecognitionMode"] is None
    assert data["recognitionModeDegraded"] is None
    # The resolver still ran, so the values it produced are shown as information only.
    assert data["speakerMargin"] == 0.08
    assert data["thresholdSource"] == "LEGACY_ENV"


# --- contract: readiness vs a real runtime capture, per device state ------------


@pytest.mark.parametrize(
    ("state", "env", "stale_db_calibration", "expected_mode", "expected_role"),
    [
        ("margin_present", (0.55, 0.08), False, SUSPECT_PLUS_INTERROGATOR, SpeakerRole.INTERROGATOR),
        ("no_margin", None, False, SUSPECT_ONLY, SpeakerRole.SUSPECT),
        ("stale_db_hides_the_env_margin", (0.55, 0.08), True, SUSPECT_ONLY, SpeakerRole.SUSPECT),
    ],
)
def test_readiness_and_a_real_capture_start_agree_for_each_device_state(
    tmp_path: Path,
    monkeypatch,
    state: str,
    env: tuple[float, float] | None,
    stale_db_calibration: bool,
    expected_mode: str,
    expected_role: SpeakerRole,
):
    """The two sides are driven independently, from one device state.

    * readiness is resolved by the route through the runtime's own calibration
      resolver (``app.state.speaker_calibration_resolver_factory``);
    * the runtime side is a real ``AsrCaptureService.start()`` plus the decision that
      operating point produces for a clear interrogator win.

    The supervisor deliberately advertises a margin in every case, so a test that fed
    both sides the supervisor's numbers would pass while the product still lied.
    """
    if env is None:
        monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
        monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    else:
        monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", str(env[0]))
        monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", str(env[1]))

    db_name = f"contract-{state}.sqlite3"
    database_url = f"sqlite:///{tmp_path / db_name}"
    supervisor = FakeSupervisor(margin=0.08)
    app = _app(tmp_path, monkeypatch, supervisor, db_name=db_name)
    if stale_db_calibration:
        _insert_stale_calibration(database_url)

    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        readiness = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    runtime = AsrCaptureService(
        session_factory=app.state.session_factory,
        device_manager=FakeDeviceManager(),
        ai_supervisor=supervisor,
        publish_event=lambda *_args: None,
        calibration_resolver=app.state.speaker_calibration_resolver_factory("ALSA"),
        read_timeout=0.01,
    )
    started = runtime.start(case_id)
    try:
        assert started["speakerMargin"] == readiness["speakerMargin"], (
            f"{state}: readiness and the runtime resolved different margins"
        )
        assert started["speakerThreshold"] == readiness["speakerThreshold"]
        assert started["thresholdSource"] == readiness["thresholdSource"]
        assert started["effectiveRecognitionMode"] == readiness["effectiveRecognitionMode"]
        assert started["recognitionModeDegraded"] == readiness["recognitionModeDegraded"]
        assert readiness["recognitionModeVerified"] is True

        role = runtime._decide_with_operating_point(
            candidates=[
                {"role": SpeakerRole.SUSPECT, "score": 0.60, "speaker_id": "s", "speaker_name": "张某"},
                {
                    "role": SpeakerRole.INTERROGATOR,
                    "score": 0.95,
                    "speaker_id": "P-001",
                    "speaker_name": "主审张警官",
                },
            ],
            enabled_roles={SpeakerRole.SUSPECT, SpeakerRole.INTERROGATOR},
            threshold=started["speakerThreshold"],
            margin=started["speakerMargin"],
            usable_duration_ms=1200,
            overlap=False,
        ).role
    finally:
        runtime.stop(case_id)

    assert readiness["effectiveRecognitionMode"] == expected_mode
    assert role is expected_role
    assert supervisor.speaker_margin == 0.08  # an unproven margin that must be ignored


def test_readiness_and_runtime_both_degrade_when_margin_is_missing(tmp_path: Path):
    engine, db = _bound_case(tmp_path, "readiness-degradation.sqlite3")
    try:
        service = VoiceprintService(db, speech_client=FakeSpeechClient())

        uncalibrated = service.readiness("CASE-1", speaker_mode=_calibrated(margin=None))
        assert uncalibrated["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert uncalibrated["effectiveRecognitionMode"] == SUSPECT_ONLY
        assert uncalibrated["recognitionModeDegraded"] is True
        assert uncalibrated["recognitionModeDegradedReason"] == DEGRADED_REASON_MARGIN_CALIBRATION_MISSING

        # Task 17B-1 rework: the threshold is informational. A missing threshold must
        # NOT be reported as a degradation the runtime does not perform.
        missing_threshold = service.readiness("CASE-1", speaker_mode=_calibrated(0.08, threshold=None))
        assert missing_threshold["effectiveRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert missing_threshold["recognitionModeDegraded"] is False
        assert missing_threshold["recognitionModeDegradedReason"] is None
        assert missing_threshold["thresholdConfigured"] is False

        calibrated = service.readiness("CASE-1", speaker_mode=_calibrated(0.08))
        assert calibrated["effectiveRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert calibrated["recognitionModeDegraded"] is False
        assert calibrated["recognitionModeDegradedReason"] is None

        # The declaration the operator sees is never rewritten by the degradation.
        assert uncalibrated["recognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    finally:
        db.close()
        engine.dispose()


# --- readiness incremental fields -----------------------------------------------


def test_readiness_exposes_suspect_enrollment_metrics(tmp_path: Path):
    engine, db = _bound_case(tmp_path, "metrics.sqlite3")
    try:
        readiness = VoiceprintService(db, speech_client=FakeSpeechClient()).readiness("CASE-1")
        assert readiness["enrollmentQuality"] == "GOOD"
        assert readiness["usableDurationMs"] == 60000
        assert readiness["modelKey"] == "eres2net_large"
        assert readiness["modelId"] == "eres2net_large"
        assert readiness["modelVersion"] == "17b1-test"
    finally:
        db.close()
        engine.dispose()


def test_readiness_without_a_suspect_row_reports_none_metrics_instead_of_failing(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'no-suspect.sqlite3'}")
    init_database(engine)
    db = Session(engine)
    try:
        db.add(Case(id="CASE-1", officer_name="测试警官"))
        db.commit()
        readiness = VoiceprintService(db, speech_client=FakeSpeechClient()).readiness(
            "CASE-1",
            speaker_mode=SpeakerModeConfig(
                margin=None,
                threshold=None,
                threshold_source=None,
                verification_source=VERIFICATION_DEVICE_CALIBRATION,
            ),
        )
        assert readiness["suspectReady"] is False
        assert readiness["enrollmentQuality"] is None
        assert readiness["usableDurationMs"] is None
        assert readiness["modelKey"] is None
        assert readiness["modelId"] is None
        assert readiness["modelVersion"] is None
        assert readiness["speakerMargin"] is None
        assert readiness["speakerThreshold"] is None
        assert readiness["thresholdSource"] is None
        assert readiness["marginConfigured"] is False
        assert readiness["thresholdConfigured"] is False
        assert readiness["effectiveRecognitionMode"] == SUSPECT_ONLY
        assert readiness["recognitionModeDegraded"] is False
        assert readiness["recognitionModeDegradedReason"] is None
    finally:
        db.close()
        engine.dispose()


def test_readiness_without_runtime_config_reports_an_unverified_mode(tmp_path: Path):
    """No injection (e.g. the enrollment-start guard) must not claim a mode.

    ``VoiceprintService.readiness`` without a resolved operating point knows the
    declaration only. Reporting the declaration as effective *and* "not degraded"
    is exactly the silent lie this task removes, so both fields are ``None`` and
    ``recognitionModeVerified`` is ``False``.
    """
    engine, db = _bound_case(tmp_path, "no-config.sqlite3")
    try:
        readiness = VoiceprintService(db, speech_client=FakeSpeechClient()).readiness("CASE-1")
        assert readiness["speakerMargin"] is None
        assert readiness["recognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert readiness["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
        assert readiness["effectiveRecognitionMode"] is None
        assert readiness["recognitionModeDegraded"] is None
        assert readiness["recognitionModeDegradedReason"] is None
        assert readiness["recognitionModeVerified"] is False
        assert readiness["recognitionModeVerificationSource"] == "UNVERIFIED"
    finally:
        db.close()
        engine.dispose()


# --- API injection: runtime speaker config reaches the service layer ------------


def _payload(response):
    body = response.json()
    assert body["ok"] is True, body
    return body["data"]


def _bind_interrogator(client: TestClient) -> str:
    created = _payload(client.post("/api/v1/cases", json={"operator_id": "op", "suspectName": "测试对象"}))
    case_id = created["id"]
    _payload(client.post("/api/v1/identity/confirm", json={
        "case_id": case_id,
        "actor_id": "op",
        "name": "测试对象",
        "id_number": "320101199001010099",
        "source": "MANUAL",
    }))
    _payload(client.post(
        f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/start",
        json={"actor_id": "op"},
    ))
    _payload(client.post(
        f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/stop",
        json={"actor_id": "op"},
    ))
    _payload(client.post(
        "/api/v1/officer-voiceprints/P-001/enrollment/start",
        json={"officer_name": "主审张警官", "actor_id": "admin"},
    ))
    _payload(client.post(
        "/api/v1/officer-voiceprints/P-001/enrollment/stop",
        json={"actor_id": "admin"},
    ))
    _payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op"}))
    _payload(client.put(f"/api/v1/cases/{case_id}/voiceprints/assignments", json={
        "interrogator_officer_id": "P-001",
        "recorder_officer_id": None,
        "actor_id": "op",
    }))
    return case_id


def test_readiness_endpoint_reports_degradation_when_the_device_has_no_margin(tmp_path: Path, monkeypatch):
    """No env margin and no DB calibration anywhere -> the runtime degrades."""
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    app = _app(tmp_path, monkeypatch, FakeSupervisor(margin=None))
    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        data = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    # The UI declaration still reflects the officer binding ...
    assert data["recognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["interrogatorReady"] is True
    # ... while the effective mode is the one the runtime will really enforce.
    assert data["effectiveRecognitionMode"] == SUSPECT_ONLY
    assert data["recognitionModeDegraded"] is True
    assert data["recognitionModeDegradedReason"] == DEGRADED_REASON_MARGIN_CALIBRATION_MISSING
    assert data["marginConfigured"] is False
    assert data["thresholdConfigured"] is True
    assert data["speakerThreshold"] == MODEL_BASELINE_THRESHOLD
    assert data["speakerMargin"] is None
    # The threshold provenance is informational and reported verbatim.
    assert data["thresholdSource"] == "MODEL_BASELINE"
    # The operating point came from the same resolver the runtime starts with.
    assert data["recognitionModeVerified"] is True
    assert data["recognitionModeVerificationSource"] == "DEVICE_CALIBRATION"
    # Enrollment metrics reach the condensed card from the same payload.
    assert data["enrollmentQuality"] == "GOOD"
    assert data["usableDurationMs"] == 60000
    assert data["modelKey"] == "eres2net_large"


def test_readiness_endpoint_reports_the_calibrated_mode_without_degradation(tmp_path: Path, monkeypatch):
    """A real device margin (through the runtime resolver's legacy-env fallback)."""
    monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", "0.55")
    monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", "0.08")
    app = _app(tmp_path, monkeypatch, FakeSupervisor(margin=0.08))
    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        data = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    assert data["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["effectiveRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["recognitionModeDegraded"] is False
    assert data["recognitionModeDegradedReason"] is None
    assert data["marginConfigured"] is True
    assert data["speakerMargin"] == 0.08
    assert data["speakerThreshold"] == 0.55
    assert data["thresholdSource"] == "LEGACY_ENV"
    assert data["recognitionModeVerified"] is True


# --- B1 regression: the readiness route must ask the capture service by case -----


def test_readiness_route_passes_the_case_id_to_the_capture_service_status(tmp_path: Path, monkeypatch):
    """``status(case_id)`` has no default argument in production.

    ``SourceAwareAsrCaptureService.status`` requires the case id; calling it without
    one raises ``TypeError``. The route used to swallow that exception and silently
    fall back to the supervisor, so the live operating point was never reachable.
    """
    app = _app(tmp_path, monkeypatch, FakeSupervisor(margin=0.08))
    capture = CaseIdOnlyCaptureService(
        {
            "caseId": "ignored",
            "active": True,
            "status": "CAPTURING",
            "speakerThreshold": 0.372,
            "thresholdSource": "MODEL_BASELINE",
            "speakerMargin": 0.051,
            "speakerMarginConfigured": True,
            "calibrationId": "CAL-1",
            "calibrationStatus": "VALID",
        }
    )
    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        app.state.asr_capture_service = capture
        data = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    # The case id must travel: a no-argument call raises TypeError.
    assert capture.calls == [case_id]
    # ... and the live operating point must win over the supervisor's margin.
    assert data["speakerMargin"] == 0.051
    assert data["marginConfigured"] is True
    assert data["speakerThreshold"] == 0.372
    assert data["effectiveRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["recognitionModeDegraded"] is False
    assert data["recognitionModeVerified"] is True
    assert data["recognitionModeVerificationSource"] == "LIVE_CAPTURE"


# --- honest "unverified": no live capture and no device calibration --------------


def test_readiness_is_unverified_when_no_capture_and_no_device_calibration(tmp_path: Path, monkeypatch):
    """A supervisor margin alone is not the runtime's operating point.

    With no capture running and no device-calibration resolver the route must say
    "unverified" instead of reporting the supervisor's margin as "not degraded".
    """
    app = _app(tmp_path, monkeypatch, FakeSupervisor(margin=0.08))
    capture = CaseIdOnlyCaptureService({"active": False, "status": "IDLE"})
    with TestClient(app) as client:
        case_id = _bind_interrogator(client)
        app.state.asr_capture_service = capture
        app.state.speaker_calibration_resolver_factory = None
        data = _payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))

    assert capture.calls == [case_id]
    assert data["recognitionModeVerified"] is False
    assert data["recognitionModeVerificationSource"] == "UNVERIFIED"
    # Neither the mode nor the degradation may be claimed ...
    assert data["effectiveRecognitionMode"] is None
    assert data["recognitionModeDegraded"] is None
    assert data["recognitionModeDegradedReason"] is None
    # ... while the declaration and the raw (unverified) values stay visible.
    assert data["recognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["declaredRecognitionMode"] == SUSPECT_PLUS_INTERROGATOR
    assert data["speakerMargin"] == 0.08
    assert data["marginConfigured"] is True

