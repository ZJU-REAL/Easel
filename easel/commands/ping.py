"""easel ping — 连通性测试（直接运行，不依赖 Docker）。"""

from __future__ import annotations

import os
import subprocess

GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = os.environ.copy()
    env.setdefault("http_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("https_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("no_proxy", "localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*")
    return env


def _step(label: str, cmd: list[str], timeout: int = 30,
          env: dict[str, str] | None = None) -> bool:
    """Run a command and print OK/FAIL."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=timeout,
            env=env,
        )
        ok = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ok = False
        result = None

    status = f"{GREEN}OK{NC}" if ok else f"{RED}FAIL{NC}"
    print(f"  {label:<50s} {status}")

    if not ok and result and result.stderr:
        for line in result.stderr.strip().splitlines()[:5]:
            print(f"    {line}")

    return ok


def cmd_ping(_args) -> int:
    print("[easel] 连通性测试\n")
    all_ok = True

    # Step 1: Gateway healthz
    all_ok &= _step(
        "Step 1: Gateway healthz (localhost:18789)",
        ["curl", "-sf", "http://localhost:18789/healthz"],
        timeout=10,
    )

    # Step 2: OpenClaw agent
    all_ok &= _step(
        "Step 2: openclaw agent --local (say PONG)",
        ["openclaw", "--profile", "easel",
         "agent", "--local", "--agent", "main",
         "--timeout", "30", "--message", "say PONG"],
        timeout=60,
        env=_proxy_env(),
    )

    print()
    if all_ok:
        print(f"{GREEN}✓ 全部通过{NC}")
    else:
        print(f"{RED}✗ 有步骤失败{NC} — 请运行 python -m easel doctor 检查环境")

    return 0 if all_ok else 1
