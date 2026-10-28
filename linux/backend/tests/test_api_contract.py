from fastapi.testclient import TestClient

from app.main import create_app


def test_ai_health_and_capabilities_are_available_without_models(monkeypatch, tmp_path):
    config = tmp_path / "registry.yaml"
    config.write_text(
        '{"models":{"llm.default":{"kind":"llm","backend":"rkllm","path":"llm/default","architecture":"qwen","required_files":["model.rkllm"],"device":"npu","context":4096,"memory_mb":4096}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_MODE", "real")
    monkeypatch.setenv("MODEL_REGISTRY", str(config))
    monkeypatch.setenv("MODEL_ROOT", str(tmp_path / "models"))

    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'health-contract.db'}")) as client:
        health = client.get("/api/v1/ai/health")
        capabilities = client.get("/api/v1/ai/capabilities")
        response = client.post(
            "/api/v1/ai/llm/generate",
            json={"prompt": "hello", "session_id": "s"},
        )

    assert health.status_code == 200
    assert capabilities.status_code == 200
    assert capabilities.json()["llm"]["installed"] is False
    assert response.status_code == 503
    payload = response.json()
    assert payload["ok"] is False
    assert payload["code"] == "MODEL_NOT_INSTALLED"


def test_asr_websocket_emits_partial_then_final(monkeypatch, tmp_path):
    config = tmp_path / "registry-ws.yaml"
    config.write_text(
        '{"models":{"asr.default":{"kind":"asr","backend":"sherpa-onnx","path":"asr/default","architecture":"paraformer","required_files":["model.onnx"],"device":"cpu","context":0,"memory_mb":256},"llm.default":{"kind":"llm","backend":"rkllm","path":"llm/default","architecture":"qwen","required_files":["model.rkllm"],"device":"npu","context":4096,"memory_mb":1024}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_MODE", "mock")
    monkeypatch.setenv("MODEL_REGISTRY", str(config))
    monkeypatch.setenv("MODEL_ROOT", str(tmp_path / "models"))

    with TestClient(create_app(database_url=f"sqlite:///{tmp_path / 'websocket-contract.db'}")) as client:
        with client.websocket_connect("/api/v1/ai/asr/stream?session_id=s1") as ws:
            ws.send_bytes(b"hello world")
            partial = ws.receive_json()
            ws.send_text('{"type":"end"}')
            final = ws.receive_json()
            ws.send_text('{"type":"close"}')

    assert partial["type"] == "partial"
    assert partial["result"]["final"] is False
    assert final["type"] == "final"
    assert final["result"]["text"] == "hello world"
