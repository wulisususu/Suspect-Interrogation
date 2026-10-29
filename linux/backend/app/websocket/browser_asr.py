from __future__ import annotations

import asyncio
import json
import logging
import struct
from collections.abc import Callable

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect


router = APIRouter()
_MAX_FRAME_BYTES = 64 * 1024
logger = logging.getLogger("suspect.browser_asr")


async def _close(websocket: WebSocket, capture_id: str, code: int, reason: str) -> None:
    # Every server-side close is logged: a silent audio-channel death leaves the
    # client streaming into a dead socket with no trace to diagnose.
    logger.warning("browser asr ws %s closing code=%s: %s", capture_id, code, reason)
    await websocket.close(code=code)


def _browser_input(websocket: WebSocket):
    return getattr(websocket.app.state, "browser_audio_input", None)


def _is_active_browser_capture(websocket: WebSocket, case_id: str, capture_id: str) -> bool:
    service = getattr(websocket.app.state, "asr_capture_service", None)
    if service is None:
        return False
    status = service.status(case_id)
    active_binding = (
        bool(status.get("active"))
        and status.get("captureSessionId") == capture_id
        and status.get("source") == "BROWSER"
    )
    coordinator = getattr(websocket.app.state, "live_speech_coordinator", None)
    has_receipt = getattr(coordinator, "has_browser_frame_receipt", None)
    if callable(has_receipt):
        return bool(has_receipt(case_id, capture_id))
    return active_binding


async def _stream_browser_pcm(
    websocket: WebSocket,
    *,
    capture_id: str = "-",
    accepts_pcm: Callable[[], bool] | None = None,
    frame_ingress: Callable[[int, int, bytes], dict[str, int]] | None = None,
    incomplete_sink: Callable[[str], bool] | None = None,
    recovery_complete_sink: Callable[[int, int], dict[str, int | str]] | None = None,
) -> None:
    browser_input = _browser_input(websocket)
    if browser_input is None:
        await _close(websocket, capture_id, 4403, "browser audio input unavailable")
        return
    if not browser_input.active and frame_ingress is None:
        await _close(websocket, capture_id, 4409, "capture is not active")
        return
    if accepts_pcm is not None and not accepts_pcm():
        await _close(websocket, capture_id, 4409, "capture session is not the active browser capture")
        return

    await websocket.accept()
    logger.info("browser asr ws %s accepted", capture_id)
    # The browser drains its durable outbox and then declares a clean stop before
    # closing the socket. Without this flag an ordinary stop looks identical to a
    # dropped connection, and every clean capture would be persisted as INCOMPLETE
    # (which blocks record finalization later).
    client_finalized = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                logger.info("browser asr ws %s client disconnected", capture_id)
                raise WebSocketDisconnect(code=message.get("code", 1000))
            text = message.get("text")
            if text is not None:
                if frame_ingress is None or incomplete_sink is None:
                    await _close(websocket, capture_id, 1003, "non-binary frame")
                    return
                try:
                    control = json.loads(text)
                except (TypeError, ValueError):
                    await _close(websocket, capture_id, 1003, "invalid formal audio control message")
                    return
                if not isinstance(control, dict):
                    await _close(websocket, capture_id, 1003, "unknown formal audio control message")
                    return
                if accepts_pcm is not None and not accepts_pcm():
                    await _close(websocket, capture_id, 4409, "capture session is no longer active")
                    return
                if control.get("type") == "capture_incomplete" and incomplete_sink is not None:
                    reason = str(control.get("reason") or "browser audio outbox exhausted")[:512]
                    try:
                        marked_incomplete = await asyncio.to_thread(incomplete_sink, reason)
                    except Exception as exc:
                        await _close(websocket, capture_id, 4410, f"unable to mark browser capture incomplete: {exc}")
                        return
                    if marked_incomplete is not True:
                        await _close(websocket, capture_id, 4410, "capture is already complete")
                        return
                    await websocket.send_json({"type": "capture_incomplete_ack", "captureId": capture_id})
                    await _close(websocket, capture_id, 4410, "browser reported incomplete audio capture")
                    return
                if control.get("type") == "capture_finalize" and incomplete_sink is not None:
                    if accepts_pcm is not None and not accepts_pcm():
                        await _close(websocket, capture_id, 4409, "capture session is no longer active")
                        return
                    client_finalized = True
                    logger.info("browser asr ws %s declared a clean stop", capture_id)
                    try:
                        await websocket.send_json({"type": "capture_finalize_ack", "captureId": capture_id})
                    except Exception:  # noqa: BLE001 - the client may close immediately after sending
                        logger.info("browser asr ws %s closed before the finalize ack", capture_id)
                    continue
                if control.get("type") == "capture_recovery_complete" and recovery_complete_sink is not None:
                    try:
                        next_sequence = control.get("nextSequence")
                        next_sample = control.get("nextSample")
                        if type(next_sequence) is not int or type(next_sample) is not int:
                            raise ValueError("browser recovery cursors must be integers")
                        if next_sequence < 1 or next_sample < 0:
                            raise ValueError("browser recovery cursors are invalid")
                        receipt = await asyncio.to_thread(
                            recovery_complete_sink,
                            next_sequence,
                            next_sample,
                        )
                    except Exception as exc:
                        await _close(websocket, capture_id, 4410, f"unable to finalize browser audio recovery: {exc}")
                        return
                    await websocket.send_json({
                        "type": "capture_recovery_complete_ack",
                        "captureId": capture_id,
                        **receipt,
                    })
                    return
                await _close(websocket, capture_id, 1003, "unknown formal audio control message")
                return
            payload = message.get("bytes")
            if payload is None:
                await _close(websocket, capture_id, 1003, "non-binary frame")
                return
            if frame_ingress is not None:
                if len(payload) < 14:
                    await _close(websocket, capture_id, 1008, "formal audio frame header or PCM16 payload is missing")
                    return
                source_sequence, start_sample = struct.unpack_from("<IQ", payload)
                pcm = payload[12:]
                if source_sequence == 0:
                    await _close(websocket, capture_id, 1008, "formal audio sequence must start at one")
                    return
            else:
                source_sequence = 0
                start_sample = 0
                pcm = payload
            if not pcm or len(pcm) % 2:
                await _close(websocket, capture_id, 1008, "pcm16 alignment violation")
                return
            if len(pcm) > _MAX_FRAME_BYTES or len(payload) > _MAX_FRAME_BYTES + 12:
                await _close(websocket, capture_id, 1009, "frame too large")
                return
            if accepts_pcm is not None and not accepts_pcm():
                await _close(websocket, capture_id, 4409, "capture session stopped being the active browser capture")
                return
            if frame_ingress is not None:
                try:
                    receipt = await asyncio.to_thread(frame_ingress, source_sequence, start_sample, bytes(pcm))
                except Exception as exc:
                    marked_incomplete = False
                    if incomplete_sink is not None:
                        try:
                            marked_incomplete = await asyncio.to_thread(incomplete_sink, str(exc))
                            marked_incomplete = marked_incomplete is True
                        except Exception:
                            logger.exception("failed to mark browser capture %s incomplete", capture_id)
                    if marked_incomplete:
                        await websocket.send_json({"type": "capture_incomplete_ack", "captureId": capture_id})
                    await _close(websocket, capture_id, 4410, f"formal audio discontinuity or durable append failure: {exc}")
                    return
                durable_end = start_sample + len(pcm) // 2
                if (
                    receipt.get("ackSequence") != source_sequence
                    or receipt.get("durableSampleEnd") != durable_end
                ):
                    marked_incomplete = False
                    if incomplete_sink is not None:
                        try:
                            marked_incomplete = await asyncio.to_thread(
                                incomplete_sink,
                                "durable audio receipt did not match the submitted frame",
                            )
                            marked_incomplete = marked_incomplete is True
                        except Exception:
                            logger.exception("failed to mark browser capture %s incomplete", capture_id)
                    if marked_incomplete:
                        await websocket.send_json({"type": "capture_incomplete_ack", "captureId": capture_id})
                    await _close(websocket, capture_id, 4410, "durable audio receipt did not match the submitted frame")
                    return
                await websocket.send_json(receipt)
                continue
            try:
                browser_input.push_pcm(pcm)
            except (RuntimeError, ValueError) as exc:
                await _close(websocket, capture_id, 1008, f"speech worker rejected audio: {exc}")
                return
    except WebSocketDisconnect:
        if (
            not client_finalized
            and frame_ingress is not None
            and incomplete_sink is not None
            and accepts_pcm is not None
            and accepts_pcm()
        ):
            try:
                await asyncio.to_thread(incomplete_sink, "browser audio connection disconnected")
            except Exception:
                logger.exception("failed to persist browser audio disconnect for %s", capture_id)


@router.websocket("/ws/asr/cases/{case_id}/capture/{capture_id}")
async def browser_asr_capture_socket(
    websocket: WebSocket,
    case_id: str,
    capture_id: str,
):
    service = getattr(websocket.app.state, "asr_capture_service", None)
    ingest = getattr(service, "ingest_browser_frame", None)
    mark_incomplete = getattr(service, "mark_browser_capture_incomplete", None)
    complete_recovery = getattr(service, "complete_browser_capture_recovery", None)
    if not callable(ingest) or not callable(mark_incomplete):
        await _close(websocket, capture_id, 4403, "durable browser audio ingress unavailable")
        return
    await _stream_browser_pcm(
        websocket,
        capture_id=capture_id,
        accepts_pcm=lambda: _is_active_browser_capture(websocket, case_id, capture_id),
        frame_ingress=lambda sequence, start_sample, pcm: ingest(
            case_id, capture_id, sequence, start_sample, pcm
        ),
        incomplete_sink=lambda reason: mark_incomplete(case_id, capture_id, reason),
        recovery_complete_sink=(
            None
            if not callable(complete_recovery)
            else lambda next_sequence, next_sample: complete_recovery(
                case_id,
                capture_id,
                next_sequence,
                next_sample,
            )
        ),
    )


@router.websocket("/ws/asr/cases/{case_id}/question-preparation/{capture_id}")
async def browser_question_preparation_socket(
    websocket: WebSocket,
    case_id: str,
    capture_id: str,
):
    del case_id
    await _stream_browser_pcm(websocket, capture_id=capture_id)
