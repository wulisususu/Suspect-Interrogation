from __future__ import annotations

import socket

import pytest

from speech_worker.ws_client import WebSocketClient, WebSocketError


class FakeServer:
    """在 socketpair 的一端扮演服务端。"""

    def __init__(self) -> None:
        self.client_sock, self.server_sock = socket.socketpair()

    def feed(self, data: bytes) -> None:
        self.server_sock.sendall(data)

    def read(self, size: int = 4096) -> bytes:
        return self.client_sock.recv(size)

    def close(self) -> None:
        for sock in (self.client_sock, self.server_sock):
            try:
                sock.close()
            except OSError:
                pass


def make_client(server: FakeServer) -> WebSocketClient:
    client = WebSocketClient("ws://127.0.0.1:8010/asr/stream")
    client._sock = server.client_sock  # 跳过握手，只测帧层
    return client


def server_frame(payload: bytes, *, opcode: int = 0x1, fin: bool = True) -> bytes:
    header = bytes([(0x80 if fin else 0x00) | opcode, len(payload)])
    return header + payload


def test_send_binary_masks_the_payload():
    server = FakeServer()
    try:
        client = make_client(server)
        client.send_binary(b"\x01\x02\x03")

        raw = server.server_sock.recv(64)
        assert raw[0] == 0x82, "必须是 FIN + binary"
        assert raw[1] & 0x80, "客户端帧必须带掩码位"
        length = raw[1] & 0x7F
        assert length == 3
        mask = raw[2:6]
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw[6:9]))
        assert payload == b"\x01\x02\x03"
    finally:
        server.close()


def test_recv_decodes_text_frame():
    server = FakeServer()
    try:
        client = make_client(server)
        server.feed(server_frame(b'{"type":"ready"}'))
        assert client.recv(1.0) == '{"type":"ready"}'
    finally:
        server.close()


def test_recv_reassembles_fragmented_message():
    server = FakeServer()
    try:
        client = make_client(server)
        server.feed(server_frame(b'{"type":', opcode=0x1, fin=False))
        server.feed(server_frame(b'"final"}', opcode=0x0, fin=True))
        assert client.recv(1.0) == '{"type":"final"}'
    finally:
        server.close()


def test_recv_answers_ping_with_pong():
    server = FakeServer()
    try:
        client = make_client(server)
        server.feed(server_frame(b"pb", opcode=0x9))
        server.feed(server_frame(b"ok"))
        assert client.recv(1.0) == "ok"
        pong = server.server_sock.recv(64)
        assert pong[0] == 0x8A, "收到 ping 必须回 pong"
    finally:
        server.close()


def test_recv_returns_none_when_nothing_arrives():
    server = FakeServer()
    try:
        client = make_client(server)
        assert client.recv(0.0) is None
        assert client.recv(0.05) is None
    finally:
        server.close()


def test_recv_raises_on_close_frame():
    server = FakeServer()
    try:
        client = make_client(server)
        server.feed(server_frame(b"", opcode=0x8))
        with pytest.raises(WebSocketError):
            client.recv(1.0)
    finally:
        server.close()


def test_rejects_non_ws_scheme():
    with pytest.raises(WebSocketError):
        WebSocketClient("http://127.0.0.1:8010/asr/stream")
