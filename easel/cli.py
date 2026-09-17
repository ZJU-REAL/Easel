"""Easel CLI — 社媒内容工作流整合层。

用法：
    easel chat                              # 新会话（选画像后进入）
    easel doctor                            # 检查环境
    easel gateway {start|stop|status}       # 管理 gateway
    easel ping                              # 连通性测试
    easel skill <name> -i "..." -p <画像>   # 运行 SKILL
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from easel.runtimes import SetupContext, get_runtime, runtime_env
from easel.commands.doctor import cmd_doctor
from easel.commands.gateway import cmd_gateway
from easel.commands.ping import cmd_ping
from easel.commands.skill import cmd_skill
from easel.persona import list_personas as _list_personas
from easel.persona import persona_prefix

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = PROJECT_ROOT / "profiles"


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = runtime_env()
    env.setdefault("EASEL_ROOT", str(PROJECT_ROOT))
    env.setdefault("http_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("https_proxy", os.environ.get("EASEL_PROXY", ""))
    env.setdefault("no_proxy", "localhost,127.0.0.1,*.xiaohongshu.com,*.devops.xiaohongshu.com,10.*")
    return env

CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
DIM = "\033[0;90m"
NC = "\033[0m"


def cmd_chat(_args) -> int:
    """启动 Easel 交互对话（每次新会话）。"""

    print()
    print(f"  {CYAN}Easel{NC} — 社媒内容工作流")
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
    print(f"  {DIM}切换历史会话: 对话中输入 /session{NC}")
    print(f"  {CYAN}Ctrl+C{NC} 退出")
    print()

    prefix = persona_prefix(selected_persona)
    try:
        # Adapter 统一处理 runtime CLI 定位与交互启动。
        result_code = get_runtime().open_chat(prefix)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{RED}{exc}{NC} — 请运行 `python -m easel doctor` 检查环境。", file=sys.stderr)
        return 1

    return result_code


def cmd_web(args) -> int:
    """启动 Web 工作台（FastAPI + React），默认 http://localhost:7860。"""
    port = getattr(args, "port", 7860)
    env = _proxy_env()
    env["EASEL_PORT"] = str(port)
    script = PROJECT_ROOT / "web" / "app.py"
    if not script.is_file():
        print(f"{RED}未找到 web/app.py{NC} — 安装可能不完整，请重跑 `bash setup.sh`。",
              file=sys.stderr)
        return 1
    # 透传子进程返回码：端口占用/依赖缺失导致 app.py 立刻退出时，调用方
    # （自启/CI/脚本）能据此判断启动是否成功，而非恒拿到 0。
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    return result.returncode


def cmd_runtime_setup(_args) -> int:
    result = get_runtime().setup(SetupContext(PROJECT_ROOT, runtime_env()))
    print(result.message)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="easel",
        description="Easel — 社媒内容工作流整合层 CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # chat
    p_chat = sub.add_parser("chat", help="交互对话（新会话）")
    p_chat.set_defaults(func=cmd_chat)

    # doctor
    p_doctor = sub.add_parser("doctor", help="检查环境")
    p_doctor.set_defaults(func=cmd_doctor)

    # gateway
    p_gw = sub.add_parser("gateway", help="管理当前 Agent runtime 服务")
    p_gw.add_argument("action", choices=["start", "stop", "restart", "status", "logs"],
                       default="status", nargs="?")
    p_gw.set_defaults(func=cmd_gateway)

    # ping
    p_ping = sub.add_parser("ping", help="连通性测试")
    p_ping.set_defaults(func=cmd_ping)

    # skill
    p_skill = sub.add_parser("skill", help="运行 SKILL（自动路由）")
    p_skill.add_argument("name", help="SKILL 名称")
    p_skill.add_argument("--input", "-i", required=True, help="输入内容")
    p_skill.add_argument("--profile", "-p", default=None, help="用户画像名称")
    p_skill.set_defaults(func=cmd_skill)

    # web
    p_web = sub.add_parser("web", help="启动 Web UI")
    p_web.add_argument("--port", type=int, default=7860, help="端口（默认 7860）")
    p_web.set_defaults(func=cmd_web)

    # Installer-facing stable hook; setup scripts never branch on runtime details.
    p_setup = sub.add_parser("runtime-setup", help=argparse.SUPPRESS)
    p_setup.set_defaults(func=cmd_runtime_setup)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{RED}{exc}{NC}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
