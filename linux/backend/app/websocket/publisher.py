"""把领域状态变更推给已连接的实时视图。

REST 处理函数跑在 FastAPI 的线程池里，不能直接 await 广播；这里统一走
`create_app` 注册在 `app.state.publish_session_event` 上的发布器（内部用
`loop.call_soon_threadsafe` 投递到事件循环）。发布器缺失、会话 ID 缺失或
事件循环尚未启动时静默跳过——实时推送是增强能力，不能反过来让写操作失败。
"""

from __future__ import annotations

from typing import Any, Mapping


def publish_state(
    app_state: Any,
    session_id: str | None,
    event: str,
    payload: Mapping[str, Any],
) -> None:
    """向指定审讯会话的所有已连接视图广播一条事件。"""
    publisher = getattr(app_state, "publish_session_event", None)
    if publisher is None or not session_id:
        return
    try:
        publisher(str(session_id), event, dict(payload))
    except Exception:  # pragma: no cover - 推送失败不能影响已提交的业务写
        return


def publish_session_state(app_state: Any, session: Mapping[str, Any] | None) -> None:
    """广播会话状态（开始 / 暂停 / 恢复 / 结束 / 切阶段）。

    payload 直接用 `session_dict` 的 camelCase 形态，前端 SESSION_STATE 处理
    逻辑可以整包合并进本地 session。
    """
    if not session:
        return
    publish_state(app_state, session.get("id"), "SESSION_STATE", session)


def publish_recording_state(app_state: Any, case_id: str, status: Mapping[str, Any]) -> None:
    """广播录音状态变化。

    只发轻量信号（running / captureSessionId），片段列表与计量字段仍由前端
    调用 REST 状态接口归一化获取，避免在两条链路上各维护一份序列化。
    """
    payload = {
        "caseId": case_id,
        "captureSessionId": status.get("captureSessionId"),
        "running": bool(status.get("active") or status.get("running")),
        "status": status.get("status"),
    }
    publish_state(app_state, status.get("interrogationSessionId"), "RECORDING_STATE", payload)
