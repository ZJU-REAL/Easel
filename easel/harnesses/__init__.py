"""Harness registry; OpenClaw retains its existing gateway/session implementation."""
from __future__ import annotations

import asyncio
from pathlib import Path

from .acp import ACPAdapter, OpenCodeAdapter
from .base import Descriptor, HarnessError, RunRequest
from .codex import CodexAdapter
from .commands import acp_command, base_command
from .store import settings

OPENCLAW = Descriptor("openclaw", "OpenClaw", "gateway / CLI", "运行原有安装流程")
CHAT_ONLY = Descriptor("api", "仅聊天模式", "模型 API 直连", "在模型配置中填写地址、模型与 Key")
ADAPTERS = {adapter.descriptor.id: adapter for adapter in (OpenCodeAdapter(), CodexAdapter(), ACPAdapter())}


def adapter(runtime: str):
    if runtime not in ADAPTERS:
        raise HarnessError("此 Agent 使用原有 OpenClaw 通道，或未注册")
    return ADAPTERS[runtime]


def describe(runtime: str) -> dict:
    descriptor = CHAT_ONLY if runtime == "api" else OPENCLAW if runtime == "openclaw" else adapter(runtime).descriptor
    from dataclasses import asdict
    result = asdict(descriptor)
    try:
        if runtime == "api":
            pass
        elif runtime == "openclaw":
            from easel.openclaw_cmd import openclaw_base_cmd
            openclaw_base_cmd.cache_clear()
            openclaw_base_cmd()
        elif runtime == "acp":
            acp_command(Path(__file__).resolve().parents[2])
        else:
            base_command(runtime)
        result["installed"] = True
    except (HarnessError, OSError):
        result["installed"] = False
    return result


async def console_turn(prompt: str, root: Path, env: dict, native_id="", *,
                       timeout=1800, interactive=True, on_bind=None) -> tuple[str, str]:
    config = settings(root / "outputs", env)
    runtime = config["runtime"]
    full_text = []
    identifiers = [native_id]

    def emit(kind, text):
        if kind == "token":
            full_text.append(text)
            print(text, end="", flush=True)
        elif kind == "activity":
            print(f"\n{text}", flush=True)

    async def ask(questions):
        if not interactive:
            raise HarnessError("请在交互式对话中确认工具权限")
        answers = {}
        for question in questions:
            print("\n" + question["question"])
            for option in question.get("options") or []:
                print("  " + option["label"])
            answer = await asyncio.to_thread(input, "回答（授权只允许选择列出的选项）：")
            answers[question["questionId"]] = [answer]
        return answers

    request = RunRequest(prompt, root, {**env, "EASEL_AGENT_RUNTIME": runtime}, native_id,
                         config["models"].get(runtime, ""), config["sandbox"], timeout,
                         codex_auto_approve=config["codex_auto_approve"])

    def bind(value):
        identifiers[0] = value
        if on_bind:
            on_bind(value)

    await asyncio.wait_for(adapter(runtime).run(request, emit, ask,
                                                bind), request.timeout)
    return "".join(full_text), identifiers[0]
