from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


# 本进程实例标识。seq 只存在于 ConnectionManager 内存里，进程重启必然从 1 重新
# 计数；客户端靠 epoch 变化判断"换代"并重置去重水位，否则重启后的实时消息会被
# 当成旧消息静默丢弃（每次部署都会重启运行时）。
INSTANCE_EPOCH = uuid4().hex


SUPPORTED_CLIENT_EVENTS = {
    "STATE_SYNC_REQUEST",
    # 旧前端重连时发的事件名，保留为 STATE_SYNC_REQUEST 的别名。
    "SESSION_RESYNC",
    "DEVICE_EVENT",
    "ASR_FRAGMENT",
    "RECORDING_STATE",
    "SIGNATURE_STATE",
}


class ClientEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # 省略时以 WebSocket 路径里的 session_id 为准：旧前端只发 {event, payload}，
    # 不该因为缺这个字段被判成非法信封。
    session_id: str | None = None
    event: str
    # 客户端上行事件不参与服务端 seq 定序，缺省即可。
    seq: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def server_envelope(session_id: str, event: str, seq: int, payload: dict | None = None) -> dict:
    return {
        "session_id": session_id,
        "event": event,
        "seq": seq,
        "epoch": INSTANCE_EPOCH,
        "timestamp": utc_timestamp(),
        "payload": payload or {},
    }
