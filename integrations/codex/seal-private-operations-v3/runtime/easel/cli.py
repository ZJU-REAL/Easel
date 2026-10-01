"""Easel CLI — 社媒内容工作流整合层。

用法：
    seal chat                              # 新会话（选画像后进入）
    seal doctor                            # 检查环境
    seal ping                              # 连通性测试
    seal skill <name> -i "..." -p <画像>   # 运行内置能力
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from easel.commands.doctor import cmd_doctor
from easel.commands.ping import cmd_ping
from easel.commands.skill import cmd_skill
from easel.persona import list_personas as _list_personas
from easel.persona import persona_prefix
from easel.timeouts import TIMEOUT_CHAT
from easel.codex_adapter import build_runtime_prompt, codex_command_prefix
from easel.paths import PROFILES_DIR, RUNTIME_ROOT, runtime_path_entries

PROJECT_ROOT = RUNTIME_ROOT
PROFILE = "easel"


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = os.environ.copy()
    env.pop("_", None)
    env.setdefault("EASEL_ROOT", str(PROJECT_ROOT))
    env.setdefault("REDBOOK_STATE_DIR", str(PROJECT_ROOT / "browser-profiles" / "redbook"))
    env.setdefault("REDBOOK_COOKIE_FILE", str(PROJECT_ROOT / "browser-profiles" / "redbook" / "cookies.json"))
    env["PATH"] = os.pathsep.join((*runtime_path_entries(), env.get("PATH", "")))
    env["PYTHONPATH"] = str(PROJECT_ROOT / "skills" / "shared" / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("http_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("https_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("no_proxy", "localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*")
    return env

CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
DIM = "\033[0;90m"
NC = "\033[0m"


def cmd_chat(_args) -> int:
    """启动 Easel 交互对话（每次新会话）。"""

    print()
    print(f"  {CYAN}Seal{NC} — 您的私人运营顾问（源自开源项目Easel）")
    print()

    # ---- 选择画像 ----
    personas = _list_personas()
    selected_persona = None

    if personas:
        print("  选择用户画像：")
        for i, name in enumerate(personas, 1):
            identity = PROFILES_DIR / name / "identity.md"
            desc = ""
            if identity.is_file():
                for line in identity.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and not line.startswith("<!--"):
                        desc = f"  — {line[:50]}"
                        break
            print(f"    {i}) {name}{desc}")
        print(f"    0) 不使用画像（通用模式）")
        print()

        try:
            choice = input("  请选择 [0]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice and choice != "0":
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(personas):
                    selected_persona = personas[idx]
            except ValueError:
                if choice in personas:
                    selected_persona = choice

    # ---- 每次新会话 ----
    if selected_persona:
        print(f"\n  {GREEN}✓{NC} 画像: {selected_persona}")
    else:
        print(f"\n  {YELLOW}→{NC} 通用模式")

    session_key = f"easel-{time.strftime('%m%d-%H%M%S')}"

    print(f"  {DIM}会话: {session_key}{NC}")
    print(f"  {DIM}历史会话由 Codex 管理；可使用 codex resume{NC}")
    print(f"  {CYAN}Ctrl+C{NC} 退出")
    print()

    cmd = [*codex_command_prefix(), "--cd", str(PROJECT_ROOT)]

    # 画像作为初始消息内联注入（无全局 USER.md，避免并发竞态；与 web/skill 同源）。
    # 说明：注入随 session 历史留存，超长会话被压缩后可能丢画像——换取「每个请求自包含」，
    # 与 docs/prompt-stack.md 声明的架构一致。
    prefix = persona_prefix(selected_persona)
    cmd += [build_runtime_prompt(prefix + "\n进入 Easel 交互工作流，等待用户任务。")]

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=_proxy_env())

    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name,
        description="Seal-您的私人运营顾问 · 源自开源项目Easel（easel 为兼容命令）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # chat
    p_chat = sub.add_parser("chat", help="交互对话（新会话）")
    p_chat.set_defaults(func=cmd_chat)

    # doctor
    p_doctor = sub.add_parser("doctor", help="检查环境")
    p_doctor.set_defaults(func=cmd_doctor)

    # ping
    p_ping = sub.add_parser("ping", help="连通性测试")
    p_ping.set_defaults(func=cmd_ping)

    # skill
    p_skill = sub.add_parser("skill", help="运行 SKILL（自动路由）")
    p_skill.add_argument("name", help="SKILL 名称")
    p_skill.add_argument("--input", "-i", required=True, help="输入内容")
    p_skill.add_argument("--profile", "-p", default=None, help="用户画像名称")
    p_skill.add_argument("--session", default=None, help="显式复用同一 Skill 会话；省略则独立执行")
    p_skill.add_argument("--image", action="append", default=None, help="附加图片路径，可重复")
    p_skill.set_defaults(func=cmd_skill)

    # web
    def cmd_web(args):
        port = getattr(args, "port", 7862)
        env = _proxy_env()
        env["EASEL_PORT"] = str(port)
        subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "web" / "app.py")],
            cwd=str(PROJECT_ROOT),
            env=env,
        )
        return 0

    p_web = sub.add_parser("web", help="启动 Web UI")
    p_web.add_argument("--port", type=int, default=7862, help="端口（默认 7862）")
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
