"""easel doctor — 检查开发环境是否就绪。"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from easel.runtimes import get_runtime
# OpenClaw 专属检查已收拢进 runtimes/openclaw.py；这三个名字保留为兼容别名 ——
# easel/openclaw_workspace.py 的版本回退与上游测试仍从 doctor 取用它们。
from easel.runtimes.openclaw import (
    openclaw_version as _openclaw_version,
    skills_synced as _skills_synced,
)
from easel.runtimes.openclaw_config import primary_model_routable as _primary_model_routable

# 项目根目录（Easel/）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
NC = "\033[0m"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    status = f"{GREEN}OK{NC}" if ok else f"{RED}FAIL{NC}"
    print(f"  {label:<40s} {status}")
    if not ok and detail:
        print(f"    └─ {detail}")
    return ok


def _node_version_ok(strict: bool, floor: tuple[int, int]) -> bool:
    """检查 Node.js 版本是否满足 runtime 给出的引擎要求。

    strict=True 对齐 openclaw@latest（2026.9.x）的引擎：>=24.16.0 <25 || >=26.1.0（25.x/26.0 被排除）。
    strict=False 只做下限比较，floor 由 runtime 决定（旧 OpenClaw 22.19、OpenCode 20.10）。
    """
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        # e.g. "v24.21.0"
        m = re.match(r"v(\d+)\.(\d+)", result.stdout.strip())
        if not m:
            return False
        major, minor = int(m.group(1)), int(m.group(2))
        if strict:
            return (major == 24 and minor >= 16) or (major == 26 and minor >= 1) or major >= 27
        return (major, minor) >= floor
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _python_version_ok() -> bool:
    import sys
    return sys.version_info >= (3, 10)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _venv_available() -> bool:
    return _module_available("venv")


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).is_file()
    except (ImportError, OSError, RuntimeError):
        return False


def cmd_doctor(_args) -> int:
    print("Easel — 环境检查\n")
    all_ok = True
    try:
        runtime = get_runtime()
    except ValueError as exc:
        _check("Agent runtime config", False, str(exc))
        return 1

    # 1. Runtime prerequisites
    all_ok &= _check("Python >= 3.10", _python_version_ok(),
                      "请安装 Python 3.10 或更高版本")
    all_ok &= _check("Python venv module", _venv_available(),
                      "Debian/Ubuntu 请安装 python3-venv")
    # Node 引擎要求由 runtime 给出：OpenClaw 2026.9.x → 24.16 / 2026.6.x → 22.19；OpenCode → 20.10。
    # （见 runtimes/openclaw.py 的 node_requirement 说明）
    node_strict, node_floor = runtime.node_requirement()
    has_node = shutil.which("node") is not None
    node_ok = _node_version_ok(node_strict, tuple(map(int, node_floor.split("."))))
    node_detail = (f"请安装 Node.js >= {node_floor}: https://nodejs.org/" if not has_node
                   else f"Node.js 版本不满足当前 {runtime.descriptor.label} 要求，请升级到 >= {node_floor}: https://nodejs.org/")
    all_ok &= _check(f"Node.js >= {node_floor}", node_ok, node_detail)
    all_ok &= _check("FFmpeg", shutil.which("ffmpeg") is not None,
                      "媒体处理需要 FFmpeg；请安装后重试")

    # 2. selected Agent CLI
    for diagnostic in runtime.diagnose():
        all_ok &= _check(diagnostic.label, diagnostic.ok, diagnostic.detail)

    for module in ("fastapi", "uvicorn", "sse_starlette", "multipart"):
        all_ok &= _check(f"Python package: {module}", _module_available(module),
                          "运行 pip install -e . 安装 Easel 运行依赖")

    frontend_ready = (PROJECT_ROOT / "web" / "frontend" / "dist" / "index.html").is_file()
    all_ok &= _check("Web frontend build", frontend_ready,
                      "运行 cd web/frontend && npm ci && npm run build")
    all_ok &= _check("Playwright Chromium", _chromium_available(),
                      "运行 python3 -m playwright install chromium")

    # 3. Key Easel-owned files
    key_files = [
        ("skills/openclaw/", PROJECT_ROOT / "skills" / "openclaw"),
    ]
    for label, path in key_files:
        all_ok &= _check(label, path.exists())

    print()
    if all_ok:
        print(f"{GREEN}✓ 环境就绪{NC} — 运行 python -m easel ping 验证连通性")
    else:
        print(f"{YELLOW}⚠ 有未满足项{NC} — 请按上述提示修复后重试")

    return 0 if all_ok else 1
