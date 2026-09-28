"""easel ping — 连通性测试（直接运行，不依赖 Docker）。"""

from __future__ import annotations

import os
from pathlib import Path

from easel.runtimes import RunRequest, get_runtime, runtime_env

GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = runtime_env()
    env.setdefault("http_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("https_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("no_proxy", "localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*")
    return env


def cmd_ping(_args) -> int:
    print("[easel] 连通性测试\n")
    all_ok = True
    runtime = get_runtime()
    runtime_id = runtime.descriptor.id

    # Step 1: selected runtime service
    gateway_ok = runtime.health().ok
    print(f"  {f'Step 1: {runtime_id} service health':<50s} "
          f"{GREEN if gateway_ok else RED}{'OK' if gateway_ok else 'FAIL'}{NC}")
    all_ok &= gateway_ok

    # Step 2: Agent call
    handle = None
    try:
        root = Path.cwd()
        handle = runtime.start(RunRequest(
            "say PONG", "ping", 30, root, _proxy_env(), root / "outputs" / "_sessions",
        ))
        for _ in handle.events():
            pass
        result = handle.wait()
        agent_ok = result.returncode == 0
    except Exception:
        agent_ok = False
    finally:
        if handle is not None:
            handle.close()
    print(f"  {f'Step 2: {runtime_id} agent (say PONG)':<50s} "
          f"{GREEN if agent_ok else RED}{'OK' if agent_ok else 'FAIL'}{NC}")
    all_ok &= agent_ok

    print()
    if all_ok:
        print(f"{GREEN}✓ 全部通过{NC}")
    else:
        print(f"{RED}✗ 有步骤失败{NC} — 请运行 python -m easel doctor 检查环境")

    return 0 if all_ok else 1
