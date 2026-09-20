"""解析 agent 实际读取的 workspace 目录（写入端与读取端的唯一真相）。

为什么需要这个模块：OpenClaw 的默认 workspace 布局在版本之间**变过**，而 Easel 有三处
各自硬编码了一个路径，于是在不同版本上必然有一处是错的：

- 2026.6.x：非 default profile 的默认 workspace 是 ``~/.openclaw/<profile 拼进目录名>``
  形式，即 ``~/.openclaw/workspace-easel``。
- 2026.9.x：改成了 state dir 下的 ``workspace``，即 ``~/.openclaw-easel/workspace``
  （见该版本自带文档 docs/concepts/agent-workspace.md「Default location」一节）。

硬编码任何一个，都会在另一个版本上写到 agent 根本不读的地方 —— 而且同步脚本照样打印
"synced"，doctor 也照样报绿（它查的是同一个错路径），技能静默不生效。issue #19 记录的
就是这个现场。

所以这里不猜：**直接问 openclaw 自己**（``status --json`` 里的 workspaceDir 就是它运行时
实际用的那个目录），问不到才逐级退化。sync.sh / setup.ps1 / doctor 全部改走这里。
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path

PROFILE = "easel"


def state_dir() -> Path:
    """profile 的 state 目录（配置/凭据所在），与 gateway_questions 同一约定。"""
    override = os.environ.get("EASEL_OPENCLAW_STATE_DIR")
    return Path(override) if override else Path.home() / f".openclaw-{PROFILE}"


def config_path() -> Path:
    return state_dir() / "openclaw.json"


def _candidates() -> list[Path]:
    """两套历史布局。顺序无关紧要，只用于「挑一个已经有内容的」。"""
    return [state_dir() / "workspace", Path.home() / ".openclaw" / f"workspace-{PROFILE}"]


def _ask_openclaw() -> Path | None:
    """问 openclaw 它运行时到底用哪个 workspace —— 唯一与版本无关的答案。"""
    try:
        from easel.openclaw_cmd import openclaw_base_cmd
        argv = openclaw_base_cmd() + ["--profile", PROFILE, "status", "--json"]
    except Exception:  # noqa: BLE001 — 没装 openclaw / 定位不到，交给后面的退化
        return None
    try:
        # 实测 2026.6.11：冷启 1.1s、gateway 在跑时 3.0s，且 status 的探测预算自带上限，
        # 没有走网络的慢路径。给 20s 足够宽；再长只是让装不上的机器多干等。
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=20)
        if proc.returncode != 0:
            return None
        agents = json.loads(proc.stdout).get("agents") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None

    entries = agents.get("agents")
    if not isinstance(entries, list):
        return None
    default_id = agents.get("defaultId")
    # 优先取默认 agent 那条；没有 defaultId 就退而取第一条带 workspaceDir 的。
    for want_default in (True, False):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if want_default and entry.get("id") != default_id:
                continue
            wd = entry.get("workspaceDir")
            if isinstance(wd, str) and wd.strip():
                return Path(wd)
    return None


def _from_config() -> Path | None:
    """openclaw.json 里显式写死的 workspace（用户/旧版 setup 设过就以它为准）。"""
    try:
        cfg = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    agents = cfg.get("agents") or {}
    # 按 agent 的覆盖优先于 defaults。per-agent 条目在 2026.6.x 里是 `agents.list`（数组，
    # 见其 dist/config-utils 的 Array.isArray(cfg.agents?.list) 判定）；`agents.entries` 是
    # 另一种形态，两种都认，谁在就读谁 —— 这一级只在「连 openclaw 都调不起来」时才走到。
    per_agent = []
    listed = agents.get("list")
    if isinstance(listed, list):
        per_agent = [e for e in listed if isinstance(e, dict) and e.get("id") == "main"]
    entries = agents.get("entries")
    if isinstance(entries, dict) and isinstance(entries.get("main"), dict):
        per_agent.append(entries["main"])
    for value in [e.get("workspace") for e in per_agent] + [(agents.get("defaults") or {}).get("workspace")]:
        if isinstance(value, str) and value.strip():
            return Path(os.path.expanduser(value))
    return None


def _existing_with_content() -> Path | None:
    """已经装过的机器：哪个候选目录里真有东西，就认哪个，别把人家搬家。"""
    for cand in _candidates():
        skills = cand / "skills"
        try:
            if skills.is_dir() and any(skills.iterdir()):
                return cand
        except OSError:
            continue
    return None


def _version_default() -> Path:
    """都问不出来时按已装 openclaw 的版本猜；连版本都读不到就按新布局。"""
    try:
        from easel.commands.doctor import _openclaw_version
        ver = _openclaw_version()
    except Exception:  # noqa: BLE001
        ver = None
    if ver is not None and ver < (2026, 9, 0):
        return Path.home() / ".openclaw" / f"workspace-{PROFILE}"
    return state_dir() / "workspace"


@lru_cache(maxsize=1)
def workspace_dir() -> Path:
    """agent 实际读取的 workspace。写入端（sync）与检查端（doctor）都必须用它。

    逐级退化，前面拿到就不往下走：
      1. EASEL_OPENCLAW_WORKSPACE —— 显式覆盖，最高优先级
      2. openclaw status --json 里的 workspaceDir —— 运行时真相，跨版本可靠
      3. openclaw.json 里显式配置的 workspace
      4. 已经有内容的那个候选目录 —— 老机器原地不动，不触发"搬家"
      5. 按 openclaw 版本推默认布局
    """
    override = os.environ.get("EASEL_OPENCLAW_WORKSPACE")
    if override:
        return Path(override)
    for resolver in (_ask_openclaw, _from_config, _existing_with_content):
        got = resolver()
        if got is not None:
            return got
    return _version_default()


if __name__ == "__main__":
    # sync.sh / setup.ps1 直接把 stdout 当路径用，所以这里只许打印这一行。
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Windows 上 stdout 被管道接走时用的是 locale 编码（zh-CN 即 cp936），路径里只要有一个
    # 编码不出的字符，print 就抛 UnicodeEncodeError、一个字节都不输出 —— 调用方只看到空，
    # 于是静默走回退路径。统一按 UTF-8 输出；setup.ps1 那边会把 Console.OutputEncoding
    # 一起钉成 UTF-8，两端才对得上（PowerShell 5.1 默认按 OEM 代码页解码原生命令的 stdout）。
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    print(workspace_dir())
