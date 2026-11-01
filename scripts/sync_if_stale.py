#!/usr/bin/env python
"""启动前按需把 skill 同步到 agent workspace——只在仓库比 workspace 新时才同步。

为什么需要这个脚本：agent 真正读的是 OpenClaw workspace 里那份 skill 副本，不是仓库里的
源文件。改了仓库里的 skill 而没同步，agent 读到的还是旧快照：症状是「我明明改了规则，
agent 就是不听」，而且 doctor 只查目录存在性时同样报绿。

这里**不自己实现同步逻辑**——同步语义由上游的 ``agents/sync.sh`` 独占（它还负责
workspace 文档、profiles/outputs 的链接、以及往 AGENTS.md 追加运行时项目根路径）。
本脚本只做一件事：判断要不要跑它。

用法：
    python scripts/sync_if_stale.py          # 需要就同步，不需要就秒退
    python scripts/sync_if_stale.py --check  # 只报告状态，不同步
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from easel.openclaw_workspace import workspace_dir  # noqa: E402
from easel.skills_sync import (  # noqa: E402
    bash_executable, ensure_workspace_links, skills_sync_state,
)


def main(argv: list[str]) -> int:
    check_only = "--check" in argv

    ok, detail = skills_sync_state()
    if ok:
        print("[easel] skill 已是最新，跳过同步")
        return 0
    if check_only:
        print(f"[easel] 需要同步：{detail}")
        return 1

    bash = bash_executable()
    if not bash:
        print(f"[easel] 需要同步（{detail}），但找不到 bash，请手动跑 agents/sync.sh", file=sys.stderr)
        return 1

    # sync.sh 自己会向 openclaw 问 workspace；Windows 上它的 python 解析链找不到
    # .venv/bin/python，会退化到错误的历史路径——直接把答案喂给它，两边同源。
    env = dict(os.environ)
    env["EASEL_OPENCLAW_WORKSPACE"] = str(workspace_dir())

    print("[easel] 检测到 skill 有更新，正在同步到 agent workspace（约 20 秒）…")
    proc = subprocess.run(
        [bash, str(PROJECT_ROOT / "agents" / "sync.sh")],
        cwd=str(PROJECT_ROOT), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=600,
    )
    # sync.sh 在 Windows 上会以非 0 退出：它的 ln -s 退化成复制，于是下一步 rm -f
    # 删不掉非空目录，set -e 直接终止——但此时 skills 其实已经同步完了。
    # 所以不看它的退出码，改用「同步后是否真的新鲜」来判定。
    if proc.returncode != 0:
        print(f"[easel] sync.sh 退出码 {proc.returncode}（Windows 下的链接步骤所致），"
              "改用同步结果判定", file=sys.stderr)

    link_problems = ensure_workspace_links()
    for problem in link_problems:
        print(f"[easel] 链接修复失败：{problem}", file=sys.stderr)

    ok_after, detail_after = skills_sync_state()
    if not ok_after:
        print(f"[easel] 同步后仍判定为未同步：{detail_after}", file=sys.stderr)
        return 1
    if link_problems:
        print("[easel] skill 已同步，但 workspace 链接有问题（agent 可能读不到画像/产物）", file=sys.stderr)
        return 1
    print("[easel] 同步完成")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
