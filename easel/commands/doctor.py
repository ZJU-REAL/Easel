"""easel doctor — 检查开发环境是否就绪。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

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


def _node_version_ok() -> bool:
    """Check Node.js >= 22.19."""
    try:
        result = subprocess.run(
            ["node", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return False
        # e.g. "v22.19.0"
        m = re.match(r"v(\d+)\.(\d+)", result.stdout.strip())
        if not m:
            return False
        major, minor = int(m.group(1)), int(m.group(2))
        return (major, minor) >= (22, 19)
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


def _gateway_healthy() -> bool:
    """Check OpenClaw gateway is running via healthz endpoint."""
    try:
        result = subprocess.run(
            ["curl", "-sf", "http://localhost:18789/healthz"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _skills_synced() -> bool:
    """Check ~/.openclaw/workspace-easel/skills/ has content."""
    skills_dir = Path.home() / ".openclaw" / "workspace-easel" / "skills"
    if not skills_dir.is_dir():
        return False
    return any(skills_dir.iterdir())


def _env_key_valid() -> bool:
    """Check .env 配置了可用的认证。

    以下任一通道满足即可：
    - 标准 API key：ANTHROPIC_API_KEY
    - Anthropic-compatible 服务：EASEL_LLM_API_KEY + EASEL_LLM_BASE_URL

    ping 才是权威连通性测试；这里只做静态配置存在性检查。
    """
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return False

    # 认证变量 → 是否已填入非占位值
    auth_vars: dict[str, str] = {}
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key in (
                "ANTHROPIC_API_KEY", "EASEL_LLM_API_KEY", "EASEL_LLM_BASE_URL",
                "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "OPENAI_API_KEY", "OPENAI_BASE_URL",
                "OPENAI_MAAS_API_KEY", "OPENAI_MAAS_ENDPOINT",
            ):
                auth_vars[key] = value
    except OSError:
        return False

    def _set(name: str) -> bool:
        v = auth_vars.get(name, "")
        return bool(v) and "REPLACE_ME" not in v

    # 标准 key 通道
    if _set("ANTHROPIC_API_KEY"):
        return True
    # Anthropic-compatible 服务：key + base_url 同时配好
    if _set("EASEL_LLM_API_KEY") and _set("EASEL_LLM_BASE_URL"):
        return True
    if _set("ANTHROPIC_AUTH_TOKEN") and _set("ANTHROPIC_BASE_URL"):
        return True
    if _set("OPENAI_API_KEY"):
        return True
    if _set("OPENAI_MAAS_API_KEY") and _set("OPENAI_MAAS_ENDPOINT"):
        return True
    return False


def cmd_doctor(_args) -> int:
    print("Easel — 环境检查\n")
    all_ok = True

    # 1. Runtime prerequisites
    all_ok &= _check("Python >= 3.10", _python_version_ok(),
                      "请安装 Python 3.10 或更高版本")
    all_ok &= _check("Python venv module", _venv_available(),
                      "Debian/Ubuntu 请安装 python3-venv")
    has_node = shutil.which("node") is not None
    node_ok = _node_version_ok()
    node_detail = ("请安装 Node.js >= 22.19: https://nodejs.org/" if not has_node
                   else "Node.js 版本过低，请升级到 >= 22.19: https://nodejs.org/")
    all_ok &= _check("Node.js >= 22.19", node_ok, node_detail)
    all_ok &= _check("FFmpeg", shutil.which("ffmpeg") is not None,
                      "媒体处理需要 FFmpeg；请安装后重试")

    # 2. openclaw command
    has_openclaw = shutil.which("openclaw") is not None
    all_ok &= _check("openclaw command", has_openclaw,
                      "请安装 openclaw: npm i -g openclaw")

    for module in ("fastapi", "uvicorn", "sse_starlette", "multipart"):
        all_ok &= _check(f"Python package: {module}", _module_available(module),
                          "运行 pip install -e . 安装 Easel 运行依赖")

    frontend_ready = (PROJECT_ROOT / "web" / "frontend" / "dist" / "index.html").is_file()
    all_ok &= _check("Web frontend build", frontend_ready,
                      "运行 cd web/frontend && npm ci && npm run build")
    all_ok &= _check("Playwright Chromium", _chromium_available(),
                      "运行 python3 -m playwright install chromium")

    # 3. .env file with valid key
    env_ok = _env_key_valid()
    all_ok &= _check(".env (API Key)", env_ok,
                      "填 ANTHROPIC_API_KEY，或 EASEL_LLM_API_KEY + EASEL_LLM_BASE_URL")

    # 4. OpenClaw gateway running
    gw_ok = _gateway_healthy()
    all_ok &= _check("OpenClaw gateway (localhost:18789)", gw_ok,
                      "运行 python -m easel gateway start")

    # 5. Skills synced
    synced = _skills_synced()
    all_ok &= _check("Skills synced", synced,
                      "重新运行 setup.ps1（Windows）或 bash openclaw/sync.sh（Linux/macOS）")

    # 6. Key project files
    gateway_label = "scripts/gateway.ps1" if os.name == "nt" else "scripts/gateway.sh"
    gateway_path = PROJECT_ROOT / "scripts" / ("gateway.ps1" if os.name == "nt" else "gateway.sh")
    key_files = [
        ("openclaw/openclaw.json5", PROJECT_ROOT / "openclaw" / "openclaw.json5"),
        ("skills/openclaw/", PROJECT_ROOT / "skills" / "openclaw"),
        (gateway_label, gateway_path),
    ]
    for label, path in key_files:
        all_ok &= _check(label, path.exists())

    print()
    if all_ok:
        print(f"{GREEN}✓ 环境就绪{NC} — 运行 python -m easel ping 验证连通性")
    else:
        print(f"{YELLOW}⚠ 有未满足项{NC} — 请按上述提示修复后重试")

    return 0 if all_ok else 1
