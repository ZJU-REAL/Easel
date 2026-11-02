"""Resolve native CLIs without a shell or Windows batch argument rewriting."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .base import HarnessError


def _windows_opencode_entry(launcher: Path) -> Path:
    failure = HarnessError("opencode 的 Windows npm 启动入口无法识别，请用 "
                           "npm install -g @opencode/cli 重新安装 CLI 并检查 PATH")
    try:
        with launcher.open("rb") as stream:
            content = stream.read(64 * 1024 + 1)
    except OSError:
        raise failure from None
    if len(content) > 64 * 1024:
        raise failure
    pattern = re.compile(
        r'(?:endLocal\s*&\s*goto\s+#_undefined_#\s+2>NUL\s*\|\|\s*'
        r'title\s+%COMSPEC%\s*&\s*)?@?(?:"%_prog%"\s+)?'
        r'"%(?:dp0%|~dp0)[\\/]*node_modules[\\/]+'
        r'(?P<package>@opencode[\\/]+cli|opencode-ai)[\\/]+bin[\\/]+'
        r'(?P<entry>opencode(?:\.exe)?)"\s+%\*\s*$', re.IGNORECASE)
    targets = set()
    for line in content.decode("utf-8-sig", errors="replace").splitlines():
        match = pattern.fullmatch(line.strip())
        if match:
            package = re.sub(r"[\\/]+", "/", match["package"].lower())
            targets.add(launcher.parent / "node_modules" / package / "bin" / match["entry"].lower())
    if len(targets) != 1:
        raise failure
    return targets.pop()


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
        script = _windows_opencode_entry(path)
        if script.suffix.lower() == ".exe":
            if script.is_file():
                return [str(script)]
            raise HarnessError("opencode 的 Windows npm 启动入口不存在，请用 "
                               "npm install -g @opencode/cli 重新安装 CLI 并检查 PATH")
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


def hermes_command(*, profile: str | None = None) -> tuple[str, ...]:
    """Resolve Hermes to a direct executable; never invoke a shell shim."""
    executable = shutil.which("hermes")
    if not executable:
        raise HarnessError("Hermes CLI 未安装或不在 PATH；请安装 Hermes Agent 并检查运行 Web 的账户 PATH")
    path = Path(executable)
    if path.suffix.lower() in (".cmd", ".bat"):
        raise HarnessError("无法安全启动 Hermes 的 Windows .cmd/.bat 入口；请安装可执行的 Hermes CLI，或配置可直接运行的 hermes.exe，再重启 Easel")
    command = [str(path.resolve())]
    if profile:
        command += ["--profile", profile]
    command.append("acp")
    return tuple(command)
