"""Cross-platform Codex runtime with isolated sessions and cancellable jobs."""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":  # pragma: no cover - imported on Windows
    import msvcrt
else:  # pragma: no cover - imported on POSIX
    import fcntl

from easel.paths import (
    BUNDLED_SKILLS_DIR,
    OUTPUTS_DIR,
    PROFILES_DIR,
    RUNTIME_ROOT,
    runtime_path_entries,
)

PROJECT_ROOT = RUNTIME_ROOT
SESSION_FILE = OUTPUTS_DIR / "_sessions" / "codex-sessions.json"


def _codex_bin() -> str:
    """Resolve Codex without assuming a shell or a specific desktop install."""
    configured = os.environ.get("EASEL_CODEX_BIN", "").strip()
    if configured:
        return str(Path(configured).expanduser()) if any(sep in configured for sep in ("/", "\\")) else configured
    discovered = shutil.which("codex")
    if discovered:
        return discovered
    if sys.platform == "darwin":
        desktop = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
        if desktop.is_file():
            return str(desktop)
    return "codex"


def codex_command_prefix(platform: str | None = None) -> list[str]:
    """Return an argv prefix that also supports Windows .cmd/.bat shims."""
    executable = _codex_bin()
    if (platform or os.name) == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", executable]
    return [executable]


def codex_available() -> bool:
    executable = _codex_bin()
    return Path(executable).is_file() if any(sep in executable for sep in ("/", "\\")) else shutil.which(executable) is not None


@contextmanager
def _file_lock(name: str, cancel: threading.Event | None = None):
    folder = SESSION_FILE.parent / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / (hashlib.sha256(name.encode()).hexdigest() + ".lock")
    mode = "a+b" if os.name == "nt" else "a"
    with lock_path.open(mode) as handle:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
        while True:
            if cancel and cancel.is_set():
                raise InterruptedError("Codex request cancelled")
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError):
                time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _load_sessions() -> dict:
    if not SESSION_FILE.exists():
        return {}
    data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid Codex session map; refusing to discard history")
    return data


def _write_sessions(data: dict) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=SESSION_FILE.parent, delete=False, encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_name = handle.name
    os.replace(temp_name, SESSION_FILE)


def _save_session(key: str, thread_id: str) -> None:
    with _file_lock("session-map"):
        data = _load_sessions()
        data[key] = thread_id
        _write_sessions(data)


def forget_session(key: str) -> bool:
    """Forget the Seal binding only; never delete global Codex history."""
    with _file_lock("turn:" + key), _file_lock("session-map"):
        data = _load_sessions()
        found = data.pop(key, None) is not None
        if found:
            _write_sessions(data)
        return found


def build_runtime_prompt(content: str) -> str:
    return f"""你是 Seal 私人运营顾问 V3，源自开源项目 Easel。Codex 是唯一 Agent 运行时。
运行根目录是 {PROJECT_ROOT}。首先完整读取 {PROJECT_ROOT / 'AGENTS.md'} 中的项目工作规则。
按任务选择 {BUNDLED_SKILLS_DIR} 下的 CAPABILITY.md，完整读取能力规范并按需读取 references/scripts。
113 项能力均属于当前 Seal V3，不把它们安装为额外 Codex Skill，也不搜索其他 Seal/Easel 目录。
定时任务使用 Codex App 原生自动化；当前运行入口没有自动化工具时交回 Codex App。
产物写入 {OUTPUTS_DIR}；缺外部 Key 或登录态就明确说明，不伪造结果。不得擅自发布、评论、回复、发送消息或购买服务。
FFmpeg 与 FFprobe 是完整媒体链路的运行依赖；调用前按 Skill 规则检查，不用文本推理冒充转码、探测或编解码结果。
不要把当前运行时不具备的工具称为已执行，不把配置检测或 mock 测试称为真实平台验收。

{content}"""


def _popen_platform_kwargs(platform: str | None = None) -> dict:
    if (platform or os.name) == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
    return {"start_new_session": True}


def _terminate(proc: subprocess.Popen, platform: str | None = None) -> None:
    if proc.poll() is not None:
        return
    if (platform or os.name) == "nt":
        proc.terminate()
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    if (platform or os.name) == "nt":
        proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    proc.wait()


def run_codex(prompt: str, *, timeout: int = 7200, images=None, session_key=None, on_event=None, cancel=None):
    """Return rc, assistant text, diagnostics. Callback receives JSONL events."""
    cancel = cancel or threading.Event()
    try:
        with _file_lock("turn:" + (session_key or os.urandom(16).hex()), cancel):
            return _run(prompt, timeout, images, session_key, on_event, cancel)
    except InterruptedError as exc:
        return 130, "", str(exc)
    except (OSError, ValueError) as exc:
        return 127, "", str(exc)


def _run(prompt, timeout, images, session_key, on_event, cancel):
    thread_id = _load_sessions().get(session_key) if session_key else None
    cmd = [*codex_command_prefix(), "exec", "--sandbox", "workspace-write"]
    if thread_id:
        cmd += ["resume", thread_id]
    else:
        cmd += ["--cd", str(PROJECT_ROOT)]
    cmd += ["--skip-git-repo-check", "--json"]
    for path in images or []:
        cmd += ["--image", str(Path(path).expanduser().resolve())]
    cmd.append("-")

    env = os.environ.copy()
    env.pop("_", None)
    if os.name != "nt":
        env["LANG"] = "en_US.UTF-8"
        env["LC_ALL"] = "en_US.UTF-8"
        env["LC_CTYPE"] = "en_US.UTF-8"
    env.setdefault("EASEL_ROOT", str(PROJECT_ROOT))
    env["PATH"] = os.pathsep.join((*runtime_path_entries(), env.get("PATH", "")))
    env["PYTHONPATH"] = os.pathsep.join(
        (str(PROJECT_ROOT / "skills/shared/scripts"), env.get("PYTHONPATH", ""))
    )

    events: queue.Queue = queue.Queue()
    parts: list[str] = []
    errors: list[str] = []
    override_rc = None
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        proc = subprocess.Popen(
            cmd, cwd=PROJECT_ROOT, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=stderr, text=True,
            **_popen_platform_kwargs(),
        )

        def read_events() -> None:
            try:
                for line in proc.stdout:
                    events.put(line)
            finally:
                events.put(None)

        reader = threading.Thread(target=read_events, daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout
        try:
            proc.stdin.write(build_runtime_prompt(prompt))
            proc.stdin.close()
            while True:
                if cancel.is_set() or time.monotonic() >= deadline:
                    override_rc = 130 if cancel.is_set() else 124
                    errors.append("Codex request cancelled" if cancel.is_set() else f"Codex request timed out after {timeout}s")
                    _terminate(proc)
                    break
                try:
                    line = events.get(timeout=0.1)
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "thread.started" and session_key and event.get("thread_id"):
                    _save_session(session_key, event["thread_id"])
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    parts.append(item.get("text", ""))
                if event.get("type") in ("error", "turn.failed"):
                    error = event.get("error") or event
                    errors.append(str(error.get("message", "Codex turn failed")))
                if on_event:
                    on_event(event)
            try:
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                override_rc = 124
                _terminate(proc)
        finally:
            if proc.poll() is None:
                _terminate(proc)
            reader.join(timeout=3)
            proc.stdout.close()
            if not proc.stdin.closed:
                proc.stdin.close()
        stderr.seek(0)
        diagnostics = stderr.read()
    rc = override_rc if override_rc is not None else proc.returncode
    if errors and rc == 0:
        rc = 1
    return rc, "\n".join(parts), "\n".join(errors + ([diagnostics] if diagnostics else []))


def build_skill_prompt(skill_name: str, content: str, profile: str | None = None) -> str:
    root = BUNDLED_SKILLS_DIR.resolve()
    target = (root / skill_name / "CAPABILITY.md").resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError(f"Unknown Seal skill: {skill_name}")
    if profile:
        profile_dir = (PROFILES_DIR / profile).resolve()
        profiles_root = PROFILES_DIR.resolve()
        if not profile_dir.is_relative_to(profiles_root) or not profile_dir.is_dir():
            raise ValueError("Unknown Seal profile")
    hint = f"先读取画像 profiles/{profile}/ 下的文件。\n" if profile else ""
    return (
        f"{hint}完整读取并执行 {target}。该路径是 Seal V3 内置能力库；"
        "不要搜索或修改其他 Seal/Easel 版本。\n"
        f"用户任务：\n{content}"
    )
