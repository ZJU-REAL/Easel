"""Environment verification for the complete Seal V3 runtime."""
from __future__ import annotations

import re
import shutil
import subprocess
import os
from pathlib import Path

from easel.codex_adapter import codex_available
from easel.paths import BUNDLED_SKILLS_DIR, RUNTIME_ROOT, runtime_path_entries

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[0;33m"
NC = "\033[0m"


def _check(label: str, ok: bool, detail: str = "", *, optional: bool = False) -> bool:
    status = f"{GREEN}OK{NC}" if ok else (f"{YELLOW}OPTIONAL{NC}" if optional else f"{RED}FAIL{NC}")
    print(f"  {label:<40s} {status}")
    if not ok and detail:
        print(f"    - {detail}")
    return ok or optional


def _command_version_ok(command: str, minimum: tuple[int, int]) -> bool:
    resolved = _which(command)
    if not resolved:
        return False
    try:
        result = subprocess.run([resolved, "--version"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    match = re.search(r"(?:v|version\s+)?(\d+)\.(\d+)", result.stdout + result.stderr, re.I)
    return result.returncode == 0 and bool(match) and tuple(map(int, match.groups())) >= minimum


def _runtime_path() -> str:
    return os.pathsep.join((*runtime_path_entries(), os.environ.get("PATH", "")))


def _which(command: str) -> str | None:
    return shutil.which(command, path=_runtime_path())


def _ffmpeg_has_filters(required: tuple[str, ...]) -> bool:
    command = _which("ffmpeg")
    if not command:
        return False
    try:
        result = subprocess.run(
            [command, "-hide_banner", "-filters"], capture_output=True, text=True,
            timeout=15, env={**os.environ, "PATH": _runtime_path()},
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    output = result.stdout + result.stderr
    return result.returncode == 0 and all(re.search(rf"\b{re.escape(name)}\b", output) for name in required)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
            if not executable.is_file():
                return False
            browser = playwright.chromium.launch(timeout=10000)
            browser.close()
            return True
    except Exception:
        return False


def _skill_count() -> int:
    if not BUNDLED_SKILLS_DIR.is_dir():
        return 0
    return sum(1 for item in BUNDLED_SKILLS_DIR.iterdir() if item.is_dir() and (item / "CAPABILITY.md").is_file())


def cmd_doctor(_args) -> int:
    import sys

    print("Seal 私人运营顾问 V3 - 完整环境检查\n")
    all_ok = True
    all_ok &= _check("Python >= 3.10", sys.version_info >= (3, 10), "请安装 Python 3.10 或更高版本")
    all_ok &= _check("Python venv", _module_available("venv"), "当前 Python 缺少 venv 模块")
    all_ok &= _check("Node.js >= 22", _command_version_ok("node", (22, 0)), "113 项能力中的公开数据工具需要 Node.js 22+")
    all_ok &= _check("V3 bundled Bun", _which("bun") is not None, "请重新运行本 Skill 的安装脚本")
    all_ok &= _check("V3 bundled Redbook", _which("redbook") is not None, "请重新运行本 Skill 的安装脚本")
    all_ok &= _check("FFmpeg", _which("ffmpeg") is not None, "完整媒体处理需要 FFmpeg")
    all_ok &= _check("FFprobe", _which("ffprobe") is not None, "完整媒体检查需要 FFprobe")
    all_ok &= _check("FFmpeg drawtext/subtitles", _ffmpeg_has_filters(("drawtext", "subtitles")), "请安装包含 libass 的完整 FFmpeg")
    all_ok &= _check("Codex CLI", codex_available(), "请从 Codex 桌面版启用 CLI，或设置 EASEL_CODEX_BIN")

    for module in ("fastapi", "uvicorn", "sse_starlette", "multipart", "playwright", "requests", "bs4", "openpyxl"):
        all_ok &= _check(f"Python package: {module}", _module_available(module), "请运行本 Skill 的安装脚本")
    all_ok &= _check("Playwright Chromium", _chromium_available(), "请运行 python -m playwright install chromium")
    all_ok &= _check("Web frontend build", (RUNTIME_ROOT / "web/frontend/dist/index.html").is_file(), "V3 包缺少已构建前端")
    count = _skill_count()
    all_ok &= _check("内置能力 113 项", count == 113, f"当前检测到 {count} 项；V3 包不完整")
    all_ok &= _check("V3 运行规则", (RUNTIME_ROOT / "AGENTS.md").is_file(), "缺少 runtime/AGENTS.md")
    _check("外部服务配置 .env", (RUNTIME_ROOT / ".env").is_file(), "仅使用需 Key 的能力时配置", optional=True)

    print()
    if all_ok:
        print(f"{GREEN}完整环境已就绪{NC} - 可运行 seal ping 或启动工作台")
    else:
        print(f"{RED}完整环境尚未就绪{NC} - 请按失败项修复")
    return 0 if all_ok else 1
