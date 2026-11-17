"""探测本机已装的 AI agent CLI，并把「能直接用」的那些接进 Easel。

为什么需要：Easel 默认要求用户填一个 LLM API key。但本机常常已经装着 Claude Code、
Gemini CLI、Codex、OpenCode 这类 agent CLI，它们自己维护着登录态 —— 这种情况用户
完全不需要再配 key。

OpenClaw（Easel 的底座）对其中两类有原生后端，会把 CLI 的登录态直接当成模型来源：
  * ``claude-cli``  ← Claude Code（anthropic 插件）
  * ``google-gemini-cli`` ← Gemini CLI（google 插件）
其余 CLI 不通过此入口作为 OpenClaw provider。Codex 可以作为 Easel 独立执行引擎，
用 nativeRuntime 单独标明；这不代表已登录，也不将其认证复制给 OpenClaw。

设计上刻意与 AionUi 的「先探测后配置」一致：先告诉用户现成有什么，再谈要不要填 key。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# 已知的 agent CLI 及其在 OpenClaw 里的后端 id。
# openclaw_provider 为 None 表示：能探测到，但 OpenClaw 没有原生 provider（不可直接接入）。
KNOWN_AGENT_CLIS: tuple[dict[str, object], ...] = (
    {
        "id": "claude-code",
        "label": "Claude Code",
        "commands": ("claude",),
        "openclaw_provider": "claude-cli",
        # openclaw.json 里的 provider 键名与后端 id 不同名：CLI 后端 = claude-cli，
        # 配置块 = anthropic（models.providers.anthropic）。
        "config_provider": "anthropic",
        "login_hint": "在终端运行 claude 完成登录后，本机即无需再填 API Key。",
    },
    {
        "id": "gemini-cli",
        "label": "Gemini CLI",
        "commands": ("gemini",),
        "openclaw_provider": "google-gemini-cli",
        "config_provider": "google",
        "login_hint": "在终端运行 gemini 完成登录后，本机即无需再填 API Key。",
    },
    {
        "id": "codex",
        "label": "Codex CLI",
        "commands": ("codex",),
        "openclaw_provider": None,
        "config_provider": None,
        "native_runtime": "codex",
        "login_hint": "可切换到独立 Codex 执行引擎，沿用 Codex 自身认证与模型配置。请先完成 codex login；配置并保存底座后新建对话。",
    },
    {
        "id": "opencode",
        "label": "OpenCode",
        "commands": ("opencode",),
        "openclaw_provider": None,
        "config_provider": None,
        "login_hint": "OpenCode 登录态暂未被底座识别为模型来源，可用其自身命令直接使用。",
    },
    {
        "id": "qwen-code",
        "label": "Qwen Code",
        "commands": ("qwen",),
        "openclaw_provider": None,
        "config_provider": None,
        "login_hint": "Qwen Code 登录态暂未被底座识别为模型来源，可用其自身命令直接使用。",
    },
    {
        "id": "copilot-cli",
        "label": "GitHub Copilot CLI",
        "commands": ("copilot",),
        # 底座的 copilot-proxy 是连到 localhost:3000 的本地代理 provider（cliBackends
        # 为空），跟「本机装了 copilot CLI」没有因果关系 —— 装了 CLI 也不代表能免 key
        # 用，所以要另起代理服务。这里如实标为不支持，避免给出假的「一键接入」。
        "openclaw_provider": None,
        "config_provider": None,
        "login_hint": "Copilot 走底座的 copilot-proxy 需要另行运行本地代理（默认 localhost:3000），不能用本机 CLI 登录态免 key。",
    },
)


def _openclaw_config_path() -> Path:
    """OpenClaw 配置位置：与 web/app.py、doctor 同一个真相源。

    之前这里是独立实现（自己的 EASEL_OPENCLAW_CONFIG 变量 + Path.home() 兜底），
    跟 easel.openclaw_workspace.config_path()（EASEL_OPENCLAW_STATE_DIR）是两套
    不一致的覆盖机制：真实场景下用户设了 EASEL_OPENCLAW_STATE_DIR 换配置目录，
    这里的探测/已接入判断仍然读旧默认位置——而 web/app.py 的写入（声明 provider、
    切主模型）已经改走 config_path()，读写对不上，「一键接入」会显示没生效或
    重复接入同一个 provider。统一委托给 config_path()，一处覆盖全生效。
    """
    from easel.openclaw_workspace import config_path
    return config_path()


def _configured_providers() -> set[str]:
    """读 openclaw.json，返回已写入的 provider 名（用于判断本地 CLI 是否已接好）。"""
    cfg = _openclaw_config_path()
    if not cfg.is_file():
        return set()
    try:
        data = json.loads(cfg.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    providers = (data.get("models") or {}).get("providers") or {}
    return {k for k in providers if isinstance(k, str)}


def catalog_for_provider(openclaw_provider: str | None) -> list[dict[str, object]]:
    """读底座插件清单，返回某 CLI 后端的可选模型目录。

    数据源：openclaw 安装目录下 extensions/<插件>/openclaw.plugin.json 的
    modelCatalog.providers[<provider>].models[]（claude-cli 9 个、
    google-gemini-cli 10 个）。给前端下拉列表用，用户接入后不用手打模型名。
    找不到插件文件 / 无该 provider 时返回空列表 —— 前端退化为文本框，不猜。
    """
    if not openclaw_provider:
        return []
    plugin_dirs = [
        Path(__file__).resolve().parent.parent / "node_modules" / "openclaw" / "dist" / "extensions",
        Path.home() / ".npm-global" / "lib" / "node_modules" / "openclaw" / "dist" / "extensions",
    ]
    # 注意：插件清单里 providers 的键 ≠ CLI 后端 id —— claude-cli 后端的模型挂在
    # "claude-cli" 键下，而 google 插件挂在 "google" 键下（真机验证发现）。
    provider_key_map = {"claude-cli": "claude-cli", "google-gemini-cli": "google"}
    # 插件目录名：claude-cli 后端在 anthropic 插件里，google-gemini-cli 在 google 插件里。
    plugin_map = {"claude-cli": "anthropic", "google-gemini-cli": "google"}
    ext = plugin_map.get(openclaw_provider)
    if not ext:
        return []
    for base in plugin_dirs:
        manifest = base / ext / "openclaw.plugin.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        catalog_key = provider_key_map.get(openclaw_provider, openclaw_provider)
        prov = ((data.get("modelCatalog") or {}).get("providers") or {}).get(catalog_key) or {}
        models = []
        for m in prov.get("models") or []:
            if isinstance(m, dict) and m.get("id"):
                models.append({
                    "id": m["id"],
                    "name": m.get("name") or m["id"],
                    "contextWindow": m.get("contextWindow"),
                })
        return models
    return []


def detect_local_agents() -> list[dict[str, object]]:
    """扫一遍 PATH，返回每个已知 agent CLI 的探测结果。

    字段：
      id / label            标识与展示名
      installed             是否在 PATH 上找到
      command / path        命中的可执行名与绝对路径
      openclaw_provider     底座的 provider id（None = 无原生后端）
      supported / usableWithoutKey 仅指 OpenClaw 的 CLI provider 路径，不验证登录
      nativeRuntime         可另行选择的 Easel 独立执行引擎；不表示已配置或已登录
      configured            该 provider 是否已出现在 openclaw.json 里
      login_hint            给用户的一句话说明
    """
    configured = _configured_providers()
    out: list[dict[str, object]] = []
    for spec in KNOWN_AGENT_CLIS:
        found_cmd = ""
        found_path = ""
        for cmd in spec["commands"]:  # type: ignore[union-attr]
            p = shutil.which(cmd)  # type: ignore[arg-type]
            if p:
                found_cmd, found_path = cmd, p
                break
        provider = spec["openclaw_provider"]
        config_provider = spec.get("config_provider")
        installed = bool(found_path)
        is_configured = bool(config_provider) and config_provider in configured
        out.append({
            "id": spec["id"],
            "label": spec["label"],
            "installed": installed,
            "command": found_cmd,
            "path": found_path,
            # 只有「有原生后端」的 CLI 才可能免 key 使用；其余如实标注不支持。
            "openclawProvider": provider,
            "configProvider": config_provider,
            "supported": provider is not None,
            "nativeRuntime": spec.get("native_runtime"),
            "configured": is_configured,
            "usableWithoutKey": bool(installed and provider is not None),
            "loginHint": spec["login_hint"],
            # 可选模型目录（有后端的 CLI 才有；空列表 = 前端退化为手填）。
            "models": catalog_for_provider(provider),  # type: ignore[arg-type]
        })
    return out


def summarize_local_agents() -> dict[str, object]:
    """给界面/doctor 用的摘要：本机装了哪些、其中哪些能免 key 用。"""
    agents = detect_local_agents()
    installed = [a for a in agents if a["installed"]]
    usable = [a for a in installed if a["usableWithoutKey"]]
    return {
        "agents": agents,
        "installedCount": len(installed),
        "usableWithoutKeyCount": len(usable),
        "usableWithoutKey": [a["id"] for a in usable],
    }
