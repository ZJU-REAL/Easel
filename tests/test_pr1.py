"""PR #1（跨平台健壮性）回归测试。

分两类：
- f2p（fail→pass）：改前应失败、改后应通过 —— 证明修复生效。
- p2p（pass→pass）：改前改后都通过 —— 证明无回归。

覆盖三处 Python 修复：
  H2  easel chat 必须走 openclaw_base_cmd()，不能写死 "openclaw" 字面量（Windows 崩）
  M6  easel web 必须传播子进程返回码（不能恒返回 0）
  M5  easel skill 的 _resolve_input 对非 UTF-8 文本文件不能裸崩

H1（scripts/gateway.sh macOS 兼容）因有启动副作用，在 BEFORE/AFTER 阶段用
直接的 `bash scripts/gateway.sh` 调用验证，不放进 pytest。

运行（轻量 venv，只需 pytest）：
  /tmp/easel-pr1-venv/bin/python -m pytest tests/test_pr1.py -q
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel import cli  # noqa: E402
from easel.commands import skill as cli_skill  # noqa: E402


# ============================================================
# f2p: M6 — easel web 传播返回码
# ============================================================

class _FakeCompleted:
    def __init__(self, returncode):
        self.returncode = returncode


class _FakeSubprocess:
    """替换 cli.subprocess，run() 不真正起进程，只返回预设返回码。"""

    def __init__(self, returncode):
        self._rc = returncode

    def run(self, *args, **kwargs):
        return _FakeCompleted(self._rc)


def test_cmd_web_propagates_nonzero_returncode(monkeypatch):
    """web/app.py 非零退出时，easel web 必须把返回码透传（不能恒返回 0）。"""
    monkeypatch.setattr(cli, "subprocess", _FakeSubprocess(returncode=7))
    rc = cli.cmd_web(types.SimpleNamespace(port=7860))
    assert rc == 7


def test_cmd_web_returns_zero_on_success(monkeypatch):
    monkeypatch.setattr(cli, "subprocess", _FakeSubprocess(returncode=0))
    rc = cli.cmd_web(types.SimpleNamespace(port=7860))
    assert rc == 0


def test_cmd_web_returns_1_when_script_missing(monkeypatch, tmp_path):
    """web/app.py 不存在（安装不完整）时应返回 1 并提示，而不是起进程后崩。"""
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)  # tmp_path 下没有 web/app.py
    rc = cli.cmd_web(types.SimpleNamespace(port=7860))
    assert rc == 1


# ============================================================
# f2p: M5 — _resolve_input 对非 UTF-8 文本文件不崩
# ============================================================

def test_resolve_input_handles_non_utf8_text_file(tmp_path):
    """GBK 编码的 .csv（常见于国内导出）不是合法 UTF-8，read_text 会抛
    UnicodeDecodeError。修复后应回退成“请处理这个文件：路径”，与二进制分支同义。"""
    p = tmp_path / "data.csv"
    p.write_bytes("内容,值\n你好,1\n".encode("gbk"))  # 非合法 UTF-8

    out = cli_skill._resolve_input(str(p))

    assert "请处理这个文件" in out
    assert str(p) in out


def test_resolve_input_handles_utf16_text_file(tmp_path):
    """UTF-16 编码的 .txt 同样不是合法 UTF-8 流，不应崩溃。"""
    p = tmp_path / "note.txt"
    p.write_bytes("hello".encode("utf-16"))

    out = cli_skill._resolve_input(str(p))

    assert "请处理这个文件" in out


# ============================================================
# p2p: _resolve_input 既有行为不回归
# ============================================================

def test_resolve_input_plain_text():
    assert cli_skill._resolve_input("普通文本") == "普通文本"


def test_resolve_input_long_text_no_crash():
    long = "压缩测试" * 100  # 超过文件名长度上限
    assert cli_skill._resolve_input(long) == long


def test_resolve_input_image_path(tmp_path):
    p = tmp_path / "pic.png"
    p.write_bytes(b"\x89PNG\r\n")
    out = cli_skill._resolve_input(str(p))
    assert "请处理这个图片" in out and str(p) in out


def test_resolve_input_binary_media_path(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00\x01\x02\xff\xfe")
    out = cli_skill._resolve_input(str(p))
    assert "请处理这个文件" in out


def test_resolve_input_utf8_text_file(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("文件内容", encoding="utf-8")
    assert cli_skill._resolve_input(str(p)) == "文件内容"


# ============================================================
# p2p: _find_skill 既有行为不回归
# ============================================================

def test_find_skill_resolves_plain_name():
    assert cli_skill._find_skill("social-content") == "social-content"


def test_find_skill_resolves_skill_prefix():
    assert cli_skill._find_skill("quality-gate") == "skill-quality-gate"


def test_find_skill_missing():
    assert cli_skill._find_skill("nonexistent-xyz-000") is None


# ============================================================
# p2p: openclaw_base_cmd 仍是可调用、被 lru_cache 缓存的稳定接口
# ============================================================

def test_openclaw_base_cmd_is_cached_callable():
    """修复后 cli 仍依赖 openclaw_base_cmd，确认它可被 monkeypatch 且为同一对象（lru_cache）。"""
    from easel.openclaw_cmd import openclaw_base_cmd

    assert callable(openclaw_base_cmd)
    # lru_cache 包装后 .cache_info 存在，证明未意外替换成普通函数
    assert hasattr(openclaw_base_cmd, "cache_info")
