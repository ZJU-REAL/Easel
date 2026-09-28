"""easel gateway — 管理 OpenClaw gateway。"""

from __future__ import annotations

from easel.runtimes import get_runtime


def cmd_gateway(args) -> int:
    action = getattr(args, "action", "status") or "status"
    result = get_runtime().manage_service(action)
    if not result.ok and result.reason:
        print(result.reason)
    return result.code
