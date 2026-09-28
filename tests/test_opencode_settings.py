"""OpenCode 设置面板（runtime=opencode）的配置层与 web 端点回归。

重点：凭证只回状态不回明文；非法输入不落盘；env 来源的凭证不在面板删；默认模型写入
项目 opencode.json 时保留既有字段。

运行：pytest tests/test_opencode_settings.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app as web  # noqa: E402
from easel.runtimes import opencode_config  # noqa: E402

SECRET = "sk-fake-opencode-secret-key"

PROJECT_CONFIG_BODY = {
    "$schema": "https://opencode.ai/config.json",
    "model": "opencode-go/deepseek-v4.1-flash",
    "instructions": ["openclaw/workspace/AGENTS.md"],
    "skills": {"paths": ["./skills/openclaw"]},
}


@pytest.fixture()
def fake_server(monkeypatch):
    """假 OpenCode server：读请求返回固定目录，写请求记账。"""
    calls: list[tuple] = []
    providers = [
        {"id": "openai", "name": "OpenAI", "source": "env", "key": SECRET,
         "models": {"gpt-4o": {}}},
        {"id": "opencode-go", "name": "OpenCode Go", "source": "api", "key": SECRET,
         "models": {"deepseek-v4.1-flash": {}}},
        {"id": "novaxai", "name": "Novax", "source": "config", "key": "", "models": {}},
    ]
    models = [
        {"id": "deepseek-v4.1-flash", "providerID": "opencode-go", "name": "DeepSeek V4.1 Flash"},
        {"id": "gpt-4o", "providerID": "openai", "name": "GPT-4o"},
    ]
    auth = {
        "openai": [{"type": "api"}],
        "opencode-go": [{"type": "api"}],
        "github-copilot": [{"type": "oauth"}],
    }

    def fake_request(method, path, body=None):
        calls.append((method, path, body))
        if path == "/global/health":
            return {"healthy": True}
        if path == "/config/providers":
            return {"providers": providers}
        if path == "/api/model":
            return {"data": models}
        if path == "/provider/auth":
            return auth
        if method in ("PUT", "DELETE", "PATCH"):
            return True
        raise AssertionError(f"unexpected request {method} {path}")

    monkeypatch.setattr(opencode_config, "_request", fake_request)
    return calls


@pytest.fixture()
def project_config(tmp_path, monkeypatch):
    path = tmp_path / "opencode.json"
    path.write_text(json.dumps(PROJECT_CONFIG_BODY, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(opencode_config, "PROJECT_CONFIG", path)
    return path


@pytest.fixture()
def client(fake_server, tmp_path, monkeypatch):
    """web 客户端：opencode runtime + 沙箱 .env，绝不碰用户真配置。"""
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "opencode")
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_MARKER=keep-me\n", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env_file)
    with TestClient(web.app) as c:
        c.env_file = env_file
        yield c


def _writes(calls):
    return [c for c in calls if c[0] in ("PUT", "DELETE", "PATCH")]


# ---- 快照：脱敏与降级 ----

def test_snapshot_never_returns_raw_key(fake_server, project_config):
    snap = opencode_config.snapshot()
    assert snap["serverReady"] is True
    assert snap["primary"] == PROJECT_CONFIG_BODY["model"]
    blob = json.dumps(snap, ensure_ascii=False)
    assert SECRET not in blob
    assert all("key" not in p for p in snap["providers"])
    assert {p["id"]: p["hasKey"] for p in snap["providers"]} == {
        "openai": True, "opencode-go": True, "novaxai": False,
    }


def test_snapshot_degrades_when_server_down(monkeypatch):
    def down(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(opencode_config, "_request", down)
    snap = opencode_config.snapshot()
    assert snap["serverReady"] is False
    assert snap["providers"] == [] and snap["models"] == []
    assert "gateway" in snap["message"]


# ---- 凭证：校验与写入 ----

@pytest.mark.parametrize("pid,key", [
    ("openai", ""),
    ("openai", "sk has space"),
    ("openai", " sk-x "),
    ("OPENAI", "sk-x"),
    ("-openai", "sk-x"),
    (" openai", "sk-x"),
    ("openai", "x" * 401),
])
def test_set_provider_key_rejects_bad_input(fake_server, pid, key):
    with pytest.raises(ValueError):
        opencode_config.set_provider_key(pid, key)
    assert _writes(fake_server) == []


def test_provider_id_error_never_echoes_value(fake_server):
    """Key 误填到 provider id 位置时，错误信息不能回显它。"""
    secret = "sk-Fake_Secret_ABC123"
    with pytest.raises(ValueError) as exc:
        opencode_config.set_provider_key(secret, "sk-x")
    assert secret[:20] not in str(exc.value)


def test_set_provider_key_puts_api_auth(fake_server):
    opencode_config.set_provider_key("opencode-go", SECRET)
    assert ("PUT", "/auth/opencode-go", {"type": "api", "key": SECRET}) in fake_server


def test_remove_provider_key_rejects_env_source(fake_server):
    with pytest.raises(ValueError, match="环境变量"):
        opencode_config.remove_provider_key("openai")
    assert _writes(fake_server) == []


def test_remove_provider_key_deletes(fake_server):
    opencode_config.remove_provider_key("opencode-go")
    assert ("DELETE", "/auth/opencode-go", None) in fake_server


# ---- 默认模型：白名单 + 合并写项目配置 ----

def test_set_primary_model_rejects_unknown(fake_server, project_config):
    with pytest.raises(ValueError, match="目录"):
        opencode_config.set_primary_model("opencode-go/not-a-model")
    assert _writes(fake_server) == []
    assert json.loads(project_config.read_text(encoding="utf-8"))["model"] == PROJECT_CONFIG_BODY["model"]


def test_set_primary_model_merges_project_config(fake_server, project_config):
    opencode_config.set_primary_model("openai/gpt-4o")
    data = json.loads(project_config.read_text(encoding="utf-8"))
    assert data["model"] == "openai/gpt-4o"
    assert data["instructions"] == PROJECT_CONFIG_BODY["instructions"]
    assert data["skills"] == PROJECT_CONFIG_BODY["skills"]
    assert data["$schema"] == PROJECT_CONFIG_BODY["$schema"]
    assert project_config.with_name("opencode.json.bak-web").is_file()
    assert opencode_config.primary_model() == "openai/gpt-4o"


# ---- web 端点 ----

def test_api_get_does_not_leak_key(client):
    r = client.get("/api/settings/opencode")
    assert r.status_code == 200
    assert SECRET not in r.text
    body = r.json()
    assert body["serverReady"] is True
    assert all("key" not in p for p in body["providers"])


def test_api_get_degrades_when_server_down(client, monkeypatch):
    def down(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(opencode_config, "_request", down)
    r = client.get("/api/settings/opencode")
    assert r.status_code == 200
    assert r.json()["serverReady"] is False


def test_api_save_rejects_invalid_without_side_effects(client, fake_server):
    r = client.post("/api/settings/opencode/save", json={"keys": {"openai": "bad key"}})
    assert r.status_code == 400
    assert _writes(fake_server) == []
    assert client.env_file.read_text(encoding="utf-8") == "SECRET_MARKER=keep-me\n"


def test_api_save_requires_something_to_change(client, fake_server):
    r = client.post("/api/settings/opencode/save", json={})
    assert r.status_code == 400
    assert _writes(fake_server) == []


def test_api_save_503_when_server_down(client, monkeypatch):
    def down(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(opencode_config, "_request", down)
    r = client.post("/api/settings/opencode/save", json={"keys": {"opencode-go": SECRET}})
    assert r.status_code == 503
    assert "gateway" in r.json()["detail"]


def test_api_save_key_and_model(client, fake_server, project_config):
    r = client.post("/api/settings/opencode/save", json={
        "keys": {"opencode-go": SECRET},
        "primary": "openai/gpt-4o",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["primary"] == "openai/gpt-4o"
    assert SECRET not in json.dumps(body, ensure_ascii=False)
    assert ("PUT", "/auth/opencode-go", {"type": "api", "key": SECRET}) in fake_server
    assert json.loads(project_config.read_text(encoding="utf-8"))["model"] == "openai/gpt-4o"
    assert client.env_file.read_text(encoding="utf-8") == "SECRET_MARKER=keep-me\n"


def test_api_save_rejected_for_non_opencode_runtime(client, fake_server, monkeypatch):
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "openclaw")
    r = client.post("/api/settings/opencode/save", json={"keys": {"opencode-go": SECRET}})
    assert r.status_code == 400
    assert "不支持" in r.json()["detail"]
    assert _writes(fake_server) == []


# ---- 运行命令：面板选的默认模型随每轮生效 ----

def _start_capture(monkeypatch, tmp_path, project_model):
    """跑一次 OpenCodeAdapter().start()，返回捕获到的命令行。"""
    from easel.runtimes import opencode as oc_mod
    from easel.runtimes.base import RunRequest

    if project_model is None:
        monkeypatch.setattr(opencode_config, "PROJECT_CONFIG", tmp_path / "missing.json")
    else:
        cfg = tmp_path / "opencode.json"
        cfg.write_text(json.dumps({"model": project_model}), encoding="utf-8")
        monkeypatch.setattr(opencode_config, "PROJECT_CONFIG", cfg)

    captured: dict = {}

    class FakeProc:
        stdout = iter(())

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(oc_mod, "base_cmd", lambda: ["opencode"])
    monkeypatch.setattr(oc_mod.subprocess, "Popen",
                        lambda cmd, **kw: (captured.__setitem__("cmd", cmd), FakeProc())[1])
    oc_mod.OpenCodeAdapter().start(
        RunRequest(prompt="hi", session_key="k", timeout=60, cwd=tmp_path, env={}))
    return captured["cmd"]


def test_opencode_run_passes_project_model(monkeypatch, tmp_path):
    """server 缓存旧配置 / 会话记着旧模型时，靠 --model 让面板选择下一条消息生效。"""
    cmd = _start_capture(monkeypatch, tmp_path, "opencode-go/glm-5.3-flash")
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "opencode-go/glm-5.3-flash"


def test_opencode_run_omits_model_when_config_missing(monkeypatch, tmp_path):
    cmd = _start_capture(monkeypatch, tmp_path, None)
    assert "--model" not in cmd
