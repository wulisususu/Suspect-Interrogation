from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


def data(response):
    body = response.json()
    assert body["ok"] is True, body
    return body["data"]


def test_backend_dev_smoke_contract_is_preserved(tmp_path, enroll_test_suspect_voiceprint):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'legacy.db'}", hardware_gateway=MockHardwareGateway(simulated=False))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

        created = data(client.post("/api/cases/create", json={"suspectName": "测试对象", "officerName": "测试警官"}))
        case_id = created["id"]
        enroll_test_suspect_voiceprint(app, case_id)

        # The legacy route no longer bypasses identity confirmation.
        refused = client.post(f"/api/cases/{case_id}/session/start", json={})
        assert refused.status_code == 409
        assert refused.json()["code"] == "IDENTITY_REQUIRED"
        data(client.post("/api/v1/identity/confirm", json={"case_id": case_id, "name": "测试对象"}))
        session = data(client.post(f"/api/cases/{case_id}/session/start", json={}))
        assert session["status"] == "RUNNING"

        message = data(client.post(f"/work/case/{case_id}/message", json={"profile": {"text": "你叫什么名字？", "from": "民警"}}))
        message_id = message["id"]

        revised = data(client.put(f"/api/cases/{case_id}/messages/{message_id}", json={"text": "请说明你的姓名。", "reason": "联调修订"}))
        assert revised["id"] == message_id
        assert revised["text"] == "请说明你的姓名。"

        revisions = data(client.get(f"/api/cases/{case_id}/messages/{message_id}/revisions"))
        assert len(revisions) == 1

        marked = data(client.post(f"/api/cases/{case_id}/messages/{message_id}/mark", json={"mark": "conflict"}))
        assert marked["mark"] == "conflict"

        assert data(client.post(f"/api/cases/{case_id}/session/pause", json={}))["status"] == "PAUSED"
        assert data(client.post(f"/api/cases/{case_id}/session/resume", json={}))["status"] == "RUNNING"
        assert data(client.post(f"/api/cases/{case_id}/session/stage", json={"stage": "STATEMENT"}))["stage"] == "STATEMENT"

        device = client.post("/api/device/action", json={"type": "identity"})
        assert device.status_code == 409
        assert device.json()["code"] == "DEVICE_NOT_CONNECTED"

        finished = data(client.post(f"/api/cases/{case_id}/session/finish", json={}))
        assert finished["status"] == "COMPLETED"

        audit = data(client.get(f"/api/cases/{case_id}/audit"))
        assert len(audit) >= 6
        assert not any(x["action"] == "IDENTITY_BYPASS_LEGACY_COMPAT" for x in audit)
        assert any(x["action"] == "IDENTITY_CONFIRM" for x in audit)

        assert client.get("/api/ai/settings").status_code == 404
        assert client.get(f"/work/case/{case_id}/session/message/inquiry", params={"message": "测试"}).status_code == 404
