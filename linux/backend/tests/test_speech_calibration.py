from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.errors import BackendUnavailableError
from app.ai.registry import ModelRegistry
from app.ai.speech.types import SpeechEventType
from app.ai.supervisor import AISupervisor
from speech_worker.funasr_runtime import FunASRSpeechRuntime
from speech_worker.session import SpeechSession


def _registry(tmp_path: Path) -> ModelRegistry:
    config = tmp_path / "model-registry.yaml"
    config.write_text(
        '''{
          "models": {
            "asr.default": {"kind":"asr","backend":"speech-worker","path":"asr/default","architecture":"paraformer","required_files":["model.onnx"],"device":"cpu","context":0,"memory_mb":512}
          }
        }''',
        encoding="utf-8",
    )
    return ModelRegistry.load(config, tmp_path / "models")


def test_calibration_uses_production_env_names_and_missing_values_are_not_configured(monkeypatch):
    from app.ai.speech.calibration import SpeakerCalibration

    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    # Legacy/unscoped names must not silently configure production biometrics.
    monkeypatch.setenv("SPEAKER_ACCEPT_THRESHOLD", "0.70")
    monkeypatch.setenv("SPEAKER_MARGIN", "0.10")

    calibration = SpeakerCalibration.from_env()

    assert calibration.accept_threshold is None
    assert calibration.margin is None
    assert calibration.configured is False
    assert calibration.state == "NOT_CONFIGURED"


def test_model_baselines_follow_the_selected_speaker_backend(monkeypatch):
    from app.ai.speech.calibration import (
        ERES2NET_LARGE_BASELINE_THRESHOLD,
        LEGACY_XVECTOR_BASELINE_THRESHOLD,
        SpeakerCalibration,
    )

    monkeypatch.delenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_MARGIN", raising=False)
    monkeypatch.delenv("SUSPECT_SPEAKER_BASELINE_THRESHOLD", raising=False)

    eres2net = SpeakerCalibration.from_env(backend_key="eres2net_large")
    xvector = SpeakerCalibration.from_env(backend_key="xvector")

    # ERes2Net-large's local ModelScope card declares ``thr: 0.372``;
    # XVector retains its own historical operating point.
    assert ERES2NET_LARGE_BASELINE_THRESHOLD == pytest.approx(0.372)
    assert LEGACY_XVECTOR_BASELINE_THRESHOLD == pytest.approx(0.9465)
    assert eres2net.effective_threshold == pytest.approx(0.372)
    assert xvector.effective_threshold == pytest.approx(0.9465)
    assert eres2net.threshold_source == "MODEL_BASELINE"


def test_calibration_rejects_non_finite_or_out_of_range_values(monkeypatch):
    from app.ai.speech.calibration import SpeakerCalibration

    invalid_pairs = [
        ("-0.01", "0.10"),
        ("1.01", "0.10"),
        ("0.70", "-0.01"),
        ("0.70", "1.01"),
        ("nan", "0.10"),
        ("inf", "0.10"),
    ]
    for threshold, margin in invalid_pairs:
        monkeypatch.setenv("SUSPECT_SPEAKER_ACCEPT_THRESHOLD", threshold)
        monkeypatch.setenv("SUSPECT_SPEAKER_MARGIN", margin)
        with pytest.raises(ValueError, match="0\.0.*1\.0"):
            SpeakerCalibration.from_env()


def test_eres2net_load_failure_keeps_asr_and_vad_available(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")
    model_root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad"):
        (model_root / name).mkdir(parents=True)
    eres_dir = model_root / "eres2net-large"
    eres_dir.mkdir()
    (eres_dir / "pretrained_eres2net.pt").write_bytes(b"fixture")

    class FakeModel:
        def generate(self, **_kwargs):
            return []

    def factory(*, model: str, **_kwargs):
        return FakeModel()

    def eres_factory(_path: Path):
        raise RuntimeError("eres2net unavailable")

    runtime = FunASRSpeechRuntime(model_root=model_root, eres2net_model_dir=eres_dir, model_factory=factory, eres2net_model_factory=eres_factory)
    runtime.load()

    health = runtime.health()
    assert health["models"] == {"asr": True, "asr_streaming": False, "vad": True, "speaker": False}
    assert runtime.asr_model is not None
    assert runtime.vad_model is not None
    assert runtime.speaker_model is None


def test_eres2net_inference_failure_does_not_discard_successful_asr():
    class Runtime:
        def vad_stream(self, _pcm, _sample_rate, *, cache, is_final, chunk_size_ms):
            del cache, is_final, chunk_size_ms
            return [[0, 1000]]

        def transcribe(self, _pcm, _sample_rate):
            return {"text": "这是有效转写", "confidence": 0.91, "model_id": "paraformer"}

        def speaker_embedding(self, _pcm, _sample_rate, *, backend_key=None):
            raise BackendUnavailableError("eres2net inference failed")

    session = SpeechSession("s-1", 16000, Runtime(), pre_roll_ms=1200)
    events = session.push_pcm(b"\x01\x00" * 16000)

    assert any(event.type is SpeechEventType.ASR_FINAL and event.text == "这是有效转写" for event in events)
    assert not any(event.type is SpeechEventType.SPEAKER_RESULT for event in events)


def test_supervisor_reports_speaker_failure_independently_from_asr_and_vad(tmp_path: Path):
    class PartialSpeechClient:
        def health(self):
            return {
                "status": "degraded",
                "models": {"asr": True, "asr_streaming": False, "vad": True, "speaker": False},
            }

    supervisor = AISupervisor(
        _registry(tmp_path),
        mode="real",
        speech_client=PartialSpeechClient(),
        speaker_accept_threshold=0.70,
        speaker_margin=0.10,
    )
    try:
        capabilities = supervisor.capabilities()
        assert capabilities["asr"]["speech_state"] == "AVAILABLE"
        assert capabilities["vad"]["state"] == "AVAILABLE"
        assert capabilities["speaker"]["state"] == "ERROR"
        assert capabilities["speaker"]["threshold_configured"] is True
        assert capabilities["speaker"]["margin_configured"] is True
    finally:
        supervisor.shutdown()
