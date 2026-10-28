from __future__ import annotations

import base64
import socket
import uuid
from pathlib import Path
from typing import Any

from ..errors import (
    AIError,
    BackendUnavailableError,
    ModelNotInstalledError,
    ResourceBusyError,
    WorkerCancelledError,
    WorkerCrashedError,
    WorkerTimeoutError,
)
from .protocol import MAX_MESSAGE_BYTES, ProtocolError, recv_frame, send_frame
from .types import SpeechEvent


_ERROR_TYPES: dict[str, type[AIError]] = {
    AIError.code: AIError,
    ModelNotInstalledError.code: ModelNotInstalledError,
    BackendUnavailableError.code: BackendUnavailableError,
    WorkerTimeoutError.code: WorkerTimeoutError,
    WorkerCancelledError.code: WorkerCancelledError,
    WorkerCrashedError.code: WorkerCrashedError,
    ResourceBusyError.code: ResourceBusyError,
}


class SpeechWorkerClient:
    def __init__(
        self,
        socket_path: str | Path,
        *,
        timeout: float = 5.0,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.timeout = max(0.001, float(timeout))
        self.max_message_bytes = int(max_message_bytes)

    def health(self) -> dict[str, Any]:
        return self._require_dict(self._request("health"))

    def open_session(
        self,
        session_id: str,
        sample_rate: int = 16000,
        *,
        speaker_backend: str | None = None,
        authoritative_backend: str | None = None,
        base_sample: int = 0,
    ) -> dict[str, Any]:
        backend_key = str(speaker_backend or "eres2net_large").strip().lower()
        if backend_key != "eres2net_large":
            raise ValueError("speaker_backend must be eres2net_large")
        authority_key = (
            None
            if authoritative_backend is None
            else str(authoritative_backend).strip().lower()
        )
        if authority_key is not None and authority_key != backend_key:
            raise ValueError("authoritative_backend must match the single speaker backend")
        if int(base_sample) < 0:
            raise ValueError("base_sample cannot be negative")

        payload: dict[str, Any] = {
            "session_id": session_id,
            "sample_rate": int(sample_rate),
            "speaker_backend": backend_key,
            "base_sample": int(base_sample),
        }
        return self._require_dict(self._request("open_session", **payload))

    def push_pcm(self, session_id: str, pcm: bytes) -> list[SpeechEvent]:
        result = self._request(
            "push_pcm",
            session_id=session_id,
            pcm_b64=base64.b64encode(pcm).decode("ascii"),
        )
        return self._events(result)

    def finalize_session(self, session_id: str) -> list[SpeechEvent]:
        return self._events(self._request("finalize_session", session_id=session_id))

    def close_session(self, session_id: str) -> None:
        self._request("close_session", session_id=session_id)

    def open_vad_session(self, session_id: str, sample_rate: int = 16000) -> dict[str, Any]:
        return self._require_dict(
            self._request("open_vad_session", session_id=session_id, sample_rate=int(sample_rate))
        )

    def push_vad_pcm(self, session_id: str, pcm: bytes) -> dict[str, Any]:
        return self._require_dict(
            self._request(
                "push_vad_pcm",
                session_id=session_id,
                pcm_b64=base64.b64encode(pcm).decode("ascii"),
            )
        )

    def finalize_vad_session(self, session_id: str) -> dict[str, Any]:
        return self._require_dict(self._request("finalize_vad_session", session_id=session_id))

    def close_vad_session(self, session_id: str) -> None:
        self._request("close_vad_session", session_id=session_id)

    def speech_segments(self, pcm: bytes, sample_rate: int = 16000) -> list[list[int]]:
        result = self._require_dict(
            self._request(
                "speech_segments",
                sample_rate=int(sample_rate),
                pcm_b64=base64.b64encode(pcm).decode("ascii"),
            )
        )
        segments = result.get("segments")
        if not isinstance(segments, list):
            raise WorkerCrashedError("speech worker VAD result must contain a segment array")
        normalized: list[list[int]] = []
        for item in segments:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise WorkerCrashedError("speech worker VAD segment must contain [start_ms, end_ms]")
            try:
                start_ms = int(item[0])
                end_ms = int(item[1])
            except (TypeError, ValueError) as exc:
                raise WorkerCrashedError("speech worker VAD segment bounds must be integers") from exc
            if start_ms < 0 or end_ms < start_ms:
                raise WorkerCrashedError("speech worker VAD segment bounds are invalid")
            normalized.append([start_ms, end_ms])
        return normalized

    def extract_embedding(
        self,
        pcm: bytes,
        sample_rate: int = 16000,
        *,
        backend: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sample_rate": int(sample_rate),
            "pcm_b64": base64.b64encode(pcm).decode("ascii"),
        }
        backend_key = str(backend or "eres2net_large").strip().lower()
        if backend_key != "eres2net_large":
            raise ValueError("speaker embedding backend must be eres2net_large")
        payload["backend_key"] = backend_key
        return self._require_dict(self._request("extract_embedding", **payload))

    def _request(self, op: str, **payload: Any) -> Any:
        if not hasattr(socket, "AF_UNIX"):
            raise BackendUnavailableError(
                "speech worker requires an AF_UNIX socket runtime",
                details={"op": op, "socket": str(self.socket_path)},
            )
        request_id = uuid.uuid4().hex
        request = {"request_id": request_id, "op": op, **payload}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(str(self.socket_path))
                send_frame(sock, request, max_message_bytes=self.max_message_bytes)
                response = recv_frame(sock, max_message_bytes=self.max_message_bytes)
        except socket.timeout as exc:
            raise WorkerTimeoutError(
                f"speech worker timed out during {op}",
                details={"op": op, "socket": str(self.socket_path)},
            ) from exc
        except ProtocolError as exc:
            raise WorkerCrashedError(
                f"speech worker returned an invalid protocol response during {op}",
                details={"op": op, "socket": str(self.socket_path)},
            ) from exc
        except OSError as exc:
            raise BackendUnavailableError(
                f"speech worker socket is unavailable during {op}",
                details={"op": op, "socket": str(self.socket_path)},
            ) from exc

        if response.get("request_id") != request_id:
            raise WorkerCrashedError(
                "speech worker response request_id mismatch",
                details={"op": op, "socket": str(self.socket_path)},
            )
        if not isinstance(response.get("ok"), bool):
            raise WorkerCrashedError(
                "speech worker response is missing boolean ok",
                details={"op": op, "socket": str(self.socket_path)},
            )
        if response["ok"]:
            return response.get("result")
        self._raise_worker_error(response, op=op)
        raise AssertionError("unreachable")

    def _raise_worker_error(self, response: dict[str, Any], *, op: str) -> None:
        error = response.get("error")
        if not isinstance(error, dict):
            raise WorkerCrashedError(
                "speech worker error response is malformed",
                details={"op": op, "socket": str(self.socket_path)},
            )
        code = str(error.get("code") or AIError.code)
        message = str(error.get("message") or "speech worker request failed")
        details = error.get("details")
        if not isinstance(details, dict):
            details = {}
        error_type = _ERROR_TYPES.get(code, AIError)
        raise error_type(message, details=details)

    @staticmethod
    def _require_dict(result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise WorkerCrashedError("speech worker result must be a JSON object")
        return result

    @staticmethod
    def _events(result: Any) -> list[SpeechEvent]:
        payload = result.get("events") if isinstance(result, dict) else result
        if not isinstance(payload, list):
            raise WorkerCrashedError("speech worker event result must be a JSON array")
        try:
            return [SpeechEvent.from_dict(item) for item in payload]
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkerCrashedError("speech worker returned a malformed event") from exc
