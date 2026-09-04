"""easel skill — 运行 SKILL，统一通过 OpenClaw agent 处理。

所有 SKILL 请求都发给 OpenClaw agent，由 OpenClaw 根据 AGENTS.md 的规则
读对应 SKILL 自己执行、并凝练 Profile。
这样无论从 chat / skill / web 哪个入口进来，逻辑都是一致的。

用法：
    easel skill check-compliance -i "文案文本"
    easel skill check-compliance -i "文案" -p 科技数码达人
    easel skill produce-shortdrama -i "30秒短剧需求"
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

from easel.persona import persona_prefix, profile_exists
from easel.timeouts import TIMEOUT_PRODUCE

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills" / "openclaw"
PROFILES_DIR = PROJECT_ROOT / "profiles"
OPENCLAW_PROFILE = "easel"


def _list_all_skills() -> list[str]:
    """列出所有可用 SKILL 名。"""
    if not SKILLS_DIR.is_dir():
        return []
    return [d.name for d in sorted(SKILLS_DIR.iterdir())
            if d.is_dir() and (d / "SKILL.md").is_file()]


def _find_skill(name: str) -> str | None:
    """查找 SKILL 是否存在，返回完整名或 None。"""
    candidates = [name, f"skill-{name}"] if not name.startswith("skill-") else [name]
    for candidate in candidates:
        if (SKILLS_DIR / candidate / "SKILL.md").is_file():
            return candidate
    return None


def _resolve_input(raw_input: str) -> str:
    """判断输入是文件路径还是文本。"""
    try:
        p = Path(raw_input)
        is_file = p.is_file()
    except OSError:
        # 文本过长（超出文件名长度上限）或含非法路径字符 → 当作文本处理
        return raw_input
    if is_file:
        suffix = p.suffix.lower()
        if suffix in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
            return f"请处理这个图片：{p.resolve()}"
        # 音视频/二进制文件不能 read_text（会 UnicodeDecodeError），只传路径
        if suffix in (".mp3", ".mp4", ".wav", ".mov", ".m4a", ".flac", ".aac",
                      ".ogg", ".webm", ".mkv", ".avi", ".pdf", ".zip",
                      ".gz", ".tar", ".7z", ".rar"):
            return f"请处理这个文件：{p.resolve()}"
        return p.read_text(encoding="utf-8")
    return raw_input


def _check_profile_exists(name: str) -> bool:
    """检查画像是否存在，不存在时打印错误与可用画像。"""
    if profile_exists(name):
        return True
    available = [d.name for d in PROFILES_DIR.iterdir()
                 if d.is_dir() and not d.name.startswith("_")]
    print(f"[easel] ERROR: 画像 '{name}' 不存在", file=sys.stderr)
    if available:
        print(f"  可用画像: {', '.join(available)}", file=sys.stderr)
    return False


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = os.environ.copy()
    env.setdefault("EASEL_ROOT", str(PROJECT_ROOT))
    env.setdefault("http_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("https_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("no_proxy", "localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*")
    return env


def _run_via_openclaw(message: str, timeout: int = 300) -> int:
    """统一通过 OpenClaw agent 执行。"""
    session_key = f"skill-{int(time.time() * 1000)}"

    cmd = [
        "openclaw", "--profile", OPENCLAW_PROFILE,
        "agent", "--agent", "main",
        "--session-key", f"agent:main:{session_key}",
        "--timeout", str(timeout),
        "--message", message,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                cwd=str(PROJECT_ROOT), timeout=timeout + 30,
                                env=_proxy_env())
    except subprocess.TimeoutExpired:
        print("⏱️ 请求超时", file=sys.stderr)
        return 124
    except Exception as e:  # noqa: BLE001 — 兜底，避免裸崩堆栈（与 web 行为一致）
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if result.stdout:
        lines = []
        for line in result.stdout.splitlines():
            clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
            if clean.startswith("[") and any(
                tag in clean[:40] for tag in
                ["[provider-", "[agents/", "[agent/", "[plugins]", "[tools]",
                 "[diagnostic]", "[fetch-", "[heartbeat]", "[health-", "[gateway]"]
            ):
                continue
            if clean.strip():
                lines.append(clean)
        output = "\n".join(lines).strip()
        if output:
            print(output)

    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return result.returncode


def cmd_skill(args) -> int:
    skill_name = args.name
    skill_full = _find_skill(skill_name)

    if skill_full is None:
        print(f"[easel] ERROR: SKILL '{skill_name}' 不存在")
        print("  可用 SKILL:")
        for name in _list_all_skills():
            print(f"    {name}")
        return 1

    # 检查 Profile
    if args.profile and not _check_profile_exists(args.profile):
        return 1

    # 构造消息——发给 OpenClaw，让它按 AGENTS.md 规则处理
    content = _resolve_input(args.input)

    message = f"{persona_prefix(args.profile)}请执行 /{skill_full}，内容如下：\n\n{content}"

    # 统一给足超时：制作类 SKILL（生视频/多镜合成）可能跑很久，取安全上界
    timeout = TIMEOUT_PRODUCE

    print(f"[easel] SKILL: {skill_full}")
    if args.profile:
        print(f"[easel] 画像: {args.profile}")
    print("─" * 50)

    return _run_via_openclaw(message, timeout=timeout)
