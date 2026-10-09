"""Saving settings must repair stale mirrors without redirecting retained keys."""
import json

import pytest
from fastapi.testclient import TestClient

import web.app as web


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    config_path = tmp_path / "openclaw.json"
    config_path.write_text(json.dumps({"models": {"providers": {}}}), encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env_path)
    monkeypatch.setattr(web, "_oc_config_path", lambda: config_path)
    local = "http://127.0.0.1:7860"
    client = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                        headers={"Origin": local})
    return client, env_path, config_path


def seed(env_path, config_path, slot, env_key="sk-env-test", base="https://current.example/v1",
         mirror_base="https://old.example/v1", mirror_key="sk-mirror-test"):
    base_var, key_var = web._SLOT_ENV_KEYS[slot]
    env_path.write_text(f"{base_var}={base}\n{key_var}={env_key}\n", encoding="utf-8")
    provider = "openai" if slot == "openai" else "anthropic"
    config_path.write_text(json.dumps({"models": {"providers": {provider: {
        "baseUrl": mirror_base, "apiKey": mirror_key,
        "models": [{"id": "old-model", "name": "Old model"}],
    }}}}), encoding="utf-8")
    return provider


@pytest.mark.parametrize("slot", ["openai", "relay", "anthropic"])
def test_unchanged_authoritative_url_repairs_stale_url_and_key(sandbox, slot):
    client, env_path, config_path = sandbox
    provider = seed(env_path, config_path, slot)
    for unused in range(2):
        response = client.post("/api/settings/models/save", json={"rows": [
            {"slot": slot, "model": "new-model", "baseUrl": "https://current.example/v1/", "key": ""},
            {"slot": "custom", "name": "other", "model": "custom-model",
             "baseUrl": "https://custom.example/v1", "key": "sk-custom-test"},
        ]})
        assert response.status_code == 200, response.text
        mirror = json.loads(config_path.read_text())["models"]["providers"][provider]
        assert mirror["baseUrl"] == "https://current.example/v1"
        assert mirror["apiKey"] == "sk-env-test"


@pytest.mark.parametrize("slot", ["openai", "relay", "anthropic"])
def test_model_only_save_repairs_authoritative_url_and_key_together(sandbox, slot):
    client, env_path, config_path = sandbox
    provider = seed(env_path, config_path, slot)
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": slot, "model": "new-model"},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"][provider]
    assert mirror["baseUrl"] == "https://current.example/v1"
    assert mirror["apiKey"] == "sk-env-test"


def test_openai_without_authoritative_url_does_not_move_env_key_to_mirror(sandbox):
    client, env_path, config_path = sandbox
    seed(env_path, config_path, "openai", base="")
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": "openai", "model": "new-model"},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"]["openai"]
    assert mirror["baseUrl"] == "https://old.example/v1"
    assert mirror["apiKey"] == "sk-mirror-test"


@pytest.mark.parametrize("slot", ["openai", "relay", "anthropic"])
@pytest.mark.parametrize("env_key", ["sk-env-test", "", "sk-ant-REPLACE_ME"])
def test_real_url_change_requires_a_new_key_even_when_env_key_is_missing(sandbox, slot, env_key):
    client, env_path, config_path = sandbox
    seed(env_path, config_path, slot, env_key=env_key)
    before = env_path.read_bytes(), config_path.read_bytes()
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": slot, "model": "new-model", "baseUrl": "https://changed.example/v1", "key": ""},
    ]})
    assert response.status_code == 400
    assert before == (env_path.read_bytes(), config_path.read_bytes())


@pytest.mark.parametrize("slot", ["openai", "relay", "anthropic"])
def test_real_url_change_with_explicit_key_updates_both_sources(sandbox, slot):
    client, env_path, config_path = sandbox
    provider = seed(env_path, config_path, slot)
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": slot, "model": "new-model", "baseUrl": "https://changed.example/v1",
         "key": "sk-replacement-test"},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"][provider]
    assert mirror["baseUrl"] == "https://changed.example/v1"
    assert mirror["apiKey"] == "sk-replacement-test"


def test_custom_url_trailing_slash_is_not_a_change(sandbox):
    client, env_path, config_path = sandbox
    config_path.write_text(json.dumps({"models": {"providers": {"other": {
        "baseUrl": "https://custom.example/v1/", "apiKey": "sk-existing-test",
    }}}}), encoding="utf-8")
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": "custom", "name": "other", "model": "custom-model",
         "baseUrl": "https://custom.example/v1", "key": ""},
    ]})
    assert response.status_code == 200, response.text


def test_anthropic_default_url_is_authoritative_when_not_explicitly_set(sandbox):
    client, env_path, config_path = sandbox
    seed(env_path, config_path, "anthropic", base="")
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": "anthropic", "model": "new-model", "key": ""},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"]["anthropic"]
    assert mirror["baseUrl"] == "https://api.anthropic.com"
    assert mirror["apiKey"] == "sk-env-test"


def test_openai_local_gateway_keeps_its_own_authentication_key(sandbox):
    client, env_path, config_path = sandbox
    seed(env_path, config_path, "openai", mirror_base="http://127.0.0.1:8890/v1",
         mirror_key="sk-gateway-test")
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": "openai", "model": "new-model", "baseUrl": "https://current.example/v1"},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"]["openai"]
    assert mirror["baseUrl"] == "http://127.0.0.1:8890/v1"
    assert mirror["apiKey"] == "sk-gateway-test"


@pytest.mark.parametrize("slot", ["openai", "anthropic", "relay"])
@pytest.mark.parametrize("env_key", ["", "sk-ant-REPLACE_ME"])
@pytest.mark.parametrize("env_base", ["", "https://unused-env.example/v1"])
def test_mirror_only_credentials_keep_their_url_on_model_only_save(sandbox, slot, env_key, env_base):
    client, env_path, config_path = sandbox
    provider = seed(env_path, config_path, slot, env_key=env_key, base=env_base)
    response = client.post("/api/settings/models/save", json={"rows": [
        {"slot": slot, "model": "new-model", "key": ""},
    ]})
    assert response.status_code == 200, response.text
    mirror = json.loads(config_path.read_text())["models"]["providers"][provider]
    assert mirror["baseUrl"] == "https://old.example/v1"
    assert mirror["apiKey"] == "sk-mirror-test"
