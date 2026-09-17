"""OpenClaw runtime adapter."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from easel.openclaw_cmd import openclaw_base_cmd
from .base import (
    ActionResult, Diagnostic, QuestionAnswer, RunRequest, RunResult, RuntimeDescriptor,
    RuntimeEvent, RuntimeHealth, ServiceAction, SetupContext, SetupResult,
)
from .common import PROJECT_ROOT, clean_output, runtime_env

_SESSION_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def stable_session_id(session_key: str) -> str:
    return str(uuid.uuid5(_SESSION_NS, session_key))


def _heal_session(session_key: str) -> None:
    try:
        import sys
        scripts = PROJECT_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import session_heal
        path = Path.home() / ".openclaw-easel" / "agents" / "main" / "sessions" / f"{stable_session_id(session_key)}.jsonl"
        if path.is_file():
            session_heal.sanitize_history_file(path)
    except Exception:
        pass


class OpenClawRunHandle:
    def __init__(self, process: subprocess.Popen, raw_path: Path, expected_session_id: str,
                 session_key: str, questions: bool):
        self.process = process
        self.raw_path = raw_path
        self.expected_session_id = expected_session_id
        self.session_key = session_key
        self.questions = questions
        self._stdout: list[str] = []
        self._text: list[str] = []
        self._result: RunResult | None = None
        self._events_done = False
        self._q: queue.Queue = queue.Queue()
        self._info = {"stop_reason": None, "last_event": None, "thinking_chars": 0}
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._tail_raw, daemon=True).start()
        if questions:
            threading.Thread(target=self._poll_questions, daemon=True).start()

    def _read_stdout(self):
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._stdout.append(line)
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
            match = re.search(r"ended with stopReason=(\S+)", clean)
            if match:
                self._info["stop_reason"] = match.group(1)
            if "model-fetch] start" in clean:
                self._q.put(RuntimeEvent("activity", "🧠 正在思考…"))

    def _tail_raw(self):
        try:
            with self.raw_path.open(encoding="utf-8") as stream:
                while True:
                    line = stream.readline()
                    if not line:
                        if self.process.poll() is not None:
                            break
                        time.sleep(.04)
                        continue
                    try:
                        raw = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(raw, dict) or raw.get("sessionId") not in (None, self.expected_session_id):
                        continue
                    event, kind, delta = raw.get("event"), raw.get("evtType"), raw.get("delta") or ""
                    if event:
                        self._info["last_event"] = event
                    if event == "assistant_text_stream" and kind == "text_delta" and delta:
                        self._text.append(delta)
                        self._q.put(RuntimeEvent("text", delta))
                    elif event == "assistant_thinking_stream" and kind == "thinking_delta" and delta:
                        self._info["thinking_chars"] += len(delta)
                        self._q.put(RuntimeEvent("thinking", delta))
        finally:
            self._q.put(None)

    def _poll_questions(self):
        try:
            from easel.gateway_questions import GatewayClient
            client = GatewayClient()
            client.connect()
            seen = set()
            try:
                while self.process.poll() is None:
                    for item in client.list_questions(
                        session_key=f"agent:main:{self.session_key}", status="pending",
                    ):
                        qid = item.get("id")
                        if qid and qid not in seen:
                            seen.add(qid)
                            self._q.put(RuntimeEvent("question", data={
                                "id": qid, "questions": item.get("questions", []),
                                "expiresAtMs": item.get("expiresAtMs"),
                            }))
                    time.sleep(2)
            finally:
                client.close()
        except Exception:
            return

    def events(self):
        if self._events_done:
            return
        while True:
            try:
                event = self._q.get(timeout=.25)
            except queue.Empty:
                if self.process.poll() is not None:
                    continue
                continue
            if event is None:
                break
            yield event
        self._events_done = True

    def wait(self) -> RunResult:
        if self._result:
            return self._result
        if not self._events_done:
            for _ in self.events():
                pass
        rc = self.process.wait()
        text = "".join(self._text) or clean_output("".join(self._stdout))
        clean_end = self._info["last_event"] in (None, "assistant_message_end") and rc == 0
        self._result = RunResult(rc, text, clean_end, self._info["stop_reason"], dict(self._info))
        return self._result

    def cancel(self) -> None:
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
        try:
            self.raw_path.unlink()
        except OSError:
            pass

    def poll(self) -> int | None:
        return self.process.poll()


class OpenClawAdapter:
    descriptor = RuntimeDescriptor(
        "openclaw", "OpenClaw", "npm install -g openclaw@latest",
        frozenset({"interactive", "managed_service", "session_delete", "questions",
                   "thinking_events", "activity_events", "native_stream"}),
    )

    def setup(self, context: SetupContext) -> SetupResult:
        if shutil.which("openclaw") is None:
            result = subprocess.run(["npm", "install", "-g", "openclaw@latest", "--loglevel", "warn"],
                                    cwd=context.project_root, env=context.env or None)
            if result.returncode:
                return SetupResult(False, "OpenClaw 安装失败")
        try:
            openclaw_base_cmd()
        except FileNotFoundError as exc:
            return SetupResult(False, str(exc))
        return SetupResult(True, "OpenClaw 已就绪")

    def open_chat(self, prompt: str | None) -> int:
        from easel.timeouts import TIMEOUT_CHAT
        cmd = openclaw_base_cmd() + [
            "--profile", "easel", "tui", "--session", f"easel-{time.strftime('%m%d-%H%M%S')}",
            "--timeout-ms", str(TIMEOUT_CHAT * 1000),
        ]
        if prompt:
            cmd += ["--message", prompt]
        return subprocess.run(cmd, cwd=PROJECT_ROOT, env=runtime_env()).returncode

    def start(self, run: RunRequest) -> OpenClawRunHandle:
        _heal_session(run.session_key)
        fd, raw_name = tempfile.mkstemp(prefix="easel-stream-", suffix=".jsonl")
        os.close(fd)
        raw_path = Path(raw_name)
        sid = stable_session_id(run.session_key)
        cmd = openclaw_base_cmd() + [
            "--profile", "easel", "agent", "--agent", "main",
            "--session-key", f"agent:main:{run.session_key}", "--session-id", sid,
            "--thinking", run.thinking, "--timeout", str(run.timeout), "--message", run.prompt,
        ]
        env = dict(run.env)
        env["OPENCLAW_RAW_STREAM"] = "1"
        env["OPENCLAW_RAW_STREAM_PATH"] = str(raw_path)
        env["EASEL_ASKUSER_CARDS"] = "1" if "questions" in self.descriptor.capabilities else "0"
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=run.cwd, text=True, bufsize=1, env=env)
        return OpenClawRunHandle(
            proc, raw_path, sid, run.session_key, "questions" in self.descriptor.capabilities,
        )

    def health(self) -> RuntimeHealth:
        port = os.environ.get("EASEL_GATEWAY_PORT", "18789")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                return RuntimeHealth(response.status == 200)
        except (OSError, urllib.error.URLError) as exc:
            return RuntimeHealth(False, str(exc))

    def diagnose(self) -> list[Diagnostic]:
        command_ok = True
        try:
            command = openclaw_base_cmd()
        except FileNotFoundError:
            command_ok, command = False, []
        version = None
        if command:
            try:
                output = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=10)
                match = re.search(r"(\d+)\.(\d+)\.(\d+)", output.stdout)
                version = tuple(map(int, match.groups())) if match else None
            except (OSError, subprocess.TimeoutExpired):
                pass
        env = runtime_env()
        auth_ok = bool(
            env.get("ANTHROPIC_API_KEY") or env.get("OPENAI_API_KEY")
            or (env.get("EASEL_LLM_API_KEY") and env.get("EASEL_LLM_BASE_URL"))
            or (env.get("ANTHROPIC_AUTH_TOKEN") and env.get("ANTHROPIC_BASE_URL"))
            or (env.get("OPENAI_MAAS_API_KEY") and env.get("OPENAI_MAAS_ENDPOINT"))
        )
        skills = Path.home() / ".openclaw" / "workspace-easel" / "skills"
        return [
            Diagnostic("OpenClaw command", command_ok, self.descriptor.install_hint),
            Diagnostic("OpenClaw >= 2026.6.11", version is not None and version >= (2026, 6, 11),
                       "请升级：npm install -g openclaw@latest"),
            Diagnostic(".env (API Key)", auth_ok, "请配置模型 API key"),
            Diagnostic("Skills synced", skills.is_dir() and any(skills.iterdir()) if skills.is_dir() else False,
                       "重新运行 setup"),
            Diagnostic("OpenClaw gateway", self.health().ok, "运行 python -m easel gateway start"),
        ]

    def manage_service(self, action: ServiceAction) -> ActionResult:
        from .opencode import _run_service_script
        return _run_service_script("gateway", action)

    def delete_session(self, session_key: str, sessions_dir: Path | None = None) -> ActionResult:
        path = Path.home() / ".openclaw-easel" / "agents" / "main" / "sessions" / "sessions.json"
        if not path.is_file():
            return ActionResult(False, "sessions file not found", data={"deleted": False})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            full = session_key if session_key.startswith("agent:") else f"agent:main:{session_key}"
            for key in (full, session_key):
                if key in data:
                    del data[key]
                    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    return ActionResult(True, data={"deleted": True})
            return ActionResult(False, "session not found", data={"deleted": False})
        except Exception as exc:
            return ActionResult(False, str(exc), data={"deleted": False})

    def answer_question(self, request: QuestionAnswer) -> ActionResult:
        try:
            from easel.gateway_questions import GatewayClient
            client = GatewayClient()
            client.connect()
            try:
                result = client.resolve(request.question_id, request.answers, request.resolved_by)
                return ActionResult(True, data={"result": result})
            finally:
                client.close()
        except Exception as exc:
            return ActionResult(False, str(exc))

    def question_status(self, question_ids: list[str]) -> ActionResult:
        try:
            from easel.gateway_questions import GatewayClient, GatewayQuestionError
            client = GatewayClient()
            client.connect()
            try:
                out = {}
                for qid in question_ids:
                    try:
                        item = client.get_question(qid)
                        out[qid] = {"status": item.get("status") if item else "not_found"}
                    except GatewayQuestionError:
                        out[qid] = {"status": "not_found"}
                    except Exception:
                        out[qid] = {"status": "unknown"}
                return ActionResult(True, data={"questions": out})
            finally:
                client.close()
        except Exception as exc:
            return ActionResult(False, str(exc), data={"questions": {}})
