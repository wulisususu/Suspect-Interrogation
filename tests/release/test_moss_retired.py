"""MOSS long-audio transcription is retired (2026-10-27).

The redeploy workflow must stop, disable and remove the board's moss-worker
unit and its MOSS-only files, while keeping /run/suspect-interrogation (which
holds ai-worker's speech.sock) under a neutral tmpfiles name.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REDEPLOY = (ROOT / ".github" / "workflows" / "rk3588-production-redeploy.yml").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / ".github" / "workflows" / "rk3588-service-bootstrap.yml").read_text(encoding="utf-8")


def test_moss_sources_and_units_are_gone():
    for relative in (
        "systemd/moss-worker.service",
        "linux/backend/moss_worker",
        "linux/backend/app/api/moss_transcription.py",
        "linux/backend/requirements-moss-rk3588.txt",
        "tools/moss_rk3588",
        ".github/workflows/rk3588-moss-embed-probe.yml",
    ):
        assert not (ROOT / relative).exists(), relative


def test_redeploy_retires_the_board_worker_and_its_files():
    assert "Retire the MOSS worker" in REDEPLOY
    assert "systemctl disable --now moss-worker.service" in REDEPLOY
    assert "rm -f /etc/systemd/system/moss-worker.service" in REDEPLOY
    for path in (
        "/opt/suspect-interrogation/models/moss-rk3588",
        "/opt/suspect-interrogation/runtime/moss-env",
        "/var/lib/suspect-interrogation/moss",
        "/etc/suspect-interrogation/moss-worker.env",
    ):
        assert path in REDEPLOY
    # FunASR assets are never part of the removal list.
    retire = REDEPLOY[REDEPLOY.index("Retire the MOSS worker"):REDEPLOY.index("Verify deployed HTTPS")]
    assert "/models/funasr" not in retire
    assert "funasr-env" not in retire
    assert "Restart MOSS worker" not in REDEPLOY
    assert "probe-moss-rk3588" not in REDEPLOY


def test_shared_runtime_directory_moves_to_a_neutral_tmpfiles_name():
    for workflow in (REDEPLOY, BOOTSTRAP):
        assert "/etc/tmpfiles.d/suspect-interrogation.conf" in workflow
    retire = REDEPLOY[REDEPLOY.index("Retire the MOSS worker"):]
    # The neutral fragment is installed before the MOSS-named one is removed.
    assert retire.index("/etc/tmpfiles.d/suspect-interrogation.conf") < retire.index("rm -f /etc/tmpfiles.d/suspect-interrogation-moss.conf")
    fragment = (ROOT / "deploy" / "tmpfiles-suspect-interrogation.conf").read_text(encoding="utf-8")
    assert "d /run/suspect-interrogation 0750 suspect-interrogation suspect-interrogation -" in fragment
    assert "moss" not in BOOTSTRAP.lower()
