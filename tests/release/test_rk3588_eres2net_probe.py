from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "rk3588-eres2net-probe.yml"


def test_eres2net_probe_is_gated_and_uses_only_the_installed_offline_model():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "hosted-contract" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "runs-on: [self-hosted, rk3588]" in text
    assert "needs: hosted-contract" in text
    assert "MODELSCOPE_OFFLINE: '1'" in text
    assert "HF_HUB_OFFLINE: '1'" in text
    assert "TRANSFORMERS_OFFLINE: '1'" in text
    assert "snapshot_download" not in text
    assert "xvector" not in text.lower()
    assert "SUSPECT_SPEAKER_BACKEND=" not in text
    assert "systemctl restart" not in text


def test_eres2net_probe_requires_a_local_checkpoint_and_validates_runtime_contract():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pretrained_eres2net.pt" in text
    assert "configuration.json" in text
    assert "ERes2Net model is not installed; download is intentionally forbidden" in text
    assert "set(backends) == {'eres2net_large'}" in text
    assert "embedding_dim'] == 512" in text
    assert "embedding_l2_norm" in text
    assert "runtime_backend_key'] == 'eres2net_large'" in text


def test_speaker_probe_explicitly_enables_only_its_isolated_legacy_worker():
    text = WORKFLOW.read_text(encoding="utf-8")
    hosted, isolated = text.split("  rk3588-eres2net:\n", 1)
    env = isolated.split("    steps:", 1)[0]
    assert "SUSPECT_LEGACY_VOICEPRINT_ENABLED: 'true'" in env
    assert "SUSPECT_LEGACY_VOICEPRINT_ENABLED" not in hosted
    assert 'SOCKET="$RUNNER_TEMP/eres2net-probe.sock"' in isolated

    production = (ROOT / ".github/workflows/rk3588-production-redeploy.yml").read_text(encoding="utf-8")
    assert "upsert SUSPECT_LEGACY_VOICEPRINT_ENABLED false" in production
    assert "SUSPECT_LEGACY_VOICEPRINT_ENABLED=true" not in production
