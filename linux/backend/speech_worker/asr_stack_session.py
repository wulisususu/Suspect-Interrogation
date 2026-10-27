"""asr-stack 后端：把 asr-stack 的流式接口适配成 speech.sock 的事件流。

设计取舍（为什么单独写一个 Session，而不是复用 SpeechSession）：

`SpeechSession` 用 fsmn-vad 自己断句、自己推算时间轴，再调 `transcribe_stream`
要文字。asr-stack 反过来 —— 它内部用 sherpa 的 `is_endpoint` 自己判断断点，只在
断点处给一条 `final`。两套断句叠在一起会互相打架（同一句话会被切两次），所以在
这里按 asr-stack 的语义重新实现编排，funasr 那条路径一行不改，靠
`SUSPECT_SPEECH_BACKEND` 灰度切换、随时回滚。

事件映射：
    text.patch   → VAD_START + ASR_PARTIAL     （对端发的是增量补丁，本地做镜像）
    final        → VAD_END + ASR_FINAL
    endpoint     → VAD_END（空文本，不上报片段）

时间戳：asr-stack 的 final 不带时间，这里用「已推入音频的累计毫秒」推算 —— 首句
起点为 0，之后以上一句的结束点为起点。误差等于句间静音长度，量级 <1s，用于笔录
时间轴足够；要做到精确必须让 asr-stack 在 final 里回传真实 start/end，那是它收编
进仓库时要一起改的契约。

传输层用标准库实现的 `ws_client`，不引入第三方依赖 —— ai-worker 跑在
`runtime/funasr-env` 里，那个环境没有 websockets，而在离线板子上加 pip 依赖要
额外改部署脚本。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.ai.errors import AIError, BackendUnavailableError, WorkerTimeoutError
from app.ai.speech.types import SpeechEvent, SpeechEventType

from .ws_client import WebSocketClient, WebSocketError

logger = logging.getLogger(__name__)

_REQUIRED_SAMPLE_RATE = 16000
_SAMPLE_WIDTH_BYTES = 2
# asr-stack 只在静音断点发 final，收尾时要自己补一段静音把它逼出来。
# 两条硬约束（实测）：必须按 160ms 分块推（整块塞进去引擎不判定端点），长度要盖过
# sherpa 的尾部静音阈值（rule1=2.4s），1.5s 不够。
_FINALIZE_SILENCE_MS = 2500
_FINALIZE_CHUNK_MS = 160
_FINALIZE_WAIT_S = 4.0


@dataclass(frozen=True)
class AsrStackEndpoint:
    """asr-stack 流式入口。

    Attributes:
        ws_url: 形如 ``ws://127.0.0.1:8010/asr/stream``。
        api_key: asr-stack 要求所有接口带 key；本机回环也不例外。
        clean: 是否让对端做去语气词（``final.visible`` 为清理后文本）。
        record: 是否让对端落 WAV。默认关闭 —— 审讯链路的原始音频由
            ``AsrCaptureService`` 自己管，开两份会重复占盘。
        connect_timeout: 建连 + 等 ``ready`` 的超时。
    """

    ws_url: str
    api_key: str
    clean: bool = True
    record: bool = False
    connect_timeout: float = 10.0

    def url(self) -> str:
        params = [f"key={self.api_key}", "record=1" if self.record else "record=0"]
        if self.clean:
            params.append("clean=1")
        joiner = "&" if "?" in self.ws_url else "?"
        return f"{self.ws_url}{joiner}{'&'.join(params)}"


class AsrStackSpeechSession:
    """一个审讯会话对应一条 asr-stack WebSocket 连接（同步阻塞）。"""

    def __init__(
        self,
        session_id: str,
        sample_rate: int,
        endpoint: AsrStackEndpoint,
        *,
        base_sample: int = 0,
        finalize_timeout: float = _FINALIZE_WAIT_S,
        client_factory: Any | None = None,
    ) -> None:
        if int(sample_rate) != _REQUIRED_SAMPLE_RATE:
            raise AIError(
                "asr-stack backend only accepts 16 kHz mono PCM",
                details={"sample_rate": sample_rate, "required": _REQUIRED_SAMPLE_RATE},
            )
        self.session_id = session_id
        self.sample_rate = int(sample_rate)
        self.endpoint = endpoint
        self.base_sample = max(0, int(base_sample))
        self.finalize_timeout = float(finalize_timeout)
        self._client_factory = client_factory or self._default_client_factory

        self._ws: WebSocketClient | None = None
        self._connected = False
        self._pushed_samples = self.base_sample
        self._pad_ms = 0
        self._doc: list[str] = []
        self._doc_revision = 0
        self._utterance_start_ms: int | None = None
        self._last_end_ms = 0

    # ---- 生命周期 -------------------------------------------------------

    def open(self) -> None:
        """建立连接并等到对端 ``ready``。

        Raises:
            BackendUnavailableError: 连接失败或握手被拒。
            WorkerTimeoutError: 等不到 ``ready``。
        """
        if self._ws is not None:
            return
        client = self._client_factory(self.endpoint)
        try:
            client.connect()
        except WebSocketError as exc:
            raise BackendUnavailableError(
                f"asr-stack connection failed: {exc}",
                details={"url": self.endpoint.ws_url},
            ) from exc
        self._ws = client
        deadline = time.monotonic() + self.endpoint.connect_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise WorkerTimeoutError(
                    "asr-stack did not send ready in time",
                    details={"url": self.endpoint.ws_url, "timeout_s": self.endpoint.connect_timeout},
                )
            payload = self._recv_payload(remaining)
            if payload is None:
                continue
            if payload.get("type") == "ready":
                self._connected = True
                return
            if payload.get("type") == "error":
                detail = str(payload.get("detail") or "")
                self.close()
                raise BackendUnavailableError(
                    f"asr-stack rejected the session: {detail}",
                    details={"url": self.endpoint.ws_url, "detail": detail},
                )

    def close(self) -> None:
        """关闭连接；可重复调用。"""
        client = self._ws
        self._ws = None
        self._connected = False
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001 - 关闭失败不该抛给调用方
                logger.warning("关闭 asr-stack 连接失败：%s", self.session_id, exc_info=True)

    # ---- speech.sock 契约 ----------------------------------------------

    def push_pcm(self, pcm: bytes) -> list[SpeechEvent]:
        """送入一段 PCM16，返回这段音频触发的事件（可能为空）。"""
        if len(pcm) % _SAMPLE_WIDTH_BYTES:
            raise AIError("pcm length must be a multiple of 2 bytes", details={"length": len(pcm)})
        if not pcm:
            return []
        client = self._require_client()
        self._pushed_samples += len(pcm) // _SAMPLE_WIDTH_BYTES
        try:
            client.send_binary(pcm)
        except WebSocketError as exc:
            raise BackendUnavailableError(
                f"failed to push pcm to asr-stack: {exc}",
                details={"session_id": self.session_id},
            ) from exc
        return self._translate(self._poll(0.0))

    def finalize(self) -> list[SpeechEvent]:
        """强制收尾。

        asr-stack 没有 flush 命令，只能补一段静音把内部 endpoint 逼出来；拿不到
        final 就退化为「把当前 partial 当最终文本」，并标记 forced，让上层知道这
        一条不是模型主动断的。
        """
        if not self._connected or self._ws is None:
            return []
        client = self._ws
        silence_chunk = b"\x00" * (_REQUIRED_SAMPLE_RATE * _SAMPLE_WIDTH_BYTES * _FINALIZE_CHUNK_MS // 1000)
        try:
            for _ in range(max(1, _FINALIZE_SILENCE_MS // _FINALIZE_CHUNK_MS)):
                client.send_binary(silence_chunk)
        except WebSocketError as exc:
            raise BackendUnavailableError(
                f"failed to flush asr-stack session: {exc}",
                details={"session_id": self.session_id},
            ) from exc
        self._pad_ms += _FINALIZE_SILENCE_MS

        events: list[SpeechEvent] = []
        deadline = time.monotonic() + self.finalize_timeout
        idle = 0.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            payloads = self._poll(min(0.1, remaining))
            if payloads:
                idle = 0.0
                produced = self._translate(payloads)
                events.extend(produced)
                if any(event.type in (SpeechEventType.ASR_FINAL, SpeechEventType.VAD_END) for event in produced):
                    break  # 对端已经收口
                continue
            idle += 0.1
            if idle >= 0.5 and self._utterance_start_ms is None:
                break  # 没有未收口的句子，对端也彻底没动静了

        if self._utterance_start_ms is not None:
            # 对端始终没给 final：把已收到的文本当作最终稿收掉，避免丢内容。
            text = "".join(self._doc).strip()
            start_ms = self._utterance_start_ms
            end_ms = self._audio_ms()
            self._reset_utterance()
            if text:
                events.append(
                    SpeechEvent(
                        type=SpeechEventType.ASR_FINAL,
                        session_id=self.session_id,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        text=text,
                        model_id="asr-stack-partial",
                        details={"forced_final": True, "backend": "asr_stack"},
                    )
                )
        return events

    def health(self) -> dict[str, Any]:
        return {
            "backend": "asr_stack",
            "url": self.endpoint.ws_url,
            "connected": self._connected,
            "doc_revision": self._doc_revision,
            "pushed_ms": self._audio_ms(),
        }

    # ---- 事件翻译 -------------------------------------------------------

    def _translate(self, payloads: list[dict[str, Any]]) -> list[SpeechEvent]:
        events: list[SpeechEvent] = []
        for payload in payloads:
            kind = str(payload.get("type") or "")
            if kind == "text.patch":
                events.extend(self._apply_patch(payload))
            elif kind == "final":
                events.extend(self._apply_final(payload))
            elif kind == "endpoint":
                events.extend(self._apply_endpoint())
            elif kind == "error":
                raise BackendUnavailableError(
                    f"asr-stack error: {payload.get('detail')}",
                    details={"detail": payload.get("detail")},
                )
            # ready / ack / text.snapshot 不产生审讯侧事件
        return events

    def _apply_patch(self, payload: dict[str, Any]) -> list[SpeechEvent]:
        start = int(payload.get("start") or 0)
        delete_count = int(payload.get("delete_count") or 0)
        insert_text = str(payload.get("insert_text") or "")
        if start < 0 or start > len(self._doc) or delete_count < 0:
            logger.warning(
                "asr-stack patch 越界，丢弃：start=%s delete=%s doc=%s",
                start, delete_count, len(self._doc),
            )
            return []
        self._doc[start:start + delete_count] = list(insert_text)
        self._doc_revision = int(payload.get("doc_revision") or self._doc_revision + 1)

        text = "".join(self._doc)
        if not text.strip():
            return []
        events: list[SpeechEvent] = []
        if self._utterance_start_ms is None:
            self._utterance_start_ms = self._last_end_ms
            events.append(
                SpeechEvent(
                    type=SpeechEventType.VAD_START,
                    session_id=self.session_id,
                    start_ms=self._utterance_start_ms,
                    details={"backend": "asr_stack", "source": "endpoint"},
                )
            )
        events.append(
            SpeechEvent(
                type=SpeechEventType.ASR_PARTIAL,
                session_id=self.session_id,
                start_ms=self._utterance_start_ms,
                end_ms=self._audio_ms(),
                text=text,
                model_id="asr-stack",
                details={"backend": "asr_stack", "doc_revision": self._doc_revision},
            )
        )
        return events

    def _apply_final(self, payload: dict[str, Any]) -> list[SpeechEvent]:
        raw_text = str(payload.get("text") or "")
        visible = str(payload.get("visible") or "")
        punctuated = str(payload.get("punctuated") or "")
        text = (visible or raw_text).strip()
        if not text:
            return self._apply_endpoint()

        start_ms = self._utterance_start_ms if self._utterance_start_ms is not None else self._last_end_ms
        end_ms = max(start_ms, self._audio_ms())
        self._reset_utterance()
        self._last_end_ms = end_ms
        details: dict[str, Any] = {
            "backend": "asr_stack",
            "raw_text": raw_text,
            "cleaned": bool(payload.get("cleaned")),
            "corrected": int(payload.get("corrected") or 0),
            "segment_id": payload.get("segment_id"),
        }
        if punctuated:
            details["punctuated"] = punctuated
        # 对端明确给了 final 就是模型自己收口的，不能因为正处在 finalize 期间就标
        # 成 forced —— forced 只用于「拿 partial 兜底」的情况。
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                details={"backend": "asr_stack"},
            ),
            SpeechEvent(
                type=SpeechEventType.ASR_FINAL,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                model_id="sherpa-onnx-zipformer-rknn",
                details=details,
            ),
        ]

    def _apply_endpoint(self) -> list[SpeechEvent]:
        if self._utterance_start_ms is None:
            return []
        start_ms = self._utterance_start_ms
        end_ms = max(start_ms, self._audio_ms())
        self._reset_utterance()
        self._last_end_ms = end_ms
        return [
            SpeechEvent(
                type=SpeechEventType.VAD_END,
                session_id=self.session_id,
                start_ms=start_ms,
                end_ms=end_ms,
                details={"backend": "asr_stack", "empty_endpoint": True},
            )
        ]

    def _reset_utterance(self) -> None:
        self._utterance_start_ms = None
        self._doc = []
        self._doc_revision = 0

    def _audio_ms(self) -> int:
        return int(self._pushed_samples * 1000 / _REQUIRED_SAMPLE_RATE)

    # ---- 传输层 ---------------------------------------------------------

    def _require_client(self) -> WebSocketClient:
        client = self._ws
        if client is None or not self._connected:
            raise BackendUnavailableError(
                "asr-stack session is not connected",
                details={"session_id": self.session_id},
            )
        return client

    def _recv_payload(self, timeout: float) -> dict[str, Any] | None:
        client = self._ws
        if client is None:
            return None
        try:
            message = client.recv(timeout)
        except WebSocketError as exc:
            self._connected = False
            raise BackendUnavailableError(
                f"asr-stack connection lost: {exc}",
                details={"session_id": self.session_id},
            ) from exc
        if message is None:
            return None
        if isinstance(message, (bytes, bytearray)):
            return None
        try:
            payload = json.loads(message)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _poll(self, timeout: float) -> list[dict[str, Any]]:
        """把已经到达的消息全部收下来，最多等 ``timeout``。"""
        payloads: list[dict[str, Any]] = []
        first = self._recv_payload(timeout)
        if first is None:
            return payloads
        payloads.append(first)
        while True:
            nxt = self._recv_payload(0.0)
            if nxt is None:
                return payloads
            payloads.append(nxt)

    @staticmethod
    def _default_client_factory(endpoint: AsrStackEndpoint) -> WebSocketClient:
        return WebSocketClient(endpoint.url(), connect_timeout=endpoint.connect_timeout)


def endpoint_from_env(env: dict[str, str]) -> AsrStackEndpoint | None:
    """按环境变量构造入口；未配置返回 None（调用方保持 funasr 后端）。"""
    url = (env.get("SUSPECT_ASR_STACK_WS_URL") or "").strip()
    key = (env.get("SUSPECT_ASR_STACK_KEY") or "").strip()
    if not url or not key:
        return None
    return AsrStackEndpoint(
        ws_url=url,
        api_key=key,
        clean=(env.get("SUSPECT_ASR_STACK_CLEAN") or "1").strip() not in {"0", "false", "False"},
        record=(env.get("SUSPECT_ASR_STACK_RECORD") or "0").strip() in {"1", "true", "True"},
        connect_timeout=float(env.get("SUSPECT_ASR_STACK_CONNECT_TIMEOUT") or 10.0),
    )
