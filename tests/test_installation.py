from __future__ import annotations

from pathlib import Path

import pytest

from easel import installation
from easel.harnesses import store
from easel.harnesses.base import HarnessError


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))


def test_skip_initializes_chat_only_without_touching_env_or_profile(tmp_path):
    env = tmp_path / ".env"
    env.write_bytes(b"ANTHROPIC_API_KEY=keep-secret\r\nEASEL_CHAT_TRANSPORT=http\r\n")
    original = env.read_bytes()
    assert installation.initialize_runtime(tmp_path) == "api"
    assert store.settings(tmp_path / "outputs", {"EASEL_CHAT_TRANSPORT": "http"})["runtime"] == "api"
    assert env.read_bytes() == original
    assert not (tmp_path / "home" / ".openclaw-easel").exists()
    assert not (tmp_path / "home" / ".codex").exists()


@pytest.mark.parametrize("runtime", store.IDS)
def test_skip_preserves_existing_engine_and_models(tmp_path, runtime):
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    config = {"runtime": runtime, "models": {"codex": "custom-model"}, "sandbox": "read-only", "future": True}
    store.write_json(config_path, config)
    original = config_path.read_bytes()
    assert installation.initialize_runtime(tmp_path) == runtime
    assert config_path.read_bytes() == original


def test_skip_preserves_other_settings_when_engine_not_selected(tmp_path):
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    config = {"models": {"opencode": "provider/model"}, "sandbox": "read-only"}
    store.write_json(config_path, config)
    installation.initialize_runtime(tmp_path)
    assert store.read_json(config_path) == {**config, "runtime": "api"}


@pytest.mark.parametrize("source", ["file", "environment"])
def test_explicit_environment_selection_is_not_overridden(tmp_path, monkeypatch, source):
    if source == "file":
        (tmp_path / ".env").write_text('EASEL_AGENT_RUNTIME="codex"\n', encoding="utf-8")
    else:
        monkeypatch.setenv("EASEL_AGENT_RUNTIME", "codex")
    assert installation.initialize_runtime(tmp_path) == "codex"
    assert not (tmp_path / "outputs" / "_harness" / "config.json").exists()


def test_skip_keeps_existing_openclaw_profile_but_does_not_require_it(tmp_path):
    state = tmp_path / "home" / ".openclaw-easel" / "openclaw.json"
    state.parent.mkdir(parents=True)
    state.write_bytes(b'{"custom": "keep"}')
    original = state.read_bytes()
    installation.initialize_runtime(tmp_path)
    assert store.settings(tmp_path / "outputs", {})["runtime"] == "api"
    assert state.read_bytes() == original


def test_repeated_skip_is_idempotent(tmp_path):
    installation.initialize_runtime(tmp_path)
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    original = config_path.read_bytes()
    installation.initialize_runtime(tmp_path)
    assert config_path.read_bytes() == original


@pytest.mark.parametrize("contents", ['{"runtime":"invalid"}', "[1]", "{", '{"models":null}', '{"sandbox":"invalid"}'])
def test_invalid_existing_config_is_not_overwritten(tmp_path, contents):
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(contents, encoding="utf-8")
    with pytest.raises(HarnessError):
        installation.initialize_runtime(tmp_path)
    assert config_path.read_text(encoding="utf-8") == contents


def test_invalid_default_does_not_write_config(tmp_path):
    with pytest.raises(ValueError):
        installation.initialize_runtime(tmp_path, "other")
    assert not (tmp_path / "outputs").exists()
