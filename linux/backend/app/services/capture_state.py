"""判断一条采集是不是"从未录到任何音频"。

浏览器点开录音后又立刻返回、或者 WS 还没建立就退出，会留下一条
``recording_status=PENDING``、``audio_sample_count=0`` 的采集行。它既没有音频
要归档，也永远不会产生 ASR 完成回调，如果把它们当作"未完成"来等，定稿就会固定
等满 drain 超时然后返回 504 —— 现场表现就是长按定稿后一直转圈、最后什么也没发生。
"""

from __future__ import annotations

from typing import Any


def is_never_recorded(capture: Any) -> bool:
    """采集行存在但从未收到任何音频（不是"录了一半"，也不是"正在录"）。"""
    sample_count = int(getattr(capture, "audio_sample_count", 0) or 0)
    recording_status = str(getattr(capture, "recording_status", "") or "").upper()
    return sample_count == 0 and recording_status == "PENDING"
