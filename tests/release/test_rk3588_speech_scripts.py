from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CALIBRATE = ROOT / "scripts" / "ci" / "rk3588-speech-calibrate.py"
SMOKE = ROOT / "scripts" / "ci" / "rk3588-speech-smoke.py"
AI_WORKFLOW = ROOT / ".github" / "workflows" / "linux-ai-runtime-rk3588.yml"
BOOTSTRAP = ROOT / ".github" / "workflows" / "rk3588-service-bootstrap.yml"
SPEAKER_POLICY = ROOT / "linux" / "backend" / "app" / "services" / "speaker_policy.py"


def test_calibration_script_contract_is_local_multi_sample_and_fail_safe():
    assert CALIBRATE.is_file(), "RK3588 speech calibration script is missing"
    source = CALIBRATE.read_text(encoding="utf-8")

    for flag in (
        "--suspect-wav",
        "--interrogator-wav",
        "--recorder-wav",
        "--output",
        "--apply",
    ):
        assert flag in source

    assert "SpeechWorkerClient" in source
    assert "extract_embedding" in source
    assert "cosine" in source.lower()
    assert "false_accept" in source
    assert "false_reject" in source
    assert "recommended_threshold" in source
    assert "recommended_margin" in source
    assert "/etc/suspect-interrogation/ai-worker.env" in source
    assert "SUSPECT_SPEAKER_ACCEPT_THRESHOLD" in source
    assert "SUSPECT_SPEAKER_MARGIN" in source
    assert "os.replace" in source
    assert "embedding" not in _report_payload_section(source).lower()
    assert "audio" not in _report_payload_section(source).lower()
    assert "wav" not in _report_payload_section(source).lower()


def test_calibration_requires_multiple_utterances_per_identity():
    source = CALIBRATE.read_text(encoding="utf-8")
    assert "MIN_SAMPLES_PER_IDENTITY" in source
    assert "at least" in source.lower() or "minimum" in source.lower()
    assert "suspect" in source
    assert "interrogator" in source
    assert "recorder" in source


def test_real_device_smoke_contract_covers_speech_stack_and_policy_modes():
    assert SMOKE.is_file(), "RK3588 speech smoke script is missing"
    source = SMOKE.read_text(encoding="utf-8")

    for required in (
        "ai-worker.service",
        "/run/suspect-interrogation/speech.sock",
        "/opt/suspect-interrogation/models/funasr",
        "findmnt",
        "paraformer",
        "fsmn-vad",
        "eres2net_large",
        "voiceprintCalibration",
        "audioCapture",
        "SUSPECT_ONLY",
        "SUSPECT_PLUS_INTERROGATOR",
        "FULL",
        "OFFICER_FALLBACK",
        "UNKNOWN",
        "systemctl restart ai-worker.service",
    ):
        assert required in source
    assert 'SUPPORTED_SPEAKER_BACKENDS = ("eres2net_large",)' in source
    assert 'default="eres2net_large"' in source


def test_ai_runtime_workflow_has_explicit_local_calibration_inputs_and_never_uploads_wavs():
    workflow = AI_WORKFLOW.read_text(encoding="utf-8")
    for input_name in (
        "suspect_wavs:",
        "interrogator_wavs:",
        "recorder_wavs:",
        "apply_calibration:",
    ):
        assert input_name in workflow

    assert "type: boolean" in workflow
    assert "rk3588-speech-calibrate.py" in workflow
    assert "rk3588-speech-smoke.py" in workflow
    assert "--apply" in workflow
    assert "actions/upload-artifact" not in _speech_calibration_workflow_section(workflow)
    assert "*.wav" not in _speech_calibration_workflow_section(workflow)
    # Port ownership is a production-bootstrap invariant; the read-only probe
    # workflow never needs to bind or stop either TCP service.
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    assert "sudo -n ss -ltnp 'sport = :8000'" in bootstrap


def test_manual_calibration_enables_legacy_only_for_its_temporary_worker():
    workflow = AI_WORKFLOW.read_text(encoding="utf-8")
    regular_steps, calibration = workflow.split("      - name: RK3588 speech calibration and real smoke", 1)
    assert "SUSPECT_LEGACY_VOICEPRINT_ENABLED" not in regular_steps
    assert "SUSPECT_LEGACY_VOICEPRINT_ENABLED: 'true'" in calibration
    assert "SUSPECT_ERES2NET_MODEL_DIR: ${{ env.ERES2NET_MODEL_DIR }}" in calibration
    assert 'SOCKET="$RUNNER_TEMP/rk3588-speech.sock"' in calibration


def test_ai_runtime_cancels_stale_pr_runs_before_they_starve_single_rk3588_runner():
    workflow = AI_WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:" in workflow
    assert "group: linux-ai-runtime-rk3588-${{ github.event.pull_request.number || github.ref }}" in workflow
    assert "cancel-in-progress: true" in workflow


def test_bootstrap_starts_real_worker_and_keeps_voice_capture_fail_closed_without_calibration():
    workflow = BOOTSTRAP.read_text(encoding="utf-8")
    assert "Prepare stable offline FunASR model and runtime layout" in workflow
    assert "SUSPECT_SPEAKER_ACCEPT_THRESHOLD" in workflow
    assert "SUSPECT_SPEAKER_MARGIN" in workflow
    assert "upsert AI_MODE real" in workflow
    assert "systemctl enable --now ai-worker.service" in workflow
    assert "systemctl is-active --quiet ai-worker.service" in workflow
    assert "/run/suspect-interrogation/speech.sock" in workflow
    assert "rk3588-speech-smoke.py" in workflow
    assert "speaker_calibration=NOT_CONFIGURED" in workflow
    assert "formal ASR capture stays fail-closed" in workflow
    assert "Existing TCP/8000 owner is preserved" in workflow
    assert "sudo -n ss -ltnp 'sport = :8000'" in workflow


def test_project_funasr_runtime_includes_torchaudio_required_by_automodel():
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    ai_workflow = AI_WORKFLOW.read_text(encoding="utf-8")
    assert "TORCHAUDIO_PACKAGE_VERSION" in bootstrap
    assert "torchaudio" in bootstrap
    assert "import funasr, torch, torchaudio" in bootstrap
    assert "https://download.pytorch.org/whl/cpu" in bootstrap
    # The PR hardware probe must be able to repair the project-isolated venv
    # before importing AutoModel; it must never mutate the unrelated :8000 env.
    assert "/opt/suspect-interrogation/runtime/funasr-env/bin/python" in ai_workflow
    assert "torchaudio" in ai_workflow
    assert "/home/youyeetoo/rkllm_model_zoo/funasr_env/bin/pip" not in ai_workflow


def test_speaker_policy_is_compatible_with_rk3588_python_310():
    source = SPEAKER_POLICY.read_text(encoding="utf-8")
    assert "from enum import StrEnum" not in source
    assert "class _StrEnumCompat(str, Enum)" in source
    assert "SpeakerRole(_StrEnumCompat)" in source
    assert "SpeakerSource(_StrEnumCompat)" in source


def _report_payload_section(source: str) -> str:
    marker = "REPORT_PAYLOAD"
    assert marker in source, "calibration report payload must be explicit and reviewable"
    return source[source.index(marker) :]


def _speech_calibration_workflow_section(workflow: str) -> str:
    marker = "RK3588 speech calibration"
    assert marker in workflow, "workflow needs a clearly named speech calibration step"
    return workflow[workflow.index(marker) :]
