from fastapi.testclient import TestClient

from app.hardware_gateway.mock import MockHardwareGateway
from app.main import create_app


def test_public_ca_endpoint_returns_configured_certificate(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_text("-----BEGIN CERTIFICATE-----\nTEST-CA\n-----END CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setenv("SUSPECT_TLS_CA_FILE", str(ca))

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'tls-api.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/tls/ca.crt")

    assert response.status_code == 200
    assert response.content == ca.read_bytes()
    assert response.headers["content-type"].startswith(("application/x-x509-ca-cert", "application/pkix-cert"))


def test_public_ca_endpoint_fails_closed_when_certificate_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SUSPECT_TLS_CA_FILE", str(tmp_path / "missing-ca.crt"))
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'tls-missing.db'}",
        hardware_gateway=MockHardwareGateway(simulated=True),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/tls/ca.crt")

    assert response.status_code == 503
    assert "CA" in response.text
