"""Atomic local harness settings and durable session ownership."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .base import HarnessError
from easel import access

IDS = ("api", "openclaw", "opencode", "codex", "acp", "hermes")
CODEX_EFFORTS = ("", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (OSError, ValueError) as error:
        raise HarnessError("Agent 设置或会话记录损坏，请检查本地文件；不会自动新建会话丢失历史") from error


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def settings(outputs: Path, env: dict[str, str]) -> dict:
    data = read_json(outputs / "_harness" / "config.json")
    state_dir = Path(env.get("EASEL_OPENCLAW_STATE_DIR") or Path.home() / ".openclaw-easel")
    legacy = "EASEL_CHAT_TRANSPORT" in env or (state_dir / "openclaw.json").is_file()
    default = "openclaw" if legacy else "api"
    runtime = env.get("EASEL_AGENT_RUNTIME", data.get("runtime", default))
    if not isinstance(runtime, str) or runtime.strip().lower() not in IDS:
        raise HarnessError("未知 Agent 底座，请在设置中选择已支持的底座")
    runtime = runtime.strip().lower()
    if runtime == "openclaw" and env.get("EASEL_CHAT_TRANSPORT", "").strip().lower() == "api":
        runtime = "api"
    models = data.get("models", {})
    if not isinstance(models, dict) or any(
            key not in IDS or not isinstance(value, str) or len(value) > 240
            or any(ord(character) < 32 for character in value)
            for key, value in models.items()):
        raise HarnessError("Agent 模型设置格式无效")
    sandbox = data.get("sandbox", "workspace-write")
    if sandbox not in ("read-only", "workspace-write"):
        raise HarnessError("Agent 权限设置无效，只允许只读或工作区写入")
    auto_approve = data.get("codex_auto_approve", False)
    if not isinstance(auto_approve, bool):
        raise HarnessError("Codex 自动授权设置必须为开关")
    full = data.get("codex_full_access", False)
    never_ask = data.get("codex_never_ask", False)
    if not isinstance(full, bool) or not isinstance(never_ask, bool):
        raise HarnessError("Codex 访问权限配置无效")
    effort = data.get("codex_effort", "")
    if effort not in CODEX_EFFORTS:
        raise HarnessError("Codex 推理强度设置无效")
    overrides = data.get("agent_access", {})
    if not isinstance(overrides, dict) or any(
            not isinstance(value, dict) or not access.valid(target, value.get("scope"), value.get("approval"))
            for target, value in overrides.items()):
        raise HarnessError("执行引擎权限设置无效")
    return {"runtime": runtime, "models": models, "sandbox": sandbox, "agent_access": overrides,
            "codex_full_access": full, "codex_never_ask": never_ask,
            "codex_auto_approve": auto_approve, "codex_effort": effort}


def binding_path(sessions: Path, key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return sessions / "harness" / f"{digest}.json"


def binding(sessions: Path, key: str) -> dict:
    record = read_json(binding_path(sessions, key))
    if record and (record.get("runtime") not in IDS
                   or not isinstance(record.get("native_id"), str)):
        raise HarnessError("Agent 会话记录格式无效，不会自动重置历史")
    return record


def bind(sessions: Path, key: str, runtime: str, native_id: str = "") -> None:
    if runtime not in IDS or not isinstance(native_id, str):
        raise HarnessError("Agent 会话绑定无效")
    current = binding(sessions, key)
    if current and current.get("runtime") != runtime:
        raise HarnessError("此会话属于其他 Agent 底座，请新建对话")
    if current.get("native_id") and current["native_id"] != native_id:
        raise HarnessError("Agent 返回了不同的原生会话 ID，不会替换已有历史")
    write_json(binding_path(sessions, key), {**current, "runtime": runtime, "native_id": native_id})


def bind_codex_fork(sessions: Path, key: str, parent: str, child: str) -> None:
    # The caller holds the web session's cross-process lock.
    current = binding(sessions, key)
    if (current.get("runtime") != "codex" or current.get("native_id") != parent
            or not parent or not child or parent == child):
        raise HarnessError("画板会话绑定已变更，请刷新后继续。")
    write_json(binding_path(sessions, key), {
        **current, "native_id": child, "forked_from": parent,
        "original_native_id": current.get("original_native_id", parent),
    })
