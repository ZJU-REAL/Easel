"""easel doctor — 检查开发环境是否就绪。"""

from __future__ import annotations

import json
import html
import os
import re
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

from easel.gateway_endpoint import healthz_url, port_source, resolve_gateway_port
from easel.openclaw_cmd import openclaw_base_cmd
from easel.direct_api import DirectAPIError, api_config, read_settings

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
    """Check OpenClaw gateway is running via healthz endpoint.

    端口走 easel/gateway_endpoint.py：非默认 profile（Easel 的 ``--profile easel``）
    不是 18789，写死就会「gateway 活着、doctor 报 FAIL」。
    """
    try:
        # 127.0.0.1 探针绝不能继承系统 http_proxy（direct_api 同款 doctrine）：
        # 默认 opener 会把回环请求发给代理，代理不可达时健康的网关被误报为 FAIL。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(healthz_url(), timeout=5) as response:
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
    cli_ok, _detail = _primary_model_cli_available()
    if cli_ok:
        return True

    settings = read_settings(PROJECT_ROOT / ".env")
    if any(settings.get(name, "").strip() for name in (
            "EASEL_DIRECT_API_BASE_URL", "EASEL_DIRECT_API_MODEL", "EASEL_DIRECT_API_KEY")):
        try:
            api_config(settings)
            return True
        except DirectAPIError:
            return False
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


def _cli_backend(primary: str) -> dict[str, object] | None:
    if "/" not in primary:
        return None
    provider = primary.split("/", 1)[0]
    try:
        from easel.local_agents import KNOWN_AGENT_CLIS
    except Exception:  # noqa: BLE001
        return None
    for item in KNOWN_AGENT_CLIS:
        if item.get("openclaw_provider") == provider:
            return item
    return None


def _primary_model_cli_available() -> tuple[bool, str]:
    cfg_path = _openclaw_config_path()
    if not cfg_path.is_file():
        return False, ""
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, ""
    primary = (((cfg.get("agents") or {}).get("defaults") or {})
               .get("model") or {}).get("primary") or ""
    backend = _cli_backend(primary)
    if not backend:
        return False, ""
    commands = tuple(backend.get("commands") or ())
    if any(shutil.which(str(cmd)) for cmd in commands):
        return True, ""
    label = backend.get("label") or backend.get("id") or primary.split("/", 1)[0]
    return False, f"primary 是 {primary}，但未在 PATH 找到 {label} CLI（{', '.join(map(str, commands))}）"


def _openclaw_config_path() -> Path:
    """easel 用独立 profile，不碰用户本机的 OpenClaw 配置。

    与 web/app.py、local_agents 同一真相源：委托 easel.openclaw_workspace.config_path()。
    之前这里自己解析 EASEL_OPENCLAW_STATE_DIR，与 config_path() 有细微差别——
    环境变量是空串时这里会返回 Path('')（相对路径），config_path() 会正确回落默认目录。
    """
    from easel.openclaw_workspace import config_path
    return config_path()


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
    backend = _cli_backend(primary)
    if backend:
        if any(shutil.which(str(cmd)) for cmd in (backend.get("commands") or ())):
            return True, ""
        return False, (f"primary 是 {primary}，但未在 PATH 找到 "
                       f"{backend.get('label') or provider} CLI —— 请先安装并登录后再试")
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


def _tool_loop_policy() -> list[str]:
    """Describe saved switches only; do not infer runtime support or defaults."""
    try:
        cfg = json.loads(_openclaw_config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ["无法读取 JSON 配置；循环保护状态未知"]
    if not isinstance(cfg, dict):
        return ["配置根节点不是对象；循环保护状态未知"]

    def switch(scope):
        if not isinstance(scope, dict):
            return "格式异常"
        for key in ("tools", "loopDetection"):
            if key not in scope:
                return "未设置"
            scope = scope[key]
            if not isinstance(scope, dict):
                return "格式异常"
        if "enabled" not in scope:
            return "未设置"
        value = scope["enabled"]
        if type(value) is not bool:
            return "格式异常"
        return "显式开启" if value else "显式关闭"

    lines = [f"tools.loopDetection.enabled：{switch(cfg)}"]
    agents = cfg.get("agents", {})
    if not isinstance(agents, dict):
        return lines + ["agents 格式异常；无法检查 Agent 覆盖"]
    # Both saved layouts exist in supported-era OpenClaw releases. Inspect
    # separately; do not guess which one a running gateway actually consumes.
    for layout, expected in (("list", list), ("entries", dict)):
        if layout not in agents:
            continue
        entries = agents[layout]
        if not isinstance(entries, expected):
            lines.append(f"agents.{layout} 格式异常；无法检查 Agent 覆盖")
            continue
        states = [switch(entry) for entry in (entries.values() if layout == "entries" else entries)]
        counts = "，".join(f"{state} {states.count(state)}" for state in
                           ("显式开启", "显式关闭", "未设置", "格式异常"))
        lines.append(f"agents.{layout} 的 Agent 开关：{counts}")
    if "list" in agents and "entries" in agents:
        lines.append("同时存在 list / entries；请用所装 OpenClaw 版本核对配置布局")
    return lines


_COMPACTION_RESERVE_FLOOR = 20_000


def _compaction_threshold(context_window: int) -> int:
    """按常见默认预留参数估算压缩阈值（token），不代表运行时保证。"""
    reserve = min(_COMPACTION_RESERVE_FLOOR, context_window // 4)
    return context_window - reserve


_SKILLS_BUDGET_DEFAULTS = {"maxSkillsInPrompt": 200, "maxSkillsPromptChars": 80_000}
_SKILLS_BUDGET_ENV = {
    "maxSkillsInPrompt": "EASEL_MAX_SKILLS_IN_PROMPT",
    "maxSkillsPromptChars": "EASEL_MAX_SKILLS_PROMPT_CHARS",
}
_OPENCLAW_SKILLS_DEFAULTS = {"maxSkillsInPrompt": 150, "maxSkillsPromptChars": 18_000}


def _builtin_skills_estimate(cfg: dict) -> tuple[int, int]:
    """源码目录的保守 UTF-16 字符估算，不查询网关或判断运行时资格。"""
    from easel.openclaw_workspace import config_path

    agents = cfg.get("agents")
    agents = agents if isinstance(agents, dict) else {}
    defaults = agents.get("defaults")
    defaults = defaults if isinstance(defaults, dict) else {}
    workspace = defaults.get("workspace")
    listed = agents.get("list")
    entries = agents.get("entries")
    overrides = listed if isinstance(listed, list) else []
    if isinstance(entries, dict) and isinstance(entries.get("main"), dict):
        overrides = [*overrides, {**entries["main"], "id": "main"}]
    for agent in overrides:
        if isinstance(agent, dict) and agent.get("id") == "main" and agent.get("workspace"):
            workspace = agent["workspace"]
    workspace = os.environ.get("EASEL_OPENCLAW_WORKSPACE") or workspace
    directory = Path(workspace).expanduser() if isinstance(workspace, str) and workspace else config_path().parent / "workspace"
    paths = sorted((PROJECT_ROOT / "skills" / "builtin").glob("*/SKILL.md"))
    chars = 1024 if paths else 0
    for path in paths:
        source = path.read_text(encoding="utf-8-sig").split("---", 2)
        if len(source) != 3 or source[0].strip():
            raise ValueError("invalid skill frontmatter")
        name = re.search(r"^name:\s*(.+)$", source[1], re.MULTILINE)
        if name is None or not re.search(r"^description:", source[1], re.MULTILINE):
            raise ValueError("missing skill metadata")
        location = str(directory / "skills" / path.parent.name / "SKILL.md")
        metadata = source[1] + name.group(1) + location
        chars += len(html.escape(metadata).encode("utf-16-le")) // 2 + 180
    return len(paths), chars


def _skills_budget_updates(cfg: dict, environment=None) -> dict[str, int]:
    """安装计划：只补缺失叶子键；显式环境覆盖除外，不直接写配置。"""
    if not isinstance(cfg, dict):
        raise ValueError("invalid config")
    skills = cfg.get("skills", {})
    if not isinstance(skills, dict):
        raise ValueError("invalid skills config")
    limits = skills.get("limits", {})
    if not isinstance(limits, dict):
        raise ValueError("invalid skills limits")
    if any("$include" in node for node in (cfg, skills, limits)):
        raise ValueError("unresolved skills config include")
    environment = os.environ if environment is None else environment
    count, chars = _builtin_skills_estimate(cfg)
    defaults = {
        "maxSkillsInPrompt": max(_SKILLS_BUDGET_DEFAULTS["maxSkillsInPrompt"], count),
        "maxSkillsPromptChars": max(_SKILLS_BUDGET_DEFAULTS["maxSkillsPromptChars"], chars + 8192),
    }
    updates = {}
    for key, variable in _SKILLS_BUDGET_ENV.items():
        raw = environment.get(variable, "")
        if raw:
            if not re.fullmatch(r"[0-9]+", raw) or len(raw) > 16 or int(raw) > 2**53 - 1:
                raise ValueError(f"invalid {variable}")
            updates[key] = int(raw)
        elif key not in limits:
            updates[key] = defaults[key]
    return updates


def _skills_catalog_policy(cfg: dict) -> list[str]:
    skills = cfg.get("skills")
    limits = skills.get("limits") if isinstance(skills, dict) else None
    lines = []
    if not isinstance(limits, dict):
        lines.append("skills.limits：未设置（技能目录预算走 OpenClaw 默认值）")
        limits = {}
    else:
        described = []
        for key in _SKILLS_BUDGET_DEFAULTS:
            value = limits.get(key)
            if key not in limits:
                described.append(f"{key} 未设置")
            elif type(value) is int and value >= 0:
                described.append(f"{key}={value:,}" + ("（显式为 0）" if value == 0 else ""))
            else:
                described.append(f"{key} 格式异常")
        lines.append("skills.limits：已设置 " + "，".join(described))
    try:
        count, chars = _builtin_skills_estimate(cfg)
    except (OSError, ValueError):
        count, chars = 0, 0
    if count:
        lines.append(f"内置技能目录离线上界估算：{count} 个，完整描述及路径约 {chars:,} UTF-16 字符；"
                     "不含第三方技能，未检查运行时资格或实际提示")
        effective = {key: limits.get(key, default) for key, default in _OPENCLAW_SKILLS_DEFAULTS.items()}
        if all(type(value) is int and value >= 0 for value in effective.values()):
            if effective["maxSkillsInPrompt"] < count or effective["maxSkillsPromptChars"] < chars:
                lines.append("目录预算低于离线估算：存在描述精简或目录截断风险；实际遗漏不能由此推定")
            else:
                lines.append("目录预算覆盖此离线估算，但不保证运行时技能或描述全部可见")
    else:
        lines.append("内置技能目录离线估算未知：源码缺失或元数据不可读")
    agents = cfg.get("agents")
    if isinstance(agents, dict):
        listed = agents.get("list")
        entries = agents.get("entries")
        overrides = listed if isinstance(listed, list) else []
        if isinstance(entries, dict):
            overrides = [*overrides, *[value for value in entries.values() if isinstance(value, dict)]]
        if any(isinstance(agent, dict) and ("skillsLimits" in agent or "skills" in agent) for agent in overrides):
            lines.append("存在 Agent 级 skillsLimits/skills 覆盖：全局预算不能代表该 Agent 的最终目录")
    lines.append("运行时可见性未知：使用 openclaw --profile easel skills list --json / skills check，"
                 "并核对当前会话的实际提示快照与截断警告；清单 Eligible 数不等于提示内可见数")
    return lines


def _context_budget_policy() -> list[str]:
    """描述已保存的上下文预算配置；不改配置，也不假设运行时已加载。"""
    try:
        cfg = json.loads(_openclaw_config_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ["无法读取 JSON 配置；上下文预算状态未知"]
    if not isinstance(cfg, dict):
        return ["配置根节点不是对象；上下文预算状态未知"]

    lines: list[str] = []
    agents = cfg.get("agents")
    defaults = agents.get("defaults") if isinstance(agents, dict) else None
    context_cap = defaults.get("contextTokens") if isinstance(defaults, dict) else None
    if type(context_cap) is not int or context_cap <= 0:
        context_cap = None
    compaction = defaults.get("compaction") if isinstance(defaults, dict) else None
    disabled = isinstance(compaction, dict) and compaction.get("enabled") is False
    if disabled:
        lines.append("agents.defaults.compaction.enabled：显式关闭；以下仅为默认参数下的参考阈值")
    models = cfg.get("models")
    providers = models.get("providers") if isinstance(models, dict) else None
    if not isinstance(providers, dict):
        lines.append("models.providers 未设置；无法计算压缩阈值")
    else:
        for provider, spec in sorted(providers.items()):
            if not isinstance(spec, dict):
                lines.append(f"{provider}：格式异常；无法计算压缩阈值")
                continue
            entries = spec.get("models")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("id") or "?")
                window = entry.get("contextWindow")
                if isinstance(window, bool) or not isinstance(window, int) or window <= 0:
                    lines.append(f"{provider}/{model_id}：未声明 contextWindow；阈值由 OpenClaw 推导")
                    continue
                effective = min(window, context_cap) if context_cap is not None else window
                cap_note = f"；contextTokens 上限 {context_cap:,}" if context_cap is not None else ""
                lines.append(f"{provider}/{model_id}：声明 {window:,}{cap_note} → "
                             f"默认参数参考压缩阈值约 {_compaction_threshold(effective):,}")

    lines.extend(_skills_catalog_policy(cfg))
    return lines


def cmd_doctor(_args) -> int:
    print("Easel — 环境检查\n")
    all_ok = True
    settings = read_settings(PROJECT_ROOT / ".env")
    from easel import harnesses
    runtime = harnesses.settings(PROJECT_ROOT / "outputs", settings)["runtime"]
    alternate = runtime not in ("api", "openclaw")
    direct = runtime == "api"
    print("  对话模式：" + (runtime if alternate else (
        "API 直连（无需 OpenClaw）" if direct else "OpenClaw")))
    if alternate:
        descriptor = harnesses.describe(runtime)
        all_ok &= _check(f"{runtime} CLI", descriptor["installed"], descriptor["install_hint"])
        print("  原生认证和模型可用性请运行 easel ping 验证；不读取或迁移凭证")
        direct = True

    # 1. Runtime prerequisites
    all_ok &= _check("Python >= 3.10", _python_version_ok(),
                      "请安装 Python 3.10 或更高版本")
    all_ok &= _check("Python venv module", _venv_available(),
                      "Debian/Ubuntu 请安装 python3-venv")
    if not direct:
        # openclaw 版本决定 Node 引擎要求：2026.9.x 需要 Node 24.16+，2026.6.x 需要 22.19+（实测其
        # engines，见 _node_version_ok 的说明）。未装 openclaw 时按 setup 的默认安装目标
        # （openclaw@latest）从严要求 24.16+。
        oc_ver = _openclaw_version()
        node_strict = oc_ver is None or oc_ver >= (2026, 9, 0)
        node_floor = "24.16" if node_strict else "22.19"
        has_node = shutil.which("node") is not None
        node_ok = _node_version_ok(node_strict)
        node_detail = (f"请安装 Node.js >= {node_floor}: https://nodejs.org/" if not has_node
                       else f"Node.js 版本不满足当前 OpenClaw 要求，请升级到 >= {node_floor}: https://nodejs.org/")
        all_ok &= _check(f"Node.js >= {node_floor}", node_ok, node_detail)
    all_ok &= _check("FFmpeg", shutil.which("ffmpeg") is not None,
                      "媒体处理需要 FFmpeg；请安装后重试")

    if not direct:
        # 2. openclaw command + 版本
        has_openclaw = shutil.which("openclaw") is not None
        all_ok &= _check("openclaw command", has_openclaw,
                          "请安装 openclaw: npm i -g openclaw")
        if has_openclaw:
            min_str = ".".join(map(str, MIN_OPENCLAW))
            ver_str = ".".join(map(str, oc_ver)) if oc_ver else "未知"
            oc_ver_ok = oc_ver is not None and oc_ver >= MIN_OPENCLAW
            all_ok &= _check(
                f"OpenClaw >= {min_str}", oc_ver_ok,
                f"当前 {ver_str}，过旧会有 provider/schema 兼容问题；请升级：npm i -g openclaw@latest",
            )

    for module in ("fastapi", "uvicorn", "sse_starlette", "multipart"):
        all_ok &= _check(f"Python package: {module}", _module_available(module),
                          "运行 pip install -e . 安装 Easel 运行依赖")

    frontend_ready = (PROJECT_ROOT / "web" / "frontend" / "dist" / "index.html").is_file()
    all_ok &= _check("Web frontend build", frontend_ready,
                      "运行 cd web/frontend && npm ci && npm run build")
    all_ok &= _check("Playwright Chromium", _chromium_available(),
                      "运行 python3 -m playwright install chromium")

    if direct and not alternate:
        try:
            base, model, _key = api_config(settings)
            all_ok &= _check(f"API 配置 ({model})", True)
        except DirectAPIError as error:
            all_ok &= _check("API 配置", False, str(error))
    elif not alternate:
        # 3. .env file with valid key
        env_ok = _env_key_valid()
        all_ok &= _check(".env (API Key)", env_ok,
                          "填 ANTHROPIC_API_KEY，或 EASEL_LLM_API_KEY + EASEL_LLM_BASE_URL")

    # 3.5 本机 agent CLI：有免 key 通道时提示用户（.env 没配也可能是绿灯路径）。
    # 不计入 all_ok —— 装不装 Claude Code 是用户的选择，不是环境故障。
    try:
        from easel.local_agents import summarize_local_agents
        la = summarize_local_agents()
        if la["installedCount"]:
            usable = ", ".join(str(a["label"]) for a in la["agents"] if a["usableWithoutKey"])
            detail = (f"检测到 {la['installedCount']} 个本机 agent CLI；"
                      + (f"可免 API key 使用：{usable}" if usable
                         else "暂无可直接接入底座的登录态"))
            _check("本机 agent CLI", True, detail)
    except Exception:  # noqa: BLE001  探测失败不阻塞 doctor
        pass

    if not direct:
        print("  OpenClaw 循环保护（只读配置诊断，不计入环境就绪结果）")
        for line in _tool_loop_policy():
            print(f"    └─ {line}")
        print("    未设置不等于关闭；继承、默认值和运行时支持由 OpenClaw 版本决定。")
        print("    已保存配置不证明网关已加载，也不代表每任务工具调用预算。")
        print("  OpenClaw 上下文预算（只读配置诊断，不计入环境就绪结果）")
        for line in _context_budget_policy():
            print(f"    └─ {line}")
        print("    阈值按常见默认预留参数估算；所装版本、运行时覆盖和压缩开关可能改变实际行为。")
        print("    contextWindow 会影响本地请求预算；缓存命中与成本还取决于供应商和提示前缀。")
        # .env 填了 ≠ setup 真的把 provider 写进了 openclaw；不对账就会「doctor 全绿但对话报错」。
        route_ok, route_detail = _primary_model_routable()
        all_ok &= _check("OpenClaw model routing", route_ok, route_detail)

        # 4. OpenClaw gateway running
        gw_ok = _gateway_healthy()
        all_ok &= _check(f"OpenClaw gateway (localhost:{resolve_gateway_port()})", gw_ok,
                          f"运行 python -m easel gateway start（端口来自 {port_source()}）")

        # 5. Skills synced
        synced, synced_detail = _skills_synced()
        all_ok &= _check("Skills synced", synced,
                          f"{synced_detail}；重新运行 setup.ps1（Windows）或 bash agents/sync.sh（Linux/macOS）")

    # 6. Key project files
    gateway_label = "scripts/gateway.ps1" if os.name == "nt" else "scripts/gateway.sh"
    gateway_path = PROJECT_ROOT / "scripts" / ("gateway.ps1" if os.name == "nt" else "gateway.sh")
    key_files = [
        ("agents/openclaw.json5", PROJECT_ROOT / "agents" / "openclaw.json5"),
        ("skills/builtin/", PROJECT_ROOT / "skills" / "builtin"),
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
