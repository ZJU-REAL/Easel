"""OpenCode runtime adapter."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from base64 import b64encode
from pathlib import Path

from .base import (
    ActionResult, Diagnostic, QuestionAnswer, RunRequest, RunResult, RuntimeDescriptor,
    RuntimeEvent, RuntimeHealth, ServiceAction, SetupContext, SetupResult,
)
from .common import PROJECT_ROOT, clean_output, env_file_value, runtime_env


def base_cmd() -> list[str]:
    executable = shutil.which("opencode")
    if not executable:
        raise FileNotFoundError("OpenCode CLI 未找到；请安装：npm install -g opencode-ai@latest")
    if Path(executable).suffix.lower() in (".cmd", ".bat"):
        native = Path(executable).parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if native.is_file():
            return [str(native)]
    return [executable]


def server_url() -> str:
    import os
    port = os.environ.get("EASEL_OPENCODE_PORT") or env_file_value("EASEL_OPENCODE_PORT") or "18789"
    default = f"http://127.0.0.1:{port}"
    return (os.environ.get("EASEL_OPENCODE_URL") or env_file_value("EASEL_OPENCODE_URL") or default).rstrip("/")


def request(method: str, path: str, body: dict | None = None):
    import os
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "x-opencode-directory": str(PROJECT_ROOT)}
    password = os.environ.get("OPENCODE_SERVER_PASSWORD") or env_file_value("OPENCODE_SERVER_PASSWORD")
    if password:
        username = os.environ.get("OPENCODE_SERVER_USERNAME") or env_file_value("OPENCODE_SERVER_USERNAME") or "opencode"
        headers["Authorization"] = "Basic " + b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(f"{server_url()}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def session_path(session_key: str, sessions_dir: Path) -> Path:
    return sessions_dir / f"opencode-{hashlib.sha256(session_key.encode()).hexdigest()[:24]}.txt"


def session_id(session_key: str, sessions_dir: Path, *, create: bool = False) -> str | None:
    path = session_path(session_key, sessions_dir)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value or not create:
        return value or None
    session = request("POST", "/session", {"title": f"Easel {session_key}"})
    value = session.get("id") if isinstance(session, dict) else None
    if not value:
        raise RuntimeError("OpenCode server 未返回 session id")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


def parse_event(line: str) -> RuntimeEvent | None:
    try:
        event = json.loads(line)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(event, dict):
        return None
    part = event.get("part") if isinstance(event.get("part"), dict) else {}
    kind = event.get("type")
    if kind == "error":
        error = event.get("error") or {}
        data = error.get("data") if isinstance(error, dict) else None
        message = (data.get("message") if isinstance(data, dict) else None)
        message = message or (error.get("message") if isinstance(error, dict) else str(error))
        raise RuntimeError(message or "OpenCode 模型请求失败")
    if kind == "text" and part.get("text"):
        return RuntimeEvent("text", str(part["text"]), {"session_id": event.get("sessionID") or part.get("sessionID")})
    if kind == "reasoning" and part.get("text"):
        return RuntimeEvent("thinking", str(part["text"]))
    if kind == "tool_use":
        return RuntimeEvent("activity", "🔧 正在调用工具…")
    return None


class OpenCodeRunHandle:
    def __init__(self, process: subprocess.Popen, native_session_id: str | None):
        self.process = process
        self.native_session_id = native_session_id
        self._text: list[str] = []
        self._events_done = False
        self._error: str | None = None

    def events(self):
        if self._events_done:
            return
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                event = parse_event(line)
            except RuntimeError as exc:
                self._error = str(exc)
                continue
            if event:
                if event.type == "text":
                    self._text.append(event.text)
                yield event
        self._events_done = True

    def wait(self) -> RunResult:
        if not self._events_done:
            for _ in self.events():
                pass
        rc = self.process.wait()
        if self._error or (rc == 0 and not self._text):
            message = self._error or "OpenCode 已退出，但没有返回正文；请检查模型配置或重试。"
            return RunResult(rc or 1, "".join(self._text), clean_end=False,
                             stop_reason="runtime_error", diagnostics={"error": message})
        return RunResult(rc, "".join(self._text), clean_end=rc == 0)

    def cancel(self) -> None:
        if self.native_session_id:
            try:
                request("POST", f"/session/{self.native_session_id}/abort")
            except Exception:
                pass
        if self.process.poll() is None:
            self.process.terminate()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)

    def poll(self) -> int | None:
        return self.process.poll()


class OpenCodeAdapter:
    descriptor = RuntimeDescriptor(
        "opencode", "OpenCode", "npm install -g opencode-ai@latest",
        frozenset({"interactive", "managed_service", "session_delete", "native_abort",
                   "thinking_events", "activity_events", "native_stream"}),
    )

    def setup(self, context: SetupContext) -> SetupResult:
        if shutil.which("opencode") is None:
            result = subprocess.run(["npm", "install", "-g", "opencode-ai@latest", "--loglevel", "warn"],
                                    cwd=context.project_root, env=context.env or None)
            if result.returncode:
                return SetupResult(False, "OpenCode 安装失败")
        try:
            base_cmd()
        except FileNotFoundError as exc:
            return SetupResult(False, str(exc))
        return SetupResult(True, "OpenCode 已就绪")

    def open_chat(self, prompt: str | None) -> int:
        cmd = base_cmd() + [str(PROJECT_ROOT)]
        if prompt:
            cmd += ["--prompt", prompt]
        return subprocess.run(cmd, cwd=PROJECT_ROOT, env=runtime_env()).returncode

    def start(self, run: RunRequest) -> OpenCodeRunHandle:
        sid = session_id(run.session_key, run.sessions_dir, create=True) if run.sessions_dir else None
        cmd = base_cmd() + ["run", "--format", "json", "--auto", "--dir", str(PROJECT_ROOT)]
        if sid:
            cmd += ["--attach", server_url(), "--session", sid]
        cmd.append(run.prompt)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=run.cwd, text=True, bufsize=1, env=run.env)
        return OpenCodeRunHandle(proc, sid)

    def health(self) -> RuntimeHealth:
        try:
            result = request("GET", "/global/health")
            ok = isinstance(result, dict) and result.get("healthy") is True
            return RuntimeHealth(ok, "" if ok else "OpenCode server 未就绪")
        except (OSError, urllib.error.URLError) as exc:
            return RuntimeHealth(False, str(exc))

    def diagnose(self) -> list[Diagnostic]:
        command_ok = shutil.which("opencode") is not None
        configured = False
        if command_ok:
            try:
                result = subprocess.run(base_cmd() + ["providers", "list"], capture_output=True, text=True,
                                        timeout=30, cwd=PROJECT_ROOT, env=runtime_env())
                import re
                configured = result.returncode == 0 and re.search(r"\b[1-9]\d* credentials?\b", result.stdout) is not None
            except (OSError, subprocess.TimeoutExpired):
                pass
        skills_ok = (PROJECT_ROOT / "opencode.json").is_file() and (PROJECT_ROOT / "skills" / "openclaw").is_dir()
        return [
            Diagnostic("OpenCode command", command_ok, self.descriptor.install_hint),
            Diagnostic("OpenCode model/provider", configured, "运行 opencode 并使用 /connect 配置模型服务"),
            Diagnostic("Skills synced", skills_ok, "重新运行 setup"),
            Diagnostic("OpenCode service", self.health().ok, "运行 python -m easel gateway start"),
        ]

    def node_requirement(self) -> tuple[bool, str]:
        return False, "20.10"

    def is_local_gateway_base(self, url: str) -> bool:
        return False

    def provider_creds(self) -> dict[str, tuple[str, str]]:
        return {}

    def sync_chat_providers(self, provider_updates: dict[str, dict], keep_custom: set[str],
                            primary_ref: str) -> str:
        return "当前 runtime（OpenCode）不支持同步 chat 供应商"

    def config_snapshot(self) -> dict:
        return {"primary": "", "providers": {}}

    def manage_service(self, action: ServiceAction) -> ActionResult:
        return _run_service_script("opencode-gateway", action)

    def delete_session(self, session_key: str, sessions_dir: Path | None = None) -> ActionResult:
        if sessions_dir is None:
            return ActionResult(False, "sessions directory is required")
        sid = session_id(session_key, sessions_dir)
        if not sid:
            return ActionResult(False, "session not found", data={"deleted": False})
        try:
            request("DELETE", f"/session/{sid}")
            session_path(session_key, sessions_dir).unlink(missing_ok=True)
            return ActionResult(True, data={"deleted": True})
        except Exception as exc:
            return ActionResult(False, str(exc), data={"deleted": False})

    def answer_question(self, request: QuestionAnswer) -> ActionResult:
        return ActionResult.unsupported("questions")

    def question_status(self, question_ids: list[str]) -> ActionResult:
        return ActionResult.unsupported("questions")


def _run_service_script(name: str, action: ServiceAction) -> ActionResult:
    import os
    script = PROJECT_ROOT / "scripts" / (f"{name}.ps1" if os.name == "nt" else f"{name}.sh")
    cmd = (["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), action]
           if os.name == "nt" else ["bash", str(script), action])
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=runtime_env())
    return ActionResult(result.returncode == 0, code=result.returncode)
