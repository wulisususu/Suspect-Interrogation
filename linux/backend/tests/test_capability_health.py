import os

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_missing_model_is_not_installed_capability_not_api_failure(monkeypatch, tmp_path):
    missing_model = tmp_path / "models" / "missing.rkllm"
    monkeypatch.setenv("SUSPECT_MODEL_PATH", os.fspath(missing_model))

    response = client.get("/health/ready")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] in {"ready", "degraded"}
    assert payload["capabilities"]["ai"]["state"] == "NOT_INSTALLED"
    assert payload["capabilities"]["ai"]["required"] is False
