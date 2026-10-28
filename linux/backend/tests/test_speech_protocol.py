from __future__ import annotations

import base64
import json
import socket
import struct
import threading
import time
from pathlib import Path

import pytest

from app.ai.errors import BackendUnavailableError, ModelNotInstalledError, WorkerCrashedError, WorkerTimeoutError
from app.ai.settings import AISettings
from app.ai.speech.client import SpeechWorkerClient
from app.ai.speech.mock_worker import MockSpeechWorker
from app.ai.speech.protocol import MAX_MESSAGE_BYTES, ProtocolMessageTooLarge, encode_frame, recv_frame
from app.ai.speech.types import SpeechEvent, SpeechEventType


def _serve_once(socket_path: Path, handler) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        if socket_path.exists():
            socket_path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            server.listen(1)
            ready.set()
            conn, _ = server.accept()
            with conn:
                handler(conn)
        socket_path.unlink(missing_ok=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def test_protocol_uses_big_endian_length_prefixed_utf8_json():
    payload = {"request_id": "req-1", "op": "health", "text": "中文"}
    frame = encode_frame(payload)

    (body_length,) = struct.unpack("!I", frame[:4])
    assert body_length == len(frame[4:])
    assert json.loads(frame[4:].decode("utf-8")) == payload


def test_client_reports_unsupported_socket_platform_as_typed_capability_error(monkeypatch, tmp_path):
    monkeypatch.delattr(socket, "AF_UNIX", raising=False)
    with pytest.raises(BackendUnavailableError, match="AF_UNIX") as exc:
        SpeechWorkerClient(tmp_path / "speech.sock").health()
    assert exc.value.details["op"] == "health"


def test_protocol_rejects_oversized_messages_before_body_read(tmp_path: Path):
    with pytest.raises(ProtocolMessageTooLarge):
        encode_frame({"payload": "x" * (MAX_MESSAGE_BYTES + 1)})

    left, right = socket.socketpair()
    try:
        left.sendall(struct.pack("!I", MAX_MESSAGE_BYTES + 1))
        with pytest.raises(ProtocolMessageTooLarge):
            recv_frame(right)
    finally:
        left.close()
        right.close()


def test_speaker_result_protocol_preserves_backend_evidence_and_legacy_source_text():
    payload = {
        "type": "SPEAKER_RESULT",
        "session_id": "session-speaker",
        "start_ms": 100,
        "end_ms": 1800,
        "embedding": [1.0, 0.0, 0.0],
        "model_id": "iic/speech_eres2net_large_200k_sv_zh-cn_16k-common",
        "details": {
            "backend_key": "eres2net_large",
            "model_version": "v1",
            "model_fingerprint": "sha256:eres-test",
            "speaker_source": "X_VECTOR",
        },
    }

    event = SpeechEvent.from_dict(payload)
    encoded = event.to_dict()

    assert encoded["details"]["backend_key"] == "eres2net_large"
    assert encoded["details"]["model_fingerprint"] == "sha256:eres-test"
    assert encoded["details"]["speaker_source"] == "X_VECTOR"
    assert encoded["model_id"] == payload["model_id"]


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires an AF_UNIX socket runtime")
def test_client_operations_round_trip_through_deterministic_mock_worker(tmp_path: Path):
    socket_path = tmp_path / "speech.sock"
    pcm = b"\x00\x01\xfe\xff" * 32

    with MockSpeechWorker(socket_path) as worker:
        client = SpeechWorkerClient(socket_path, timeout=0.5)

        health = client.health()
        assert health["status"] == "ok"
        assert health["sessions"] == 0

        opened = client.open_session("session-1", sample_rate=16000)
        assert opened == {"session_id": "session-1", "sample_rate": 16000}

        events = client.push_pcm("session-1", pcm)
        assert events
        assert all(isinstance(event, SpeechEvent) for event in events)
        assert events[0].type in {SpeechEventType.VAD_START, SpeechEventType.ASR_PARTIAL}

        request = worker.last_request
        response = worker.last_response
        assert request["op"] == "push_pcm"
        assert request["request_id"]
        assert response["request_id"] == request["request_id"]
        assert "pcm" not in request
        assert base64.b64decode(request["pcm_b64"], validate=True) == pcm

        final_events = client.finalize_session("session-1")
        assert any(event.type == SpeechEventType.ASR_FINAL for event in final_events)

        client.open_session("empty-session", sample_rate=16000)
        empty_final_events = client.finalize_session("empty-session")
        assert not any(event.type is SpeechEventType.ASR_FINAL for event in empty_final_events)
        client.close_session("empty-session")

        embedding = client.extract_embedding(pcm, sample_rate=16000)
        assert embedding["model_id"] == "mock-xvector"
        assert embedding["embedding"] == [1.0, 0.0, 0.0]

        client.close_session("session-1")
        assert client.health()["sessions"] == 0


def test_mock_worker_omits_final_event_for_zero_byte_session(tmp_path: Path):
    worker = MockSpeechWorker(tmp_path / "speech.sock")
    opened = worker._dispatch(
        {
            "request_id": "open-empty",
            "op": "open_session",
            "session_id": "empty-session",
            "sample_rate": 16000,
        }
    )
    assert opened["ok"] is True

    finalized = worker._dispatch(
        {
            "request_id": "finalize-empty",
            "op": "finalize_session",
            "session_id": "empty-session",
        }
    )
    assert finalized["ok"] is True
    assert not any(
        event["type"] == SpeechEventType.ASR_FINAL.value
        for event in finalized["result"]["events"]
    )


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires an AF_UNIX socket runtime")
def test_worker_typed_errors_map_to_existing_ai_errors(tmp_path: Path):
    socket_path = tmp_path / "speech.sock"
    with MockSpeechWorker(socket_path) as worker:
        worker.fail_next(
            "health",
            code="MODEL_NOT_INSTALLED",
            message="xvector is missing",
            details={"model": "xvector"},
        )
        client = SpeechWorkerClient(socket_path, timeout=0.5)
        with pytest.raises(ModelNotInstalledError) as exc_info:
            client.health()
        assert exc_info.value.code == "MODEL_NOT_INSTALLED"
        assert exc_info.value.details == {"model": "xvector"}


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires an AF_UNIX socket runtime")
def test_missing_socket_timeout_and_malformed_response_become_typed_errors(tmp_path: Path):
    missing = SpeechWorkerClient(tmp_path / "missing.sock", timeout=0.05)
    with pytest.raises(BackendUnavailableError):
        missing.health()

    timeout_socket = tmp_path / "timeout.sock"

    def slow_handler(conn: socket.socket) -> None:
        recv_frame(conn)
        time.sleep(0.15)

    thread = _serve_once(timeout_socket, slow_handler)
    with pytest.raises(WorkerTimeoutError):
        SpeechWorkerClient(timeout_socket, timeout=0.03).health()
    thread.join(timeout=1)

    malformed_socket = tmp_path / "malformed.sock"

    def malformed_handler(conn: socket.socket) -> None:
        request = recv_frame(conn)
        body = b"{not-json"
        conn.sendall(struct.pack("!I", len(body)) + body)
        assert request["request_id"]

    thread = _serve_once(malformed_socket, malformed_handler)
    with pytest.raises(WorkerCrashedError):
        SpeechWorkerClient(malformed_socket, timeout=0.5).health()
    thread.join(timeout=1)


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires an AF_UNIX socket runtime")
def test_disconnect_then_restart_does_not_leak_session_state(tmp_path: Path):
    socket_path = tmp_path / "speech.sock"
    worker = MockSpeechWorker(socket_path)
    worker.start()
    client = SpeechWorkerClient(socket_path, timeout=0.5)
    client.open_session("old-session")
    assert client.health()["sessions"] == 1
    worker.stop()

    with pytest.raises(BackendUnavailableError):
        client.health()

    replacement = MockSpeechWorker(socket_path)
    replacement.start()
    try:
        reconnected = SpeechWorkerClient(socket_path, timeout=0.5)
        assert reconnected.health()["sessions"] == 0
        reconnected.open_session("new-session")
        assert reconnected.health()["sessions"] == 1
        reconnected.close_session("new-session")
    finally:
        replacement.stop()


def test_ai_settings_support_speech_socket_and_unconfigured_speaker_thresholds(monkeypatch, tmp_path: Path):
    socket_path = tmp_path / "speech.sock"
    monkeypatch.setenv("SUSPECT_SPEECH_SOCKET", str(socket_path))
    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    monkeypatch.setenv("SUSPECT_SPEAKER_BACKEND", "eres2net_large")

    settings = AISettings.from_env()
    assert settings.speech_socket == socket_path
    assert settings.speaker_accept_threshold is None
    assert settings.speaker_effective_threshold == pytest.approx(0.372)
    assert settings.speaker_margin is None

    monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", "0.73")
    monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", "0.08")
    calibrated = AISettings.from_env()
    assert calibrated.speaker_accept_threshold == pytest.approx(0.73)
    assert calibrated.speaker_margin == pytest.approx(0.08)
