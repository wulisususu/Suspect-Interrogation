"""通道②全程录音的浏览器推流。

协议（与正式采集的帧格式一致：<IQ 序号/起始样本 + PCM16）：
  1. 连上后浏览器先发 {"type": "segment_open", "fresh": bool}，服务端回
     {"type": "segment_opened", "status", "clientSampleEnd", "nextSequence"}；
  2. 每个二进制帧落盘后回 {"type": "ack", "ackSequence", "durableSampleEnd"}；
  3. 暂停/结束询问后浏览器送完缓存，发 {"type": "segment_finalize"}，
     服务端落成 WAV 并回 {"type": "segment_finalize_ack", ...}。
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.domain.errors import DomainError
from app.websocket.browser_asr import _claim_socket, _release_socket, _touch_socket

router = APIRouter()
logger = logging.getLogger("suspect.session_recording")
_MAX_FRAME_BYTES = 64 * 1024


async def _close(websocket: WebSocket, segment_id: str, code: int, reason: str) -> None:
    logger.warning("session recording ws %s closing code=%s: %s", segment_id, code, reason)
    await websocket.close(code=code)


@router.websocket("/ws/recording/cases/{case_id}/segments/{segment_id}")
async def session_recording_socket(websocket: WebSocket, case_id: str, segment_id: str):
    store = getattr(websocket.app.state, "session_recording_store", None)
    if store is None:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    lease_key = f"segment:{case_id}:{segment_id}"
    lease = _claim_socket(websocket.app, lease_key)
    if lease is None:
        await _close(websocket, segment_id, 4429, "segment is already streaming from another connection")
        return
    opened = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))
            if not _touch_socket(websocket.app, lease_key, lease):
                await _close(websocket, segment_id, 4410, "superseded by a newer recording connection")
                return
            text = message.get("text")
            if text is not None:
                try:
                    control = json.loads(text)
                except ValueError:
                    control = None
                kind = control.get("type") if isinstance(control, dict) else None
                if kind == "segment_open":
                    state = await asyncio.to_thread(store.attach, case_id, segment_id, fresh=bool(control.get("fresh")))
                    await websocket.send_json({"type": "segment_opened", **state})
                    if state["status"] not in ("RECORDING", "CLOSING"):
                        await _close(websocket, segment_id, 4409, "segment is already saved")
                        return
                    opened = True
                    continue
                if kind == "segment_finalize" and opened:
                    result = await asyncio.to_thread(store.finalize, case_id, segment_id, client_confirmed=True)
                    await websocket.send_json({"type": "segment_finalize_ack", **result})
                    await websocket.close(code=1000)
                    return
                await _close(websocket, segment_id, 1003, "unknown recording control message")
                return
            payload = message.get("bytes")
            if payload is None or not opened:
                await _close(websocket, segment_id, 1003, "segment_open must precede audio frames")
                return
            if len(payload) < 14 or len(payload) > _MAX_FRAME_BYTES + 12:
                await _close(websocket, segment_id, 1008, "recording frame size is invalid")
                return
            sequence, start_sample = struct.unpack_from("<IQ", payload)
            try:
                receipt = await asyncio.to_thread(store.ingest, case_id, segment_id, sequence, start_sample, bytes(payload[12:]))
            except DomainError as exc:
                await _close(websocket, segment_id, 4409, exc.code)
                return
            except (OSError, ValueError) as exc:
                await _close(websocket, segment_id, 4410, f"recording append failed: {exc}")
                return
            await websocket.send_json(receipt)
    except WebSocketDisconnect:
        logger.info("session recording ws %s disconnected", segment_id)
    except DomainError as exc:
        await _close(websocket, segment_id, 4404, exc.code)
    finally:
        _release_socket(websocket.app, lease_key, lease)
