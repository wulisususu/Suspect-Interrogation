from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.repositories import sessions as session_repo
from app.services.document_service import DocumentService
from app.services.message_service import MessageService
from app.services.session_service import SessionService
from app.websocket.protocol import ClientEnvelope, SUPPORTED_CLIENT_EVENTS, server_envelope

router = APIRouter()

# Compatibility registry for the Linux HAL bridge. The authoritative transport
# registry remains ConnectionManager; this single-socket view exists so hardware
# events from the standalone HAL can be forwarded without replacing the core
# WebSocket protocol.
connections: dict[str, WebSocket] = {}


async def broadcast_hardware_event(event: dict[str, Any]) -> None:
    """Broadcast a normalized HAL event to active interrogation sockets.

    This preserves the hardware workstream's public bridge contract while the
    main ConnectionManager remains responsible for durable session protocol,
    sequence numbers and state synchronization.
    """
    stale: list[str] = []
    message = {"type": "hardware_event", "event": event}
    for session_id, websocket in tuple(connections.items()):
        try:
            await websocket.send_json(message)
        except Exception:
            stale.append(session_id)
    for session_id in stale:
        connections.pop(session_id, None)


class ConnectionManager:
    """Owns transport handles only; persisted interrogation truth remains in SQLite."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._sequence: dict[str, int] = defaultdict(int)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].append(websocket)
        connections[session_id] = websocket

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        peers = self._connections.get(session_id, [])
        if websocket in peers:
            peers.remove(websocket)
        if not peers:
            self._connections.pop(session_id, None)
            connections.pop(session_id, None)
        elif connections.get(session_id) is websocket:
            connections[session_id] = peers[-1]

    def next_seq(self, session_id: str) -> int:
        self._sequence[session_id] += 1
        return self._sequence[session_id]

    async def send(self, websocket: WebSocket, session_id: str, event: str, payload: dict | None = None) -> None:
        await websocket.send_json(server_envelope(session_id, event, self.next_seq(session_id), payload))

    async def broadcast(self, session_id: str, event: str, payload: dict | None = None) -> None:
        message = server_envelope(session_id, event, self.next_seq(session_id), payload)
        stale: list[WebSocket] = []
        for peer in list(self._connections.get(session_id, [])):
            try:
                await peer.send_json(message)
            except Exception:
                stale.append(peer)
        for peer in stale:
            self.disconnect(session_id, peer)

    async def broadcast_all(self, event: str, payload: dict | None = None) -> None:
        for session_id in list(self._connections):
            await self.broadcast(session_id, event, payload)


def _state_sync(websocket: WebSocket, session_id: str) -> dict:
    factory = websocket.app.state.session_factory
    db = factory()
    try:
        session = session_repo.get_by_id(db, session_id)
        if session is None:
            return {"error": {"code": "SESSION_NOT_FOUND", "message": "审讯会话不存在"}}
        session_state = SessionService(db).get_state(session.case_id)
        messages = MessageService(db).list(session.case_id)
        document = DocumentService(db).status(session.case_id)
        return {
            "case_id": session.case_id,
            "session": session_state,
            "messages": messages,
            "document": document,
        }
    finally:
        db.close()


@router.websocket("/ws/interrogation/{session_id}")
async def interrogation_socket(websocket: WebSocket, session_id: str):
    manager: ConnectionManager = websocket.app.state.websocket_manager
    await manager.connect(session_id, websocket)
    try:
        sync = _state_sync(websocket, session_id)
        if "error" in sync:
            await manager.send(websocket, session_id, "PROTOCOL_ERROR", sync["error"])
            await websocket.close(code=4404)
            return
        await manager.send(websocket, session_id, "STATE_SYNC", sync)

        while True:
            raw = await websocket.receive_json()
            try:
                incoming = ClientEnvelope.model_validate(raw)
                if incoming.session_id is not None and incoming.session_id != session_id:
                    raise ValueError("session_id does not match websocket path")
                if incoming.event not in SUPPORTED_CLIENT_EVENTS:
                    raise ValueError(f"unsupported event: {incoming.event}")
            except (ValidationError, ValueError) as exc:
                await manager.send(websocket, session_id, "PROTOCOL_ERROR", {
                    "code": "INVALID_WEBSOCKET_ENVELOPE",
                    "message": str(exc),
                })
                continue

            if incoming.event in {"STATE_SYNC_REQUEST", "SESSION_RESYNC"}:
                sync = _state_sync(websocket, session_id)
                if "error" in sync:
                    await manager.send(websocket, session_id, "PROTOCOL_ERROR", sync["error"])
                    await websocket.close(code=4404)
                    return
                await manager.send(websocket, session_id, "STATE_SYNC", sync)
                continue

            # Device/ASR/recording/signature transport events are broadcast to all
            # connected views. Durable domain state for those features is written by
            # their REST/services layer, not by this connection registry.
            await manager.broadcast(session_id, incoming.event, incoming.payload)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(session_id, websocket)
