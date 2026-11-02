#!/usr/bin/env python
"""Explicitly sync repository skill files, or report their state with --check.

Only skills/ and shared/ source files are copied. Workspace memories, custom
files and existing profile/output copies are preserved. No agent is restarted.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from easel.skills_sync import ensure_workspace_links, skills_sync_state, synchronize_skills


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Report only; do not write files or links')
    args = parser.parse_args(argv)
    ok, detail = skills_sync_state()
    if args.check:
        print(f'[easel] {detail}')
        return 0 if ok else 1
    try:
        copied = 0 if ok else synchronize_skills()
        problems = ensure_workspace_links()
        for problem in problems:
            print(f'[easel] {problem}', file=sys.stderr)
        ok_after, detail_after = skills_sync_state()
    except (OSError, ValueError, RuntimeError):
        print('[easel] 同步失败，请检查目录权限和目标链接；未删除任何目录', file=sys.stderr)
        return 1
    if problems or not ok_after:
        print(f'[easel] 未完成全部同步检查：{detail_after}', file=sys.stderr)
        return 1
    print(f'[easel] 同步完成（更新 {copied} 个文件）；额外本机文件、画像和记忆保留；不自动重启已有会话')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
