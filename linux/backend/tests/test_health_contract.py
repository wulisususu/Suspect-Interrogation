from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_liveness_is_process_only():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_required_checks_and_capabilities():
    response = client.get("/health/ready")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ready", "degraded"}
    assert set(payload["checks"]) >= {"storage", "database"}
    assert set(payload["capabilities"]) >= {
        "hardware",
        "ai",
        "asr",
        "vad",
        "speaker",
        "voiceprintCalibration",
        "audioCapture",
    }
    assert payload["checks"]["storage"]["required"] is True
    assert payload["checks"]["database"]["required"] is True
    assert payload["capabilities"]["hardware"]["required"] is False
    assert payload["capabilities"]["ai"]["required"] is False
    for name in ("asr", "vad", "speaker", "voiceprintCalibration", "audioCapture"):
        assert payload["capabilities"][name]["required"] is False


def test_voiceprint_calibration_health_is_fail_closed_until_both_values_exist(monkeypatch):
    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    missing = client.get("/health/ready").json()["capabilities"]["voiceprintCalibration"]
    assert missing["state"] == "NOT_CONFIGURED"

    monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", "0.73")
    monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", "0.08")
    calibrated = client.get("/health/ready").json()["capabilities"]["voiceprintCalibration"]
    assert calibrated["state"] == "READY"


class _StubRequest:
    """Request-less health probe: only ``app.state`` is consulted."""

    def __init__(self, state):
        self.app = SimpleNamespace(state=state)


def _stub_session_factory():
    """Borrowed-session stand-in: the runtime resolver takes a db handle."""

    from contextlib import contextmanager

    @contextmanager
    def _session():
        yield None

    return _session()


def test_voiceprint_calibration_is_unverified_without_a_runtime_resolver():
    """Task 17B-1: no runtime operating point -> "unverified", never READY.

    With neither a device-calibration resolver nor a supervisor-carrying runtime the
    capability must not be advertised as ready just because env values exist.
    """
    from app.health import readiness_snapshot

    calibration = readiness_snapshot(_StubRequest(SimpleNamespace()))["capabilities"][
        "voiceprintCalibration"
    ]

    assert calibration["state"] == "UNVERIFIED"
    assert calibration["verified"] is False
    assert calibration["verificationSource"] == "UNVERIFIED"


def test_voiceprint_calibration_reports_the_runtime_device_calibration(monkeypatch):
    """The same resolver the capture runtime starts with decides the capability."""
    from app.services.speaker_calibration_runtime import ResolvedSpeakerCalibration

    from app.health import readiness_snapshot

    resolved = ResolvedSpeakerCalibration(
        calibration_id="CAL-1",
        threshold=0.61,
        margin=0.07,
        source="DEVICE_CALIBRATED",
        status="VALID",
        speaker_model_fingerprint="a" * 64,
        microphone_fingerprint="b" * 64,
    )
    state = SimpleNamespace(
        speaker_calibration_resolver_factory=lambda source: (lambda db: resolved),
        session_factory=_stub_session_factory,
    )

    calibration = readiness_snapshot(_StubRequest(state))["capabilities"]["voiceprintCalibration"]

    assert calibration["state"] == "READY"
    assert calibration["verified"] is True
    assert calibration["verificationSource"] == "DEVICE_CALIBRATION"
    assert calibration["marginConfigured"] is True
    assert calibration["thresholdConfigured"] is True


def test_capabilities_recording_is_not_available_when_calibration_is_unverified():
    """The runtime capability contract must not advertise recording as AVAILABLE."""
    from app.health import runtime_capabilities

    class Supervisor:
        def capabilities(self):
            return {
                "asr": {"state": "AVAILABLE", "speech_worker": True, "speech_state": "AVAILABLE"},
                "vad": {"state": "AVAILABLE"},
                "speaker": {"state": "AVAILABLE"},
            }

    state = SimpleNamespace(ai_supervisor=Supervisor())

    recording = runtime_capabilities(_StubRequest(state))["recording"]

    assert recording["state"] == "UNVERIFIED"
    assert recording["metadata"]["calibration"]["state"] == "UNVERIFIED"
    assert recording["metadata"]["calibration"]["verified"] is False


def test_runtime_capabilities_endpoint_exposes_frontend_contract():
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "identity", "camera", "microphone", "fingerprint", "signature",
        "recording", "asr", "ocr", "llm", "report",
    }
    assert payload["microphone"]["state"] in {"AVAILABLE", "NOT_CONFIGURED", "ERROR"}
    assert payload["asr"]["state"] in {"AVAILABLE", "NOT_CONFIGURED", "ERROR", "MODEL_NOT_INSTALLED"}


def test_speech_capability_prefers_ready_worker_over_stopped_registry_worker():
    from app.health import _speech_capability

    class Supervisor:
        def capabilities(self):
            return {
                "asr": {
                    "state": "STOPPED",
                    "detail": "registry worker is idle",
                    "speech_worker": True,
                    "speech_state": "AVAILABLE",
                }
            }

    result = _speech_capability("asr", supervisor=Supervisor(), calibration={"state": "NOT_CONFIGURED"})
    assert result["state"] == "AVAILABLE"
    assert result["speech_state"] == "AVAILABLE"
