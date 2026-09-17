"""Stable seam between Easel and an agent runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Protocol

Capability = Literal[
    "interactive", "managed_service", "session_delete", "native_abort",
    "questions", "thinking_events", "activity_events", "native_stream",
]
EventType = Literal["text", "thinking", "activity", "question"]
ServiceAction = Literal["start", "stop", "restart", "status", "logs"]


@dataclass(frozen=True)
class RuntimeDescriptor:
    id: str
    label: str
    install_hint: str
    capabilities: frozenset[Capability]

    def as_dict(self) -> dict:
        return {**asdict(self), "capabilities": sorted(self.capabilities)}


@dataclass(frozen=True)
class SetupContext:
    project_root: Path
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SetupResult:
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class RunRequest:
    prompt: str
    session_key: str
    timeout: int
    cwd: Path
    env: dict[str, str]
    sessions_dir: Path | None = None
    thinking: str = "low"
    stream: bool = True


@dataclass(frozen=True)
class RuntimeEvent:
    type: EventType
    text: str = ""
    data: dict | None = None


@dataclass(frozen=True)
class RunResult:
    returncode: int
    text: str = ""
    clean_end: bool = True
    stop_reason: str | None = None
    diagnostics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeHealth:
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class Diagnostic:
    label: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    reason: str = ""
    code: int = 0
    data: dict = field(default_factory=dict)

    @classmethod
    def unsupported(cls, operation: str) -> "ActionResult":
        return cls(False, f"当前 runtime 不支持 {operation}", 2)


@dataclass(frozen=True)
class QuestionAnswer:
    question_id: str
    answers: dict
    resolved_by: str | None = None


class RunHandle(Protocol):
    def events(self) -> Iterable[RuntimeEvent]: ...
    def wait(self) -> RunResult: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...
    def poll(self) -> int | None: ...


class RuntimeAdapter(Protocol):
    descriptor: RuntimeDescriptor

    def setup(self, context: SetupContext) -> SetupResult: ...
    def open_chat(self, prompt: str | None) -> int: ...
    def start(self, request: RunRequest) -> RunHandle: ...
    def health(self) -> RuntimeHealth: ...
    def diagnose(self) -> list[Diagnostic]: ...
    def manage_service(self, action: ServiceAction) -> ActionResult: ...
    def delete_session(self, session_key: str, sessions_dir: Path | None = None) -> ActionResult: ...
    def answer_question(self, request: QuestionAnswer) -> ActionResult: ...
    def question_status(self, question_ids: list[str]) -> ActionResult: ...
