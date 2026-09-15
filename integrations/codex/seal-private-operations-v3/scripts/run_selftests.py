#!/usr/bin/env python3
"""Run every deterministic self-test shipped with V3's execution scripts."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
SEARCH_ROOTS = (RUNTIME / "skills/shared/scripts", ROOT / "bundled-skills")
sys.path.insert(0, str(RUNTIME))

from easel.paths import runtime_path_entries  # noqa: E402


def discover() -> list[tuple[Path, str]]:
    found = []
    for base in SEARCH_ROOTS:
        for path in base.rglob("*.py"):
            source = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"add_parser\([\"']selftest[\"']", source):
                found.append((path, "selftest"))
            elif re.search(r"add_argument\([\"']--selftest[\"']", source):
                found.append((path, "--selftest"))
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    env = os.environ.copy()
    env["EASEL_ROOT"] = str(RUNTIME)
    env["SEAL_RUNTIME_ROOT"] = str(RUNTIME)
    env["SEAL_BUNDLED_SKILLS"] = str(ROOT / "bundled-skills")
    env["PATH"] = os.pathsep.join((*runtime_path_entries(), env.get("PATH", "")))
    env["PYTHONPATH"] = os.pathsep.join((str(RUNTIME / "skills/shared/scripts"), env.get("PYTHONPATH", "")))
    failures = []
    tests = discover()
    for index, (path, mode) in enumerate(tests, 1):
        rel = path.relative_to(ROOT)
        print(f"[{index:02d}/{len(tests):02d}] {rel} {mode}", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, str(path), mode], cwd=RUNTIME, env=env,
                capture_output=True, text=True, timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            failures.append((str(rel), "超时"))
            continue
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            failures.append((str(rel), detail[-1] if detail else f"退出码 {result.returncode}"))
    if failures:
        print("\n失败项：")
        for path, detail in failures:
            print(f"- {path}: {detail}")
        return 1
    print(f"\n{len(tests)} 个脚本自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
