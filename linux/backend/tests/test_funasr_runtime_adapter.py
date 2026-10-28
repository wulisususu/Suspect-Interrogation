from __future__ import annotations

import math
from pathlib import Path

import pytest

from app.ai.errors import BackendUnavailableError, ModelNotInstalledError, WorkerCrashedError
from speech_worker.funasr_runtime import FunASRSpeechRuntime


class FakeAutoModel:
    calls: list[dict] = []
    outputs: dict[str, object] = {}
    fail_for: dict[str, Exception] = {}

    def __init__(self, **kwargs):
        name = Path(kwargs["model"]).name
        self.name = name
        self.generate_calls: list[dict] = []
        self.outputs_override: object | None = None
        type(self).calls.append(dict(kwargs))
        failure = type(self).fail_for.get(name)
        if failure is not None:
            raise failure

    def generate(self, **kwargs):
        self.generate_calls.append(dict(kwargs))
        value = self.outputs_override if self.outputs_override is not None else type(self).outputs.get(self.name)
        if isinstance(value, Exception):
            raise value
        return value


class FakeLegacySpeaker:
    def __init__(self) -> None:
        self.generate_calls: list[dict] = []

    def generate(self, **kwargs):
        self.generate_calls.append(dict(kwargs))
        return [{"spk_embedding": [[3.0, 4.0]]}]


class FakeEResModel:
    def __init__(self) -> None:
        self.waveforms: list[list[float]] = []

    def extract_embedding(self, waveform):
        self.waveforms.append(list(waveform))
        return [3.0, 4.0]


@pytest.fixture(autouse=True)
def reset_fake_model(monkeypatch):
    monkeypatch.setenv("SUSPECT_LEGACY_VOICEPRINT_ENABLED", "true")
    FakeAutoModel.calls = []
    FakeAutoModel.fail_for = {}
    FakeAutoModel.outputs = {
        "paraformer": [{"text": "测试文本", "confidence": 0.91}],
        "fsmn-vad": [{"value": [[120, 820], [1000, 1450]]}],
        "xvector": [{"spk_embedding": [[3.0, 4.0]]}],
    }


def _loaded_runtime(tmp_path: Path) -> FunASRSpeechRuntime:
    root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad"):
        (root / name).mkdir(parents=True, exist_ok=True)
    eres_dir = tmp_path / "eres2net-large"
    eres_dir.mkdir()
    (eres_dir / "local-checkpoint.bin").write_bytes(b"local-only")
    runtime = FunASRSpeechRuntime(
        model_root=root,
        model_factory=FakeAutoModel,
        eres2net_model_dir=eres_dir,
        eres2net_model_factory=lambda path: FakeEResModel(),
    )
    runtime.load()
    return runtime


def test_default_model_paths_are_stable_opt_layout(monkeypatch):
    monkeypatch.setattr(Path, "is_dir", lambda self: self.name in {"paraformer", "fsmn-vad"})
    runtime = FunASRSpeechRuntime(model_factory=FakeAutoModel)
    runtime.load()

    assert runtime.model_root == Path("/opt/suspect-interrogation/models/funasr")
    assert [Path(call["model"]) for call in FakeAutoModel.calls] == [
        runtime.model_root / "paraformer",
        runtime.model_root / "fsmn-vad",
    ]
    for call in FakeAutoModel.calls:
        assert call["device"] == "cpu"
        assert call["disable_update"] is True
        assert call["disable_pbar"] is True
    vad_call = next(call for call in FakeAutoModel.calls if call["model"].endswith("fsmn-vad"))
    assert vad_call["max_single_segment_time"] == 5000


def test_streaming_model_id_health_uses_configured_model(monkeypatch):
    model_id = "damo/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online"
    monkeypatch.setenv("SUSPECT_FUNASR_STREAMING_MODEL_ID", model_id)
    runtime = FunASRSpeechRuntime(model_factory=FakeAutoModel)

    assert runtime.health()["asr_streaming"]["model_id"] == model_id


def test_vad_and_asr_outputs_are_normalized_without_fabricated_partials(tmp_path: Path):
    runtime = _loaded_runtime(tmp_path)
    pcm = b"\x00\x00" * 1600

    assert runtime.vad(pcm, 16000) == [[120, 820], [1000, 1450]]
    result = runtime.transcribe(pcm, 16000)
    assert result == {"text": "测试文本", "confidence": pytest.approx(0.91)}
    assert "partial" not in result

    vad_call = runtime.vad_model.generate_calls[-1]
    asr_call = runtime.asr_model.generate_calls[-1]
    import numpy as np

    expected = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    assert isinstance(vad_call["input"], np.ndarray) and vad_call["input"].dtype == np.float32
    assert np.array_equal(vad_call["input"], expected)
    assert vad_call["fs"] == 16000
    assert isinstance(asr_call["input"], np.ndarray) and np.array_equal(asr_call["input"], expected)
    assert asr_call["fs"] == 16000


def test_pcm_starting_with_mp3_sync_bytes_is_converted_not_container_decoded(tmp_path: Path):
    """MP3 帧同步字节(0xFF 0xFx, 响亮负样本常见)不得触发 FunASR 的容器解码分支。"""
    import numpy as np

    runtime = _loaded_runtime(tmp_path)
    pcm = b"\xff\xfb\x90\x44" + b"\x00\x00" * 1596

    assert runtime.vad(pcm, 16000) == [[120, 820], [1000, 1450]]
    result = runtime.transcribe(pcm, 16000)
    assert result["text"] == "测试文本"

    vad_call = runtime.vad_model.generate_calls[-1]
    asr_call = runtime.asr_model.generate_calls[-1]
    for call in (vad_call, asr_call):
        assert not isinstance(call["input"], bytes)
        assert isinstance(call["input"], np.ndarray) and call["input"].dtype == np.float32

    runtime.vad_stream(pcm, 16000, cache={}, is_final=False)
    stream_call = runtime.vad_model.generate_calls[-1]
    assert not isinstance(stream_call["input"], bytes)


def test_streaming_vad_passes_only_new_pcm_and_session_cache(tmp_path: Path):
    runtime = _loaded_runtime(tmp_path)
    cache: dict = {}
    runtime.vad_model.outputs_override = [{"value": [[25, -1]]}]
    chunk = b"\x01\x00" * 3200

    events = runtime.vad_stream(chunk, 16000, cache=cache, is_final=False, chunk_size_ms=200)
    assert events == [[25, -1]]
    call = runtime.vad_model.generate_calls[-1]
    import numpy as np

    expected = np.frombuffer(chunk, dtype="<i2").astype(np.float32) / 32768.0
    assert np.array_equal(call["input"], expected)
    assert call["cache"] is cache
    assert call["max_single_segment_time"] == 5000
    assert call["is_final"] is False
    assert call["chunk_size"] == 200


def test_streaming_asr_uses_600ms_output_chunks(tmp_path: Path):
    runtime = _loaded_runtime(tmp_path)
    streaming_model = FakeAutoModel(model="paraformer-streaming")
    streaming_model.outputs_override = [{"text": "实时字幕"}]
    runtime.streaming_asr_model = streaming_model

    result = runtime.transcribe_stream(b"\x01\x00" * 4800, 16000, cache={}, is_final=False)

    assert result == "实时字幕"
    assert streaming_model.generate_calls[-1]["chunk_size"] == [0, 10, 5]
    assert streaming_model.generate_calls[-1]["encoder_chunk_look_back"] == 4


def test_speaker_embedding_is_flat_normalized_float_list(tmp_path: Path):
    runtime = _loaded_runtime(tmp_path)
    result = runtime.speaker_embedding(b"\x00\x00" * 1600, 16000)

    embedding = result["embedding"]
    assert result["backend_key"] == "eres2net_large"
    assert result["model_id"] == "iic/speech_eres2net_large_200k_sv_zh-cn_16k-common"
    assert embedding == pytest.approx([0.6, 0.8], abs=1e-6)
    assert all(isinstance(value, float) for value in embedding)
    assert math.sqrt(sum(value * value for value in embedding)) == pytest.approx(1.0, abs=1e-6)


def test_explicit_eres_backend_uses_configured_local_model(tmp_path: Path):
    root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad"):
        (root / name).mkdir(parents=True, exist_ok=True)
    eres_dir = tmp_path / "eres2net-large"
    eres_dir.mkdir()
    (eres_dir / "local-checkpoint.bin").write_bytes(b"local-only")
    fake_eres = FakeEResModel()

    runtime = FunASRSpeechRuntime(
        model_root=root,
        model_factory=FakeAutoModel,
        eres2net_model_dir=eres_dir,
        eres2net_model_factory=lambda path: fake_eres,
    )
    runtime.load()
    result = runtime.speaker_embedding(
        b"\x00\x40" * 1600,
        16000,
        backend_key="eres2net_large",
    )

    assert result["backend_key"] == "eres2net_large"
    assert result["model_id"] == "iic/speech_eres2net_large_200k_sv_zh-cn_16k-common"
    assert result["embedding"] == pytest.approx([0.6, 0.8], abs=1e-6)
    assert runtime.health()["speaker_backends"]["eres2net_large"]["ready"] is True
    assert fake_eres.waveforms


def test_missing_eres_backend_is_explicit_and_never_falls_back_to_xvector(tmp_path: Path):
    root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad"):
        (root / name).mkdir(parents=True, exist_ok=True)
    runtime = FunASRSpeechRuntime(model_root=root, model_factory=FakeAutoModel)
    runtime.load()
    pcm = b"\x00\x00" * 1600

    with pytest.raises(BackendUnavailableError) as missing:
        runtime.speaker_embedding(pcm, 16000, backend_key="eres2net_large")
    assert missing.value.details["backend_key"] == "eres2net_large"
    with pytest.raises(BackendUnavailableError):
        runtime.speaker_embedding(pcm, 16000, backend_key="xvector")


def test_clearing_models_keeps_eres2net_metadata_for_degraded_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("SUSPECT_ERES2NET_MODEL_VERSION", "eres-test-version")
    runtime = _loaded_runtime(tmp_path)

    runtime._clear_models()

    health = runtime.health()
    assert health["speaker_backend"] is None
    assert health["speaker_backend_key"] == "eres2net_large"
    assert health["speaker_model_id"] == "eres2net_large"
    assert health["speaker_model_version"] == "eres-test-version"


def test_legacy_xvector_assets_are_not_loaded_by_the_eres_runtime(tmp_path: Path):
    root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad", "xvector"):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "xvector" / "sv.pth").write_bytes(b"checkpoint")
    (root / "xvector" / "sv.yaml").write_text("model: xvector\n", encoding="utf-8")
    FakeAutoModel.fail_for["xvector"] = RuntimeError("legacy xvector is not registered")
    legacy = FakeLegacySpeaker()
    calls: list[Path] = []

    def legacy_factory(path: Path):
        calls.append(path)
        return legacy

    runtime = FunASRSpeechRuntime(
        model_root=root,
        model_factory=FakeAutoModel,
        legacy_speaker_factory=legacy_factory,
    )
    runtime.load()

    assert runtime.health()["status"] == "degraded"
    assert runtime.health()["models"] == {"asr": True, "asr_streaming": False, "vad": True, "speaker": False}
    assert calls == []
    with pytest.raises(BackendUnavailableError):
        runtime.speaker_embedding(b"\x00\x00" * 1600, 16000)


def test_speaker_embedding_rejects_the_retired_backend(tmp_path: Path):
    runtime = _loaded_runtime(tmp_path)
    with pytest.raises(BackendUnavailableError, match="only enabled"):
        runtime.speaker_embedding(b"\x00\x00" * 1600, 16000, backend_key="xvector")


def test_missing_model_directory_is_typed_not_installed(tmp_path: Path):
    root = tmp_path / "missing-funasr"
    root.mkdir()
    with pytest.raises(ModelNotInstalledError):
        FunASRSpeechRuntime(model_root=root, model_factory=FakeAutoModel).load()


def test_model_factory_failure_becomes_backend_unavailable(tmp_path: Path):
    root = tmp_path / "funasr"
    for name in ("paraformer", "fsmn-vad", "xvector"):
        (root / name).mkdir(parents=True, exist_ok=True)
    FakeAutoModel.fail_for["fsmn-vad"] = RuntimeError("bad checkpoint")

    with pytest.raises(BackendUnavailableError, match="fsmn-vad"):
        FunASRSpeechRuntime(model_root=root, model_factory=FakeAutoModel).load()
