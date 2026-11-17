"""Codex native app-server adapter; credentials remain in Codex."""
from __future__ import annotations

import asyncio
import re

from easel import __version__

from .base import Descriptor, HarnessError, RunRequest
from .commands import base_command
from .permissions import can_auto_approve
from .rpc import connection
from .workspace import harness_instructions
from .codex_diagnostics import failure
from .store import CODEX_EFFORTS


class CodexAdapter:
    descriptor = Descriptor("codex", "Codex", "app-server", "npm install -g @openai/codex；codex login")

    async def run(self, request: RunRequest, emit, ask, bind):
        try:
            return await self._run(request, emit, ask, bind)
        except HarnessError as error:
            detail = failure(str(error))
            if detail["code"] != "unknown" or str(error).startswith("Agent 协议错误："):
                raise HarnessError(detail["message"]) from error
            raise

    async def _run(self, request: RunRequest, emit, ask, bind):
        if request.sandbox not in ("read-only", "workspace-write"):
            raise HarnessError("Codex 只允许只读或工作区写入权限")
        if request.codex_effort not in CODEX_EFFORTS:
            raise HarnessError("Codex 推理强度设置无效")
        completion = asyncio.get_running_loop().create_future()
        thread_id = request.native_id
        turn_id = ""
        streamed: set[str] = set()
        usage = {}

        def safe_detail(value):
            text = str(value)
            for key, secret in request.env.items():
                if len(secret) >= 4 and any(marker in key.upper() for marker in (
                        "KEY", "TOKEN", "SECRET", "PASSWORD", "COOKIE")):
                    text = text.replace(secret, "***")
            return re.sub(r"sk-[A-Za-z0-9_-]{12,}|Bearer\s+\S+", "***", text, flags=re.I)

        def activity(item, completed=False):
            kind = item.get("type", "tool")
            status = "完成" if completed else "开始"
            if kind == "commandExecution":
                command = safe_detail(item.get("command") or "命令")[:600]
                result = f" · 退出码 {item['exitCode']}" if completed and item.get("exitCode") is not None else ""
                emit("activity", f"{status}执行：{command}{result}")
            elif kind == "fileChange":
                paths = [safe_detail(change.get("path", "")) for change in (item.get("changes") or [])[:12]
                         if isinstance(change, dict)]
                emit("activity", f"{status}修改文件：{'、'.join(paths)[:1000]}（{item.get('status', '')}）")
            elif kind not in ("agentMessage", "reasoning", "userMessage"):
                emit("activity", f"{status}工具：{kind}")

        def notify(method, params):
            def _thread_scoped() -> bool:
                # 无 threadId/turnId 的是全局事件（连接级/认证失败常在 turn/start 前发出）；
                # 带 id 的必须匹配本会话。放行判定独立于 turn_id 是否已闩锁。
                if params.get("threadId") is None and params.get("turnId") is None:
                    return True
                return bool(turn_id) and params.get("threadId") == thread_id \
                    and params.get("turnId", turn_id) == turn_id

            # 致命 error 事件常不带 thread 上下文（如 turn/start 前的认证失败）；
            # 放在 id 过滤之前处理，否则只能等外层 wait_for 超时（30min+）才报错。
            if method == "error":
                if params.get("willRetry", False) or not _thread_scoped():
                    return
                if not completion.done():
                    completion.set_exception(HarnessError(failure(params.get("error"))["message"]))
                return

            if not turn_id or params.get("threadId") != thread_id or params.get("turnId", turn_id) != turn_id:
                return
            if method == "item/agentMessage/delta":
                streamed.add(params.get("itemId", ""))
                emit("token", params.get("delta", ""))
            elif method in ("item/reasoning/summaryTextDelta", "item/reasoning/textDelta"):
                emit("thinking", params.get("delta", ""))
            elif method == "item/started":
                item = params.get("item") or {}
                activity(item)
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("id") not in streamed:
                    emit("token", item.get("text", ""))
                activity(item, completed=True)
            elif method == "thread/tokenUsage/updated":
                current = params.get("tokenUsage") or {}
                if isinstance(current, dict):
                    usage.update(current)
            elif method == "turn/plan/updated":
                for step in (params.get("plan") or [])[:12]:
                    if isinstance(step, dict):
                        label = {"pending": "待执行", "inProgress": "进行中", "completed": "已完成"}.get(step.get("status"), "计划")
                        emit("activity", f"{label}：{safe_detail(step.get('step', ''))[:500]}")
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn.get("id") != turn_id or completion.done():
                    return
                if turn.get("status") == "completed":
                    total = usage.get("total") or {}
                    if not isinstance(total, dict):
                        total = {}
                    counts = {key: value for key, value in total.items()
                              if isinstance(value, int) and not isinstance(value, bool) and value >= 0}
                    if "totalTokens" in counts:
                        emit("activity", f"会话累计用量：{counts['totalTokens']} tokens"
                             f"（输入 {counts.get('inputTokens', 0)}，输出 {counts.get('outputTokens', 0)}，"
                             f"缓存输入 {counts.get('cachedInputTokens', 0)}）")
                    completion.set_result(None)
                else:
                    error = turn.get("error") or {}
                    completion.set_exception(HarnessError(
                        failure(error)["message"] if error else f"Codex 本轮未完成：{turn.get('status')}"))

        async def respond(method, params):
            if params.get("threadId") != thread_id or (
                    turn_id and params.get("turnId", turn_id) != turn_id):
                raise HarnessError("不属于当前会话的请求")
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                if can_auto_approve(method, params, request):
                    emit("activity", "Codex：已自动通过普通操作授权")
                    return {"decision": "accept"}
                detail = params.get("command") or params.get("reason") or params.get("itemId", "")
                answers = await ask([{
                    "questionId": "permission", "header": "执行授权",
                    "question": f"Codex 请求额外权限（仅本次）：{safe_detail(detail)[:3000]}" + (
                        "\n此操作不属于可自动批准的普通操作，请确认风险。" if request.codex_auto_approve else ""),
                    "options": [{"label": "允许本次"}, {"label": "拒绝"}],
                }])
                return {"decision": "accept" if answers.get("permission") == ["允许本次"] else "decline"}
            if method == "item/tool/requestUserInput":
                questions = params.get("questions") or []
                if any(question.get("isSecret") for question in questions):
                    raise HarnessError("请在终端完成敏感凭证输入")
                normalized = [{**question, "questionId": question["id"]} for question in questions]
                answers = await ask(normalized)
                return {"answers": {key: {"answers": value} for key, value in answers.items()}}
            raise HarnessError("不支持的 Codex 客户端请求")

        command = list(request.command) if request.command else base_command("codex") + ["app-server"]
        async with connection(request, command, notify, respond) as rpc:
            if rpc.initialized is None:
                rpc.initialized = await rpc.call("initialize", {
                    "clientInfo": {"name": "easel", "version": __version__},
                    "capabilities": {"experimentalApi": True}})
                await rpc.send({"method": "initialized"})
            options = {"cwd": str(request.cwd), "approvalPolicy": "on-request",
                       "sandbox": request.sandbox,
                       "developerInstructions": harness_instructions(request)}
            if request.model:
                options["model"] = request.model
            if thread_id and rpc.native_id == thread_id:
                result = {"thread": {"id": thread_id}}
            elif thread_id:
                result = await rpc.call("thread/resume", {**options, "threadId": thread_id})
            else:
                result = await rpc.call("thread/start", options)
            resumed_id = (result.get("thread") or {}).get("id", "")
            if request.native_id and resumed_id != request.native_id:
                raise HarnessError("Codex 返回了不同的原生会话 ID，不会替换已有历史")
            thread_id = resumed_id
            if not thread_id:
                raise HarnessError("Codex 未返回原生会话 ID")
            bind(thread_id)
            rpc.native_id = thread_id
            policy = {"type": "readOnly"} if request.sandbox == "read-only" else {
                "type": "workspaceWrite", "writableRoots": [str(request.cwd)],
                "networkAccess": False}
            params = {"threadId": thread_id, "input": [{"type": "text", "text": request.prompt}],
                      "approvalPolicy": "on-request", "sandboxPolicy": policy}
            params["input"].extend({"type": "localImage", "path": path} for path in request.images)
            if request.codex_effort:
                params["effort"] = request.codex_effort
            if request.model:
                params["model"] = request.model
            early: list[tuple[str, dict]] = []
            original_notify = rpc.notify
            rpc.notify = lambda method, data: early.append((method, data))
            result = await rpc.call("turn/start", params)
            turn_id = (result.get("turn") or {}).get("id", "")
            if not turn_id:
                raise HarnessError("Codex 未返回本轮 ID")
            rpc.notify = original_notify
            for method, data in early:
                notify(method, data)
            try:
                await rpc.wait_notification(completion)
            except asyncio.CancelledError:
                try:
                    await rpc.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout=2)
                except HarnessError:
                    pass
                raise
            finally:
                if completion.done() and not completion.cancelled():
                    completion.exception()
