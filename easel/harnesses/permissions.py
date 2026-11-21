"""Conservative automatic approval of ordinary Codex requests."""
from __future__ import annotations

import re
from pathlib import Path

from .base import RunRequest


def inside_workspace(value: str, root: Path) -> bool:
    try:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def can_auto_approve(method: str, params: dict, request: RunRequest) -> bool:
    if not request.codex_auto_approve:
        return False
    if params.get("additionalPermissions"):
        return False
    decisions = params.get("availableDecisions")
    if decisions is not None and (not isinstance(decisions, list) or "accept" not in decisions):
        return False
    if method == "item/fileChange/requestApproval":
        root = params.get("grantRoot")
        return (request.sandbox == "workspace-write" and isinstance(root, str)
                and bool(root.strip()) and inside_workspace(root, request.cwd))
    if method != "item/commandExecution/requestApproval" or params.get("kind", "command") != "command":
        return False
    cwd = params.get("cwd", str(request.cwd))
    command = params.get("command")
    if not isinstance(cwd, str) or not cwd.strip() or not inside_workspace(cwd, request.cwd):
        return False
    # Only literal, single-command reads with known options can be reviewed locally.
    # Shell wrappers, remote operations and repository-configured helpers use interactive approval.
    if not isinstance(command, str) or not re.fullmatch(r"[\w ./-]+", command):
        return False
    tokens = command.split()
    if not tokens:
        return False
    cmd, *args = tokens
    if cmd == "pwd":
        return not args
    if cmd == "ls":
        args = [arg for arg in args if not re.fullmatch(r"-[alh]+", arg)]
    elif cmd not in ("cat", "head", "tail", "wc", "stat"):
        return False
    elif not args:
        return False
    directory = request.cwd / cwd
    return all(not arg.startswith("-") and inside_workspace(str(directory / arg), request.cwd)
               for arg in args)
