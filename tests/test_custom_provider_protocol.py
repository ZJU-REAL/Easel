"""自定义供应商的协议支持（openai 默认 / anthropic-messages）。

背景：自定义供应商此前写死 openai-completions——中转站卖原生 Anthropic
格式（/v1/messages）时，面板显示「已配置」，实际请求全部 404/错乱，典型假
成功。现在保存行可带 protocol，落盘为 openclaw provider 的 api 字段。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import pytest
from fastapi.testclient import TestClient

import web.app as web
from easel import openclaw_workspace as ws


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EASEL_CHAT_TRANSPORT", "http")
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    oc = tmp_path / "openclaw.json"
    oc.write_text(json.dumps({
        "models": {"providers": {"openai": {"api": "openai-completions"}}},
        "agents": {"defaults": {"model": {"primary": "openai/gpt-x"}}},
    }), encoding="utf-8")
    monkeypatch.setattr(web, "_read_env", lambda: {})
    local = "http://127.0.0.1:7860"
    c = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234), headers={"Origin": local})
    return c, oc


def _row(**kw):
    base = {"slot": "custom", "name": "claude-relay", "model": "claude-sonnet-4-6",
            "baseUrl": "https://relay.example.com", "key": "sk-test", "primary": True}
    base.update(kw)
    return base


def test_custom_default_writes_no_api_field(client):
    """不选协议 = openai 默认：不写 api 字段，与既有配置零差异。"""
    c, oc = client
    r = c.post("/api/settings/models/save", json={"channel": "chat", "rows": [_row()]})
    assert r.status_code == 200, r.text
    provs = json.loads(oc.read_text())["models"]["providers"]
    assert "claude-relay" in provs and "api" not in provs["claude-relay"]


def test_custom_anthropic_writes_messages_api(client):
    """选 anthropic：provider 落 api=anthropic-messages。"""
    c, oc = client
    r = c.post("/api/settings/models/save",
               json={"channel": "chat", "rows": [_row(protocol="anthropic")]})
    assert r.status_code == 200, r.text
    provs = json.loads(oc.read_text())["models"]["providers"]
    assert provs["claude-relay"]["api"] == "anthropic-messages"


def test_custom_switch_back_to_openai_removes_api(client):
    """从 anthropic 切回 openai：api 字段被清掉，不留脏状态。"""
    c, oc = client
    c.post("/api/settings/models/save",
           json={"channel": "chat", "rows": [_row(protocol="anthropic")]})
    r = c.post("/api/settings/models/save",
               json={"channel": "chat", "rows": [_row(protocol="openai")]})
    assert r.status_code == 200
    provs = json.loads(oc.read_text())["models"]["providers"]
    assert "api" not in provs["claude-relay"]


def test_custom_invalid_protocol_rejected(client):
    c, _ = client
    r = c.post("/api/settings/models/save",
               json={"channel": "chat", "rows": [_row(protocol="grpc")]})
    assert r.status_code == 400


def test_channels_echo_protocol(client):
    """列表回显：anthropic-messages 的 provider 显示 protocol=anthropic。"""
    c, oc = client
    c.post("/api/settings/models/save",
           json={"channel": "chat", "rows": [_row(protocol="anthropic")]})
    data = c.get("/api/settings/models").json()
    row = next(r for r in data["channels"]["chat"]["rows"] if r.get("name") == "claude-relay")
    assert row["protocol"] == "anthropic"
