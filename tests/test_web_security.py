"""设置类接口的安全回归（PR #46/#47 引入的写 .env / 装工具入口）。

这些接口的特殊之处：`web/app.py` 监听 0.0.0.0 且无鉴权，而 `setup.sh` 会 `source .env` ——
所以「往 .env 写值」和「按 id 装工具」两条路径上的任何一点松动，都会直接变成命令执行或
Key 外泄。下面全是负向用例，配一条正向用例保证闸没修成谁都过不去。

运行：pytest tests/test_web_security.py -q
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
import install_tool  # noqa: E402

ORIGINAL_ENV = (
    "OPENAI_BASE_URL=https://api.openai.com/v1\n"
    "OPENAI_API_KEY=sk-fake-not-a-real-key-for-test\n"
    "SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1\n"
    "SILICONFLOW_API_KEY=sk-fake-siliconflow-test-value\n"
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把 .env 与 openclaw.json 同步都换成沙箱，绝不碰用户真配置。"""
    env_file = tmp_path / ".env"
    env_file.write_text(ORIGINAL_ENV, encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env_file)
    monkeypatch.setattr(web, "_openclaw_provider_creds",
                        lambda: {"myproxy": ("https://good.example.com/v1", "sk-fake-custom")})
    # openclaw.json 也必须隔离：_sync_openclaw_chat 直连 Path.home()/'.openclaw-easel'/openclaw.json，
    # 不隔离就会把夹具值写进用户真配置（models[0].id / baseUrl / apiKey），跑完 pytest 主模型与
    # provider 目录失配，对话报 Unknown model（issue #62）。重定向 home 根一次覆盖所有运行时路径。
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    oc_dir = tmp_path / ".openclaw-easel"
    oc_dir.mkdir()
    (oc_dir / "openclaw.json").write_text(json.dumps({
        "models": {"providers": {"openai": {
            "api": "openai-completions",
            "apiKey": "sk-fake-existing",
            "baseUrl": "https://api.openai.com/v1",
            "models": [{"id": "gpt-4o"}],
        }}},
        "agents": {"defaults": {"model": {"primary": "openai/gpt-4o"}}},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # local_write_guard 会把「非本机写请求」判 403。设置为本机来源。
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, client=('127.0.0.1', 51234),
                    headers={'Origin': local}) as c:
        c.env_file = env_file          # 用例里用来断言「.env 一个字节都没变」
        c.openclaw_cfg = oc_dir / "openclaw.json"   # 同理：真 openclaw.json 也不许被写
        yield c


def _save(client, payload):
    return client.post("/api/settings/models/save", json=payload)


def _assert_blocked(client, payload):
    resp = _save(client, payload)
    assert resp.status_code >= 400, f"本该拒绝却放行了：{resp.status_code} {resp.text[:200]}"
    assert client.env_file.read_text(encoding="utf-8") == ORIGINAL_ENV, ".env 被改动了"


# ---- .env 换行注入：值里塞一行 → setup.sh `source .env` 时被当命令执行 ----

@pytest.mark.parametrize("row", [
    {"slot": "openai", "model": "gpt-4o", "baseUrl": "https://api.openai.com/v1\nMALICIOUS=1"},
    {"slot": "openai", "model": "m\nEVIL=$(id)"},
    {"slot": "openai", "key": "sk-a\nPATH=/tmp"},
    {"slot": "openai", "key": "sk-a\rPATH=/tmp"},
])
def test_env_newline_injection_rejected(client, row):
    _assert_blocked(client, {"channel": "chat", "rows": [row]})


@pytest.mark.parametrize("updates", [
    {"OPENAI_API_KEY": "sk-x\nPATH=/tmp/evil"},   # 值里换行
    {"OPENAI_API_KEY": "sk-x\x00"},               # 值里 NUL
    {"A=B\nC": "1"},                              # 键名里换行
    {"FOO BAR": "1"},                             # 键名含空格
    {"9LIVES": "1"},                              # 键名数字开头
    {"": "1"},                                    # 空键名
])
def test_guard_env_values_rejects(updates):
    with pytest.raises(Exception):
        web._guard_env_values(updates)


# ---- 不换行也能执行命令：bash 在赋值右侧照做命令替换 ----
# `KEY=$(id)` 里没有任何换行，却在 `source .env` 时直接执行；`KEY=a;id` 则是元字符截断赋值
# 另起一条命令。只拦 \r\n\x00 等于没拦住这条路。
@pytest.mark.parametrize("value", [
    "sk-a$(id)",            # 命令替换
    "sk-a`id`",             # 反引号
    "sk-a${HOME}",          # 变量展开（值会被悄悄改写）
    "sk-a;id",              # 分号另起一条命令
    "sk-a&&id",
    "sk-a|id",
    "sk-a >/tmp/pwn",       # 空格 + 重定向
    "sk-a'\"",              # 引号：破坏后续解析
    "sk-a\\",               # 反斜杠续行
])
def test_guard_env_values_rejects_shell_metachars(value):
    with pytest.raises(Exception):
        web._guard_env_values({"OPENAI_API_KEY": value})


def test_env_shell_substitution_rejected_via_api(client):
    """走真接口也得拦住，且 .env 一个字节都不许变。"""
    _assert_blocked(client, {"channel": "chat",
                             "rows": [{"slot": "openai", "model": "gpt-4o", "key": "sk-a$(id)"}]})


def test_guard_env_values_allows_normal():
    web._guard_env_values({"OPENAI_API_KEY": "sk-normal", "OPENAI_BASE_URL": "https://a.com/v1"})


@pytest.mark.parametrize("value", [
    "sk-proj-Abc123_-xyz",                                   # 常见 key 形态
    "https://api.example.com/v1",                            # base url
    "https://gw.example.com:8443/openai/v1?api-version=1",   # 带端口与 query
    "anthropic/claude-sonnet-5",                             # 模型 id
    "8890",                                                  # 端口
    "a.b-c_d@e+f=g~h,i%j#k[l]",                              # 允许字符集全覆盖
])
def test_guard_env_values_allows_real_values(value):
    """收紧字符集不能把正常值一起误杀 —— 这几类是面板真会写进去的。"""
    web._guard_env_values({"OPENAI_API_KEY": value})


def test_both_env_writers_are_guarded():
    """两个写入口都得挂闸——漏一个等于没修。"""
    import inspect
    for fn in (web._write_env, web._write_env_direct):
        assert "_guard_env_values" in inspect.getsource(fn), fn.__name__


# ---- 换址窃 Key：改 Base URL + Key 留空（留空=沿用旧 Key）----

@pytest.mark.parametrize("channel,row", [
    ("chat", {"slot": "openai", "baseUrl": "https://evil.example.com/v1", "key": ""}),
    ("transcribe", {"slot": "siliconflow", "baseUrl": "https://evil.example.com/v1", "key": ""}),
    # 自定义供应商压根不写 .env，只有 openclaw.json 那侧的闸能拦
    ("chat", {"slot": "custom", "name": "myproxy", "model": "x",
              "baseUrl": "https://evil.example.com/v1", "key": ""}),
])
def test_rebase_without_new_key_rejected(client, channel, row):
    _assert_blocked(client, {"channel": channel, "rows": [row]})


def test_local_gateway_user_is_not_locked_out(client, monkeypatch):
    """这道闸不能把本地网关用户一起关在外面。

    网关模式下 openclaw.json 存的 baseUrl 是 127.0.0.1:8890（真实上游在 easel-models.yaml），
    面板显示/回传的却是上游地址 —— 两者天生不等，闸按「换址」判就会让网关用户连改个模型都
    保存不了。而且 _sync_openclaw_chat 那边本来就不改网关的 baseUrl，不存在拿旧 Key 打新地址。
    """
    monkeypatch.setattr(web, "_openclaw_provider_creds",
                        lambda: {"myproxy": ("http://127.0.0.1:8890/v1", "sk-fake-gw")})
    resp = _save(client, {"channel": "chat",
                          "rows": [{"slot": "custom", "name": "myproxy", "model": "gpt-5.5",
                                    "baseUrl": "https://upstream.example.com/v1", "key": ""}]})
    assert resp.status_code < 400, f"网关用户被误拦：{resp.status_code} {resp.text[:200]}"


def test_local_gateway_helper():
    assert web._is_local_gateway_base("http://127.0.0.1:8890/v1")
    assert not web._is_local_gateway_base("https://api.openai.com/v1")
    assert not web._is_local_gateway_base("")
    assert not web._is_local_gateway_base(None)


# ---- Base URL 必须整串校验（只看开头挡不住内嵌凭据/控制字符）----

@pytest.mark.parametrize("bad", [
    "http://u:p@evil.example.com/v1",
    "ftp://evil.example.com",
    "https://api.openai.com/v1\tx",
    "javascript:alert(1)",
])
def test_base_url_validated_whole_string(client, bad):
    _assert_blocked(client, {"channel": "chat",
                             "rows": [{"slot": "openai", "baseUrl": bad, "key": "sk-new"}]})


@pytest.mark.parametrize("url,ok", [
    ("https://api.openai.com/v1", True),
    ("http://example.org:8080/v1", True),
    ("https://a.com\nX=1", False),
    ("http://u:p@evil.com", False),
    ("https://", False),
    ("not-a-url", False),
])
def test_valid_base_url(url, ok):
    assert web._valid_base_url(url) is ok


# ---- 自测探针会把真 Key 当 Bearer 发出去：不许指向本机/内网/云元数据 ----

@pytest.mark.parametrize("url", [
    "http://127.0.0.1:18789/v1",
    "http://localhost/v1",
    "http://169.254.169.254/latest",      # 云元数据
    "http://10.0.0.1/v1",
    "http://192.168.1.1/v1",
    "http://[::1]/v1",
    "http://no-such-host-zzz.invalid/v1",  # 解析不了就当不安全
])
def test_ssrf_guard_rejects_internal(url):
    assert web._ssrf_safe(url) is False


def test_selftest_probe_has_guards():
    import inspect
    src = inspect.getsource(web.api_models_selftest)
    assert "_valid_base_url" in src and "_ssrf_safe" in src, "探针前必须先过两道闸"
    assert "redirect_request" in src, "不能跟跳转——跟了等于绕过前面的判断"


# ---- 装工具接口：id 只认引擎里真实存在的配方 ----

@pytest.mark.parametrize("bad_id", ["--help", "; touch /tmp/pwn", "../../etc/passwd", "nope-xyz"])
def test_install_id_must_be_known(client, bad_id):
    assert client.post("/api/env/install", json={"id": bad_id}).status_code >= 400


def test_install_ids_come_from_engine():
    ids = web._install_tool_ids()
    assert ids and "node" in ids, f"配方表读不出来：{ids}"


# ---- 配方里的 {dir}：必须整元素落地，不可拼进更大的串（拼进去就能逃逸成代码）----

def test_fill_rejects_embedded_dir():
    with pytest.raises(ValueError):
        install_tool._fill(["--prefix={dir}/x"], "python3", "/tmp/a")


def test_fill_keeps_dir_intact():
    assert install_tool._fill(["{dir}"], "python3", "/tmp/a b'c") == ["/tmp/a b'c"]


# ---- 正向：别把闸修成谁都过不去 ----

def test_legit_save_still_works(client):
    resp = _save(client, {"channel": "chat", "rows": [
        {"slot": "openai", "model": "gpt-4o",
         "baseUrl": "https://new.example.com/v1", "key": "sk-fresh"}]})
    assert resp.status_code == 200, resp.text[:300]
    env = web._read_env()
    assert env["OPENAI_BASE_URL"] == "https://new.example.com/v1"
    assert env["OPENAI_API_KEY"] == "sk-fresh"


def test_model_only_change_not_blocked(client):
    """地址没变、只改模型（Key 留空）是日常操作，不能被换址规则误伤。"""
    resp = _save(client, {"channel": "chat", "rows": [
        {"slot": "openai", "model": "gpt-4o-mini",
         "baseUrl": "https://api.openai.com/v1", "key": ""}]})
    assert resp.status_code == 200, resp.text[:300]
    assert web._read_env()["OPENAI_MODEL"] == "gpt-4o-mini"


def test_save_never_writes_real_openclaw_config(client):
    """回归（#62）：保存模型只能落在沙箱 openclaw.json 上。

    _sync_openclaw_chat 会改写 provider 目录与 primary。一旦 home 没被隔离，pytest 就会把夹具值
    写进用户真配置，跑完测试对话报 Unknown model。这里既断言 home 确实被重定向，又读回沙箱文件
    断言写入结果——若哪天隔离失效（例如路径改成 import 期常量），两条断言都会响亮失败。
    """
    assert Path.home() != Path("~").expanduser(), "fixture 必须把 home 重定向到沙箱"
    resp = _save(client, {"channel": "chat", "rows": [
        {"slot": "openai", "model": "deepseek-flash",
         "baseUrl": "https://api.deepseek.com", "key": "sk-fake-new"}]})
    assert resp.status_code == 200, resp.text[:300]
    data = json.loads(client.openclaw_cfg.read_text(encoding="utf-8"))
    assert data["models"]["providers"]["openai"]["models"][0]["id"] == "deepseek-flash"


# ---- #48 传输层：直连常驻网关提速，但绝不能把会话历史搞丢 ----

def test_http_path_falls_back_without_httpx(monkeypatch):
    """httpx 没装时必须判定端点不可用 → 回退 CLI，而不是每轮报连接失败。"""
    import builtins
    real_import = builtins.__import__

    def _no_httpx(name, *a, **k):
        if name == "httpx":
            raise ImportError("no httpx")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_httpx)
    assert web._gateway_http_ready(force=True) is False


def test_ready_probe_hits_chat_completions_not_models():
    """探针不能打 /v1/models：那个路径会被网关控制台 SPA 的 catch-all 接走，端点没开也返回
    200（body 是 HTML 首页），于是只要网关活着就恒为 True —— 等于没探，每轮对话直接撞 404。

    探针的 **端口** 同样不能写死：Easel 用 --profile easel，OpenClaw 对非默认 profile
    分配的端口不是 18789（easel → 37289），写死就恒探不通、对话悄悄退回 CLI 冷启动路径。
    所以 URL 一律走 easel/gateway_endpoint 解析。"""
    import inspect
    # 去掉 docstring 再比 —— 注释里本来就要写清为什么不能探 /v1/models
    body = inspect.getsource(web._gateway_http_ready).split('"""')[-1]
    assert "chat_completions_url()" in body
    assert "127.0.0.1" not in body
    assert "/v1/models" not in body

    from easel.gateway_endpoint import chat_completions_url
    assert chat_completions_url().endswith("/v1/chat/completions")


@pytest.mark.parametrize("code,expected", [(400, True), (404, False), (500, False)])
def test_ready_probe_reads_status_code(monkeypatch, code, expected):
    """400（缺 messages）= 路由挂着；404 = chatCompletions.enabled 没开。"""
    def _raise(*a, **k):
        raise web.urllib.error.HTTPError("u", code, "x", None, None)

    monkeypatch.setattr(web.urllib.request, "urlopen", _raise)
    assert web._gateway_http_ready(force=True) is expected


@pytest.fixture()
def _tp(tmp_path, monkeypatch):
    """把两个判定依赖的目录都挪进 tmp。"""
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path / "sess")
    monkeypatch.setattr(web, "OPENCLAW_SESSIONS_DIR", tmp_path / "oc")
    (tmp_path / "oc").mkdir()
    monkeypatch.setattr(web, "CHAT_TRANSPORT", "http")
    monkeypatch.setattr(web, "_gateway_http_ready", lambda *a, **k: True)
    return tmp_path


def test_existing_cli_session_never_switches_to_http(_tp):
    """已有 CLI transcript 的会话必须继续走 cli。

    两条路径写的是不同 transcript：CLI 用 `--session-id`（uuid5）钉死，而
    /v1/chat/completions 压根不读 x-openclaw-session-id（openclaw 2026.6.11 实测：只有 MCP
    端点消费它），网关自己挑文件名。中途换边 = agent 看不到任何历史（实测答"无历史"）。
    """
    sk = "web-existing"
    (_tp / "oc" / f"{web._openclaw_session_id(sk)}.jsonl").write_text("{}", encoding="utf-8")
    assert web._resolve_transport(sk) == "cli"


def test_pinned_http_session_stays_http(_tp, monkeypatch):
    """钉过 http 的会话即使探针此刻说不可用也不能改判 cli —— 网关那份 transcript 我们按
    名字找不回来，改判就是静默丢历史。"""
    sk = "web-pinned"
    web._pin_transport(sk, "http")
    monkeypatch.setattr(web, "_gateway_http_ready", lambda *a, **k: False)
    assert web._resolve_transport(sk) == "http"


def test_new_session_uses_http_when_endpoint_live(_tp):
    assert web._resolve_transport("web-brand-new") == "http"


def test_new_session_falls_back_when_endpoint_dead(_tp, monkeypatch):
    monkeypatch.setattr(web, "_gateway_http_ready", lambda *a, **k: False)
    assert web._resolve_transport("web-brand-new") == "cli"


def test_transport_env_switch_forces_cli(_tp, monkeypatch):
    monkeypatch.setattr(web, "CHAT_TRANSPORT", "cli")
    assert web._resolve_transport("web-brand-new") == "cli"


def test_pin_transport_never_pins_cli(_tp):
    """cli 侧由 uuid5 transcript 文件自证，不该再落一份可能跟现实打架的状态。"""
    web._pin_transport("web-x", "cli")
    assert not web._transport_pin_file("web-x").exists()


def test_http_mode_drops_raw_text_delta():
    """HTTP 模式正文以 SSE 为准；raw 流里的 text_delta 必须丢弃，否则每个字进两次队列。"""
    import inspect
    src = inspect.getsource(web.api_chat_stream)
    seg = src.split('et == "text_delta"')[1][:220]
    assert "is_http" in seg, "HTTP 模式没有屏蔽 raw 流的正文，前端会看到重复内容"


def test_http_mode_still_tails_raw_stream_for_thinking():
    """openclaw 的 chat/completions 不回传任何 reasoning 增量（实测该实现里 thinking/reasoning
    出现 0 次），思考只在共享 raw 流里。HTTP 模式不 tail 它，思考面板就永远是空的。"""
    import inspect
    src = inspect.getsource(web.api_chat_stream)
    seg = src.split("stdout_fut = None")[1][:600]
    assert seg.count("_tail") >= 2, "HTTP 分支没有启动 raw 流 tail，思考流会整个丢失"
