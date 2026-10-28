import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def tls_env(tmp_path: Path, lan_ip: str, extra_san: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "SUSPECT_ETC_DIR": str(tmp_path / "etc"),
        "SUSPECT_TLS_DIR": str(tmp_path / "etc" / "tls"),
        "SUSPECT_TLS_LAN_IP": lan_ip,
        "SUSPECT_SERVICE_GROUP": env.get("USER", "root"),
        "SUSPECT_DRY_RUN": "1",
    })
    if extra_san is not None:
        env["SUSPECT_TLS_EXTRA_SAN"] = extra_san
    return env


def run_tls_helper(tmp_path: Path, lan_ip: str, extra_san: str | None = None) -> tuple[str, str]:
    env = tls_env(tmp_path, lan_ip, extra_san)
    command = f'''
set -euo pipefail
source "{ROOT}/deploy/lib/common.sh"
source "{ROOT}/deploy/lib/tls.sh"
ensure_tls_material
openssl x509 -in "$SUSPECT_TLS_CA_FILE" -noout -fingerprint -sha256
openssl x509 -in "$SUSPECT_TLS_CERT_FILE" -noout -ext subjectAltName
'''
    completed = subprocess.run(
        ["bash", "-c", command],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = completed.stdout.strip().splitlines()
    return lines[0], "\n".join(lines[1:])


def test_tls_helper_and_windows_bootstrap_exist():
    assert (ROOT / "deploy/lib/tls.sh").is_file()
    assert (ROOT / "scripts/windows/install-lan-ca.ps1").is_file()


def test_tls_helper_reuses_ca_and_renews_leaf_when_lan_ip_changes(tmp_path: Path):
    first_ca, first_san = run_tls_helper(tmp_path, "192.168.0.9")
    second_ca, second_san = run_tls_helper(tmp_path, "192.168.0.99")

    assert first_ca == second_ca
    assert "IP Address:192.168.0.9," in first_san
    assert "IP Address:127.0.0.1" in first_san
    assert "DNS:localhost" in first_san
    assert "IP Address:192.168.0.99," in second_san
    assert "IP Address:127.0.0.1" in second_san
    assert "DNS:localhost" in second_san
    assert "IP Address:192.168.0.9," not in second_san


def test_tls_helper_appends_extra_sans_and_renews_when_the_list_changes(tmp_path: Path):
    first_ca, first_san = run_tls_helper(
        tmp_path, "192.168.2.109", "IP:192.168.0.26, IP:192.168.0.4, IP:124.223.176.99"
    )
    assert "IP Address:192.168.0.26," in first_san
    assert "IP Address:192.168.0.4," in first_san
    assert "IP Address:124.223.176.99" in first_san

    # CA 必须复用：SAN 列表变化只重签叶子证书，根不能换（否则所有客户端要重装 CA）
    second_ca, second_san = run_tls_helper(tmp_path, "192.168.2.109", "IP:192.168.0.26, IP:124.223.176.99")
    assert second_ca == first_ca
    assert "IP Address:124.223.176.99" in second_san
    # 从列表里删掉的地址必须从证书上消失，而不是继续带着废弃 SAN
    assert "IP Address:192.168.0.4" not in second_san


def test_tls_helper_without_extra_san_keeps_the_three_default_entries(tmp_path: Path):
    _, san = run_tls_helper(tmp_path, "192.168.2.109")
    assert "IP Address:192.168.2.109," in san
    assert "IP Address:127.0.0.1" in san
    assert "DNS:localhost" in san


def test_tls_helper_refuses_to_silently_replace_an_existing_broken_ca(tmp_path: Path):
    run_tls_helper(tmp_path, "192.168.0.9")
    ca_path = tmp_path / "etc" / "tls" / "ca.crt"
    ca_path.write_text("BROKEN EXISTING CA\n", encoding="utf-8")

    command = f'''
set -euo pipefail
source "{ROOT}/deploy/lib/common.sh"
source "{ROOT}/deploy/lib/tls.sh"
ensure_tls_material
'''
    completed = subprocess.run(
        ["bash", "-c", command],
        env=tls_env(tmp_path, "192.168.0.9"),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert ca_path.read_text(encoding="utf-8") == "BROKEN EXISTING CA\n"
    assert "manual CA rotation" in completed.stderr


def test_systemd_uvicorn_uses_configured_tls_certificate_and_key():
    service = read("systemd/interrogation-api.service")
    assert '--ssl-certfile "$SUSPECT_TLS_CERT_FILE"' in service
    assert '--ssl-keyfile "$SUSPECT_TLS_KEY_FILE"' in service


def test_release_control_prepares_tls_and_verifies_https_with_ca():
    control = read("deploy/control.sh")
    assert 'source "$SCRIPT_DIR/lib/tls.sh"' in control
    assert "ensure_tls_material" in control
    assert "install_tls_trust" in control
    assert "curl_tls" in control
    assert "https://127.0.0.1" in control
    assert 'SUSPECT_HEALTH_RETRIES:-30' in control
    assert 'for attempt in $(seq 1 "$retries")' in control
    assert "curl -k" not in control
    assert "curl --insecure" not in control


def test_production_workflow_uses_https_and_verifies_certificate_identity():
    workflow = read(".github/workflows/rk3588-production-redeploy.yml")
    assert 'https://127.0.0.1:${SUSPECT_DEPLOY_PORT}' in workflow
    assert "SUSPECT_TLS_LAN_IP" in workflow
    assert "openssl x509" in workflow
    assert "subjectAltName" in workflow or "Subject Alternative Name" in workflow
    assert "TCP/8000 preserved" in workflow
    assert "0019_deferred_speaker_analysis (head)" in workflow


def test_production_workflow_targets_the_selected_board_and_runner():
    workflow = read(".github/workflows/rk3588-production-redeploy.yml")
    assert "runs-on: [self-hosted, rk3588, target-192-168-2-109]" in workflow
    assert "SUSPECT_TLS_LAN_IP: '192.168.2.109'" in workflow


def test_service_bootstrap_allows_eres2net_cold_start_before_requiring_socket():
    workflow = read(".github/workflows/rk3588-service-bootstrap.yml")
    assert "for _ in $(seq 1 240); do" in workflow
    assert "sudo -n test -S /run/suspect-interrogation/speech.sock" in workflow
    assert "sudo -n -u suspect-interrogation env" in workflow
    assert "sudo -n curl --cacert /etc/suspect-interrogation/tls/ca.crt" in workflow
    assert "SpeechWorkerClient('/run/suspect-interrogation/speech.sock', timeout=30).health()" in workflow


def test_ca_download_endpoint_is_registered_without_private_key_endpoint():
    assert (ROOT / "linux/backend/app/api/tls.py").is_file()
    main = read("linux/backend/app/main.py")
    assert "tls_router" in main
    route = read("linux/backend/app/api/tls.py")
    assert "/api/v1/tls/ca.crt" in route
    assert "ca.key" not in route
    assert "server.key" not in route


def test_kiosk_defaults_to_https_without_disabling_certificate_verification():
    kiosk = read("scripts/kiosk-launch.sh")
    assert "https://127.0.0.1" in kiosk
    assert "--ignore-certificate-errors" not in kiosk
    assert "--allow-insecure-localhost" not in kiosk


def test_repository_definition_of_done_uses_https():
    rules = read("AGENTS.md")
    assert "https://192.168.2.109:18080" in rules
    assert "http://192.168.2.109:18080" not in rules


def test_windows_bootstrap_limits_insecure_tls_to_ca_download_then_verifies_strictly():
    script = read("scripts/windows/install-lan-ca.ps1")
    lowered = script.lower()
    assert "curl.exe" in lowered
    assert "/api/v1/tls/ca.crt" in lowered
    assert "certutil" in lowered
    assert "-addstore" in lowered
    assert "root" in lowered
    assert "/health/live" in lowered
    assert "--ssl-no-revoke" in lowered
    assert lowered.count(" -k ") == 1 or lowered.count(" --insecure ") == 1


def test_tls_directory_is_accessible_to_the_service_group_for_private_key_loading():
    tls = read("deploy/lib/tls.sh")
    assert 'chown root:"${SUSPECT_SERVICE_GROUP:-suspect-interrogation}" "$SUSPECT_TLS_DIR"' in tls
