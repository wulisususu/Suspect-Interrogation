"""最小 RFC 6455 WebSocket 客户端（纯标准库）。

为什么不用 `websockets` 库：ai-worker 跑在 `runtime/funasr-env` 里，那个环境
没有 websockets，而离线板子上新增 pip 依赖要额外改部署脚本、还得依赖外网索引。
这里只需要「发二进制、收 JSON 文本」这一条最窄的路径，用标准库实现一百多行就
够，且同步阻塞的语义正好匹配 speech.sock 那套线程模型。

只实现客户端必需的部分：握手（含 accept 校验）、掩码帧、文本/二进制/关闭/心跳，
以及分片重组。不做扩展协商（permessage-deflate 一律不声明）。
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
from typing import Any
from urllib.parse import urlsplit

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_CONT = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA
_MAX_MESSAGE_BYTES = 8 * 1024 * 1024


class WebSocketError(RuntimeError):
    """握手或帧层失败。"""


class WebSocketClient:
    """阻塞式 WebSocket 客户端。

    Args:
        url: 形如 ``ws://127.0.0.1:8010/asr/stream?key=...``（仅支持 ws://）。
        connect_timeout: TCP 连接与握手的最长等待秒数。
        max_message_bytes: 单条消息上限，防止对端异常时把内存吃爆。
    """

    def __init__(self, url: str, *, connect_timeout: float = 10.0, max_message_bytes: int = _MAX_MESSAGE_BYTES) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "ws":
            raise WebSocketError(f"only ws:// is supported, got {parsed.scheme!r}")
        if not parsed.hostname:
            raise WebSocketError(f"websocket url has no host: {url!r}")
        self._url = url
        self._host = parsed.hostname
        self._port = parsed.port or 80
        self._path = parsed.path or "/"
        if parsed.query:
            self._path = f"{self._path}?{parsed.query}"
        self._timeout = float(connect_timeout)
        self._max_message_bytes = int(max_message_bytes)
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        self._closed = False

    # ---- 生命周期 -------------------------------------------------------

    def connect(self) -> None:
        """建 TCP 连接并完成 HTTP Upgrade 握手。"""
        if self._sock is not None:
            return
        sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock
        try:
            self._handshake()
        except BaseException:
            self._hard_close()
            raise

    def close(self) -> None:
        """发送关闭帧并断开；可重复调用。"""
        if self._closed:
            return
        self._closed = True
        sock = self._sock
        if sock is None:
            return
        try:
            self._send_frame(_OP_CLOSE, b"\x03\xe8")
        except OSError:
            pass
        self._hard_close()

    # ---- 收发 -----------------------------------------------------------

    def send_binary(self, payload: bytes) -> None:
        self._send_frame(_OP_BINARY, payload)

    def send_text(self, text: str) -> None:
        self._send_frame(_OP_TEXT, text.encode("utf-8"))

    def recv(self, timeout: float) -> str | bytes | None:
        """收一条完整消息。

        Args:
            timeout: 等待秒数。``0`` 表示只取已到达的数据（非阻塞）。

        Returns:
            文本消息返回 ``str``，二进制返回 ``bytes``，超时返回 ``None``。

        Raises:
            WebSocketError: 连接已关闭或帧格式非法。
        """
        deadline = None if timeout <= 0 else _now() + timeout
        fragments: list[bytes] = []
        fragments_opcode: int | None = None
        while True:
            frame = self._read_frame(deadline)
            if frame is None:
                return None
            fin, opcode, payload = frame
            if opcode == _OP_PING:
                self._send_frame(_OP_PONG, payload)
                continue
            if opcode == _OP_PONG:
                continue
            if opcode == _OP_CLOSE:
                self._hard_close()
                raise WebSocketError("websocket closed by peer")
            if opcode in (_OP_TEXT, _OP_BINARY):
                fragments = [payload]
                fragments_opcode = opcode
            elif opcode == _OP_CONT:
                if fragments_opcode is None:
                    raise WebSocketError("continuation frame without initial frame")
                fragments.append(payload)
            else:
                raise WebSocketError(f"unsupported opcode: {opcode}")
            if not fin:
                continue
            data = b"".join(fragments)
            if len(data) > self._max_message_bytes:
                raise WebSocketError("message too large")
            return data.decode("utf-8", errors="replace") if fragments_opcode == _OP_TEXT else data

    # ---- 内部实现 -------------------------------------------------------

    def _handshake(self) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = self._host if self._port == 80 else f"{self._host}:{self._port}"
        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        sock = self._require_socket()
        sock.sendall(request.encode("ascii"))
        header_bytes = self._read_until(b"\r\n\r\n")
        header_text = header_bytes.decode("iso-8859-1")
        status_line = header_text.split("\r\n", 1)[0]
        if " 101 " not in status_line:
            raise WebSocketError(f"handshake rejected: {status_line.strip()}")
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        headers = {}
        for line in header_text.split("\r\n")[1:]:
            if ":" in line:
                name, _, value = line.partition(":")
                headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != expected:
            raise WebSocketError("handshake accept key mismatch")

    def _read_until(self, marker: bytes) -> bytes:
        while True:
            index = self._buf.find(marker)
            if index >= 0:
                end = index + len(marker)
                head = bytes(self._buf[:end])
                del self._buf[:end]
                return head
            if len(self._buf) > 64 * 1024:
                raise WebSocketError("handshake response too large")
            if not self._fill(self._timeout):
                raise WebSocketError("connection closed during handshake")

    def _fill(self, timeout: float | None) -> bool:
        sock = self._require_socket()
        previous = sock.gettimeout()
        try:
            sock.settimeout(None if timeout is None else max(0.001, timeout))
            chunk = sock.recv(65536)
        except socket.timeout:
            return False
        except OSError as exc:
            raise WebSocketError(f"socket error: {exc}") from exc
        finally:
            try:
                sock.settimeout(previous)
            except OSError:
                pass
        if not chunk:
            return False
        self._buf.extend(chunk)
        return True

    def _read_frame(self, deadline: float | None) -> tuple[bool, int, bytes] | None:
        """从缓冲区取一帧；不足时按 deadline 等待。``None`` 表示超时。"""
        while True:
            frame = self._try_parse_frame()
            if frame is not None:
                return frame
            if deadline is None:
                timeout = 0.0
            else:
                remaining = deadline - _now()
                if remaining <= 0:
                    return None
                timeout = remaining
            if not self._fill(timeout):
                return None

    def _try_parse_frame(self) -> tuple[bool, int, bytes] | None:
        buf = self._buf
        if len(buf) < 2:
            return None
        first, second = buf[0], buf[1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < offset + 2:
                return None
            length = struct.unpack("!H", bytes(buf[offset:offset + 2]))[0]
            offset += 2
        elif length == 127:
            if len(buf) < offset + 8:
                return None
            length = struct.unpack("!Q", bytes(buf[offset:offset + 8]))[0]
            offset += 8
        if length > self._max_message_bytes:
            raise WebSocketError("frame too large")
        mask_bytes = 4 if masked else 0
        if len(buf) < offset + mask_bytes + length:
            return None
        mask = bytes(buf[offset:offset + mask_bytes]) if masked else b""
        start = offset + mask_bytes
        payload = bytes(buf[start:start + length])
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        del buf[:start + length]
        return fin, opcode, payload

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        sock = self._require_socket()
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        header.extend(mask)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        try:
            sock.sendall(bytes(header) + masked)
        except OSError as exc:
            raise WebSocketError(f"failed to send frame: {exc}") from exc

    def _require_socket(self) -> socket.socket:
        sock = self._sock
        if sock is None:
            raise WebSocketError("websocket is not connected")
        return sock

    def _hard_close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        self._buf.clear()


def _now() -> float:
    import time

    return time.monotonic()
