"""思考档位读取顺序：进程环境 → 项目 .env → 默认 medium。

回归背景：THINKING_LEVEL 在模块导入时求值，此前只读 os.environ；
而 .env 不会被注入进程环境（本文件由 _read_env 按需解析），
导致用户在 .env 里写 EASEL_THINKING_LEVEL=ultra 完全不生效 ——
对只支持特定档位的模型（如 glm-5.3 仅 off/ultra）直接报
`Thinking level "medium" is not supported`，对话无法开始。
"""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web" / "app.py"


def _load_fn():
    """从 web/app.py 中抽出 _thinking_level_setting，独立求值（避免导入整个 app）。"""
    src = APP.read_text(encoding="utf-8")
    i = src.index("def _thinking_level_setting")
    j = src.index('    return "medium"', i) + len('    return "medium"')
    ns = {"os": os, "Path": Path}
    exec(compile(src[i:j], str(APP), "exec"), ns)
    return ns["_thinking_level_setting"]


def test_module_does_not_reference_env_only():
    """THINKING_LEVEL 不得只取 os.environ（否则 .env 无效）。"""
    src = APP.read_text(encoding="utf-8")
    line = next(l for l in src.splitlines() if l.startswith("THINKING_LEVEL = "))
    assert "_thinking_level_setting()" in line, f"THINKING_LEVEL 应走解析函数，实际：{line}"


def test_process_env_wins(monkeypatch):
    fn = _load_fn()
    monkeypatch.setenv("EASEL_THINKING_LEVEL", "high")
    assert fn() == "high"


def test_falls_back_to_default_when_absent(monkeypatch, tmp_path):
    """没有环境变量、.env 里也没配 → medium。"""
    fn = _load_fn()
    monkeypatch.delenv("EASEL_THINKING_LEVEL", raising=False)
    # 把项目根指向一个没有 .env 的临时目录
    fake_app = tmp_path / "web" / "app.py"
    fake_app.parent.mkdir(parents=True)
    fake_app.write_text("", encoding="utf-8")
    src = APP.read_text(encoding="utf-8")
    i = src.index("def _thinking_level_setting")
    j = src.index('    return "medium"', i) + len('    return "medium"')
    ns = {"os": os, "Path": Path, "__file__": str(fake_app)}
    exec(compile(src[i:j], str(fake_app), "exec"), ns)
    assert ns["_thinking_level_setting"]() == "medium"


def test_reads_env_file_when_process_env_absent(monkeypatch, tmp_path):
    """.env 里有值 → 生效（这正是修复的目标场景）。"""
    monkeypatch.delenv("EASEL_THINKING_LEVEL", raising=False)
    root = tmp_path
    (root / "web").mkdir()
    (root / ".env").write_text(
        "# 注释行\nEASEL_THINKING_LEVEL=ultra\nOTHER=1\n", encoding="utf-8")
    fake_app = root / "web" / "app.py"
    fake_app.write_text("", encoding="utf-8")
    src = APP.read_text(encoding="utf-8")
    i = src.index("def _thinking_level_setting")
    j = src.index('    return "medium"', i) + len('    return "medium"')
    ns = {"os": os, "Path": Path, "__file__": str(fake_app)}
    exec(compile(src[i:j], str(fake_app), "exec"), ns)
    assert ns["_thinking_level_setting"]() == "ultra"


def test_env_file_value_strips_quotes(monkeypatch, tmp_path):
    monkeypatch.delenv("EASEL_THINKING_LEVEL", raising=False)
    root = tmp_path
    (root / "web").mkdir()
    (root / ".env").write_text('EASEL_THINKING_LEVEL="off"\n', encoding="utf-8")
    fake_app = root / "web" / "app.py"
    fake_app.write_text("", encoding="utf-8")
    src = APP.read_text(encoding="utf-8")
    i = src.index("def _thinking_level_setting")
    j = src.index('    return "medium"', i) + len('    return "medium"')
    ns = {"os": os, "Path": Path, "__file__": str(fake_app)}
    exec(compile(src[i:j], str(fake_app), "exec"), ns)
    assert ns["_thinking_level_setting"]() == "off"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
