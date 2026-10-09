"""gateway 端口解析的回归测试。

钉住的坑：Easel 用 ``--profile easel``，而 **OpenClaw 对非默认 profile 不用 18789** ——
它按 ``20000 + fnv1a32(profile) % 40000`` 算，easel → 37289（见 OpenClaw
dist/paths-*.mjs ``resolveGatewayPort``）。Easel 以前在 web/app.py、doctor、ping、
scripts/gateway.* 里各自写死 18789，于是「gateway 活着、面板常驻网关离线」，
``gateway.sh start`` 还会反复 --force 重启一个健康的 gateway。

修法是五端共用 easel/gateway_endpoint.py，且它的优先级与 OpenClaw 逐条对齐。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel import gateway_endpoint as ge  # noqa: E402

PORT_ENV_KEYS = ("OPENCLAW_GATEWAY_PORT", "EASEL_GATEWAY_PORT", "EASEL_GATEWAY_HOST")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """把 HOME / state dir 挪进 tmp，并且清掉会干扰端口判定的环境变量。"""
    for key in PORT_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return tmp_path


def write_config(tmp_path, gateway: dict | None) -> None:
    cfg = {} if gateway is None else {"gateway": gateway}
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "openclaw.json").write_text(json.dumps(cfg), encoding="utf-8")


# ── profile 哈希：就是本 issue 的现场 ──────────────────────────────────


def test_profile_hash_matches_openclaw():
    """easel → 37289。算错这一位，就等于又写死了一个假端口。"""
    assert ge.profile_port("easel") == 37289


def test_default_profile_keeps_18789():
    """只有默认 profile 才是历史默认端口 —— 这正是当初写死 18789 的由来。"""
    assert ge.profile_port("default") == ge.DEFAULT_GATEWAY_PORT
    assert ge.profile_port("") == ge.DEFAULT_GATEWAY_PORT


def test_profile_hash_is_deterministic_and_in_range():
    for name in ("easel", "dev", "staging", "a" * 64):
        port = ge.profile_port(name)
        assert 20000 <= port < 60000
        assert port == ge.profile_port(name)


def test_profile_hash_is_case_sensitive():
    """OpenClaw 的 normalizeProfileName 只在判断是否等于 "default" 时转小写比较，
    参与哈希的仍是原始大小写——"Easel"/"easel" 是两个不同 profile，端口不同。"""
    assert ge.profile_port("Easel") == 45577
    assert ge.profile_port("EASEL") == 48137
    assert ge.profile_port("Easel") != ge.profile_port("easel")


def test_default_profile_name_is_case_insensitive():
    """「是不是 default」这一步判定，OpenClaw 确实是大小写不敏感的。"""
    assert ge.profile_port("Default") == ge.DEFAULT_GATEWAY_PORT
    assert ge.profile_port("DEFAULT") == ge.DEFAULT_GATEWAY_PORT


# ── 解析优先级：环境变量 > openclaw.json > profile 哈希 ────────────────


def test_env_wins_over_config_and_hash(isolated, monkeypatch):
    write_config(isolated, {"port": 37289})
    monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", "19001")
    assert ge.resolve_gateway_port() == 19001
    assert ge.port_source() == "$OPENCLAW_GATEWAY_PORT"


def test_openclaw_env_beats_easel_env(isolated, monkeypatch):
    """gateway 进程只认 OPENCLAW_GATEWAY_PORT，两边冲突时必须跟随它，否则又错配。"""
    monkeypatch.setenv("EASEL_GATEWAY_PORT", "19002")
    monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", "19001")
    assert ge.resolve_gateway_port() == 19001


def test_easel_env_alone_is_honored(isolated, monkeypatch):
    """继承 2026.9 起 gateway_questions 的历史行为：EASEL_GATEWAY_PORT 仍可覆盖。"""
    monkeypatch.setenv("EASEL_GATEWAY_PORT", "19003")
    assert ge.resolve_gateway_port() == 19003
    assert ge.port_source() == "$EASEL_GATEWAY_PORT"


def test_config_beats_hash(isolated):
    write_config(isolated, {"port": 19004})
    assert ge.resolve_gateway_port() == 19004
    assert ge.port_source() == "openclaw.json"


def test_hash_used_when_config_has_no_port(isolated):
    """配置文件存在但没写端口（--allow-unconfigured / 手写配置）→ 哈希兜底。"""
    write_config(isolated, {"mode": "local"})
    assert ge.resolve_gateway_port() == 37289


def test_hash_used_when_config_missing(isolated):
    assert ge.resolve_gateway_port() == 37289


# ── 环境变量写法：与 OpenClaw 的 parseGatewayPortEnvValue 对齐 ─────────


@pytest.mark.parametrize("raw,expected", [
    ("18789", 18789),
    ("  19001  ", 19001),
    ("127.0.0.1:19001", 19001),
    ("[::1]:19002", 19002),
    # OpenClaw 的解析就这么宽：host 部分随便写，只取冒号后的数字。跟着它走，
    # 免得它认、我们不认，又变成端口错配。
    ("1:2", 2),
])
def test_env_port_forms(isolated, monkeypatch, raw, expected):
    monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", raw)
    assert ge.resolve_gateway_port() == expected


@pytest.mark.parametrize("raw", [
    "", "   ", "not-a-port", "0", "65536", "1:2:3", ":19001", "host:", "5.0", "+5",
])
def test_bad_env_port_falls_through(isolated, monkeypatch, raw):
    """非法值不能把解析卡死，也不能退到 0/65536 这种打不通的端口。"""
    monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", raw)
    assert ge.resolve_gateway_port() == 37289


# ── 配置文件容错 ───────────────────────────────────────────────────────


@pytest.mark.parametrize("gateway,expected", [
    (None, 37289),                      # 没有 gateway 段
    ({}, 37289),                        # 空 gateway
    ({"port": None}, 37289),
    ({"port": "19005"}, 37289),         # 字符串：OpenClaw 也不认（typeof number 才用）
    ({"port": True}, 37289),            # bool 是 int 子类，必须排掉
    ({"port": 0}, 37289),
    ({"port": 70000}, 37289),
])
def test_config_rejects_unusable_ports(isolated, gateway, expected):
    write_config(isolated, gateway)
    assert ge.resolve_gateway_port() == expected


def test_config_corrupt_json_falls_through(isolated):
    state = isolated / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "openclaw.json").write_text("{ not json", encoding="utf-8")
    assert ge.resolve_gateway_port() == 37289


# ── URL / host 拼装 ────────────────────────────────────────────────────


def test_urls_follow_resolved_port(isolated, monkeypatch):
    monkeypatch.setenv("OPENCLAW_GATEWAY_PORT", "19001")
    assert ge.healthz_url() == "http://127.0.0.1:19001/healthz"
    assert ge.chat_completions_url() == "http://127.0.0.1:19001/v1/chat/completions"


def test_ipv6_host_gets_brackets(isolated, monkeypatch):
    monkeypatch.setenv("EASEL_GATEWAY_HOST", "::1")
    assert ge.gateway_base_url() == "http://[::1]:37289"


# ── Windows 侧：不许再镜像一份端口解析 ────────────────────────────────────
# 这里原本有一整套「把 gateway.ps1 的 PowerShell 实现与 Python 解析器逐例对拍」的
# 回归，前提是「gateway.ps1 没法 import Python，只能镜像一份」。那个前提是错的 ——
# gateway.sh 一直就是 `python3 -c 'from easel.gateway_endpoint import ...'`，
# gateway.ps1 同样可以。
#
# 镜像实现的代价是真实发生过的事故：同一个端口有三份独立推导（gateway.ps1、
# gateway_endpoint.py、OpenClaw 自己），只要一份跟不上版本变化就错配，而 start 带
# --force —— 错配的后果不是探不通，而是杀掉占用那个端口的别人家 gateway。
# 现在 gateway.ps1 改为直接问 Python，对拍也就没有意义了：没有第二份实现可对。
# 取而代之的是下面这几条结构性断言（另见 tests/test_setup_ps1_static.py）。


def test_gateway_ps1_delegates_to_python_resolver():
    """gateway.ps1 必须调用 easel/gateway_endpoint.py，而不是自己算端口。"""
    text = (PROJECT_ROOT / "scripts" / "gateway.ps1").read_text(encoding="utf-8")
    assert "gateway_endpoint" in text and "resolve_gateway_port" in text, \
        "端口必须问单一真相源"
    for const in ("2166136261", "16777619", "40000"):
        assert const not in text, f"不该再出现自己实现端口推导的常量 {const}"


def test_gateway_ps1_fails_loudly_when_unresolvable():
    """解析不出端口要明着失败，不能退到一个猜的端口。

    「悄悄探错端口」会让 healthz 恒假，于是 start 反复 --force 重启一个健康的
    gateway —— 这正是当初要根治的病。
    """
    text = (PROJECT_ROOT / "scripts" / "gateway.ps1").read_text(encoding="utf-8")
    assert "无法解析 gateway 端口" in text
    assert "if ($Port -le 0)" in text


# ── 别再写死：源码层面钉住 ─────────────────────────────────────────────

GATEWAY_FILES = [
    "web/app.py",
    "easel/commands/doctor.py",
    "easel/commands/ping.py",
    "scripts/gateway.sh",
    "scripts/gateway.ps1",
]


@pytest.mark.parametrize("rel", GATEWAY_FILES)
def test_no_hardcoded_gateway_endpoint(rel):
    """别再用 ``<host>:18789`` 这种字面端点 —— 那正是本 issue 的病灶。

    只盯「端点字面量」和「shell 里直接喂端口」，不盯普通数字：doctor 的说明文字、
    gateway.ps1 里镜像 OpenClaw 的默认端口（只有 default profile 才是 18789）都合法。
    """
    text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    for bad in ("127.0.0.1:18789", "localhost:18789", "[::1]:18789",
                "18789/healthz", "18789/v1", "_port_pid 18789", "GATEWAY_PORT=18789"):
        assert bad not in text, f"{rel} 仍有写死的端点：{bad}"


@pytest.mark.parametrize("rel,needle", [
    ("web/app.py", "from easel.gateway_endpoint import"),
    ("easel/commands/doctor.py", "from easel.gateway_endpoint import"),
    ("easel/commands/ping.py", "from easel.gateway_endpoint import"),
    ("scripts/gateway.sh", "resolve_gateway_port"),
    ("scripts/gateway.ps1", "resolve_gateway_port"),
])
def test_port_comes_from_resolver(rel, needle):
    """每个入口都必须真的去查端口，而不是自己造一个。"""
    assert needle in (PROJECT_ROOT / rel).read_text(encoding="utf-8")
