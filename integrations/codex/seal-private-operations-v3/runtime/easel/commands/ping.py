"""seal ping - Codex 连通性测试。"""

from __future__ import annotations

from easel.codex_adapter import run_codex

GREEN = "\033[0;32m"
RED = "\033[0;31m"
NC = "\033[0m"


def cmd_ping(_args) -> int:
    print("[Seal V3] 连通性测试\n")
    all_ok = True

    # First invocation may warm Codex's local plugin/session cache; allow a
    # little more than the ordinary request timeout for this smoke test.
    rc, stdout, stderr = run_codex("只回复 PONG。不要调用任何工具。", timeout=120)
    ok = rc == 0 and "PONG" in stdout.upper()
    print(f"  {'Codex exec smoke test (PONG)':<50s} {GREEN if ok else RED}{'OK' if ok else 'FAIL'}{NC}")
    if not ok and stderr:
        print(f"    {stderr.strip().splitlines()[-1]}")
    all_ok &= ok

    print()
    if all_ok:
        print(f"{GREEN}✓ 全部通过{NC}")
    else:
        print(f"{RED}✗ 有步骤失败{NC} — 请运行 python -m easel doctor 检查环境")

    return 0 if all_ok else 1
