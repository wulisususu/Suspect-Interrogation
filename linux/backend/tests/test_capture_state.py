from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.capture_state import is_never_recorded


def _capture(**values) -> SimpleNamespace:
    return SimpleNamespace(
        audio_sample_count=values.get("audio_sample_count", 0),
        recording_status=values.get("recording_status", "PENDING"),
    )


def test_flags_a_capture_that_never_received_audio():
    assert is_never_recorded(_capture(audio_sample_count=0, recording_status="PENDING")) is True


@pytest.mark.parametrize(
    "values",
    [
        # 有音频但没收尾：这是真正的"未完成"，必须继续拦
        {"audio_sample_count": 16000, "recording_status": "PENDING"},
        # 录了一半被中断：更要拦
        {"audio_sample_count": 16000, "recording_status": "INCOMPLETE"},
        # 0 音频但已正常收尾：不再参与判断
        {"audio_sample_count": 0, "recording_status": "COMPLETE"},
        # 正在录（定稿会先停采集，这里只是防御）
        {"audio_sample_count": 0, "recording_status": "CAPTURING"},
    ],
)
def test_does_not_flag_captures_that_matter(values):
    assert is_never_recorded(_capture(**values)) is False


def test_handles_missing_columns_without_raising():
    # 字段缺失时按"不是空采集"处理：宁可多等一次，也不要把真采集当成空的跳过
    assert is_never_recorded(SimpleNamespace()) is False
