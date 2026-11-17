"""A bounded native login ceremony; credentials never pass through Easel."""
from __future__ import annotations

import asyncio
import uuid
from urllib.parse import urlsplit

from easel.timeouts import TIMEOUT_CODEX_DIAGNOSTICS, TIMEOUT_CODEX_LOGIN, TIMEOUT_HARNESS_CANCEL

from .base import HarnessError, RunRequest
from .commands import base_command
from .codex_diagnostics import initialize, reject
from .rpc import RPC, close_sessions


def official_login_url(value) -> str:
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 for c in value):
        raise HarnessError("登录地址无效，请更新 Codex 后重试")
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and url.hostname in ("auth.openai.com", "chatgpt.com")
                 and url.port in (None, 443) and not url.username and not url.password and "\\" not in value)
    except ValueError:
        valid = False
    if not valid:
        raise HarnessError("未收到官方登录地址，请检查 Codex 配置")
    return value


class CodexLogin:
    """One attempt per local Easel service. Reloading the page reattaches to it."""

    def __init__(self):
        self.record = {"state": "idle"}
        self.task = None
        self.ready = None

    @property
    def pending(self):
        return self.task is not None and not self.task.done()

    def snapshot(self):
        return dict(self.record)

    async def start(self, request: RunRequest, method="browser"):
        if method not in ("browser", "device"):
            raise HarnessError("请选择浏览器登录或验证码登录")
        if self.pending:
            if method != self.record.get("method"):
                raise HarnessError("请先取消当前登录，再切换登录方式")
        else:
            self.record = {"id": uuid.uuid4().hex, "state": "starting", "method": method}
            self.ready = asyncio.get_running_loop().create_future()
            self.task = asyncio.create_task(self._run(request, method))
        # A closing browser must not cancel the native login callback server.
        await asyncio.shield(self.ready)
        return self.snapshot()

    async def cancel(self, identifier):
        if identifier != self.record.get("id"):
            raise HarnessError("登录请求已更新，请刷新后重试")
        if self.pending:
            if self.record.get("state") not in ("success", "failed", "expired", "cancelled"):
                self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            if not self.ready.done():
                self.record.update(state="cancelled", message="已取消本次登录。")
                self.ready.set_result(None)
        return self.snapshot()

    async def close(self):
        if self.pending:
            await self.cancel(self.record.get("id"))

    async def logout(self, request: RunRequest):
        if self.pending:
            raise HarnessError("请先完成或取消当前登录")
        command = list(request.command) or base_command("codex") + ["app-server"]
        try:
            async with RPC(request, command, lambda *_: None, reject) as rpc:
                await initialize(rpc)
                await rpc.call("account/logout", {}, timeout=TIMEOUT_CODEX_DIAGNOSTICS)
            await close_sessions(runtime="codex")
            self.record = {"state": "logged_out", "message": "已退出 Codex，原有对话和作品仍保留。"}
            return self.snapshot()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise HarnessError("退出 Codex 失败，请稍后重试；原有登录状态未主动清除") from error

    async def _run(self, request, method):
        native_id = ""
        completed = asyncio.get_running_loop().create_future()
        early = []

        def notify(name, params):
            if name != "account/login/completed":
                return
            if not native_id:
                if len(early) < 16:
                    early.append(params)
                return
            if params.get("loginId") == native_id and not completed.done():
                completed.set_result(params.get("success") is True)

        def finish(state, message):
            self.record = {key: value for key, value in self.record.items()
                           if key not in ("authUrl", "userCode")}
            self.record.update(state=state, message=message)

        try:
            command = list(request.command) or base_command("codex") + ["app-server"]
            async with RPC(request, command, notify, reject) as rpc:
                try:
                    async def begin():
                        await initialize(rpc)
                        return await rpc.call("account/login/start", {
                            "type": "chatgpt" if method == "browser" else "chatgptDeviceCode"})
                    result = await asyncio.wait_for(begin(), TIMEOUT_CODEX_DIAGNOSTICS)
                    native_id = result.get("loginId", "")
                    if not isinstance(native_id, str) or not native_id:
                        raise HarnessError("Codex 未返回登录请求标识")
                    url = official_login_url(result.get("authUrl") if method == "browser" else result.get("verificationUrl"))
                    self.record.update(state="pending", authUrl=url, message="请在官方页面完成登录，完成后这里会自动更新。")
                    if method == "device":
                        code = result.get("userCode")
                        if not isinstance(code, str) or not 1 <= len(code) <= 64 or not all(c.isalnum() or c == '-' for c in code):
                            raise HarnessError("Codex 未返回有效的登录验证码")
                        self.record["userCode"] = code
                    for params in early:
                        notify("account/login/completed", params)
                    if not self.ready.done():
                        self.ready.set_result(None)
                    success = await asyncio.wait_for(rpc.wait_notification(completed), TIMEOUT_CODEX_LOGIN)
                    if success:
                        # Web blocks Codex turns during login, so these connections are idle.
                        await close_sessions(runtime="codex")
                        finish("success", "登录成功，账号已连接。")
                    else:
                        finish("failed", "登录未完成，请重试；也可以使用验证码登录。")
                finally:
                    if native_id and self.record.get("state") not in ("success", "failed"):
                        try:
                            await rpc.call("account/login/cancel", {"loginId": native_id}, timeout=TIMEOUT_HARNESS_CANCEL)
                        except HarnessError:
                            pass
        except asyncio.CancelledError:
            finish("cancelled", "已取消本次登录。")
        except asyncio.TimeoutError:
            finish("expired", "登录等待超时，请重新登录。")
        except Exception:
            # Native errors can include OAuth state or credentials. Never return them.
            finish("failed", "无法完成登录，请重试或改用验证码登录；仍失败时可在终端运行 codex login。")
        finally:
            if not self.ready.done():
                self.ready.set_result(None)
            if completed.done() and not completed.cancelled():
                completed.exception()
