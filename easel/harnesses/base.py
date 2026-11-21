"""Internal contract for agent harness integrations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol


class HarnessError(Exception):
    pass


class CodexWriterBusy(HarnessError):
    """The native thread could not be resumed before a turn was submitted."""


Emit = Callable[[str, str], None]
Ask = Callable[[list[dict]], Awaitable[dict[str, list[str]]]]
Bind = Callable[[str], None]


@dataclass(frozen=True)
class Descriptor:
    id: str
    label: str
    protocol: str
    install_hint: str


@dataclass(frozen=True)
class RunRequest:
    prompt: str
    cwd: Path
    env: dict[str, str]
    native_id: str = ""
    model: str = ""
    sandbox: str = "workspace-write"
    timeout: int = 1800
    command: tuple[str, ...] = ()
    session_key: str = ""
    codex_auto_approve: bool = False
    codex_effort: str = ""
    images: tuple[str, ...] = ()
    codex_never_ask: bool = False
    permission_scope: str = "native"
    permission_approval: str = "ask"
    bind_fork: Callable[[str, str], None] | None = None


class Adapter(Protocol):
    descriptor: Descriptor

    async def run(self, request: RunRequest, emit: Emit, ask: Ask, bind: Bind) -> None: ...
