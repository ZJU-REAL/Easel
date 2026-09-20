"""设置类接口的安全回归（PR #46/#47 引入的写 .env / 装工具入口）。

这些接口的特殊之处：`web/app.py` 监听 0.0.0.0 且无鉴权，而 `setup.sh` 会 `source .env` ——
所以「往 .env 写值」和「按 id 装工具」两条路径上的任何一点松动，都会直接变成命令执行或
Key 外泄。下面全是负向用例，配一条正向用例保证闸没修成谁都过不去。

运行：pytest tests/test_web_security.py -q
"""
from __future__ import annotations

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
    monkeypatch.setattr(web, "_sync_openclaw_chat", lambda *a, **k: "")
    with TestClient(web.app) as c:
        c.env_file = env_file          # 用例里用来断言「.env 一个字节都没变」
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


# ---- #48 传输层：默认必须是久经考验的 CLI 路径 ----

def test_chat_transport_defaults_to_cli(monkeypatch):
    assert web.CHAT_TRANSPORT == "cli"


def test_http_path_falls_back_without_httpx():
    """httpx 没装时必须判定端点不可用 → 回退 CLI，而不是每轮报连接失败。"""
    import inspect
    assert "import httpx" in inspect.getsource(web._gateway_http_ready)
