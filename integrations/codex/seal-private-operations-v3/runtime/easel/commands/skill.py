"""easel skill — 运行 Seal 内置能力，统一通过 Codex CLI 处理。

所有能力请求都发给 Codex agent，由 Codex 根据 AGENTS.md 的规则
读对应 CAPABILITY.md 自己执行、并凝练 Profile。
这样无论从 chat / skill / web 哪个入口进来，逻辑都是一致的。

用法：
    easel skill check-compliance -i "文案文本"
    easel skill check-compliance -i "文案" -p 科技数码达人
    easel skill produce-shortdrama -i "30秒短剧需求"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from easel.persona import persona_prefix, profile_exists
from easel.timeouts import TIMEOUT_PRODUCE
from easel.codex_adapter import build_skill_prompt, run_codex

from easel.paths import BUNDLED_SKILLS_DIR, PROFILES_DIR, RUNTIME_ROOT

PROJECT_ROOT = RUNTIME_ROOT
SKILLS_DIR = BUNDLED_SKILLS_DIR


def _list_all_skills() -> list[str]:
    """列出所有可用能力名。"""
    if not SKILLS_DIR.is_dir():
        return []
    return [d.name for d in sorted(SKILLS_DIR.iterdir())
            if d.is_dir() and (d / "CAPABILITY.md").is_file()]


def _find_skill(name: str) -> str | None:
    """查找内置能力是否存在，返回完整名或 None。"""
    candidates = [name, f"skill-{name}"] if not name.startswith("skill-") else [name]
    for candidate in candidates:
        if (SKILLS_DIR / candidate / "CAPABILITY.md").is_file():
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
    print(f"[Seal V3] ERROR: 画像 '{name}' 不存在", file=sys.stderr)
    if available:
        print(f"  可用画像: {', '.join(available)}", file=sys.stderr)
    return False


def cmd_skill(args) -> int:
    skill_name = args.name
    skill_full = _find_skill(skill_name)

    if skill_full is None:
        print(f"[Seal V3] ERROR: SKILL '{skill_name}' 不存在")
        print("  可用 SKILL:")
        for name in _list_all_skills():
            print(f"    {name}")
        return 1

    # 检查 Profile
    if args.profile and not _check_profile_exists(args.profile):
        return 1

    # 构造消息——发给 Codex，让它按 AGENTS.md 规则处理
    content = _resolve_input(args.input)

    message = build_skill_prompt(skill_full, f"{persona_prefix(args.profile)}{content}", args.profile)

    # 统一给足超时：制作类 SKILL（生视频/多镜合成）可能跑很久，取安全上界
    timeout = TIMEOUT_PRODUCE

    print(f"[Seal V3] SKILL: {skill_full}")
    if args.profile:
        print(f"[Seal V3] 画像: {args.profile}")
    print("─" * 50)

    session = getattr(args, "session", None)
    key = f"cli:{args.profile or 'default'}:{session}" if session else None
    rc, stdout, stderr = run_codex(message, timeout=timeout, session_key=key, images=getattr(args, "image", None))
    if stdout.strip():
        print(stdout.strip())
    if stderr.strip():
        print(stderr.strip(), file=sys.stderr)
    return rc
