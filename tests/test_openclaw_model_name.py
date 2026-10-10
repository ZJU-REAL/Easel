"""Saving a provider must preserve or supply a nonempty model display name."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import pytest
from fastapi.testclient import TestClient

import web.app as web


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(json.dumps({
        "models": {"providers": {"openai": {"api": "openai-completions"}}},
        "agents": {"defaults": {"model": {"primary": "openai/gpt-x"}}},
    }), encoding="utf-8")
    monkeypatch.setattr(web, "_read_env", lambda: {})
    local = "http://127.0.0.1:7860"
    test_client = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                             headers={"Origin": local})
    return test_client, config_path


def _row(**overrides):
    row = {"slot": "custom", "name": "newrelay", "model": "deepseek-v3",
           "baseUrl": "https://relay.example.com/v1", "key": "sk-test"}
    row.update(overrides)
    return row


def _providers(config_path):
    return json.loads(config_path.read_text(encoding="utf-8"))["models"]["providers"]


def test_new_custom_provider_gets_model_name(client):
    test_client, config_path = client
    response = test_client.post("/api/settings/models/save",
                                json={"channel": "chat", "rows": [_row()]})
    assert response.status_code == 200, response.text
    entry = _providers(config_path)["newrelay"]["models"][0]
    assert entry["id"] == "deepseek-v3"
    assert entry["name"] == "deepseek-v3"


@pytest.mark.parametrize("model_name", ["DeepSeek V3 (relay)", "", "   ", None, 123, {"bad": "name"}])
def test_existing_model_name_is_kept_or_repaired(client, model_name):
    test_client, config_path = client
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["models"]["providers"]["newrelay"] = {
        "baseUrl": "https://relay.example.com/v1",
        "apiKey": "sk-old",
        "models": [{"id": "deepseek-v3", "name": model_name}],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    response = test_client.post("/api/settings/models/save",
                                json={"channel": "chat", "rows": [_row(key="")]})
    assert response.status_code == 200, response.text
    provider = _providers(config_path)["newrelay"]
    expected = model_name if isinstance(model_name, str) and model_name.strip() else "deepseek-v3"
    assert provider["models"][0]["name"] == expected
    assert provider["apiKey"] == "sk-old"
