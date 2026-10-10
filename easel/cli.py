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
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from easel.commands.doctor import cmd_doctor
from easel.commands.gateway import cmd_gateway
from easel.commands.ping import cmd_ping
from easel.commands.skill import cmd_skill
from easel.openclaw_cmd import openclaw_base_cmd
from easel.persona import list_personas as _list_personas
from easel.persona import persona_prefix
from easel.persona import load_profile_text
from easel.direct_api import (DirectAPIError, SYSTEM_PROMPT, api_mode, history_path,
                              read_settings, stream_chat)
from easel.timeouts import TIMEOUT_CHAT

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = PROJECT_ROOT / "profiles"
PROFILE = "easel"


def _proxy_env() -> dict[str, str]:
    """返回带外网代理的环境变量（保护内网直连）。"""
    env = os.environ.copy()
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


def _build_chat_cmd(session_key: str, message_prefix: str = "") -> list[str]:
    """组装 `easel chat` 的 openclaw tui 命令行。

    必须用 openclaw_base_cmd() 解析启动方式，不能写死字面量 "openclaw"：Windows 上
    PATH 里的 openclaw 是 .cmd shim，CreateProcess 跑不了（见 easel/openclaw_cmd.py）。
    必须用 tui 子命令——`chat`/`terminal` 是 tui 的别名，会强制本地模式
    （openclaw dist/tui-cli-*.js: invokedSubcommand === "chat" → isLocal = true），
    而 --local 要求独占 state 目录，与 Easel 自启的 gateway 冲突，只会打印
    "A Gateway is running for this state directory" 后退出。
    """
    cmd = openclaw_base_cmd() + [
        "--profile", PROFILE,
        "tui",
        "--session", session_key,
        # chat 里可能直接发起制作层/跨层编排，给足制作层预算，避免长任务被 turn 超时掐断（O2）。
        # 超时统一走 easel/timeouts.py（三入口单一真相源），毫秒 = TIMEOUT_CHAT * 1000。
        "--timeout-ms", str(TIMEOUT_CHAT * 1000),
    ]
    # 画像作为初始消息内联注入（无全局 USER.md，避免并发竞态；与 web/skill 同源）。
    # 说明：注入随 session 历史留存，超长会话被压缩后可能丢画像——换取「每个请求自包含」，
    # 与 docs/prompt-stack.md 声明的架构一致。
    if message_prefix:
        cmd += ["--message", message_prefix]
    return cmd


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

    if api_mode(read_settings()):
        print("  API 直连模式（文字问答；/exit 退出）\n")
        system = SYSTEM_PROMPT
        if selected_persona:
            system += "\n\n当前画像：\n" + load_profile_text(selected_persona)
        async def reply(message):
            async for kind, text in stream_chat(
                    read_settings(), message, system=system,
                    history_file=history_path(PROJECT_ROOT / "outputs" / "_sessions", session_key),
                    timeout=TIMEOUT_CHAT):
                if kind == "token":
                    print(text, end="", flush=True)
        while True:
            try:
                message = input("你：").strip()
                if message in ("/exit", "/quit"):
                    return 0
                if message:
                    asyncio.run(asyncio.wait_for(reply(message), TIMEOUT_CHAT))
                    print()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            except (DirectAPIError, asyncio.TimeoutError) as error:
                print(f"\n❌ {error or 'API 请求超时'}")

    print(f"  {DIM}会话: {session_key}{NC}")
    print(f"  {DIM}切换历史会话: 对话中输入 /session{NC}")
    print(f"  {CYAN}Ctrl+C{NC} 退出")
    print()

    prefix = persona_prefix(selected_persona)
    try:
        # openclaw_base_cmd() 在 openclaw 全装不上时抛 FileNotFoundError；
        # subprocess.run 在可执行文件缺失时同样抛 FileNotFoundError。两者都提示安装。
        cmd = _build_chat_cmd(session_key, prefix)
        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=_proxy_env())
    except FileNotFoundError:
        print(f"{RED}未找到 openclaw{NC} — 请先安装：npm i -g openclaw，"
              f"或运行 `python -m easel doctor` 检查环境。", file=sys.stderr)
        return 1

    return result.returncode


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
    p_gw = sub.add_parser("gateway", help="管理 OpenClaw gateway")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
