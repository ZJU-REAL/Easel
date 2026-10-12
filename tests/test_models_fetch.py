"""拉取模型列表：自定义供应商的「模型名」不再靠手打。

OpenAI 兼容网关普遍提供 GET {base}/models。此前面板里自定义供应商的模型名
只能靠用户去别处查了再抄进来，抄错一个字符要到对话报 Unknown model 才发现。
本端点代前端去拉一次列表，UI 上变成下拉/补全。

安全设计与 /api/settings/models/selftest 一致：
  * key 由前端显式传入（未保存的草稿也能拉），服务端不落盘、不写日志；
  * 目标必须过 _valid_base_url + _ssrf_safe —— 拉取虽只读，但带着用户 Key，
    一样不能变成把凭据送进内网的跳板。

运行：pytest tests/test_models_fetch.py -q
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import app as web  # noqa: E402

ORIGINAL_ENV = (
    "OPENAI_BASE_URL=https://api.openai.com/v1\n"
    "OPENAI_API_KEY=sk-fak...test\n"
)


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "openclaw")
    env_file = tmp_path / ".env"
    env_file.write_text(ORIGINAL_ENV, encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env_file)
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        c.env_file = env_file
        yield c


class _Resp:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload, self.status = payload, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


def _stub_opener(monkeypatch, payload: bytes, capture: list | None = None):
    capture = capture if capture is not None else []
    # 测试环境 DNS 对 example.com 的解析不可控（可能落到内网网段被 _ssrf_safe 拒）。
    # 正常路径用例只关心「请求怎么发、响应怎么解析」，放行交给 _ssrf_safe 自己的用例。
    monkeypatch.setattr(web, "_ssrf_safe", lambda u: True)
    # 同一原因：_valid_base_url 也会做 DNS/格式校验，测试环境不可控。
    monkeypatch.setattr(web, "_valid_base_url", lambda u: True)
    class _Opener:
        def open(self, rq, timeout=None):
            capture.append((rq.full_url, {k.lower(): v for k, v in dict(rq.headers).items()}))
            return _Resp(payload)

    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *a, **k: _Opener())


def test_fetch_parses_openai_shape(sandbox, monkeypatch):
    """标准 OpenAI 形状 {"data":[{"id":...}]} → 返回排好序的 id 列表。"""
    capture: list = []
    _stub_opener(monkeypatch, json.dumps(
        {"data": [{"id": "b-model"}, {"id": "a-model"}, {"object": "chat.model"}]}).encode(), capture)
    resp = sandbox.post("/api/settings/models/available",
                        json={"baseUrl": "https://api.example.com/v1", "key": "sk-x"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["models"] == ["a-model", "b-model"], "应去重外的非模型项并排序"
    url, headers = capture[0]
    assert url == "https://api.example.com/v1/models"
    assert headers.get("authorization") == "Bearer sk-x"


def test_fetch_parses_anthropic_shape(sandbox, monkeypatch):
    """anthropic 协议：x-api-key 头 + {"data":[{"id":...}]}（/v1/models）。"""
    capture: list = []
    _stub_opener(monkeypatch, json.dumps({"data": [{"id": "claude-sonnet-4-6"}]}).encode(), capture)
    resp = sandbox.post("/api/settings/models/available",
                        json={"baseUrl": "https://api.anthropic.com",
                              "key": "sk-ant-x", "protocol": "anthropic"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["models"] == ["claude-sonnet-4-6"]
    url, headers = capture[0]
    assert url == "https://api.anthropic.com/v1/models"
    assert headers.get("x-api-key") == "sk-ant-x"
    assert headers.get("anthropic-version")


def test_fetch_falls_back_to_bare_list(sandbox, monkeypatch):
    """有些网关直接返回 [\"m1\",\"m2\"]，别报 500。"""
    _stub_opener(monkeypatch, json.dumps(["z", "y"]).encode())
    resp = sandbox.post("/api/settings/models/available",
                        json={"baseUrl": "https://api.example.com/v1", "key": "k"})
    assert resp.status_code == 200
    assert resp.json()["models"] == ["y", "z"]


def test_fetch_rejects_private_targets(sandbox, monkeypatch):
    """带着 Key 的请求不许进内网（SSRF 闸与 selftest 同款）。"""
    seen: list = []

    def _boom(*a, **k):  # pragma: no cover - 若被调用说明闸失效
        seen.append(a)
        raise AssertionError("内网目标不应发起请求")

    monkeypatch.setattr(web.urllib.request, "urlopen", _boom)
    resp = sandbox.post("/api/settings/models/available",
                        json={"baseUrl": "http://169.254.169.254/latest", "key": "k"})
    assert resp.status_code >= 400
    assert not seen


def test_fetch_requires_base_url(sandbox):
    resp = sandbox.post("/api/settings/models/available", json={"key": "k"})
    assert resp.status_code >= 400


def test_fetch_reuses_stored_key_when_draft_empty(sandbox, monkeypatch):
    """草稿没填 Key 时回落到该槽位已存的值（不用为了拉列表再贴一遍明文）。"""
    capture: list = []
    _stub_opener(monkeypatch, json.dumps({"data": [{"id": "m1"}]}).encode(), capture)
    resp = sandbox.post("/api/settings/models/available",
                        json={"slot": "openai", "protocol": "openai"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["models"] == ["m1"]
    url, headers = capture[0]
    # base 也回落到 .env 里的 OPENAI_BASE_URL
    assert url == "https://api.openai.com/v1/models"
    assert headers.get("authorization") == "Bearer sk-fak...test"


def test_fetch_custom_slot_uses_provider_name(sandbox, monkeypatch):
    """自定义供应商：凭据按 provider 名从 openclaw.json 取。"""
    monkeypatch.setattr(web, "_openclaw_provider_creds",
                        lambda: {"myproxy": ("https://my.example.com/v1", "sk-stored")})
    capture: list = []
    _stub_opener(monkeypatch, json.dumps({"data": [{"id": "m2"}]}).encode(), capture)
    resp = sandbox.post("/api/settings/models/available",
                        json={"slot": "custom", "name": "myproxy"})
    assert resp.status_code == 200, resp.text
    url, headers = capture[0]
    assert url == "https://my.example.com/v1/models"
    assert headers.get("authorization") == "Bearer sk-stored"
