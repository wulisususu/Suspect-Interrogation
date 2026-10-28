import struct

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database.models import InterrogationSession, SessionVoiceAssignment
from app.domain.errors import DomainError
from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


SAMPLE_RATE = 16000
GOOD_SEGMENTS = [[0, 20000], [21000, 41000], [42000, 62000]]
GOOD_EMBEDDINGS = [
    [1.0, 0.0, 0.0],
    [0.99, 0.1, 0.0],
    [0.98, -0.1, 0.0],
]


def payload(response):
    body = response.json()
    assert body["ok"] is True, body
    assert body["code"] == "OK"
    return body["data"]


def pcm16(duration_ms: int = 62000, sample: int = 1200) -> bytes:
    samples = duration_ms * SAMPLE_RATE // 1000
    return struct.pack(f"<{samples}h", *([sample] * samples))


class FakeSpeechClient:
    def __init__(self):
        self.embedding_calls = 0

    def speech_segments(self, pcm: bytes, sample_rate: int = SAMPLE_RATE):
        assert pcm
        assert sample_rate == SAMPLE_RATE
        return [list(item) for item in GOOD_SEGMENTS]

    def extract_embedding(self, pcm: bytes, sample_rate: int = SAMPLE_RATE):
        assert pcm
        assert sample_rate == SAMPLE_RATE
        vector = GOOD_EMBEDDINGS[self.embedding_calls % len(GOOD_EMBEDDINGS)]
        self.embedding_calls += 1
        return {"embedding": vector, "backend_key": "eres2net_large", "model_id": "eres2net_large", "model_version": "api-test"}


class FakeCaptureService:
    def __init__(self):
        self.active: tuple[str, str] | None = None

    def start(self, kind: str, subject_id: str, source: str = "ALSA"):
        if self.active is not None:
            raise DomainError(
                "RESOURCE_BUSY",
                "已有声纹录音正在进行",
                409,
                data={"kind": self.active[0], "subjectId": self.active[1]},
            )
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
        if self.active != (kind, subject_id):
            raise DomainError("CAPTURE_SUBJECT_MISMATCH", "当前声纹录音对象不匹配", 409)
        self.active = None
        return pcm16()

    def status(self):
        if self.active is None:
            return {"active": False}
        return {"active": True, "kind": self.active[0], "subjectId": self.active[1]}


def app_with_voiceprint_fakes(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'voiceprint-api.sqlite3'}",
        hardware_gateway=MockHardwareGateway(simulated=False),
    )
    app.state.speech_client = FakeSpeechClient()
    app.state.voiceprint_capture = FakeCaptureService()
    return app


def create_identity_ready_case(client: TestClient, *, operator_id: str = "op") -> str:
    created = payload(client.post("/api/v1/cases", json={"operator_id": operator_id, "suspectName": "测试对象"}))
    case_id = created["id"]
    payload(client.post("/api/v1/identity/confirm", json={
        "case_id": case_id,
        "actor_id": operator_id,
        "name": "测试对象",
        "id_number": "320101199001010099",
        "source": "MANUAL",
    }))
    return case_id


def enroll_suspect(client: TestClient, case_id: str, *, actor_id: str = "op"):
    started = payload(client.post(
        f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/start",
        json={"actor_id": actor_id},
    ))
    assert started["active"] is True
    enrolled = payload(client.post(
        f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/stop",
        json={"actor_id": actor_id},
    ))
    assert enrolled["ready"] is True
    return enrolled


def test_enrollment_status_exposes_active_capture_for_progress_ui(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)
        payload(client.post(
            f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/start",
            json={"actor_id": "op"},
        ))

        status = payload(client.get("/api/v1/voiceprints/enrollment/status"))

    assert status == {"active": True, "kind": "suspect", "subjectId": case_id}


def enroll_officer(client: TestClient, officer_id: str, officer_name: str, *, actor_id: str = "admin"):
    started = payload(client.post(
        f"/api/v1/officer-voiceprints/{officer_id}/enrollment/start",
        json={"officer_name": officer_name, "actor_id": actor_id},
    ))
    assert started["active"] is True
    enrolled = payload(client.post(
        f"/api/v1/officer-voiceprints/{officer_id}/enrollment/stop",
        json={"actor_id": actor_id},
    ))
    assert enrolled["officerId"] == officer_id
    assert enrolled["officerName"] == officer_name
    return enrolled


def test_suspect_enrollment_changes_readiness_and_allows_session_start(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)

        before = payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))
        # Task 17B-1 extended readiness with speaker-mode/degradation fields; the
        # pre-existing startability contract is asserted unchanged.
        assert {
            name: before[name]
            for name in (
                "selectedSpeakerBackend",
                "authoritativeSpeakerBackend",
                "suspectReady",
                "interrogatorReady",
                "recorderReady",
                "recognitionMode",
                "canStart",
            )
        } == {
            "selectedSpeakerBackend": "eres2net_large",
            "authoritativeSpeakerBackend": "eres2net_large",
            "suspectReady": False,
            "interrogatorReady": False,
            "recorderReady": False,
            "recognitionMode": "SUSPECT_ONLY",
            "canStart": False,
        }

        enrolled = enroll_suspect(client, case_id)
        assert enrolled["usableDurationMs"] == 60000
        assert enrolled["embeddingDim"] == 3

        after = payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))
        assert after["suspectReady"] is True
        assert after["canStart"] is True
        assert after["recognitionMode"] == "SUSPECT_ONLY"

        session = payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op"}))
        assert session["status"] == "RUNNING"


def test_officer_library_and_full_role_assignment_api(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)
        enroll_suspect(client, case_id)
        officer = enroll_officer(client, "P-001", "张警官")
        assert officer["active"] is True

        listed = payload(client.get("/api/v1/officer-voiceprints"))
        assert len(listed) == 1
        assert listed[0]["officerId"] == "P-001"

        started = payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={"actor_id": "op"}))
        assert started["status"] == "RUNNING"
        readiness = payload(client.put(f"/api/v1/cases/{case_id}/voiceprints/assignments", json={
            "interrogator_officer_id": "P-001",
            "recorder_officer_id": "P-001",
            "actor_id": "op",
        }))
        assert readiness["suspectReady"] is True
        assert readiness["interrogatorReady"] is True
        assert readiness["recorderReady"] is True
        assert readiness["recognitionMode"] == "FULL"
        assert readiness["roleBindingScope"] == "ACTIVE_SESSION"

        # 定稿校验与签署只在审讯结束后才看得到，那时已经没有 active session。
        # 角色绑定必须仍能被读到，并明确标为"本场审讯"的绑定。
        finished = payload(client.post(f"/api/v1/cases/{case_id}/session/finish", json={"actor_id": "op"}))
        assert finished["status"] == "COMPLETED"
        after_end = payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/readiness"))
        assert after_end["roleBindingScope"] == "LAST_SESSION"
        assert after_end["roleBindingSessionId"] == started["id"]
        assert after_end["interrogatorReady"] is True
        assert after_end["recorderReady"] is True
        assert after_end["recognitionMode"] == "FULL"

        revoked = payload(client.delete("/api/v1/officer-voiceprints/P-001?actor_id=admin"))
        assert revoked["active"] is False


def test_case_voice_role_draft_survives_reload_before_session_start(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)
        officer = enroll_officer(client, "P-001", "张警官")
        assert officer["active"] is True

        initial = payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/role-draft"))
        assert initial == {
            "caseId": case_id,
            "interrogatorOfficerId": None,
            "recorderOfficerId": None,
        }

        saved = payload(client.put(f"/api/v1/cases/{case_id}/voiceprints/role-draft", json={
            "interrogator_officer_id": "P-001",
            "recorder_officer_id": None,
            "actor_id": "op",
        }))
        assert saved == {
            "caseId": case_id,
            "interrogatorOfficerId": "P-001",
            "recorderOfficerId": None,
        }

        reloaded = payload(client.get(f"/api/v1/cases/{case_id}/voiceprints/role-draft"))
        assert reloaded == saved


def test_session_start_binds_voiceprint_roles_atomically(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)
        enroll_suspect(client, case_id)

        blocked = client.post(f"/api/v1/cases/{case_id}/session/start", json={
            "actor_id": "op",
            "interrogator_officer_id": "P-MISSING",
        })
        assert blocked.status_code == 404
        assert blocked.json()["code"] == "OFFICER_VOICEPRINT_NOT_FOUND"
        assert payload(client.get(f"/api/v1/cases/{case_id}"))["workflowState"] == "IDENTITY_READY"

        with app.state.session_factory() as db:
            assert db.scalar(select(InterrogationSession).where(InterrogationSession.case_id == case_id)) is None
            assert db.scalar(select(SessionVoiceAssignment).join(InterrogationSession).where(InterrogationSession.case_id == case_id)) is None

        enrolled_officer = enroll_officer(client, "P-001", "张警官")
        assert enrolled_officer["active"] is True
        started = payload(client.post(f"/api/v1/cases/{case_id}/session/start", json={
            "actor_id": "op",
            "interrogator_officer_id": "P-001",
        }))
        assert started["status"] == "RUNNING"

        with app.state.session_factory() as db:
            session = db.scalar(select(InterrogationSession).where(InterrogationSession.case_id == case_id))
            assignment = db.scalar(select(SessionVoiceAssignment).where(SessionVoiceAssignment.session_id == session.id))
            assert assignment is not None
            assert assignment.interrogator_officer_id == "P-001"
            assert assignment.recorder_officer_id is None
            assert assignment.recognition_mode == "SUSPECT_PLUS_INTERROGATOR"


def test_concurrent_voiceprint_enrollment_returns_resource_busy(tmp_path):
    app = app_with_voiceprint_fakes(tmp_path)
    with TestClient(app) as client:
        case_id = create_identity_ready_case(client)
        first = payload(client.post(
            f"/api/v1/cases/{case_id}/voiceprints/suspect/enrollment/start",
            json={"actor_id": "op"},
        ))
        assert first["active"] is True

        blocked = client.post(
            "/api/v1/officer-voiceprints/P-002/enrollment/start",
            json={"officer_name": "李警官", "actor_id": "admin"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["code"] == "RESOURCE_BUSY"
