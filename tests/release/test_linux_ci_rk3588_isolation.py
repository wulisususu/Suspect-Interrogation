from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "linux-ci.yml"


def test_rk3588_tests_use_isolated_mutable_runtime_paths():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'RK3588_TEST_ROOT="$RUNNER_TEMP/suspect-linux-ci"' in workflow
    assert 'export SUSPECT_DATA_DIR="$RK3588_TEST_ROOT/data"' in workflow
    assert 'export SUSPECT_LOG_DIR="$RK3588_TEST_ROOT/log"' in workflow
    assert 'export SUSPECT_DB_PATH="$RK3588_TEST_ROOT/interrogation.db"' in workflow
    assert 'export SUSPECT_MIN_FREE_MB=1' in workflow
    assert 'rm -rf "$RK3588_TEST_ROOT"' in workflow


@pytest.mark.parametrize("workflow_name", [
    "linux-ai-runtime-rk3588.yml", "linux-ci.yml", "rk3588-service-bootstrap.yml",
])
def test_ci_storage_overrides_satisfy_runtime_settings(workflow_name):
    backend = str(ROOT / "linux" / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app.runtime_settings import RuntimeSettings

    workflow = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
    overrides = re.findall(r"export SUSPECT_MIN_FREE_MB=(\d+)", workflow)
    assert overrides, "CI must explicitly isolate its disk reserve from production"
    for value in overrides:
        assert RuntimeSettings(min_free_mb=int(value)).min_free_mb == 1


def test_rk3588_checkout_falls_back_to_sha_pinned_source_archive():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "codeload.github.com/${GITHUB_REPOSITORY}/tar.gz/${GITHUB_SHA}" in workflow
    assert "--strip-components=1" in workflow
    assert "source archive root does not match requested SHA" in workflow


def test_kiosk_visual_qa_requires_populated_template_and_raw_asr_fixture():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    screenshot_script = (
        ROOT / "scripts" / "ci" / "capture-kiosk-screenshots.mjs"
    ).read_text(encoding="utf-8")

    expected_text = (
        "你什么时候到现场？",
        "晚上八点左右。",
        "你把钥匙放到哪里去了？",
        "我放在门口鞋柜里了。",
    )
    for value in expected_text:
        assert value in workflow
        assert value in screenshot_script
