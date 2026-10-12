"""Resolve native CLIs without a shell or Windows batch argument rewriting."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import HarnessError


def base_command(name: str) -> list[str]:
    executable = shutil.which(name)
    if not executable:
        raise HarnessError(f"{name} CLI 未安装或不在 PATH，请先安装并在终端登录")
    path = Path(executable)
    if path.suffix.lower() not in (".cmd", ".bat"):
        node = path.parent / ("node.exe" if os.name == "nt" else "node")
        if node.is_file() and os.access(node, os.X_OK):
            with path.open("rb") as entry:
                shebang = entry.readline(128).strip()
            if shebang.startswith(b"#!") and b"node" in shebang.split():
                return [str(node), str(path.resolve())]
        return [executable]
    adjacent_node = path.parent / "node.exe"
    node = str(adjacent_node) if adjacent_node.is_file() else shutil.which("node")
    package = path.parent / "node_modules"
    if name == "codex":
        script = package / "@openai" / "codex" / "bin" / "codex.js"
    else:
        native = package / "opencode-ai" / "bin" / "opencode.exe"
        if native.is_file():
            return [str(native)]
        script = package / "opencode-ai" / "bin" / "opencode"
    if node and script.is_file():
        return [node, str(script)]
    raise HarnessError(f"{name} 的 Windows npm 启动入口不存在，请重新安装 CLI")


def acp_command(cwd: Path) -> tuple[str, ...]:
    from .store import read_json
    config = read_json(cwd / "outputs" / "_harness" / "acp.json")
    command = config.get("command")
    if not isinstance(command, list) or not command or len(command) > 32:
        raise HarnessError("通用 ACP 尚未配置，请在 outputs/_harness/acp.json 设置 command 参数数组")
    if any(not isinstance(part, str) or not part or "\0" in part or "\n" in part for part in command):
        raise HarnessError("ACP command 必须是无控制字符的参数数组")
    executable = shutil.which(command[0])
    if not executable or Path(executable).suffix.lower() in (".bat", ".cmd"):
        raise HarnessError("ACP command 必须使用可执行程序，Windows 请使用 node + 脚本而非 .cmd")
    return (executable, *command[1:])
