"""easel doctor — 检查开发环境是否就绪。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from easel.openclaw_cmd import openclaw_base_cmd
from easel.runtimes import get_runtime

# 项目根目录（Easel/）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# OpenClaw 已验证的稳定下限（= 我们实测跑通过的最老版本）。低于它会命中 anthropic provider 必须
# 原子写入、models.providers.*.timeoutSeconds 被判 Unrecognized key 等破坏性变更（见 issue #9/#11）。
#
# 别拿「记忆检索 memory.search.*」当抬高下限的理由：2026.6.11 **没有** memory.search（实测
# `config set memory.search.…` 报 Unrecognized key），那是 2026.9.x 才有的 schema，setup.sh:613
# 已经按「先试新的、失败退回 agents.defaults.memorySearch」探测处理，不需要版本下限兜。
MIN_OPENCLAW = (2026, 6, 11)

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


def _node_version_ok(strict: bool) -> bool:
    """检查 Node.js 版本。

    strict=True 对齐 openclaw@latest（2026.9.x）的引擎：>=24.16.0 <25 || >=26.1.0（25.x/26.0 被排除）。
    strict=False 用于已装较旧 OpenClaw（我们支持的下限 2026.6.11）。**下限是 22.19**，不是 20.10：
    实测 openclaw@2026.6.11 的 package.json engines 就是 `">=22.19.0"`，且其 openclaw.mjs 里还有
    一道硬运行时检查（MIN_NODE_MAJOR=22 / MIN_NODE_MINOR=19，不满足直接 process.exit(1)）。
    写 20.10 的后果是：Node 20.10–22.18 上 doctor 报绿，而每一条 openclaw 命令都起不来。
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
        return (major, minor) >= (22, 19)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _openclaw_version() -> tuple[int, int, int] | None:
    """解析 `openclaw --version`，返回 (year, month, patch)；无法确定时返回 None。"""
    try:
        # 不能裸调 ["openclaw", ...]：Windows 上它是 npm 装的 `.cmd` shim，
        # CreateProcess 不按 PATHEXT 解析、裸名找不到文件 → FileNotFoundError
        # → 版本被误判「未知」。统一走 openclaw_cmd 的解析（Windows 上解析为
        # node + openclaw.mjs，Unix 上为直接可执行路径）。
        result = subprocess.run(
            openclaw_base_cmd() + ["--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        # e.g. "OpenClaw 2026.9.4 (3a9d69d)"
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


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
        with urllib.request.urlopen("http://127.0.0.1:18789/healthz", timeout=5) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def _skills_synced() -> tuple[bool, str]:
    """检查 agent 真正读取的那个 workspace 里有没有 skills。

    这里的目标目录**不能**硬编码：OpenClaw 的默认布局在 2026.6.x / 2026.9.x 之间变过
    （见 easel/openclaw_workspace.py）。以前这里写死了旧布局，而 sync.sh 写的是新布局，
    于是同步脚本报 "synced"、doctor 报绿，agent 却读不到任何技能（issue #19）。
    """
    from easel.openclaw_workspace import workspace_dir

    ws = workspace_dir()
    skills_dir = ws / "skills"
    try:
        ok = skills_dir.is_dir() and any(skills_dir.iterdir())
    except OSError:
        ok = False
    return ok, f"agent 实际读取的 workspace 是 {ws}，其中 skills/ 为空或不存在"


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


def _openclaw_config_path() -> Path:
    """easel 用独立 profile，不碰用户本机的 OpenClaw 配置（与 gateway_questions 同一约定）。"""
    state = os.environ.get("EASEL_OPENCLAW_STATE_DIR")
    return (Path(state) if state else Path.home() / ".openclaw-easel") / "openclaw.json"


def _primary_model_routable() -> tuple[bool, str]:
    """检查 agents.defaults.model.primary 指向的 provider 在 openclaw 里真的配了认证。

    上面的 `.env (API Key)` 只查 .env 静态有没有填值，查不出 setup 有没有真把 provider
    写进 openclaw.json。两边脱节时（例如认证判定被占位符卡住、provider 一个字没写却照样
    设了 primary），doctor 会全绿而对话直接报
    "No route-compatible authentication source is configured for <provider>"。
    这条就是补上 openclaw 侧的对账。

    返回 (是否可路由, 失败提示)。拿不准的情况一律放行，不制造假告警。
    """
    cfg_path = _openclaw_config_path()
    if not cfg_path.is_file():
        return False, f"{cfg_path} 不存在 — 先跑 bash setup.sh（Windows: setup.ps1）"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"{cfg_path} 读不出来（{exc}）"

    primary = (((cfg.get("agents") or {}).get("defaults") or {})
               .get("model") or {}).get("primary") or ""
    if not primary:
        return False, "未设置 agents.defaults.model.primary — 重新跑 setup 脚本"
    if "/" not in primary:
        # 不是 provider/model 形式，解析不出 provider，交给 `easel ping` 去判，不在这里猜。
        return True, ""

    provider = primary.split("/", 1)[0]
    providers = (cfg.get("models") or {}).get("providers") or {}
    entry = providers.get(provider)
    if not isinstance(entry, dict):
        return False, (f"primary 是 {primary}，但 models.providers.{provider} 不存在 —— "
                       "在 .env 填好真实 key 后重新跑 setup 脚本")
    # apiKey / 本地适配器 / OAuth 任一即可。字段名随 OpenClaw 版本变过，这里从宽认。
    has_auth = bool(str(entry.get("apiKey") or "").strip()) or bool(entry.get("localService")) \
        or any(k for k, v in entry.items() if "oauth" in k.lower() and v)
    if not has_auth:
        return False, (f"models.providers.{provider} 没有 apiKey —— "
                       "在 .env 填好真实 key 后重新跑 setup 脚本")
    return True, ""


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
    if runtime.descriptor.id == "openclaw":
        # openclaw 版本决定 Node 引擎要求：2026.9.x 需要 Node 24.16+，2026.6.x 需要 22.19+（实测
        # 其 engines，见 _node_version_ok 的说明）。未装 openclaw 时按 setup 的默认安装目标
        # （openclaw@latest）从严要求 24.16+。
        oc_ver = _openclaw_version()
        node_strict = oc_ver is None or oc_ver >= (2026, 9, 0)
        node_floor = "24.16" if node_strict else "22.19"
    else:
        node_strict, node_floor = False, "20.10"
    has_node = shutil.which("node") is not None
    node_ok = _node_version_ok(node_strict)
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

    # OpenClaw-specific config validation remains available without imposing it
    # on other runtimes.
    if runtime.descriptor.id == "openclaw":
        route_ok, route_detail = _primary_model_routable()
        all_ok &= _check("OpenClaw model routing", route_ok, route_detail)

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
