from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


def ok(response):
    body = response.json()
    assert body["ok"] is True, body
    return body["data"]


def create_running_case(client, app, enroll_test_suspect_voiceprint):
    case = ok(client.post("/api/v1/cases", json={"operator_id": "op-ws"}))
    ok(client.post("/api/v1/identity/read", json={"case_id": case["id"]}))
    enroll_test_suspect_voiceprint(app, case["id"])
    session = ok(client.post(f"/api/v1/cases/{case['id']}/session/start", json={}))
    return case["id"], session["id"]


def test_websocket_initial_sync_rejects_retired_mock_ai_event(tmp_path, enroll_test_suspect_voiceprint):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'ws.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    assert not hasattr(app.state, "ai_gateway")
    with TestClient(app) as client:
        case_id, session_id = create_running_case(client, app, enroll_test_suspect_voiceprint)
        with client.websocket_connect(f"/ws/interrogation/{session_id}") as ws:
            first = ws.receive_json()
            assert first["session_id"] == session_id
            assert first["event"] == "STATE_SYNC"
            assert first["seq"] >= 1
            assert first["timestamp"].endswith("+00:00")
            assert first["payload"]["case_id"] == case_id
            assert first["payload"]["session"]["state"] == "QUESTIONING"

            ws.send_json({"session_id": session_id, "event": "USER_TEXT", "seq": 1, "timestamp": "2026-08-26T00:00:00+00:00", "payload": {"text": "  测试   问题  "}})
            error = ws.receive_json()
            assert error["event"] == "PROTOCOL_ERROR"
            assert error["payload"]["code"] == "INVALID_WEBSOCKET_ENVELOPE"

            ws.send_json({"payload": {}})
            error = ws.receive_json()
            assert error["event"] == "PROTOCOL_ERROR"
            assert error["payload"]["code"] == "INVALID_WEBSOCKET_ENVELOPE"


def test_websocket_reconnect_sync_comes_from_persisted_database(tmp_path, enroll_test_suspect_voiceprint):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'reconnect.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as client:
        case_id, session_id = create_running_case(client, app, enroll_test_suspect_voiceprint)
        with client.websocket_connect(f"/ws/interrogation/{session_id}") as ws:
            assert ws.receive_json()["payload"]["session"]["state"] == "QUESTIONING"

        ok(client.post(f"/api/v1/cases/{case_id}/session/pause", json={}))

        with client.websocket_connect(f"/ws/interrogation/{session_id}") as ws:
            sync = ws.receive_json()
            assert sync["event"] == "STATE_SYNC"
            assert sync["payload"]["session"]["status"] == "PAUSED"
            assert sync["payload"]["session"]["state"] == "PAUSED"
            ws.send_json({"session_id": session_id, "event": "STATE_SYNC_REQUEST", "seq": 9, "timestamp": "2026-08-26T00:00:00+00:00", "payload": {}})
            requested = ws.receive_json()
            assert requested["event"] == "STATE_SYNC"
            assert requested["payload"]["session"]["state"] == "PAUSED"


def test_envelope_carries_process_epoch_and_tolerates_legacy_resync(tmp_path, enroll_test_suspect_voiceprint):
    """旧前端重连只发 {event, payload}，不能因此换回 PROTOCOL_ERROR。

    seq 只存在于 ConnectionManager 内存里，进程重启后从 1 重新计数；客户端必须
    能通过 epoch 判断"换代"，否则重启后的实时消息会被当成旧消息丢弃。
    """
    app = create_app(database_url=f"sqlite:///{tmp_path / 'epoch.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as client:
        case_id, session_id = create_running_case(client, app, enroll_test_suspect_voiceprint)
        with client.websocket_connect(f"/ws/interrogation/{session_id}") as ws:
            first = ws.receive_json()
            assert first["event"] == "STATE_SYNC"
            assert isinstance(first["epoch"], str) and first["epoch"]

            # 旧前端格式：没有 session_id / seq / timestamp 信封字段
            ws.send_json({"event": "SESSION_RESYNC", "payload": {"session_id": session_id, "last_seq": 0}})
            sync = ws.receive_json()
            assert sync["event"] == "STATE_SYNC"
            assert sync["epoch"] == first["epoch"]
            assert sync["payload"]["case_id"] == case_id


def test_session_state_is_pushed_to_connected_views(tmp_path, enroll_test_suspect_voiceprint):
    """别的终端暂停审讯后，已连接的视图必须收到 SESSION_STATE，而不是只能刷新。"""
    app = create_app(database_url=f"sqlite:///{tmp_path / 'push.db'}", hardware_gateway=MockHardwareGateway(simulated=True))
    with TestClient(app) as client:
        case_id, session_id = create_running_case(client, app, enroll_test_suspect_voiceprint)
        with client.websocket_connect(f"/ws/interrogation/{session_id}") as ws:
            assert ws.receive_json()["event"] == "STATE_SYNC"

            ok(client.post(f"/api/v1/cases/{case_id}/session/pause", json={"actor_id": "OFFICER-7"}))
            pushed = ws.receive_json()
            assert pushed["event"] == "SESSION_STATE"
            assert pushed["session_id"] == session_id
            assert pushed["payload"]["status"] == "PAUSED"

            ok(client.post(f"/api/v1/cases/{case_id}/session/resume", json={}))
            resumed = ws.receive_json()
            assert resumed["event"] == "SESSION_STATE"
            assert resumed["payload"]["status"] == "RUNNING"
