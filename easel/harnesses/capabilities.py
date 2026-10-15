"""Budget capability evidence, separate from CLI installation and permission prompts."""
from .base import HarnessError


def tool_budget_capability(runtime: str) -> dict:
    if runtime == "api":
        return {"admission": "no_tools", "enforcement_verified": True,
                "reason": "chat_only_no_tool_execution"}
    if runtime == "openclaw":
        return {"admission": "plugin_required", "enforcement_verified": False,
                "reason": "active_gateway_plugin_not_attested"}
    if runtime in {"codex", "acp", "opencode"}:
        return {"admission": "observation_only", "enforcement_verified": False,
                "reason": "adapter_has_no_universal_pre_execution_gate"}
    raise HarnessError("未知 Agent 底座，无法确认工具限额能力")


def require_tool_budget(runtime: str, env: dict) -> None:
    """Fail before dispatch; an installed binary or a user assertion is not attestation."""
    value = env.get("EASEL_REQUIRE_TOOL_BUDGET", "0")
    if not isinstance(value, str) or value.strip() not in {"0", "1"}:
        raise HarnessError("EASEL_REQUIRE_TOOL_BUDGET 必须为 0 或 1")
    if value.strip() == "0":
        return
    capability = tool_budget_capability(runtime)
    if not capability["enforcement_verified"]:
        raise HarnessError(
            f"{runtime} 无法确认执行前强制工具限额（{capability['reason']}），本次任务未启动。"
            "工具通知和权限确认不能替代调用预算；请使用具备已验证执行端保障的通道。")
