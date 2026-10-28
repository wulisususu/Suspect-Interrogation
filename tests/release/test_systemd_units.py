from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(name: str) -> str:
    return (ROOT / "systemd" / name).read_text(encoding="utf-8")


def test_api_unit_runs_non_root_and_is_hardened():
    unit = _read("interrogation-api.service")
    assert "User=suspect-interrogation" in unit
    assert "Group=suspect-interrogation" in unit
    assert "SupplementaryGroups=audio" in unit
    assert "WorkingDirectory=/opt/suspect-interrogation/current/linux/backend" in unit
    assert "EnvironmentFile=/etc/suspect-interrogation/runtime.env" in unit
    assert "EnvironmentFile=-/etc/suspect-interrogation/ai-worker.env" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=true" in unit
    assert "PrivateTmp=true" in unit
    assert "ReadWritePaths=/var/lib/suspect-interrogation /var/log/suspect-interrogation -/run/suspect-interrogation" in unit
    assert "0.0.0.0" not in unit
    assert "/home/youyeetoo/backend" not in unit
    assert ":8000" not in unit


def test_ai_worker_is_optional_non_root_and_sandboxed_for_funasr():
    unit = _read("ai-worker.service")
    assert "User=suspect-interrogation" in unit
    assert "EnvironmentFile=-/etc/suspect-interrogation/ai-worker.env" in unit
    assert "Restart=on-failure" in unit
    assert "ConditionPathExists=/opt/suspect-interrogation/current/linux/backend" in unit
    # A RuntimeDirectory declaration here would make every ai-worker stop GC
    # /run/suspect-interrogation and drop the bound speech.sock. The tmpfiles
    # fragment (deploy/tmpfiles-suspect-interrogation.conf) creates it instead.
    assert "RuntimeDirectory" not in unit
    assert "ProtectHome=true" in unit
    assert "ReadWritePaths=/run/suspect-interrogation /var/lib/suspect-interrogation /var/log/suspect-interrogation" in unit
    assert "ReadOnlyPaths=/opt/suspect-interrogation/models/funasr /opt/suspect-interrogation/runtime/funasr-env" in unit
    assert "/opt/suspect-interrogation/models/funasr" in unit
    assert "/opt/suspect-interrogation/runtime/funasr-env" in unit
    assert "/run/suspect-interrogation/speech.sock" in unit
    assert "/home/youyeetoo/backend" not in unit
    assert ":8000" not in unit
    assert "systemctl stop" not in unit


def test_kiosk_orders_after_api_and_uses_launcher():
    unit = _read("kiosk.service")
    assert "After=graphical.target interrogation-api.service" in unit
    assert "ExecStart=/opt/suspect-interrogation/current/scripts/kiosk-launch.sh" in unit
    assert "Restart=always" in unit
