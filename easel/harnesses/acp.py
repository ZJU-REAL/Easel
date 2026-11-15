"""ACP v1 adapter shared by OpenCode and locally configured future harnesses."""
from __future__ import annotations

import asyncio

from easel import __version__
from easel.timeouts import TIMEOUT_HARNESS_CANCEL

from .base import Descriptor, HarnessError, RunRequest
from .workspace import harness_instructions
from .commands import acp_command, base_command
from .rpc import connection


class ACPAdapter:
    descriptor = Descriptor("acp", "通用 ACP", "ACP v1", "配置本机 ACP CLI，详见 docs/agent-harnesses.md")

    async def run(self, request: RunRequest, emit, ask, bind):
        session_id = request.native_id
        active = False

        def notify(method, params):
            if not active or method != "session/update" or params.get("sessionId") != session_id:
                return
            update = params.get("update") or {}
            kind = update.get("sessionUpdate")
            if kind in ("agent_message_chunk", "agent_thought_chunk"):
                content = update.get("content") or {}
                if content.get("type") == "text":
                    emit("token" if kind == "agent_message_chunk" else "thinking", content.get("text", ""))
            elif kind in ("tool_call", "tool_call_update"):
                emit("activity", f"工具：{update.get('title') or update.get('toolCallId', '')} "
                     f"{update.get('status', '')}")

        async def respond(method, params):
            if method != "session/request_permission" or params.get("sessionId") != session_id:
                raise HarnessError("不支持的 ACP 客户端请求")
            options = params.get("options") or []
            allowed = [option for option in options if option.get("kind") in ("allow_once", "reject_once")]
            if not allowed:
                return {"outcome": {"outcome": "cancelled"}}
            labels = {f"{index + 1}. {option['name']}": option["optionId"]
                      for index, option in enumerate(allowed)}
            tool = params.get("toolCall") or {}
            answers = await ask([{"questionId": "permission", "header": "执行授权",
                                  "question": f"Agent 请求工具权限（仅本次）：{tool.get('title', '')}",
                                  "options": [{"label": label} for label in labels]}])
            selected = answers.get("permission") or []
            if len(selected) != 1 or selected[0] not in labels:
                return {"outcome": {"outcome": "cancelled"}}
            return {"outcome": {"outcome": "selected", "optionId": labels[selected[0]]}}

        command = list(request.command) if request.command else list(acp_command(request.cwd))
        async with connection(request, command, notify, respond, acp=True) as rpc:
            if rpc.initialized is None:
                rpc.initialized = await rpc.call("initialize", {
                    "protocolVersion": 1, "clientInfo": {"name": "easel", "version": __version__},
                    "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False},
                                           "terminal": False}})
            initialized = rpc.initialized
            if initialized.get("protocolVersion") != 1:
                raise HarnessError("Agent 不支持 ACP v1")
            capabilities = initialized.get("agentCapabilities") or {}
            params = {"cwd": str(request.cwd), "mcpServers": []}
            if session_id and rpc.native_id == session_id:
                result = rpc.session_info
            elif session_id:
                if not capabilities.get("loadSession"):
                    raise HarnessError("此 ACP Agent 不支持历史续接；请新建对话")
                result = await rpc.call("session/load", {**params, "sessionId": session_id})
                if result.get("sessionId", session_id) != session_id:
                    raise HarnessError("ACP 返回了不同的原生会话 ID，不会替换已有历史")
            else:
                result = await rpc.call("session/new", params)
                session_id = result.get("sessionId", "")
                if not session_id:
                    raise HarnessError("ACP Agent 未返回会话 ID")
            bind(session_id)
            rpc.native_id = session_id
            rpc.session_info = result
            if request.model:
                await self.set_model(rpc, result, session_id, request.model)
            active = True
            prompt = harness_instructions(request) + "\n\n" + request.prompt
            pending = asyncio.create_task(rpc.call("session/prompt", {
                "sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]},
                timeout=request.timeout))
            try:
                # Keep the original response alive: ACP v1 acknowledges cancel
                # by resolving session/prompt, not by replying to session/cancel.
                result = await asyncio.shield(pending)
                if result.get("stopReason") != "end_turn":
                    raise HarnessError(f"Agent 本轮未正常完成：{result.get('stopReason', 'unknown')}")
            except asyncio.CancelledError:
                async def cancel_and_wait():
                    await rpc.send({"method": "session/cancel", "params": {"sessionId": session_id}})
                    await asyncio.shield(pending)
                try:
                    await asyncio.wait_for(cancel_and_wait(), TIMEOUT_HARNESS_CANCEL)
                except (HarnessError, asyncio.TimeoutError):
                    pass
                raise
            finally:
                active = False
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def set_model(self, rpc, result, session_id: str, model: str) -> None:
        config_options = result.get("configOptions") or []
        model_option = next((option for option in config_options if option.get("category") == "model"), None)
        if model_option:
            await rpc.call("session/set_config_option", {
                "sessionId": session_id, "configId": model_option["id"], "value": model})
        elif result.get("models"):
            await rpc.call("session/set_model", {"sessionId": session_id, "modelId": model})
        else:
            raise HarnessError("此 ACP Agent 未提供模型切换能力，请清空覆盖值使用原生配置")


class OpenCodeAdapter(ACPAdapter):
    descriptor = Descriptor("opencode", "OpenCode", "ACP v1",
                            "npm install -g @opencode/cli；opencode auth login")

    async def run(self, request: RunRequest, emit, ask, bind):
        from dataclasses import replace
        command = request.command or tuple(base_command("opencode") + ["acp"])
        await super().run(replace(request, command=command), emit, ask, bind)
