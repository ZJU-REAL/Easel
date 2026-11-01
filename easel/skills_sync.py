"""判断仓库里的 skill 是否比 agent workspace 里的新——也就是「改了 skill 到底生效没有」。

为什么需要这个模块：``doctor._skills_synced()`` 原本只查「workspace/skills 目录存在吗、
非空吗」。这漏掉了最常见的一种失效：**仓库里改了 skill，但从没重新同步，于是 agent 读到的
还是旧快照**。而 doctor 会报绿、同步脚本不跑时也不会提示——症状是「我明明改了规则，agent
就是不听」，极难查。

这与 issue #19 是同一类坑：写入端与读取端不一致时，各处都报「正常」，技能静默不生效。
区别在于 #19 是**路径写错**，这里是**内容过期**——所以光比路径不够，必须比内容新鲜度。

判断依据：源目录（仓库 skills/builtin + skills/shared）里最新文件的修改时间，是否晚于
目标目录（workspace/skills + workspace/shared）里最新文件的修改时间。``cp -r`` 不保留
mtime（同步后的目标文件 mtime = 同步时刻），所以同步完成后必然满足「源不晚于目标」。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from easel.openclaw_workspace import state_dir, workspace_dir

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 源端：仓库里的内置技能 + 共享层（skill 会引用 ../../shared/，改了同样要同步）
SOURCE_DIRS = ("skills/builtin", "skills/shared")

# 文件系统时间戳精度容差（秒）：避免同一秒内的写/拷被判成"未同步"
_MTIME_TOLERANCE = 2.0

# workspace 里应当指向项目目录的链接（名字 → 项目内源目录）
WORKSPACE_LINKS = {
    "easel-profiles": "profiles",
    "outputs": "outputs",
}


@lru_cache(maxsize=1)
def agent_workspace() -> Path:
    """agent 实际读取的 workspace 目录（带缓存）。

    ``easel.openclaw_workspace.workspace_dir()`` 的权威做法是 spawn ``openclaw status
    --json`` 去问运行时——但那要冷启 Node（实测数秒）。而本模块每次启动都要问好几次，
    所以先走快路径：

    1. ``EASEL_OPENCLAW_WORKSPACE`` 显式覆盖；
    2. 已知的两套布局里，哪一套的 ``skills/`` 非空就认哪一套——agent 真正读 skill 的
       目录必然有 skills/，这本身就是"它读这里"的证据；
    3. 都看不出来才去问 openclaw（首次同步、workspace 还是空的时候）。

    布局若再变，第 3 步仍然兜得住。
    """
    override = os.environ.get("EASEL_OPENCLAW_WORKSPACE")
    if override:
        return Path(override)

    candidates = [
        state_dir() / "workspace",                      # 2026.9.x 布局
        Path.home() / ".openclaw" / "workspace-easel",  # 2026.6.x 布局
    ]
    for candidate in candidates:
        skills = candidate / "skills"
        try:
            if skills.is_dir() and any(skills.iterdir()):
                return candidate
        except OSError:
            continue
    return workspace_dir()


def _latest_mtime(root: Path) -> float:
    """目录下最新文件的 mtime；目录不存在返回 0。

    用 os.scandir 手写递归而不是 pathlib.rglob：Windows 上 rglob 对上千个文件的
    stat 开销很大（实测 800+ 文件要几秒），启动时每次都跑这个判断，不能这么慢。
    """
    latest = 0.0
    stack = [str(root)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                            if mtime > latest:
                                latest = mtime
                    except OSError:
                        continue
        except OSError:
            continue
    return latest


def skills_sync_state() -> tuple[bool, str]:
    """返回 (是否已同步, 说明文字)。

    已同步 = workspace 里有 skills，且仓库侧没有比它更新的内容。
    """
    ws = agent_workspace()
    dst_skills = ws / "skills"
    try:
        if not dst_skills.is_dir() or not any(dst_skills.iterdir()):
            return False, f"agent 实际读取的 workspace 是 {ws}，其中 skills/ 为空或不存在"
    except OSError:
        return False, f"agent 实际读取的 workspace 是 {ws}，无法读取其中的 skills/"

    src_latest = 0.0
    for name in SOURCE_DIRS:
        src_latest = max(src_latest, _latest_mtime(PROJECT_ROOT / name))
    dst_latest = max(_latest_mtime(dst_skills), _latest_mtime(ws / "shared"))

    if src_latest > dst_latest + _MTIME_TOLERANCE:
        return False, (
            f"仓库里的 skill 比 workspace 里的新（改了但没同步，agent 读到的还是旧版本）。"
            f"请跑 agents/sync.sh 后重启 agent。"
        )
    return True, f"agent 实际读取的 workspace 是 {ws}，技能内容已是最新"


def sync_needed() -> bool:
    """便捷判断：是否需要同步。"""
    ok, _ = skills_sync_state()
    return not ok


def bash_executable() -> str | None:
    """找一个能跑 agents/sync.sh 的 bash（Windows 上 Git Bash 不在默认 PATH）。"""
    override = os.environ.get("EASEL_BASH")
    if override and Path(override).is_file():
        return override
    for candidate in (
        "C:/Program Files/Git/bin/bash.exe",
        "C:/Program Files/Git/usr/bin/bash.exe",
        "C:/Program Files (x86)/Git/bin/bash.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def ensure_workspace_links() -> list[str]:
    """保证 workspace 里的 profiles/outputs 指向项目目录，而不是副本。

    为什么需要它：``agents/sync.sh`` 用 ``ln -s`` 建这两个链接。在 Windows 上，
    Git Bash 的 ``ln -s`` 没有 ``MSYS=winsymlinks:nativestrict`` 时会**退化成复制**——
    于是 workspace 里留下的是一份**快照副本**。两个后果：

    1. agent 读到的是画像的旧版本（改了 profile，agent 那边没变）；
    2. agent 产出的文件落在副本里，项目的 ``outputs/`` 永远收不到产物。

    而且下次同步时 ``rm -f`` 删不掉非空目录，``set -e`` 会让 sync.sh 以非 0 退出——
    技能其实已经同步完了，退出码却在说"失败"。

    Windows 上改用 ``mklink /J``（目录联接）：对程序透明、不需要管理员权限、
    也不是快照。Linux/macOS 上 ``ln -s`` 本来就对，无需处理。

    返回问题描述列表（空表示都正常）。
    """
    problems: list[str] = []
    if os.name != "nt":
        return problems

    ws = agent_workspace()
    for name, source in WORKSPACE_LINKS.items():
        link = ws / name
        target = PROJECT_ROOT / source
        if not target.is_dir():
            # 源目录还不存在（比如还没产出过东西的 outputs/）——没有可链的内容，跳过即可，
            # 不是故障：等它被建出来，下次同步自然会链上。
            continue
        if link.is_symlink():
            continue                      # 已经是真链接（MSYS=nativestrict 时 ln -s 的效果）
        if link.exists():
            # 是副本目录：先删掉，否则 mklink 会因同名目录已存在而失败
            try:
                shutil.rmtree(link)
            except OSError as exc:
                problems.append(f"{name}：无法删除旧副本（{exc}）")
                continue
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            problems.append(f"{name}：建目录联接失败（{detail[-1] if detail else proc.returncode}）")
    return problems
