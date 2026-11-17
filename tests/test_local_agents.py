"""本机 agent CLI 探测与接入。

场景：用户本机已经装着 Claude Code / Gemini CLI 并且登录过，这种情况下填 API Key
是多余的 —— OpenClaw 底座有 claude-cli / google-gemini-cli 后端，直接复用 CLI 的
登录态。这个模块负责「探测本机有什么」以及「如实说明哪些能免 key 用」。

关键约束：探测结果必须**诚实**。装了的 CLI 不等于能免 key 用（要有底座后端），
没装的不许报成已装。宁可显示「不支持」，也不能让用户以为配好了。

运行：pytest tests/test_local_agents.py -q
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
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import app as web  # noqa: E402
from easel import local_agents as la  # noqa: E402


# ---- 探测层 ----


def test_detect_reports_installed_and_missing(monkeypatch):
    """PATH 上有 claude、没有 codex → 结果如实反映。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    by_id = {a["id"]: a for a in la.detect_local_agents()}
    assert by_id["claude-code"]["installed"] is True
    assert by_id["claude-code"]["command"] == "claude"
    assert by_id["codex"]["installed"] is False
    assert by_id["codex"]["path"] == ""


def test_only_clis_with_backend_are_usable_without_key(monkeypatch):
    """装了 Codex 也不能算「免 key 可用」——底座没有它的 provider。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: f"/usr/bin/{c}")
    by_id = {a["id"]: a for a in la.detect_local_agents()}
    assert by_id["claude-code"]["usableWithoutKey"] is True
    assert by_id["gemini-cli"]["usableWithoutKey"] is True
    assert by_id["codex"]["installed"] is True
    assert by_id["codex"]["supported"] is False
    assert by_id["codex"]["usableWithoutKey"] is False, "没有底座后端就不算免 key 可用"
    assert by_id["opencode"]["usableWithoutKey"] is False


def test_missing_cli_is_never_usable(monkeypatch):
    """没装 CLI 时即便有底座后端，也不能报成可用。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: None)
    for a in la.detect_local_agents():
        assert a["installed"] is False
        assert a["usableWithoutKey"] is False


def test_codex_native_entry_does_not_claim_openclaw_or_authenticated_access(monkeypatch):
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/codex" if c == "codex" else None)
    monkeypatch.setattr(la, "_configured_providers", lambda: {"openai"})
    agents = {a["id"]: a for a in la.detect_local_agents()}
    codex = agents["codex"]
    assert codex["installed"] is True
    assert codex["nativeRuntime"] == "codex"
    assert codex["supported"] is False
    assert codex["configured"] is False
    assert codex["usableWithoutKey"] is False
    assert codex["openclawProvider"] is None
    assert codex["models"] == []
    assert "codex login" in codex["loginHint"]
    assert agents["copilot-cli"]["nativeRuntime"] is None


def test_configured_reflects_openclaw_json(monkeypatch, tmp_path):
    """openclaw.json 里已有 anthropic provider → configured 为真（cli 已接入）。"""
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({"models": {"providers": {"anthropic": {"baseUrl": "x"}}}}),
                   encoding="utf-8")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    by_id = {a["id"]: a for a in la.detect_local_agents()}
    assert by_id["claude-code"]["configured"] is True


def test_broken_config_does_not_raise(monkeypatch, tmp_path):
    """openclaw.json 损坏时探测要能降级，不能把界面打挂。"""
    cfg = tmp_path / "openclaw.json"
    cfg.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(la.shutil, "which", lambda c: None)
    assert la.summarize_local_agents()["installedCount"] == 0


def test_summary_counts(monkeypatch):
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    s = la.summarize_local_agents()
    assert s["installedCount"] == 1
    assert s["usableWithoutKeyCount"] == 1
    assert s["usableWithoutKey"] == ["claude-code"]


# ---- Web 接口 ----


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_BASE_URL=https://api.openai.com/v1\n", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env_file)

    oc_dir = tmp_path / ".openclaw-easel"
    oc_dir.mkdir()
    oc = oc_dir / "openclaw.json"
    oc.write_text(json.dumps({
        "models": {"providers": {"openai": {"baseUrl": "https://x/v1", "apiKey": "k",
                                            "models": [{"id": "m"}]}}},
        "agents": {"defaults": {"model": {"primary": "openai/m"}}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(web.Path, "home", staticmethod(lambda: tmp_path))

    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=("127.0.0.1", 51234),
                    headers={"Origin": local}) as c:
        c.env_file = env_file
        c.oc_file = oc
        yield c


def test_api_local_agents_lists_all(sandbox, monkeypatch):
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    resp = sandbox.get("/api/settings/local-agents")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["installedCount"] == 1
    ids = {a["id"] for a in body["agents"]}
    assert {"claude-code", "gemini-cli", "codex", "opencode"} <= ids


def test_enable_rejects_unknown_agent(sandbox):
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "not-a-thing"})
    assert resp.status_code == 404


def test_enable_rejects_not_installed(sandbox, monkeypatch):
    """没装 Claude Code 却想接入 → 400，不能凭空造出 provider。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: None)
    before = sandbox.oc_file.read_text(encoding="utf-8")
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert resp.status_code == 400
    assert "没有找到" in resp.json()["detail"]
    assert sandbox.oc_file.read_text(encoding="utf-8") == before, "被拒绝的请求不该动配置"


def test_enable_rejects_cli_without_backend(sandbox, monkeypatch):
    """Codex 装了但底座不支持 → 明确拒绝，而不是写入一个用不了的 provider。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/codex" if c == "codex" else None)
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "codex"})
    assert resp.status_code == 400
    assert "暂无底座后端" in resp.json()["detail"]
    providers = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))["models"]["providers"]
    assert "codex" not in providers and "anthropic" not in providers


def test_enable_claude_code_writes_provider_and_primary(sandbox, monkeypatch):
    """接入 Claude Code：声明 anthropic provider + 主模型切到 claude-cli。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert resp.status_code == 200, resp.text

    data = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))
    assert data["models"]["providers"]["anthropic"]["baseUrl"] == "https://api.anthropic.com"
    # 不写 apiKey：登录态由 CLI 自己持有，写空 key 反而会覆盖掉已有配置
    assert "apiKey" not in data["models"]["providers"]["anthropic"]
    assert data["agents"]["defaults"]["model"]["primary"] == "claude-cli/claude-sonnet-4-6"
    # 原有 provider 与备份行为不变
    assert data["models"]["providers"]["openai"]["apiKey"] == "k"
    assert (sandbox.oc_file.parent / "openclaw.json.bak-web").is_file()


def test_enable_claude_code_respects_relay_base_from_env(sandbox, monkeypatch):
    """.env 里配了中转站时，一键接入必须保留它，不能覆盖成官方端点。

    （真实 bug：实现最初用 os.environ 读 base —— .env 不在进程环境里，
    永远拿到空，然后把用户已配好的 ANTHROPIC_BASE_URL 静默覆盖成官方端点。）
    """
    sandbox.env_file.write_text(
        "OPENAI_BASE_URL=https://api.openai.com/v1\n"
        "ANTHROPIC_BASE_URL=https://my-relay.example.com\n",
        encoding="utf-8")
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert resp.status_code == 200, resp.text
    data = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))
    assert data["models"]["providers"]["anthropic"]["baseUrl"] == "https://my-relay.example.com"


def test_enable_gemini_cli_writes_primary(sandbox, monkeypatch):
    """Gemini CLI 接入必须真的写点什么。

    真实 bug：最初 gemini 分支只设 note、primary_ref 为空 → 返回
    「已接入」但 openclaw.json 一个字节都没变（假成功）。google 插件的
    CLI 后端默认启用，所以接入动作就是切主模型。
    """
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/gemini" if c == "gemini" else None)
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "gemini-cli"})
    assert resp.status_code == 200, resp.text
    data = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))
    assert data["agents"]["defaults"]["model"]["primary"].startswith("google-gemini-cli/"), \
        "gemini 接入没有切换主模型 = 假成功"


def test_every_supported_cli_has_an_enable_path(sandbox, monkeypatch):
    """所有 supported=true 的 CLI 都必须能接入（否则就是假承诺）。

    这条是防回归：新增后端时若忘了写接入分支，会落到 500 而不是静默成功。
    """
    monkeypatch.setattr(la.shutil, "which", lambda c: f"/usr/bin/{c}")
    for a in la.detect_local_agents():
        if not a["supported"]:
            continue
        resp = sandbox.post("/api/settings/local-agents/enable", json={"id": a["id"]})
        assert resp.status_code == 200, f"{a['id']} 声称可接入却失败：{resp.status_code} {resp.text[:200]}"


def test_enable_is_idempotent(sandbox, monkeypatch):
    """重复接入不该反复改写配置（第二次没有变化 → note 为空）。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    first = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert first.status_code == 200
    snap = sandbox.oc_file.read_text(encoding="utf-8")
    second = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert second.status_code == 200
    assert sandbox.oc_file.read_text(encoding="utf-8") == snap, "无变化时不该重写"


# ── 模型目录 + enable 选模型（审计后补全：像 AionUi 一样可下拉选模型） ──

def test_catalog_returns_real_models_for_claude_cli():
    """claude-cli 的模型目录从插件清单真实读出（本机装了 openclaw 才有）。"""
    cat = la.catalog_for_provider("claude-cli")
    if not cat:  # CI 环境可能没有 openclaw 安装
        import pytest; pytest.skip("openclaw 未安装")
    ids = {m["id"] for m in cat}
    assert "claude-sonnet-4-6" in ids
    assert all(m.get("name") for m in cat)


def test_catalog_empty_for_unknown_or_unsupported():
    assert la.catalog_for_provider(None) == []
    assert la.catalog_for_provider("copilot-proxy") == []
    assert la.catalog_for_provider("nonexistent-backend") == []


def test_detect_local_agents_includes_models_field(sandbox):
    for a in la.detect_local_agents():
        assert "models" in a, a["id"]
        if a["supported"]:
            assert isinstance(a["models"], list)
        else:
            assert a["models"] == []


def test_enable_with_chosen_model_switches_primary(sandbox, monkeypatch):
    """enable 传 model=claude-opus-5-5 → 主模型必须是那个，不是默认 sonnet。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    resp = sandbox.post("/api/settings/local-agents/enable",
                        json={"id": "claude-code", "model": "claude-opus-5-5"})
    assert resp.status_code == 200, resp.text
    data = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))
    assert data["agents"]["defaults"]["model"]["primary"] == "claude-cli/claude-opus-5-5"


def test_enable_rejects_model_not_in_catalog(sandbox, monkeypatch):
    """目录外模型 → 400 拒绝，绝不写入不存在的模型引用。

    sandbox 里没有 openclaw 插件文件，catalog_for_provider 返回空 → 生产上
    「目录为空时无法校验」；这里 mock 一份真实形状的目录来钉住校验逻辑。
    """
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    monkeypatch.setattr(la, "catalog_for_provider",
                        lambda p: [{"id": "claude-sonnet-4-6", "name": "x", "contextWindow": 1},
                                   {"id": "claude-opus-5-5", "name": "y", "contextWindow": 1}] if p == "claude-cli" else [])
    resp = sandbox.post("/api/settings/local-agents/enable",
                        json={"id": "claude-code", "model": "claude-not-a-model"})
    assert resp.status_code == 400
    assert "可选" in resp.text


def test_enable_default_model_unchanged_when_no_model_param(sandbox, monkeypatch):
    """不传 model → 行为与此前完全一致（claude 默认 sonnet-4-6）。"""
    monkeypatch.setattr(la.shutil, "which", lambda c: "/usr/bin/claude" if c == "claude" else None)
    resp = sandbox.post("/api/settings/local-agents/enable", json={"id": "claude-code"})
    assert resp.status_code == 200
    data = json.loads(sandbox.oc_file.read_text(encoding="utf-8"))
    assert data["agents"]["defaults"]["model"]["primary"] == "claude-cli/claude-sonnet-4-6"


def test_gemini_cli_catalog_real(tmp_path, monkeypatch):
    """google 插件的目录键是 'google'（不是后端 id），gemini 模型必须能读到。

    注意不能用 sandbox fixture：它会 monkeypatch Path.home 到 tmp_path，
    导致 catalog_for_provider 找不到真实安装的 openclaw 插件清单。
    """
    cat = la.catalog_for_provider("google-gemini-cli")
    if not cat:
        import pytest; pytest.skip("openclaw 未安装")
    ids = {m["id"] for m in cat}
    assert "gemini-3.1-pro-preview" in ids
    assert len(cat) >= 5
