"""openclaw_base_cmd() 命中 Windows npm .cmd shim 时必须绕开 cmd.exe。

背景（PR #78，实机复现于 #77）：PATH 中 nvm 的 node 排在独立 node 目录之前时，
`which("openclaw")` 命中 npm 生成的 `.CMD` shim。直接运行该 shim 会被
CreateProcess 经 cmd.exe 解析 argv，多行 `--message` 在第一个换行处被截断——
agent 只收到 chat_turn_message 的第一行（画像前缀），表现为每轮只回
「收到，画像已确认」。修复：识别 `.cmd`/`.bat` shim，解析其同目录的
`node.exe` + `node_modules/openclaw/openclaw.mjs`（标准 npm 全局布局）直接
运行，完全绕开 cmd.exe；顺带避免用 PATH 上版本不对的 node（如 nvm 的旧版）
跑 openclaw。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel import openclaw_cmd as oc  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache():
    oc.openclaw_base_cmd.cache_clear()
    yield
    oc.openclaw_base_cmd.cache_clear()


def _fake_npm_global_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """造一个 Windows npm 全局布局：shim/node.exe/node_modules 同目录。"""
    npm_dir = tmp_path / "AppData" / "Roaming" / "npm"
    mjs = npm_dir / "node_modules" / "openclaw" / "openclaw.mjs"
    mjs.parent.mkdir(parents=True)
    mjs.write_text("// fake\n", encoding="utf-8")
    node_exe = npm_dir / "node.exe"
    node_exe.write_text("", encoding="utf-8")
    shim = npm_dir / "openclaw.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    return shim, node_exe, mjs


def test_cmd_shim_resolves_to_colocated_node_and_mjs(tmp_path, monkeypatch):
    shim, node_exe, mjs = _fake_npm_global_layout(tmp_path)
    # PATH 上的 node 是另一个目录（模拟 nvm node 排在前面，版本/位置都跟 shim 无关）。
    other_node = tmp_path / "nvm" / "node"
    other_node.parent.mkdir(parents=True)
    other_node.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda c: {
        "node": str(other_node), "openclaw": str(shim),
    }.get(c))
    cmd = oc.openclaw_base_cmd()
    assert cmd == [str(node_exe), str(mjs)], cmd
    # 绝不能用 PATH 上的 nvm node——那正是 bug 的根因。
    assert str(other_node) not in cmd


def test_cmd_shim_without_colocated_node_falls_through(tmp_path, monkeypatch):
    """shim 旁边没有 node.exe（非标准布局）：不能崩，老老实实退化到后续探测/直接跑 shim。"""
    npm_dir = tmp_path / "npm"
    mjs = npm_dir / "node_modules" / "openclaw" / "openclaw.mjs"
    mjs.parent.mkdir(parents=True)
    mjs.write_text("// fake\n", encoding="utf-8")
    shim = npm_dir / "openclaw.cmd"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    # 不造 node.exe
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(shim) if c == "openclaw" else None)
    cmd = oc.openclaw_base_cmd()
    assert cmd == [str(shim)]


def test_bat_shim_also_recognized(tmp_path, monkeypatch):
    npm_dir = tmp_path / "npm"
    mjs = npm_dir / "node_modules" / "openclaw" / "openclaw.mjs"
    mjs.parent.mkdir(parents=True)
    mjs.write_text("// fake\n", encoding="utf-8")
    node_exe = npm_dir / "node.exe"
    node_exe.write_text("", encoding="utf-8")
    shim = npm_dir / "openclaw.bat"
    shim.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(shim) if c == "openclaw" else None)
    cmd = oc.openclaw_base_cmd()
    assert cmd == [str(node_exe), str(mjs)]


def test_non_shim_openclaw_on_path_unaffected(tmp_path, monkeypatch):
    """常规 Unix 场景（openclaw 是真可执行文件，非 .cmd/.bat）：新分支不介入，行为不变。"""
    real = tmp_path / "bin" / "openclaw"
    real.parent.mkdir(parents=True)
    real.write_text("#!/bin/sh\n", encoding="utf-8")
    real.chmod(0o755)
    monkeypatch.setattr(oc.shutil, "which", lambda c: str(real) if c == "openclaw" else None)
    cmd = oc.openclaw_base_cmd()
    assert cmd == [str(real)]
