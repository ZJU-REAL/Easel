"""openclaw_base_cmd() 必须能找到 npm 自定义全局前缀下的 openclaw。

背景（实机复现）：npm 全局前缀被设为用户目录（官方推荐的免 sudo 装法
`npm config set prefix ~/.npm-global`）时，node 在系统路径、openclaw 装在
`<prefix>/lib/node_modules/openclaw/openclaw.mjs` —— 原实现的三个候选路径
全部落空，于是 `easel chat/skill/ping` 全部抛 FileNotFoundError，而 gateway
其实跑得好好的（用户被误导成"没装 openclaw"）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel import openclaw_cmd as oc  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    # 用例间/runner 环境的隔离：npm_config_prefix 在装过 npm 的机器上真实存在，
    # 不清掉会让「显式覆盖」等用例的行为依赖宿主机状态。
    oc.openclaw_base_cmd.cache_clear()
    yield
    oc.openclaw_base_cmd.cache_clear()


def _fake_tree(tmp_path: Path) -> tuple[Path, Path]:
    """造一个 npm 自定义前缀布局：node 在别处，openclaw 在 <prefix> 下。"""
    prefix = tmp_path / "npm-global"
    mjs = prefix / "lib" / "node_modules" / "openclaw" / "openclaw.mjs"
    mjs.parent.mkdir(parents=True)
    mjs.write_text("// fake\n", encoding="utf-8")
    node = tmp_path / "usr" / "bin" / "node"
    node.parent.mkdir(parents=True)
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)
    return prefix, node


def test_npm_prefix_env_var_resolves_openclaw(tmp_path, monkeypatch):
    """EASEL_NPM_GLOBAL_PREFIX / npm_config_prefix 指向的布局应被识别。"""
    prefix, node = _fake_tree(tmp_path)
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(node) if c == "node" else None)
    monkeypatch.setenv("npm_config_prefix", str(prefix))
    cmd = oc.openclaw_base_cmd()
    assert cmd[0] == str(node)
    assert cmd[1].endswith("openclaw.mjs")
    assert str(prefix) in cmd[1]


def test_explicit_env_override_wins(tmp_path, monkeypatch):
    prefix, node = _fake_tree(tmp_path)
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(node) if c == "node" else None)
    monkeypatch.setenv("EASEL_NPM_GLOBAL_PREFIX", str(prefix))
    cmd = oc.openclaw_base_cmd()
    assert str(prefix) in cmd[1]


def test_home_npm_global_fallback(tmp_path, monkeypatch):
    """没有 npm_config_prefix 时，~/.npm-global 这个最流行的约定也要覆盖。"""
    prefix, node = _fake_tree(tmp_path)
    fake_home = tmp_path / "home"
    (fake_home / ".npm-global" / "lib" / "node_modules" / "openclaw").mkdir(parents=True)
    (fake_home / ".npm-global" / "lib" / "node_modules" / "openclaw" / "openclaw.mjs").write_text("// x", encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(node) if c == "node" else None)
    monkeypatch.setattr(oc.Path, "home", staticmethod(lambda: fake_home))
    cmd = oc.openclaw_base_cmd()
    assert ".npm-global" in cmd[1]


def test_path_openclaw_symlink_still_preferred(tmp_path, monkeypatch):
    """原有行为不能退化：PATH 上的 openclaw 指向 .mjs 时优先用它。"""
    mjs = tmp_path / "openclaw.mjs"
    mjs.write_text("// real", encoding="utf-8")
    link = tmp_path / "bin" / "openclaw"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(mjs)
    except OSError:
        pytest.skip("此环境无法创建 symlink（Windows 非管理员）")
    node = tmp_path / "node"
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)

    def which(c):
        return {"node": str(node), "openclaw": str(link)}.get(c)

    monkeypatch.setattr(oc.shutil, "which", which)
    cmd = oc.openclaw_base_cmd()
    assert cmd == [str(node), str(mjs.resolve())]


def test_missing_everywhere_raises_with_actionable_message(tmp_path, monkeypatch):
    """真的都没有时才抛错，且错误信息要给出可操作建议。"""
    monkeypatch.setattr(oc.shutil, "which", lambda c: None)
    monkeypatch.setattr(oc.Path, "home", staticmethod(lambda: tmp_path))
    with pytest.raises(FileNotFoundError) as ei:
        oc.openclaw_base_cmd()
    assert "npm i -g openclaw" in str(ei.value)


def test_npmrc_prefix_is_read(tmp_path, monkeypatch):
    """用户级 ~/.npmrc 的 prefix= 是 npm 自定义前缀的权威来源，应被读取。"""
    prefix, node = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".npmrc").write_text(f"prefix={prefix}\n", encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(node) if c == "node" else None)
    monkeypatch.setattr(oc.Path, "home", staticmethod(lambda: home))
    cmd = oc.openclaw_base_cmd()
    assert str(prefix) in cmd[1]


def test_npmrc_malformed_is_tolerated(tmp_path, monkeypatch):
    """.npmrc 语法怪异（注释/空行/引号）不应导致崩溃。"""
    prefix, node = _fake_tree(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".npmrc").write_text(
        "# comment\n; another\n\nregistry=https://x\n", encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(node) if c == "node" else None)
    monkeypatch.setattr(oc.Path, "home", staticmethod(lambda: home))
    # 没 prefix 配置 → 走 ~/.npm-global 约定（也不存在）→ 报错，但不崩出非预期异常
    with pytest.raises(FileNotFoundError):
        oc.openclaw_base_cmd()
