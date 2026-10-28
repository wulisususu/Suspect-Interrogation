from __future__ import annotations

import os
import subprocess

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "scripts" / "ai-worker-start.sh"
SERVICE = ROOT / "systemd" / "ai-worker.service"
STABLE_PYTHONPATH = "/opt/suspect-interrogation/current/linux/backend"


def _base_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    model_root = tmp_path / "funasr-models"
    for name in ("paraformer", "fsmn-vad"):
        (model_root / name).mkdir(parents=True)
    eres_model_dir = tmp_path / "eres2net-large"
    eres_model_dir.mkdir()
    (eres_model_dir / "pretrained_eres2net.pt").write_bytes(b"test-checkpoint")
    socket_path = tmp_path / "run" / "speech.sock"
    socket_path.parent.mkdir()

    capture = tmp_path / "capture.txt"
    fake_python = tmp_path / "funasr-python"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$PYTHONPATH\" > \"$CAPTURE_FILE\"\n"
        "printf '%s\\n' \"$@\" >> \"$CAPTURE_FILE\"\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "SUSPECT_FUNASR_PYTHON": os.fspath(fake_python),
            "SUSPECT_FUNASR_MODEL_ROOT": os.fspath(model_root),
            "SUSPECT_ERES2NET_MODEL_DIR": os.fspath(eres_model_dir),
            "SUSPECT_SPEECH_SOCKET": os.fspath(socket_path),
            "CAPTURE_FILE": os.fspath(capture),
        }
    )
    return env, capture


def test_launcher_executes_stable_speech_worker_module_with_project_pythonpath(tmp_path: Path):
    env, capture = _base_env(tmp_path)

    result = subprocess.run(
        ["bash", os.fspath(LAUNCHER)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        STABLE_PYTHONPATH,
        "-m",
        "speech_worker.main",
    ]


def test_launcher_fails_closed_when_required_runtime_inputs_are_missing(tmp_path: Path):
    env, _ = _base_env(tmp_path)

    for missing in (
        "SUSPECT_FUNASR_PYTHON",
        "SUSPECT_FUNASR_MODEL_ROOT",
        "SUSPECT_SPEECH_SOCKET",
    ):
        candidate = dict(env)
        candidate.pop(missing)
        result = subprocess.run(
            ["bash", os.fspath(LAUNCHER)],
            cwd=ROOT,
            env=candidate,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0
        assert missing in result.stderr


def test_launcher_rejects_invalid_python_and_incomplete_model_root(tmp_path: Path):
    env, _ = _base_env(tmp_path)

    bad_python = dict(env)
    bad_python["SUSPECT_FUNASR_PYTHON"] = os.fspath(tmp_path / "missing-python")
    result = subprocess.run(
        ["bash", os.fspath(LAUNCHER)],
        cwd=ROOT,
        env=bad_python,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SUSPECT_FUNASR_PYTHON" in result.stderr

    incomplete_root = tmp_path / "incomplete-models"
    incomplete_root.mkdir()
    incomplete = dict(env)
    incomplete["SUSPECT_FUNASR_MODEL_ROOT"] = os.fspath(incomplete_root)
    result = subprocess.run(
        ["bash", os.fspath(LAUNCHER)],
        cwd=ROOT,
        env=incomplete,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "paraformer" in result.stderr or "fsmn-vad" in result.stderr

    missing_eres = dict(env)
    missing_eres["SUSPECT_LEGACY_VOICEPRINT_ENABLED"] = "true"
    missing_eres.pop("SUSPECT_ERES2NET_MODEL_DIR")
    result = subprocess.run(
        ["bash", os.fspath(LAUNCHER)],
        cwd=ROOT,
        env=missing_eres,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SUSPECT_ERES2NET_MODEL_DIR" in result.stderr


def test_systemd_delegates_stale_socket_safety_to_worker_server():
    text = SERVICE.read_text(encoding="utf-8")

    assert "ExecStart=/opt/suspect-interrogation/current/scripts/ai-worker-start.sh" in text
    assert "ExecStartPre=/usr/bin/rm -f /run/suspect-interrogation/speech.sock" not in text
    assert "\nRuntimeDirectory=" not in text
    tmpfiles = (ROOT / "deploy" / "tmpfiles-suspect-interrogation.conf").read_text(encoding="utf-8")
    assert "d /run/suspect-interrogation 0750 suspect-interrogation suspect-interrogation" in tmpfiles
    assert "ReadOnlyPaths=/opt/suspect-interrogation/models/funasr" in text


def test_launcher_does_not_require_retired_speaker_models_by_default(tmp_path: Path):
    env, capture = _base_env(tmp_path)
    env.pop("SUSPECT_ERES2NET_MODEL_DIR")
    env["SUSPECT_LEGACY_VOICEPRINT_ENABLED"] = "false"
    result = subprocess.run(["bash", os.fspath(LAUNCHER)], cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert capture.read_text(encoding="utf-8").splitlines() == [STABLE_PYTHONPATH, "-m", "speech_worker.main"]
