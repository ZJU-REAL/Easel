"""easel ping — 连通性测试（直接运行，不依赖 Docker）。"""

from __future__ import annotations

import os
import asyncio
import subprocess
import urllib.error
import urllib.request

from easel.gateway_endpoint import healthz_url, port_source, resolve_gateway_port
from easel.openclaw_cmd import openclaw_base_cmd
from easel.direct_api import DirectAPIError, api_mode, read_settings, stream_chat

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
    settings = read_settings()
    if api_mode(settings):
        async def probe():
            async for kind, text in stream_chat(settings, "请只回复 PONG", timeout=30):
                if kind == "token":
                    print(text, end="", flush=True)
        try:
            asyncio.run(asyncio.wait_for(probe(), timeout=35))
        except (DirectAPIError, asyncio.TimeoutError) as error:
            print(f"\n{RED}API 直连 FAIL{NC}：{error or '请求超时'}")
            return 1
        print(f"\n{GREEN}✓ API 直连通过（未使用 OpenClaw）{NC}")
        return 0
    all_ok = True

    # Step 1: Gateway healthz（端口不写死：非默认 profile 走哈希，easel → 37289）
    gateway_step = f"Step 1: Gateway healthz (localhost:{resolve_gateway_port()})"
    try:
        with urllib.request.urlopen(healthz_url(), timeout=10) as response:
            gateway_ok = response.status == 200
    except (OSError, urllib.error.URLError):
        gateway_ok = False
    print(f"  {gateway_step:<50s} "
          f"{GREEN if gateway_ok else RED}{'OK' if gateway_ok else 'FAIL'}{NC}")
    if not gateway_ok:
        print(f"    └─ 端口来自 {port_source()}；改了 profile/端口后请 python -m easel gateway restart")
    all_ok &= gateway_ok

    # Step 2: OpenClaw agent
    oc_cmd = openclaw_base_cmd() + [
        "--profile", "easel",
        "agent", "--agent", "main",
        "--timeout", "30", "--message", "say PONG",
    ]
    all_ok &= _step(
        "Step 2: OpenClaw agent via Gateway (say PONG)",
        oc_cmd,
        timeout=60,
        env=_proxy_env(),
    )

    print()
    if all_ok:
        print(f"{GREEN}✓ 全部通过{NC}")
    else:
        print(f"{RED}✗ 有步骤失败{NC} — 请运行 python -m easel doctor 检查环境")

    return 0 if all_ok else 1
