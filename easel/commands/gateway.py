"""easel gateway — 管理 OpenClaw gateway。"""

from __future__ import annotations

import subprocess
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_SCRIPT = PROJECT_ROOT / "scripts" / ("gateway.ps1" if os.name == "nt" else "gateway.sh")


def cmd_gateway(args) -> int:
    from easel import harnesses
    from easel.direct_api import read_settings
    runtime = harnesses.settings(PROJECT_ROOT / "outputs", read_settings())["runtime"]
    if runtime == "api":
        print("仅聊天模式直接请求模型 API，无需 Agent 或 OpenClaw gateway；用 easel ping 检查连通性")
        return 0
    if runtime != "openclaw":
        print(f"{runtime} 通过私有 stdio 按轮启动，无需 OpenClaw gateway；用 easel ping 检查连通性")
        return 0
    action = getattr(args, "action", "status") or "status"
    command = (
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(GATEWAY_SCRIPT), action]
        if os.name == "nt"
        else ["bash", str(GATEWAY_SCRIPT), action]
    )
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    return result.returncode
