from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.services.asr_capture_service import AsrCaptureService


def _service() -> AsrCaptureService:
    service = object.__new__(AsrCaptureService)
    service._lock = threading.Lock()
    service._active = {}
    service.reaped = []
    service.stop = lambda case_id: service.reaped.append(case_id)  # type: ignore[method-assign]
    return service


def _live_thread() -> threading.Thread:
    thread = threading.Thread(target=lambda: time.sleep(0.5), daemon=True)
    thread.start()
    return thread


def _runtime(case_id: str, *, idle_seconds: float, alive: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        case_id=case_id,
        thread=_live_thread() if alive else None,
        last_frame_at=time.monotonic() - idle_seconds,
    )


def test_reaps_a_capture_that_stopped_sending_audio():
    service = _service()
    service._active["CASE-OLD"] = _runtime("CASE-OLD", idle_seconds=300)

    assert service._reap_idle_captures() == ["CASE-OLD"]
    assert service.reaped == ["CASE-OLD"]


def test_keeps_a_capture_that_is_still_sending_audio():
    service = _service()
    service._active["CASE-LIVE"] = _runtime("CASE-LIVE", idle_seconds=1)

    assert service._reap_idle_captures() == []
    assert service.reaped == []


def test_can_skip_the_case_that_is_about_to_start():
    service = _service()
    service._active["CASE-SELF"] = _runtime("CASE-SELF", idle_seconds=300)
    service._active["CASE-OTHER"] = _runtime("CASE-OTHER", idle_seconds=300)

    assert service._reap_idle_captures(exclude_case_id="CASE-SELF") == ["CASE-OTHER"]
    assert service.reaped == ["CASE-OTHER"]


def test_ignores_captures_whose_thread_already_exited():
    service = _service()
    service._active["CASE-DEAD"] = _runtime("CASE-DEAD", idle_seconds=300, alive=False)

    # 线程已经结束的 runtime 不会挡住新录音，无需再收尾
    assert service._reap_idle_captures() == []


def test_reap_survives_a_failing_stop():
    service = _service()

    def boom(case_id: str) -> None:
        raise RuntimeError(f"cannot stop {case_id}")

    service.stop = boom  # type: ignore[method-assign]
    service._active["CASE-BAD"] = _runtime("CASE-BAD", idle_seconds=300)

    # 收尾失败不能让调用方（开始录音）跟着失败
    assert service._reap_idle_captures() == ["CASE-BAD"]
