"""Conservative automatic approval of ordinary Codex requests."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from .base import RunRequest


def _inside_workspace(value: str, root: Path) -> bool:
    try:
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def can_auto_approve(method: str, params: dict, request: RunRequest) -> bool:
    if not request.codex_auto_approve:
        return False
    if method == "item/fileChange/requestApproval":
        root = params.get("grantRoot")
        return (request.sandbox == "workspace-write" and isinstance(root, str)
                and bool(root) and _inside_workspace(root, request.cwd))
    if method != "item/commandExecution/requestApproval" or params.get("additionalPermissions"):
        return False
    decisions = params.get("availableDecisions")
    if decisions is not None and "accept" not in decisions:
        return False
    if params.get("kind", "command") != "command":
        return False
    command = params.get("command")
    if not isinstance(command, str) or not command.strip():
        return False
    cwd = params.get("cwd", str(request.cwd))
    if not isinstance(cwd, str) or not _inside_workspace(cwd, request.cwd):
        return False
    for depth in range(3):
        try:
            tokens = shlex.split(command)
        except ValueError:
            return False
        if len(tokens) == 3 and tokens[0] in (
                "bash", "sh", "zsh", "/bin/bash", "/bin/sh", "/bin/zsh",
                "/usr/bin/bash", "/usr/bin/sh", "/usr/bin/zsh") and tokens[1] in ("-c", "-lc"):
            command = tokens[2]
            continue
        break
    else:
        return False
    if not tokens or re.search(r"[;&|<>`$\n\r]", command):
        return False
    if tokens[0] in ("pwd", "ls", "cat", "head", "tail", "wc", "stat", "grep"):
        return not any(token.startswith("--") and "=" in token for token in tokens[1:])
    if tokens[0] == "rg":
        return not any(token in ("--pre", "--hostname-bin") or token.startswith(
            ("--pre=", "--hostname-bin=")) for token in tokens[1:])
    if tokens[0] == "git":
        if len(tokens) > 1 and tokens[1] == "fetch":
            return len(tokens) <= 4 and all(re.fullmatch(r"[\w./-]+", token)
                                           and not token.startswith("-") for token in tokens[2:])
        return len(tokens) > 1 and tokens[1] in ("status", "diff", "log", "show") and not any(
            token in ("--ext-diff", "--textconv", "--output", "--exec", "--upload-pack", "--receive-pack")
            or token.startswith(("--output=", "--exec=", "--upload-pack=", "--receive-pack="))
            for token in tokens[2:])
    return False
