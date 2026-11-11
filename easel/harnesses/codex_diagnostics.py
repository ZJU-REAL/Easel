"""Read native account state and probe inference without copying credentials."""
from __future__ import annotations

import asyncio
import json
import time

from easel import __version__
from easel.timeouts import TIMEOUT_CODEX_DIAGNOSTICS, TIMEOUT_CODEX_PROBE

from .base import HarnessError, RunRequest
from .commands import base_command
from .rpc import RPC


def failure(value) -> dict[str, str]:
    # Never echo provider responses: they may contain credentials or account data.
    text = json.dumps(value, ensure_ascii=False, default=str).lower()
    categories = [
        ("quota", ("insufficient_quota", "usage limit", "quota exceeded", "usage_limit", "usagelimit", "额度已用尽"),
         "Codex 额度已用尽，请查看额度重置时间或原生账号套餐。"),
        ("auth", ("unauthorized", "401", "authentication", "not logged", "token expired", "refresh token", "refresh_token", "invalid_api_key", "登录失效"),
         "Codex 登录失效或未登录，请在运行 Easel 的终端执行 codex login，再刷新状态。"),
        ("rate_limit", ("429", "rate limit", "ratelimit", "rate_limit", "请求受到限流"),
         "Codex 请求受到限流，请稍后重试并查看额度窗口。"),
        ("model", ("modelnotfound", "model_not_found", "unsupported model", "invalid model", "model does not exist", "not supported", "reasoning effort", "模型或推理强度不可用"),
         "Codex 模型或推理强度不可用，请拉取原生模型列表，重新选择后测试连接。"),
        ("context", ("contextwindow", "context_length", "context window", "too many tokens", "上下文超出限制"),
         "Codex 上下文超出限制，请减少附件或新建对话。"),
        ("network", ("connection refused", "tls", "dns", "network", "connection reset", "failed to connect", "stream disconnected", "网络连接失败"),
         "Codex 网络连接失败，请检查运行 Easel 的终端代理与网络后重试。"),
        ("timeout", ("timeout", "timed out", "超时"),
         "Codex 请求超时，请检查网络后重试。"),
    ]
    for code, markers, message in categories:
        if any(marker in text for marker in markers):
            return {"code": code, "message": message}
    return {"code": "unknown", "message": "Codex 执行失败，请检查原生 CLI 登录、模型配置与版本，再测试连接。"}


async def initialize(rpc):
    await rpc.call("initialize", {
        "clientInfo": {"name": "easel", "version": __version__},
        "capabilities": {"experimentalApi": True}})
    await rpc.send({"method": "initialized"})


async def reject(method, params):
    raise HarnessError("诊断期间不接受工具执行或授权请求")


def rate_windows(result: dict) -> list[dict]:
    buckets = result.get("rateLimitsByLimitId") or {"codex": result.get("rateLimits")}
    rows = []
    if not isinstance(buckets, dict):
        return rows
    for bucket, data in list(buckets.items())[:12]:
        if not isinstance(data, dict):
            continue
        for window in ("primary", "secondary"):
            values = data.get(window)
            if not isinstance(values, dict):
                continue
            safe = {key: value for key in ("usedPercent", "windowDurationMins", "resetsAt")
                    if isinstance(value := values.get(key), (int, float))
                    and not isinstance(value, bool) and 0 <= value < 10**12}
            if "usedPercent" in safe:
                rows.append({"window": window, **safe})
    return rows


async def account_status(request: RunRequest) -> dict:
    async def read():
        command = list(request.command) or base_command("codex") + ["app-server"]
        async with RPC(request, command, lambda *_: None, reject) as rpc:
            await initialize(rpc)
            result = await rpc.call("account/read", {"refreshToken": False})
            account = result.get("account") or {}
            authenticated = bool(account.get("type"))
            state = "authenticated" if authenticated else (
                "external" if result.get("requiresOpenaiAuth") is False else "unauthenticated")
            kind = account.get("type")
            response = {"state": state, "authType": kind if kind in (
                "chatgpt", "apiKey", "chatgptAuthTokens", "bedrock") else "unknown", "windows": []}
            if authenticated:
                try:
                    response["windows"] = rate_windows(await rpc.call("account/rateLimits/read", {}, timeout=10))
                except HarnessError:
                    response["quotaNote"] = "当前账号或 CLI 未提供额度窗口；不影响连接测试。"
            return response
    try:
        return await asyncio.wait_for(read(), TIMEOUT_CODEX_DIAGNOSTICS)
    except (HarnessError, OSError, asyncio.TimeoutError) as error:
        return {"state": "unknown", "windows": [], "error": failure(str(error) or "timeout")}


async def probe(request: RunRequest) -> dict:
    """One ephemeral, read-only turn; no Easel session or settings are created."""
    started = time.monotonic()
    done = asyncio.get_running_loop().create_future()
    thread_id = ""
    turn_id = ""
    early = []
    answered = False

    def notify(method, params):
        nonlocal answered
        if not turn_id:
            early.append((method, params))
            return
        if method == "error" and params.get("threadId") is None and params.get("turnId") is None:
            if not params.get("willRetry") and not done.done():
                done.set_result({"status": "failed", "error": params.get("error")})
            return
        if params.get("threadId") != thread_id or params.get("turnId", turn_id) != turn_id:
            return
        if method == "item/agentMessage/delta" and params.get("delta"):
            answered = True
        if method == "item/completed" and (params.get("item") or {}).get("type") == "agentMessage":
            answered = answered or bool(params["item"].get("text"))
        if method == "error" and not params.get("willRetry") and not done.done():
            done.set_result({"status": "failed", "error": params.get("error")})
        if method == "turn/completed" and not done.done():
            turn = params.get("turn") or {}
            if turn.get("id") == turn_id:
                done.set_result(turn)

    async def run():
        nonlocal thread_id, turn_id
        command = list(request.command) or base_command("codex") + ["app-server"]
        async with RPC(request, command, notify, reject) as rpc:
            await initialize(rpc)
            options = {"cwd": str(request.cwd), "ephemeral": True, "sandbox": "read-only",
                       "approvalPolicy": "never", "developerInstructions":
                       "This is a connection check. Reply OK. Do not use any tools or read any files."}
            if request.model:
                options["model"] = request.model
            result = await rpc.call("thread/start", options)
            thread_id = result["thread"]["id"]
            params = {"threadId": thread_id, "input": [{"type": "text", "text": "Reply OK only."}],
                      "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"}}
            if request.codex_effort:
                params["effort"] = request.codex_effort
            result = await rpc.call("turn/start", params)
            turn_id = result["turn"]["id"]
            for method, values in early:
                notify(method, values)
            turn = await rpc.wait_notification(done)
            if turn.get("status") != "completed" or not answered:
                return {"ok": False, "error": failure(turn.get("error"))}
            return {"ok": True, "model": request.model or "原生默认", "elapsedMs": round(
                (time.monotonic() - started) * 1000)}
    try:
        return await asyncio.wait_for(run(), TIMEOUT_CODEX_PROBE)
    except (HarnessError, OSError, asyncio.TimeoutError) as error:
        return {"ok": False, "error": failure(str(error) or "timeout")}
    finally:
        if done.done() and not done.cancelled():
            done.exception()
