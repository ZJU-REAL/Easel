"""Hermes Agent integration through its ACP v1 stdio server."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlsplit

from .acp import ACPAdapter
from .base import Descriptor, HarnessError
from .commands import hermes_command


class HermesAdapter(ACPAdapter):
    descriptor = Descriptor(
        "hermes", "Hermes Agent", "ACP v1",
        "安装 Hermes Agent，并运行 `hermes pm install --extra acp`；创建并配置独立的 easel profile，详见 docs/agent-harnesses.md",
    )

    def launch_command(self) -> tuple[str, ...]:
        return hermes_command(profile="easel")

    @staticmethod
    def _profile_env(env: Mapping[str, str]) -> dict[str, str]:
        """Pass only runtime necessities; provider secrets remain in Hermes's profile."""
        allowed = {
            "PATH", "HOME", "USER", "LOGNAME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
            "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
            "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "PWD",
            "HERMES_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "EASEL_ROOT", "EASEL_AGENT_RUNTIME",
        }
        proxy_names = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
        safe = {}
        for key, value in env.items():
            normalized = key.upper()
            if normalized not in allowed:
                continue
            if normalized in proxy_names:
                try:
                    parsed = urlsplit(value)
                    if parsed.username is not None or parsed.password is not None:
                        continue
                except ValueError:
                    continue
            safe[key] = value
        return safe

    async def run(self, request, emit, ask, bind):
        # request.command is retained as a fake-process injection point for tests.
        command = request.command or self.launch_command()
        await super().run(replace(request, command=command, env=self._profile_env(request.env)),
                          emit, ask, bind)

    async def set_model(self, rpc, result, session_id: str, model: str) -> None:
        await rpc.call("session/set_model", {"sessionId": session_id, "modelId": model})


def available() -> bool:
    """Return whether ACP is installed without exposing CLI output or credentials."""
    command = list(hermes_command(profile="easel")) + ["--check"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=10,
            env=HermesAdapter._profile_env(os.environ),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
