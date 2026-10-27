from __future__ import annotations

import base64
import binascii
import errno
import os
import signal
import socket
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ai.errors import AIError, ResourceBusyError, WorkerCrashedError
from app.ai.speech.protocol import ProtocolError, recv_frame, send_frame
from .funasr_runtime import DEFAULT_MODEL_ROOT, FunASRSpeechRuntime
from .session import SpeechSession
from .vad_progress import VadProgressSession


DEFAULT_SOCKET_PATH = Path("/run/suspect-interrogation/speech.sock")


@dataclass
class _SessionEntry:
    session: Any
    lock: threading.RLock


class SpeechWorkerServer:
    def __init__(self, socket_path: str | Path, runtime: Any, *, asr_stack: Any | None = None) -> None:
        self.socket_path = Path(socket_path)
        self.runtime = runtime
        # 非 None 时实时识别改走 asr-stack；funasr 仅保留声纹与 VAD 相关能力。
        self.asr_stack = asr_stack
        self._server: socket.socket | None = None
        self._owned_socket: tuple[int, int] | None = None
        self._stop = threading.Event()
        self._sessions: dict[str, _SessionEntry] = {}
        self._vad_sessions: dict[str, _SessionEntry] = {}
        self._sessions_lock = threading.RLock()
        self._runtime_lock = threading.RLock()
        self._client_threads: set[threading.Thread] = set()
        self._client_threads_lock = threading.Lock()

    def bind(self) -> None:
        if self._server is not None:
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._prepare_socket_path()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(os.fspath(self.socket_path))
            os.chmod(self.socket_path, 0o660)
            server.listen(16)
            server.settimeout(0.2)
            info = self.socket_path.lstat()
            self._owned_socket = (info.st_dev, info.st_ino)
            self._server = server
            self._stop.clear()
        except Exception:
            server.close()
            self._cleanup_socket_path()
            raise

    def serve_forever(self) -> None:
        server = self._server
        if server is None:
            raise RuntimeError("speech worker server is not bound")
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                thread = threading.Thread(target=self._handle_client_thread, args=(conn,), daemon=True)
                with self._client_threads_lock:
                    self._client_threads.add(thread)
                thread.start()
        finally:
            self._close_listener()
            self._join_client_threads()
            self._cleanup_socket_path()

    def stop(self) -> None:
        self._stop.set()
        self._close_listener()
        self._join_client_threads()
        with self._sessions_lock:
            self._sessions.clear()
            self._vad_sessions.clear()
        self._cleanup_socket_path()

    def _prepare_socket_path(self) -> None:
        try:
            info = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode):
            raise ResourceBusyError("speech worker path exists and is not a Unix socket", details={"socket": str(self.socket_path)})
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(0.2)
        try:
            probe.connect(os.fspath(self.socket_path))
        except OSError as exc:
            if exc.errno not in {errno.ECONNREFUSED, errno.ENOENT}:
                raise ResourceBusyError("cannot prove existing speech worker socket is stale", details={"socket": str(self.socket_path), "errno": exc.errno}) from exc
        else:
            raise ResourceBusyError("an active speech worker is already listening on the Unix socket", details={"socket": str(self.socket_path)})
        finally:
            probe.close()
        self.socket_path.unlink(missing_ok=True)

    def _handle_client_thread(self, conn: socket.socket) -> None:
        current = threading.current_thread()
        try:
            with conn:
                self._handle_connection(conn)
        finally:
            with self._client_threads_lock:
                self._client_threads.discard(current)

    def _handle_connection(self, conn: socket.socket) -> None:
        request_id = ""
        try:
            request = recv_frame(conn)
            request_id = str(request.get("request_id") or "")
            result = self._dispatch(request)
            response = {"request_id": request_id, "ok": True, "result": result}
        except AIError as exc:
            response = {"request_id": request_id, "ok": False, "error": {"code": exc.code, "message": exc.message, "details": dict(exc.details)}}
        except ProtocolError as exc:
            response = self._error_response(request_id, "WORKER_CRASHED", str(exc), {})
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            response = self._error_response(request_id, "AI_ERROR", str(exc), {"error_type": type(exc).__name__})
        except Exception as exc:
            response = self._error_response(request_id, "WORKER_CRASHED", "speech worker request failed unexpectedly", {"error_type": type(exc).__name__})
        try:
            send_frame(conn, response)
        except OSError:
            return

    def _dispatch(self, request: dict[str, Any]) -> Any:
        op = str(request.get("op") or "")
        if op == "health":
            with self._runtime_lock:
                health = dict(self.runtime.health())
            if self.asr_stack is not None:
                # 灰度期两套后端并存：把 asr-stack 的可用性合并进同一份 health，
                # 部署校验仍然按 models.asr / models.speaker 判断。
                health["backend"] = "asr_stack"
                health["asr_stack"] = {"url": self.asr_stack.ws_url, "configured": True}
                models = dict(health.get("models") or {})
                models["asr"] = True
                health["models"] = models
            with self._sessions_lock:
                health["sessions"] = len(self._sessions)
                health["vad_progress_sessions"] = len(self._vad_sessions)
            return health

        if op == "open_session":
            session_id = self._required_session_id(request)
            sample_rate = int(request.get("sample_rate") or 16000)
            base_sample = int(request.get("base_sample") or 0)
            speaker_backend = str(request.get("speaker_backend") or "eres2net_large").strip().lower()
            if speaker_backend != "eres2net_large":
                raise AIError("speaker_backend must be eres2net_large")
            with self._sessions_lock:
                if session_id in self._sessions:
                    raise ResourceBusyError("speech session is already open", details={"session_id": session_id})
                if self.asr_stack is not None:
                    from .asr_stack_session import AsrStackSpeechSession

                    session: Any = AsrStackSpeechSession(
                        session_id,
                        sample_rate,
                        self.asr_stack,
                        base_sample=base_sample,
                    )
                    session.open()
                else:
                    session = SpeechSession(
                        session_id,
                        sample_rate,
                        self.runtime,
                        speaker_backend_key=speaker_backend,
                        authoritative_speaker_backend_key="eres2net_large",
                        base_sample=base_sample,
                    )
                self._sessions[session_id] = _SessionEntry(session, threading.RLock())
            result = {
                "session_id": session_id,
                "sample_rate": sample_rate,
                "speaker_backend": speaker_backend,
                "backend": "asr_stack" if self.asr_stack is not None else "funasr",
            }
            return result

        if op == "push_pcm":
            session_id = self._required_session_id(request)
            entry = self._session_entry(session_id)
            with entry.lock, self._runtime_lock:
                events = entry.session.push_pcm(self._decode_pcm(request))
            return {"events": [event.to_dict() for event in events]}

        if op == "finalize_session":
            session_id = self._required_session_id(request)
            entry = self._session_entry(session_id)
            with entry.lock, self._runtime_lock:
                events = entry.session.finalize()
            return {"events": [event.to_dict() for event in events]}

        if op == "close_session":
            self._pop_session(self._sessions, self._required_session_id(request), "speech")
            return {}

        if op == "open_vad_session":
            session_id = self._required_session_id(request)
            sample_rate = int(request.get("sample_rate") or 16000)
            with self._sessions_lock:
                if session_id in self._vad_sessions:
                    raise ResourceBusyError("VAD progress session is already open", details={"session_id": session_id})
                session = VadProgressSession(session_id, sample_rate, self.runtime)
                self._vad_sessions[session_id] = _SessionEntry(session, threading.RLock())
            return session._snapshot()

        if op == "push_vad_pcm":
            session_id = self._required_session_id(request)
            entry = self._vad_session_entry(session_id)
            with entry.lock, self._runtime_lock:
                return entry.session.push_pcm(self._decode_pcm(request))

        if op == "finalize_vad_session":
            session_id = self._required_session_id(request)
            entry = self._vad_session_entry(session_id)
            with entry.lock, self._runtime_lock:
                return entry.session.finalize()

        if op == "close_vad_session":
            self._pop_session(self._vad_sessions, self._required_session_id(request), "VAD progress")
            return {}

        if op == "speech_segments":
            pcm = self._decode_pcm(request)
            sample_rate = int(request.get("sample_rate") or 16000)
            with self._runtime_lock:
                segments = self.runtime.vad(pcm, sample_rate)
            return {"segments": segments, "sample_rate": sample_rate}

        if op == "extract_embedding":
            pcm = self._decode_pcm(request)
            sample_rate = int(request.get("sample_rate") or 16000)
            backend_key = request.get("backend_key")
            with self._runtime_lock:
                if backend_key is None:
                    return self.runtime.speaker_embedding(pcm, sample_rate)
                return self.runtime.speaker_embedding(pcm, sample_rate, backend_key=str(backend_key))

        raise AIError(f"unknown speech operation: {op}", details={"op": op})

    @staticmethod
    def _error_response(request_id: str, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {"request_id": request_id, "ok": False, "error": {"code": code, "message": message, "details": details}}

    @staticmethod
    def _required_session_id(request: dict[str, Any]) -> str:
        session_id = str(request.get("session_id") or "")
        if not session_id:
            raise AIError("session_id is required")
        return session_id

    @staticmethod
    def _decode_pcm(request: dict[str, Any]) -> bytes:
        value = request.get("pcm_b64")
        if not isinstance(value, str):
            raise AIError("pcm_b64 is required")
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise AIError("pcm_b64 is invalid base64") from exc

    def _session_entry(self, session_id: str) -> _SessionEntry:
        with self._sessions_lock:
            entry = self._sessions.get(session_id)
        if entry is None:
            raise AIError("speech session is not open", details={"session_id": session_id})
        return entry

    def _vad_session_entry(self, session_id: str) -> _SessionEntry:
        with self._sessions_lock:
            entry = self._vad_sessions.get(session_id)
        if entry is None:
            raise AIError("VAD progress session is not open", details={"session_id": session_id})
        return entry

    def _pop_session(self, collection: dict[str, _SessionEntry], session_id: str, label: str) -> _SessionEntry:
        with self._sessions_lock:
            entry = collection.pop(session_id, None)
        if entry is None:
            raise AIError(f"{label} session is not open", details={"session_id": session_id})
        # asr-stack 会话背后是一条真实的 WebSocket，不主动关会一直占着对端会话。
        close = getattr(entry.session, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - 关闭失败不该阻断会话清理
                logger.warning("关闭 %s 会话失败：%s", label, session_id, exc_info=True)
        return entry

    def _close_listener(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def _join_client_threads(self) -> None:
        current = threading.current_thread()
        with self._client_threads_lock:
            threads = list(self._client_threads)
        for thread in threads:
            if thread is not current:
                thread.join(timeout=1.0)

    def _cleanup_socket_path(self) -> None:
        owned = self._owned_socket
        if owned is None:
            return
        try:
            info = self.socket_path.lstat()
        except FileNotFoundError:
            self._owned_socket = None
            return
        if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == owned:
            self.socket_path.unlink(missing_ok=True)
        self._owned_socket = None


def main() -> int:
    socket_path = Path(os.environ.get("SUSPECT_SPEECH_SOCKET", str(DEFAULT_SOCKET_PATH)))
    model_root = Path(os.environ.get("SUSPECT_FUNASR_MODEL_ROOT", str(DEFAULT_MODEL_ROOT)))
    backend = (os.environ.get("SUSPECT_SPEECH_BACKEND") or "funasr").strip().lower()

    asr_stack = None
    if backend == "asr_stack":
        from .asr_stack_session import endpoint_from_env

        asr_stack = endpoint_from_env(dict(os.environ))
        if asr_stack is None:
            raise SystemExit(
                "SUSPECT_SPEECH_BACKEND=asr_stack 需要同时设置 "
                "SUSPECT_ASR_STACK_WS_URL 与 SUSPECT_ASR_STACK_KEY"
            )
        # 实时识别交给 asr-stack 后，FunASR 只承担声纹与 VAD，省掉两套 ASR 模型的常驻。
        runtime = FunASRSpeechRuntime(model_root=model_root, profile="speaker_vad")
    else:
        runtime = FunASRSpeechRuntime(model_root=model_root)
    runtime.load()
    server = SpeechWorkerServer(socket_path, runtime, asr_stack=asr_stack)

    def handle_signal(signum: int, frame: Any) -> None:
        del signum, frame
        server.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    server.bind()
    try:
        server.serve_forever()
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
