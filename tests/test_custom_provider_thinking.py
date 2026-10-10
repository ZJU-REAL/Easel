import copy
import json

import pytest
from fastapi.testclient import TestClient

import web.app as web


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EASEL_CHAT_TRANSPORT", "http")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(web, "_read_env", lambda: {})
    config = tmp_path / "openclaw.json"
    config.write_text(json.dumps({
        "models": {"providers": {}},
        "agents": {"defaults": {"model": {"primary": ""}}},
    }), encoding="utf-8")
    origin = "http://127.0.0.1:7860"
    api = TestClient(web.app, base_url=origin, client=("127.0.0.1", 51234),
                     headers={"Origin": origin})
    return api, config


def row(**values):
    return {"slot": "custom", "name": "test-relay", "model": "reasoner",
            "baseUrl": "https://relay.example.com/v1", "key": "sk-test", **values}


def save(client, **values):
    api, config = client
    response = api.post("/api/settings/models/save",
                        json={"channel": "chat", "rows": [row(**values)]})
    assert response.status_code == 200, response.text
    return json.loads(config.read_text(encoding="utf-8"))["models"]["providers"]["test-relay"]


def seed(client, model_entry, **provider_values):
    _, config = client
    data = json.loads(config.read_text(encoding="utf-8"))
    data["models"]["providers"]["test-relay"] = {
        "baseUrl": row()["baseUrl"], "apiKey": "sk-test",
        "models": [model_entry, {"id": "other", "name": "Other", "reasoning": True}],
        **provider_values,
    }
    config.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("thinking_format", sorted(web.THINKING_FORMATS))
def test_enable_and_echo(client, thinking_format):
    provider = save(client, thinking=True, thinkingFormat=thinking_format)
    model = provider["models"][0]
    assert model["reasoning"] is True
    assert model["compat"] == {
        "thinkingFormat": thinking_format, "supportsReasoningEffort": True,
    }
    api, _ = client
    rows = api.get("/api/settings/models").json()["channels"]["chat"]["rows"]
    saved_row = next(entry for entry in rows if entry["name"] == "test-relay")
    assert saved_row["thinking"] is True
    assert saved_row["thinkingFormat"] == thinking_format


def test_enable_without_format_defaults_to_openai(client):
    assert save(client, thinking=True)["models"][0]["compat"]["thinkingFormat"] == "openai"


def test_enable_preserves_other_model_metadata_and_effort_mapping(client):
    model = {
        "id": "reasoner", "name": "Reasoner 中文", "contextWindow": 32000,
        "agentRuntime": {"id": "openclaw"},
        "compat": {"supportsTools": True, "thinkingFormat": "deepseek",
                   "supportedReasoningEfforts": ["low", "high"],
                   "reasoningEffortMap": {"medium": "high"}},
    }
    seed(client, model)
    provider = save(client, thinking=True)
    saved_model = provider["models"][0]
    assert saved_model == {
        **model, "reasoning": True,
        "compat": {**model["compat"], "supportsReasoningEffort": True},
    }
    assert provider["models"][1] == {"id": "other", "name": "Other", "reasoning": True}


def test_disable_removes_only_thinking_compat(client):
    model = {
        "id": "reasoner", "name": "Reasoner", "reasoning": True,
        "compat": {"thinkingFormat": "deepseek", "supportsReasoningEffort": True,
                   "supportedReasoningEfforts": ["low", "high"],
                   "reasoningEffortMap": {"medium": "high"},
                   "supportsTools": True, "maxTokensField": "max_tokens",
                   "supportsStore": False},
    }
    seed(client, model)
    provider = save(client, thinking=False)
    assert provider["models"][0]["reasoning"] is False
    assert provider["models"][0]["compat"] == {
        "supportsTools": True, "maxTokensField": "max_tokens", "supportsStore": False,
    }
    assert provider["models"][1]["reasoning"] is True


def test_disable_removes_empty_compat(client):
    seed(client, {"id": "reasoner", "name": "Reasoner", "reasoning": True,
                  "compat": {"thinkingFormat": "deepseek"}})
    assert "compat" not in save(client, thinking=False)["models"][0]


@pytest.mark.parametrize("values", [{}, {"thinking": None}])
def test_omitted_or_null_preserves_exact_declaration(client, values):
    model = {
        "id": "reasoner", "name": "Reasoner", "reasoning": True,
        "compat": {"supportsReasoningEffort": False, "thinkingFormat": "qwen",
                   "supportedReasoningEfforts": ["low"], "supportsTools": True},
    }
    seed(client, model)
    assert save(client, **values)["models"][0] == model


def test_new_provider_without_thinking_has_no_declaration(client):
    model = save(client)["models"][0]
    assert "reasoning" not in model
    assert "compat" not in model


def test_native_anthropic_declares_reasoning_without_openai_compat(client):
    provider = save(client, protocol="anthropic", thinking=True)
    assert provider["api"] == "anthropic-messages"
    assert provider["models"][0]["reasoning"] is True
    assert "compat" not in provider["models"][0]


@pytest.mark.parametrize("values, status", [
    ({"thinking": True, "thinkingFormat": "invalid"}, 400),
    ({"thinkingFormat": "openai"}, 400),
    ({"protocol": "anthropic", "thinking": True, "thinkingFormat": "deepseek"}, 400),
    ({"thinking": "yes"}, 422),
    ({"thinking": 1}, 422),
])
def test_invalid_declarations_do_not_change_config(client, values, status):
    api, config = client
    before = config.read_bytes()
    response = api.post("/api/settings/models/save",
                        json={"channel": "chat", "rows": [row(**values)]})
    assert response.status_code == status
    assert config.read_bytes() == before


def test_toggle_is_saved_even_when_other_fields_unchanged(client):
    seed(client, {"id": "reasoner", "name": "Reasoner"})
    assert save(client, thinking=True)["models"][0]["reasoning"] is True
    assert save(client, thinking=False)["models"][0]["reasoning"] is False


def test_idempotent_thinking_save_keeps_backup(client):
    save(client, thinking=True)
    _, config = client
    backup = config.with_suffix(".json.bak-web")
    before = backup.read_bytes()
    save(client, thinking=True)
    assert backup.read_bytes() == before


def test_native_anthropic_preserves_unrelated_compat(client):
    model = {"id": "reasoner", "name": "Reasoner",
             "compat": {"supportsTools": True}}
    seed(client, copy.deepcopy(model), api="anthropic-messages")
    assert save(client, thinking=True)["models"][0] == {**model, "reasoning": True}


def test_enable_preserves_explicit_effort_parameter_opt_out(client):
    seed(client, {"id": "reasoner", "name": "Reasoner",
                  "compat": {"supportsReasoningEffort": False, "thinkingFormat": "deepseek"}})
    assert save(client, thinking=True)["models"][0]["compat"]["supportsReasoningEffort"] is False


def test_missing_or_malformed_compat_echoes_safely(client):
    seed(client, {"id": "reasoner", "name": "Reasoner", "compat": None})
    api, _ = client
    rows = api.get("/api/settings/models").json()["channels"]["chat"]["rows"]
    saved_row = next(entry for entry in rows if entry["name"] == "test-relay")
    assert saved_row["thinking"] is False
    assert saved_row["thinkingFormat"] == ""


@pytest.mark.parametrize("reasoning, expected", [(False, "off"), (True, "medium"), (None, "medium")])
def test_cli_thinking_respects_primary_model_capability(client, monkeypatch, reasoning, expected):
    save(client, thinking=reasoning, primary=True)
    monkeypatch.setattr(web, "THINKING_LEVEL", "medium")
    assert web._agent_thinking_level() == expected


def test_cli_thinking_preserves_global_off(client, monkeypatch):
    save(client, thinking=True, primary=True)
    monkeypatch.setattr(web, "THINKING_LEVEL", "off")
    assert web._agent_thinking_level() == "off"


def test_cli_thinking_respects_main_agent_override(client, monkeypatch):
    save(client, thinking=True, primary=True)
    _, config = client
    data = json.loads(config.read_text(encoding="utf-8"))
    data["models"]["providers"]["test-relay"]["models"].append({
        "id": "plain/model", "name": "Plain", "reasoning": False,
    })
    data["agents"]["list"] = [{"id": "main", "model": "test-relay/plain/model"}]
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(web, "THINKING_LEVEL", "medium")
    assert web._agent_thinking_level() == "off"


def test_cli_thinking_handles_missing_config(client, monkeypatch):
    _, config = client
    config.unlink()
    monkeypatch.setattr(web, "THINKING_LEVEL", "low")
    assert web._agent_thinking_level() == "low"
