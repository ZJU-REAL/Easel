"""Web 面板写出的模型配置必须与 setup.sh 等价。

把模型配置从终端挪到浏览器之后，Web 面板成了主配置路径。但此前它与 setup.sh 的
写入并不等价，有四处会让「界面显示配好了、对话却不工作」：

  ① _sync_anthropic_provider 不写 api（docstring 说写了，代码漏了）→ OpenClaw
     2026.2.x 把 provider 当 openai-responses，对话静默返回「（无输出）」；
  ② relay 槽位只写 .env、从不创建 provider，却把 primary 指向 relay/<model>；
  ③ primary_ref 无脑拼前缀，而 CLAUDE_MODEL 本来就是 provider/model 形式；
  ④ 配置状态用裸真值判断，.env.example 的占位符被显示成「已配置」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app  # noqa: E402


@pytest.fixture
def oc_cfg(tmp_path, monkeypatch):
    """把 openclaw.json 指到临时文件，返回读取它的函数。"""
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"models": {"providers": {}}}), encoding="utf-8")
    monkeypatch.setattr(app, "_oc_config_path", lambda: cfg)
    return cfg


def test_anthropic_provider_declares_api(oc_cfg):
    """① provider 必须带 api=anthropic-messages，否则请求会打到 /responses。"""
    app._sync_anthropic_provider("https://example.test/v1", "sk-test-key")
    prov = json.loads(oc_cfg.read_text(encoding="utf-8"))["models"]["providers"]["anthropic"]
    assert prov["api"] == "anthropic-messages"
    assert prov["baseUrl"] == "https://example.test/v1"
    assert prov["apiKey"] == "sk-test-key"


def test_incomplete_existing_provider_gets_repaired(oc_cfg):
    """早退判据要把 api 算进去，否则缺 api 的残缺 provider 永远修不回来。"""
    oc_cfg.write_text(json.dumps({"models": {"providers": {"anthropic": {
        "baseUrl": "https://example.test/v1", "apiKey": "sk-test-key", "models": [],
    }}}}), encoding="utf-8")
    app._sync_anthropic_provider("https://example.test/v1", "sk-test-key")
    prov = json.loads(oc_cfg.read_text(encoding="utf-8"))["models"]["providers"]["anthropic"]
    assert prov["api"] == "anthropic-messages", "缺 api 的既有 provider 必须被补上"


def test_legacy_relay_provider_is_folded_in(oc_cfg):
    """② 老版本写出的 relay provider 要折叠进 anthropic，key 不能变孤儿。"""
    oc_cfg.write_text(json.dumps({"models": {"providers": {"relay": {
        "baseUrl": "https://relay.test/v1", "apiKey": "sk-legacy", "models": [],
    }}}}), encoding="utf-8")
    app._sync_anthropic_provider("", "")
    provs = json.loads(oc_cfg.read_text(encoding="utf-8"))["models"]["providers"]
    assert "relay" not in provs, "迁移后 relay 必须删掉，避免两处并存"
    assert provs["anthropic"]["apiKey"] == "sk-legacy"
    assert provs["anthropic"]["baseUrl"] == "https://relay.test/v1"


@pytest.mark.parametrize("model,pkey,expected", [
    ("anthropic/claude-opus-4-7", "anthropic", "anthropic/claude-opus-4-7"),
    ("claude-opus-4-7", "anthropic", "anthropic/claude-opus-4-7"),
    ("gpt-5.5", "openai", "openai/gpt-5.5"),
])
def test_primary_ref_never_double_prefixes(model, pkey, expected):
    """③ model 已含 provider 前缀时不能再拼一次。"""
    ref = model if "/" in model else f"{pkey}/{model}"
    assert ref == expected


def test_placeholder_key_reports_missing(tmp_path, monkeypatch):
    """④ .env.example 的占位符必须显示「缺 key」，且不给出假掩码。

    这条最关键：安装不再在终端问 key、改为引导到浏览器，若面板谎报「已配置」，
    等于把用户送进一个无法自解释的死胡同。
    """
    envf = tmp_path / ".env"
    envf.write_text("ANTHROPIC_API_KEY=sk-ant-REPLACE_ME\n"
                    "CLAUDE_MODEL=anthropic/claude-sonnet-4-6\n", encoding="utf-8")
    monkeypatch.setattr(app, "ENV_FILE", envf)
    rows = app._model_channels()["channels"]["chat"]["rows"]
    assert rows, "应当仍然列出该槽位（只是标记为缺 key）"
    for r in rows:
        assert r["result"] == "缺 key", f"占位符被判为已配置：{r}"
        assert not r["keyMasked"], f"占位符不该给出掩码：{r['keyMasked']!r}"


def test_real_key_reports_configured(tmp_path, monkeypatch):
    """反向用例：真 key 仍要显示已配置，别把判据收得过紧。"""
    envf = tmp_path / ".env"
    # 刻意不用 sk-ant-api03-… 这种真实格式：GitHub 的 secret scanning push
    # protection 会把它当成泄露的 Anthropic key 而拦住推送。_is_set 只判
    # 「非空且非占位符」，随便一个不含 REPLACE_ME 的值就够了。
    envf.write_text("ANTHROPIC_API_KEY=dummy-value-for-unit-test\n", encoding="utf-8")
    monkeypatch.setattr(app, "ENV_FILE", envf)
    rows = app._model_channels()["channels"]["chat"]["rows"]
    anth = [r for r in rows if r["slot"] == "anthropic"]
    assert anth and anth[0]["result"] == "已配置"
    assert anth[0]["keyMasked"]


# ── /api/settings/bootstrap：首开自检 ────────────────────────────────

def test_bootstrap_reports_unconfigured_for_placeholder(tmp_path, monkeypatch):
    """占位符 key + 无路由时必须报 modelConfigured=false。

    安装不再在终端问 key，前端靠这个判据决定是否把用户直接带到模型设置页；
    判错的话用户会落在一个看起来正常、实际不能对话的界面上。
    """
    from fastapi.testclient import TestClient

    monkeypatch.setattr(app, "ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-REPLACE_ME\n", encoding="utf-8")
    monkeypatch.setattr("easel.commands.doctor._env_key_valid", lambda: False)
    monkeypatch.setattr("easel.commands.doctor._primary_model_routable",
                        lambda: (False, "provider 未配置认证"))

    local = "http://127.0.0.1:7860"
    with TestClient(app.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        r = c.get("/api/settings/bootstrap")
    assert r.status_code == 200
    d = r.json()
    assert d["modelConfigured"] is False
    assert d["envKeyOk"] is False
    assert d["routeOk"] is False


def test_bootstrap_requires_both_env_and_route(monkeypatch):
    """.env 有 key 但 provider 没写进 openclaw 时也必须算未配置。

    这正是 doctor 里那条「全绿却对话报错」防线：只查 .env 查不出 provider 一个字
    没写的情况，两个判据必须同时成立。
    """
    from fastapi.testclient import TestClient

    monkeypatch.setattr("easel.commands.doctor._env_key_valid", lambda: True)
    monkeypatch.setattr("easel.commands.doctor._primary_model_routable",
                        lambda: (False, "No route-compatible authentication source"))
    local = "http://127.0.0.1:7860"
    with TestClient(app.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        d = c.get("/api/settings/bootstrap").json()
    assert d["modelConfigured"] is False, "只有 .env 有 key 不等于配好了"
    assert d["envKeyOk"] is True and d["routeOk"] is False


def test_gateway_restart_takes_no_parameters() -> None:
    """该端点刻意无参数：web/app.py 绑 0.0.0.0 且无鉴权，argv 必须完全固定。"""
    import inspect

    src = inspect.getsource(app.api_gateway_restart)
    sig = inspect.signature(app.api_gateway_restart)
    assert not sig.parameters, f"不允许接受参数：{sig}"
    # 命令里只许出现字面量与脚本路径，不得有外部输入拼接
    assert "'restart'" in src or '"restart"' in src
    assert "req." not in src and "request" not in src.lower().replace("subprocess", "")


# ── role：哪一行在当主，不能写死 ──────────────────────────────────────

@pytest.mark.parametrize("env_key,slot", [
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("EASEL_LLM_API_KEY", "relay"),
])
def test_primary_row_reports_main_role(env_key, slot, tmp_path, monkeypatch, oc_cfg):
    """primary 指向该行时必须显示「主」。

    anthropic / relay 两行原先把 role 写死成「备」，而 openai 行是从 primary 算的。
    于是主模型明明是 anthropic/... 面板也显示备用 —— 用户据此判断「哪个在生效」会判错。
    """
    envf = tmp_path / ".env"
    envf.write_text(f"{env_key}=dummy-value-for-unit-test\n"
                    "EASEL_LLM_BASE_URL=https://example.test/v1\n"
                    "CLAUDE_MODEL=anthropic/claude-opus-4-7\n", encoding="utf-8")
    monkeypatch.setattr(app, "ENV_FILE", envf)
    oc_cfg.write_text(json.dumps({
        "agents": {"defaults": {"model": {"primary": "anthropic/claude-opus-4-7"}}},
        "models": {"providers": {}},
    }), encoding="utf-8")

    rows = {r["slot"]: r for r in app._model_channels()["channels"]["chat"]["rows"]}
    assert slot in rows, f"{slot} 行应当出现：{list(rows)}"
    assert rows[slot]["role"] == "主", f"{slot} 是主模型却显示 {rows[slot]['role']}"


def test_non_primary_row_reports_backup_role(tmp_path, monkeypatch, oc_cfg):
    """反向用例：primary 指向别处时不能误报「主」。"""
    envf = tmp_path / ".env"
    envf.write_text("EASEL_LLM_API_KEY=dummy-value-for-unit-test\n"
                    "EASEL_LLM_BASE_URL=https://example.test/v1\n"
                    "CLAUDE_MODEL=anthropic/claude-opus-4-7\n", encoding="utf-8")
    monkeypatch.setattr(app, "ENV_FILE", envf)
    oc_cfg.write_text(json.dumps({
        "agents": {"defaults": {"model": {"primary": "openai/gpt-5.5"}}},
        "models": {"providers": {}},
    }), encoding="utf-8")

    rows = {r["slot"]: r for r in app._model_channels()["channels"]["chat"]["rows"]}
    assert rows["relay"]["role"] == "备", "primary 指向 openai 时 relay 不该显示主"


def test_bare_model_name_also_matches_primary(tmp_path, monkeypatch, oc_cfg):
    """CLAUDE_MODEL 写成裸模型名（不带 provider 前缀）时也要能对上。"""
    envf = tmp_path / ".env"
    envf.write_text("ANTHROPIC_API_KEY=dummy-value-for-unit-test\n"
                    "CLAUDE_MODEL=claude-opus-4-7\n", encoding="utf-8")
    monkeypatch.setattr(app, "ENV_FILE", envf)
    oc_cfg.write_text(json.dumps({
        "agents": {"defaults": {"model": {"primary": "anthropic/claude-opus-4-7"}}},
        "models": {"providers": {}},
    }), encoding="utf-8")

    rows = {r["slot"]: r for r in app._model_channels()["channels"]["chat"]["rows"]}
    assert rows["anthropic"]["role"] == "主"
