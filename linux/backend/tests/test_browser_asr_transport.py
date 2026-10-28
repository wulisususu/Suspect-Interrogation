from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect
import asyncio
import struct
import threading
import time

from app.services.browser_audio_input import BrowserAudioInput
from app.websocket.browser_asr import router


class FakeAsrCaptureService:
    def __init__(self, status_by_case: dict[str, dict[str, object]]):
        self.status_by_case = status_by_case
        self.frames = []
        self.incomplete = []
        self.completed = []

    def status(self, case_id: str) -> dict[str, object]:
        return dict(self.status_by_case.get(case_id, {"active": False}))

    def ingest_browser_frame(self, case_id, capture_id, sequence, start_sample, pcm):
        self.frames.append((case_id, capture_id, sequence, start_sample, bytes(pcm)))
        return {"ackSequence": sequence, "durableSampleEnd": start_sample + len(pcm) // 2}

    def mark_browser_capture_incomplete(self, case_id, capture_id, reason):
        self.incomplete.append((case_id, capture_id, reason))
        return True

    def complete_browser_capture_recovery(self, case_id, capture_id, next_sequence, next_sample):
        self.completed.append((case_id, capture_id, next_sequence, next_sample))
        return {
            "captureId": capture_id,
            "recordingStatus": "COMPLETE",
            "nextSequence": next_sequence,
            "nextSample": next_sample,
        }


def make_app(status_by_case: dict[str, dict[str, object]]) -> tuple[FastAPI, BrowserAudioInput]:
    app = FastAPI()
    browser_input = BrowserAudioInput()
    browser_input.start_record()
    app.state.browser_audio_input = browser_input
    app.state.asr_capture_service = FakeAsrCaptureService(status_by_case)
    app.include_router(router)
    return app, browser_input


def test_browser_asr_socket_accepts_only_the_active_browser_capture():
    app, browser_input = make_app({
        "CASE-A": {
            "active": True,
            "captureSessionId": "CAPTURE-A",
            "source": "BROWSER",
        },
    })
    pcm = b"\x01\x00" * 160

    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_bytes(struct.pack("<IQ", 1, 0) + pcm)
            assert websocket.receive_json() == {"ackSequence": 1, "durableSampleEnd": 160}

    assert app.state.asr_capture_service.frames == [("CASE-A", "CAPTURE-A", 1, 0, pcm)]
    assert browser_input.read_audio_frames(timeout=0.01) == b""


def test_formal_browser_socket_acks_only_the_durable_sequenced_frame():
    pcm = b"\x01\x00" * 160
    frame = struct.pack("<IQ", 1, 0) + pcm
    calls = []

    class DurableIngress:
        def ingest_browser_frame(self, case_id, capture_id, sequence, start_sample, payload):
            calls.append((case_id, capture_id, sequence, start_sample, payload))
            return {"ackSequence": sequence, "durableSampleEnd": start_sample + len(payload) // 2}

    app, browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.asr_capture_service.ingest_browser_frame = DurableIngress().ingest_browser_frame

    class FakeWebSocket:
        def __init__(self):
            self.app = app
            self.messages = [
                {"type": "websocket.receive", "bytes": frame},
                {"type": "websocket.disconnect"},
            ]
            self.sent_json = []
            self.closed = []

        async def accept(self):
            pass

        async def receive(self):
            return self.messages.pop(0)

        async def send_json(self, payload):
            self.sent_json.append(payload)

        async def close(self, code, reason=None):
            self.closed.append((code, reason))

    socket = FakeWebSocket()
    asyncio.run(router.routes[0].endpoint(socket, "CASE-A", "CAPTURE-A"))

    assert calls == [("CASE-A", "CAPTURE-A", 1, 0, pcm)]
    assert socket.sent_json == [{"ackSequence": 1, "durableSampleEnd": 160}]
    assert socket.closed == []


def test_formal_browser_socket_waits_for_durable_ingress_before_acknowledging():
    app, _browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    ingress_started = threading.Event()
    allow_commit = threading.Event()

    def blocking_ingress(case_id, capture_id, sequence, start_sample, pcm):
        ingress_started.set()
        assert allow_commit.wait(timeout=2)
        return {"ackSequence": sequence, "durableSampleEnd": start_sample + len(pcm) // 2}

    app.state.asr_capture_service.ingest_browser_frame = blocking_ingress
    pcm = b"\x01\x00" * 10
    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_bytes(struct.pack("<IQ", 1, 0) + pcm)
            received = []
            reader = threading.Thread(target=lambda: received.append(websocket.receive_json()))
            reader.start()
            assert ingress_started.wait(timeout=1)
            time.sleep(0.02)
            assert received == []
            allow_commit.set()
            reader.join(timeout=1)

    assert received == [{"ackSequence": 1, "durableSampleEnd": 10}]


def test_formal_browser_socket_marks_sequence_gaps_as_discontinuities():
    app, _browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })

    def reject_gap(_case_id, _capture_id, _sequence, _start_sample, _pcm):
        raise RuntimeError("formal browser frame sequence discontinuity")

    app.state.asr_capture_service.ingest_browser_frame = reject_gap
    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_bytes(struct.pack("<IQ", 2, 0) + b"\x01\x00")
            assert websocket.receive_json() == {
                "type": "capture_incomplete_ack",
                "captureId": "CAPTURE-A",
            }
            close = websocket.receive()

    assert close["type"] == "websocket.close"
    assert close["code"] == 4410


def test_formal_browser_socket_persists_client_incomplete_state():
    app, _browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    reason = "browser audio outbox capacity is exhausted"
    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_text('{"type":"capture_incomplete","reason":"browser audio outbox capacity is exhausted"}')
            assert websocket.receive_json() == {
                "type": "capture_incomplete_ack",
                "captureId": "CAPTURE-A",
            }
            close = websocket.receive()

    assert close["type"] == "websocket.close"
    assert close["code"] == 4410
    assert app.state.asr_capture_service.incomplete == [("CASE-A", "CAPTURE-A", reason)]


def test_formal_browser_socket_confirms_recovery_only_after_server_finalization():
    app, _browser_input = make_app({
        "CASE-A": {"active": False, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.live_speech_coordinator = type(
        "RecoveryCoordinator",
        (),
        {"has_browser_frame_receipt": lambda _self, _case_id, _capture_id: True},
    )()

    class FakeWebSocket:
        def __init__(self):
            self.app = app
            self.messages = [{
                "type": "websocket.receive",
                "text": '{"type":"capture_recovery_complete","nextSequence":3,"nextSample":160}',
            }]
            self.sent_json = []
            self.closed = []

        async def accept(self):
            pass

        async def receive(self):
            return self.messages.pop(0)

        async def send_json(self, payload):
            self.sent_json.append(payload)

        async def close(self, code, reason=None):
            self.closed.append((code, reason))

    socket = FakeWebSocket()
    asyncio.run(router.routes[0].endpoint(socket, "CASE-A", "CAPTURE-A"))

    assert app.state.asr_capture_service.completed == [("CASE-A", "CAPTURE-A", 3, 160)]
    assert socket.sent_json == [{
        "type": "capture_recovery_complete_ack",
        "captureId": "CAPTURE-A",
        "recordingStatus": "COMPLETE",
        "nextSequence": 3,
        "nextSample": 160,
    }]
    assert socket.closed == []


def test_formal_browser_socket_does_not_ack_an_unpersisted_incomplete_marker():
    app, _browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.asr_capture_service.mark_browser_capture_incomplete = lambda *_args: False

    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_text('{"type":"capture_incomplete","reason":"browser audio outbox capacity is exhausted"}')
            close = websocket.receive()

    assert close["type"] == "websocket.close"
    assert close["code"] == 4410


def test_incomplete_control_can_be_retried_after_ack_loss_and_incomplete_restart():
    app, _browser_input = make_app({
        "CASE-A": {"active": False, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.live_speech_coordinator = type(
        "RecoveryCoordinator",
        (),
        {"has_browser_frame_receipt": lambda _self, _case_id, _capture_id: True},
    )()

    class FakeWebSocket:
        def __init__(self):
            self.app = app
            self.messages = [{
                "type": "websocket.receive",
                "text": '{"type":"capture_incomplete","reason":"browser outbox failure"}',
            }]
            self.sent_json = []
            self.closed = []

        async def accept(self):
            pass

        async def receive(self):
            return self.messages.pop(0)

        async def send_json(self, payload):
            self.sent_json.append(payload)

        async def close(self, code, reason=None):
            self.closed.append((code, reason))

    sockets = [FakeWebSocket(), FakeWebSocket()]
    for socket in sockets:
        asyncio.run(router.routes[0].endpoint(socket, "CASE-A", "CAPTURE-A"))

    expected_ack = {"type": "capture_incomplete_ack", "captureId": "CAPTURE-A"}
    assert [socket.sent_json for socket in sockets] == [[expected_ack], [expected_ack]]
    assert app.state.asr_capture_service.incomplete == [
        ("CASE-A", "CAPTURE-A", "browser outbox failure"),
        ("CASE-A", "CAPTURE-A", "browser outbox failure"),
    ]


def test_first_frame_failure_can_reconnect_to_incomplete_browser_marker():
    app, _browser_input = make_app({
        "CASE-A": {"active": False, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.live_speech_coordinator = type(
        "RestartedCoordinator",
        (),
        {"has_browser_frame_receipt": lambda _self, _case_id, _capture_id: True},
    )()

    def first_frame_failed(_case_id, _capture_id, _sequence, _start_sample, _pcm):
        raise RuntimeError("capture is not accepting audio")

    app.state.asr_capture_service.ingest_browser_frame = first_frame_failed
    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            websocket.send_bytes(struct.pack("<IQ", 1, 0) + b"\x01\x00")
            assert websocket.receive_json() == {
                "type": "capture_incomplete_ack",
                "captureId": "CAPTURE-A",
            }
            close = websocket.receive()

    assert close["type"] == "websocket.close"
    assert close["code"] == 4410
    assert app.state.asr_capture_service.incomplete == [
        ("CASE-A", "CAPTURE-A", "capture is not accepting audio"),
    ]


def test_stale_active_service_binding_cannot_reopen_a_completed_capture():
    app, _browser_input = make_app({
        "CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"},
    })
    app.state.live_speech_coordinator = type(
        "CompletedCoordinator",
        (),
        {"has_browser_frame_receipt": lambda _self, _case_id, _capture_id: False},
    )()

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as close:
            with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A"):
                pass

    assert close.value.code == 4409


def test_question_preparation_socket_keeps_unsequenced_pcm_protocol():
    app, browser_input = make_app({})
    pcm = b"\x01\x00" * 32

    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/question-preparation/PREP-A") as websocket:
            websocket.send_bytes(pcm)

    assert browser_input.read_audio_frames(timeout=0.01) == pcm


@pytest.mark.parametrize(
    "case_id,capture_id,status_by_case",
    [
        ("CASE-B", "CAPTURE-A", {"CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"}}),
        ("CASE-A", "CAPTURE-B", {"CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "BROWSER"}}),
        ("CASE-A", "CAPTURE-A", {"CASE-A": {"active": True, "captureSessionId": "CAPTURE-A", "source": "ALSA"}}),
        ("CASE-A", "CAPTURE-A", {"CASE-A": {"active": False, "captureSessionId": "CAPTURE-A", "source": "BROWSER"}}),
    ],
)
def test_browser_asr_socket_rejects_any_connection_not_bound_to_active_browser_capture(
    case_id: str,
    capture_id: str,
    status_by_case: dict[str, dict[str, object]],
):
    app, browser_input = make_app(status_by_case)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as close:
            with client.websocket_connect(f"/ws/asr/cases/{case_id}/capture/{capture_id}"):
                pass

    assert close.value.code == 4409
    assert browser_input.read_audio_frames(timeout=0.01) == b""


def test_browser_asr_socket_rechecks_capture_before_accepting_each_pcm_frame():
    status_by_case = {
        "CASE-A": {
            "active": True,
            "captureSessionId": "CAPTURE-A",
            "source": "BROWSER",
        },
    }
    app, browser_input = make_app(status_by_case)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/asr/cases/CASE-A/capture/CAPTURE-A") as websocket:
            status_by_case["CASE-A"] = {
                "active": True,
                "captureSessionId": "CAPTURE-B",
                "source": "BROWSER",
            }
            websocket.send_bytes(struct.pack("<IQ", 1, 0) + b"\x01\x00" * 160)
            close = websocket.receive()

    assert close["type"] == "websocket.close"
    assert close["code"] == 4409
    assert browser_input.read_audio_frames(timeout=0.01) == b""
    assert app.state.asr_capture_service.frames == []


def test_ordinary_browser_disconnect_marks_active_capture_incomplete():
    app, _ = make_app({'CASE-A': {'active': True, 'captureSessionId': 'CAPTURE-A', 'source': 'BROWSER'}})
    with TestClient(app) as client:
        with client.websocket_connect('/ws/asr/cases/CASE-A/capture/CAPTURE-A'):
            pass
    assert app.state.asr_capture_service.incomplete == [
        ('CASE-A', 'CAPTURE-A', 'browser audio connection disconnected')
    ]
