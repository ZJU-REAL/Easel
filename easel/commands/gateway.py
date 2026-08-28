"""easel gateway — 管理 OpenClaw gateway。"""

from __future__ import annotations

import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_SCRIPT = PROJECT_ROOT / "scripts" / "gateway.sh"


def cmd_gateway(args) -> int:
    action = getattr(args, "action", "status") or "status"
    result = subprocess.run(
        ["bash", str(GATEWAY_SCRIPT), action],
        cwd=PROJECT_ROOT,
    )
    return result.returncode
