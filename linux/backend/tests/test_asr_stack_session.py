from __future__ import annotations

import pytest

from app.ai.errors import AIError, BackendUnavailableError
from app.ai.speech.types import SpeechEventType
from speech_worker.asr_stack_session import AsrStackEndpoint, AsrStackSpeechSession, endpoint_from_env


class FakeClient:
    """记录发出的二进制帧，recv 永远没有消息。"""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False

    def connect(self) -> None:
        return None

    def send_binary(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, timeout: float):
        return None

    def close(self) -> None:
        self.closed = True


def make_session(**kwargs) -> AsrStackSpeechSession:
    endpoint = AsrStackEndpoint(ws_url="ws://127.0.0.1:8010/asr/stream", api_key="test-key")
    return AsrStackSpeechSession("sess-1", 16000, endpoint, **kwargs)


def patch(start: int, delete: int, insert: str, revision: int = 1) -> dict:
    return {
        "type": "text.patch",
        "segment_id": "seg-1",
        "doc_revision": revision,
        "base_revision": revision - 1,
        "start": start,
        "delete_count": delete,
        "insert_text": insert,
        "source": "asr",
    }


def test_patch_builds_partial_and_mirrors_the_visible_document():
    session = make_session()
    session._pushed_samples = 16000  # 1 秒音频

    events = session._translate([patch(0, 0, "今天星"), patch(3, 0, "期二", 2)])

    kinds = [event.type for event in events]
    assert kinds[0] is SpeechEventType.VAD_START
    assert kinds.count(SpeechEventType.ASR_PARTIAL) == 2
    assert events[0].start_ms == 0
    assert events[-1].text == "今天星期二"
    assert events[-1].end_ms == 1000


def test_patch_replaces_text_in_place_like_a_websocket_diff_consumer():
    session = make_session()
    session._translate([patch(0, 0, "你好世界")])

    # 对端把「世界」改成「先生」：start=2, delete=2, insert="先生"
    events = session._translate([patch(2, 2, "先生", 2)])

    assert events[-1].text == "你好先生"


def test_final_closes_the_utterance_and_uses_pushed_audio_for_timestamps():
    session = make_session()
    session._pushed_samples = 16000  # 1 秒
    session._translate([patch(0, 0, "第一个问题")])

    session._pushed_samples = 32000  # 累计 2 秒
    events = session._translate([
        {
            "type": "final",
            "text": "第一个问题",
            "visible": "第一个问题？",
            "segment_id": "seg-1",
            "cleaned": True,
            "corrected": 0,
            "punctuated": "第一个问题？",
        }
    ])

    assert [event.type for event in events] == [SpeechEventType.VAD_END, SpeechEventType.ASR_FINAL]
    assert events[0].start_ms == 0
    assert events[0].end_ms == 2000
    assert events[1].text == "第一个问题？"
    assert events[1].details["raw_text"] == "第一个问题"
    assert events[1].details["punctuated"] == "第一个问题？"
    # 收口后内部状态要清干净，下一句才不会带着上一句的起点
    assert session._last_end_ms == 2000 and session._utterance_start_ms is None


def test_second_utterance_starts_where_the_previous_one_ended():
    session = make_session()
    session._pushed_samples = 16000  # 第一句结束于第 1 秒
    session._translate([patch(0, 0, "第一句")])
    session._translate([{"type": "final", "text": "第一句", "visible": "第一句。", "punctuated": "第一句。"}])

    session._pushed_samples = 48000
    events = session._translate([patch(0, 0, "第二句")])

    assert events[0].type is SpeechEventType.VAD_START
    # asr-stack 不给时间戳，只能沿用上一句的结束点当起点
    assert events[0].start_ms == 1000
    assert events[-1].end_ms == 3000


def test_empty_endpoint_only_closes_an_open_utterance():
    session = make_session()
    assert session._translate([{"type": "endpoint"}]) == []

    session._pushed_samples = 8000
    session._translate([patch(0, 0, "半句")])
    events = session._translate([{"type": "endpoint"}])

    assert [event.type for event in events] == [SpeechEventType.VAD_END]
    assert events[0].details["empty_endpoint"] is True


def test_out_of_range_patch_is_dropped_instead_of_corrupting_the_document():
    session = make_session()
    session._translate([patch(0, 0, "正常")])

    events = session._translate([patch(99, 0, "越界", 2)])

    assert events == []
    assert "".join(session._doc) == "正常"


def test_worker_side_error_surfaces_as_backend_unavailable():
    session = make_session()

    with pytest.raises(BackendUnavailableError):
        session._translate([{"type": "error", "detail": "invalid api key"}])


def test_finalize_pushes_silence_and_falls_back_to_the_partial_text():
    fake = FakeClient()
    session = make_session(finalize_timeout=0.2, client_factory=lambda endpoint: fake)
    session._ws = fake
    session._connected = True
    session._pushed_samples = 16000
    session._translate([patch(0, 0, "没收口的一句")])

    events = session.finalize()

    assert fake.sent, "必须补推静音去触发对端 endpoint"
    # 必须分块推：整块静音塞进去，引擎不会判定端点（实测）
    assert len(fake.sent) > 1
    assert all(byte == 0 for chunk in fake.sent for byte in chunk)
    finals = [event for event in events if event.type is SpeechEventType.ASR_FINAL]
    assert len(finals) == 1
    assert finals[0].text == "没收口的一句"
    assert finals[0].details["forced_final"] is True


def test_non_16k_streams_are_rejected_early():
    endpoint = AsrStackEndpoint(ws_url="ws://x/asr/stream", api_key="k")
    with pytest.raises(AIError):
        AsrStackSpeechSession("s", 8000, endpoint)


def test_endpoint_url_carries_key_and_flags():
    endpoint = AsrStackEndpoint(ws_url="ws://127.0.0.1:8010/asr/stream", api_key="abc", clean=False, record=False)
    assert endpoint.url() == "ws://127.0.0.1:8010/asr/stream?key=abc&record=0"


def test_endpoint_from_env_requires_both_url_and_key():
    assert endpoint_from_env({}) is None
    assert endpoint_from_env({"SUSPECT_ASR_STACK_WS_URL": "ws://x/asr/stream"}) is None

    endpoint = endpoint_from_env({
        "SUSPECT_ASR_STACK_WS_URL": "ws://x/asr/stream",
        "SUSPECT_ASR_STACK_KEY": "k",
    })
    assert endpoint is not None and endpoint.clean is True
