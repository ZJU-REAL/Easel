"""Read native model catalogs without starting a conversation."""
from __future__ import annotations

import asyncio
import os
import signal

from easel import __version__

from .base import HarnessError, RunRequest
from .commands import base_command
from .rpc import RPC


def _valid_id(value):
    return isinstance(value, str) and 0 < len(value) <= 240 and not any(
        ord(character) < 32 for character in value)


async def available_models(runtime: str, request: RunRequest) -> list[dict]:
    if runtime == "codex":
        async def reject(method, params):
            raise HarnessError("读取模型列表时不允许执行工具")

        models = []
        cursor = None
        async with RPC(request, base_command("codex") + ["app-server"],
                       lambda method, params: None, reject) as rpc:
            await rpc.call("initialize", {
                "clientInfo": {"name": "easel", "version": __version__},
                "capabilities": {"experimentalApi": True}}, timeout=15)
            await rpc.send({"method": "initialized"})
            for page in range(20):
                params = {"limit": 100, "includeHidden": False}
                if cursor:
                    params["cursor"] = cursor
                response = await rpc.call("model/list", params, timeout=15)
                if not isinstance(response, dict) or not isinstance(response.get("data"), list):
                    raise HarnessError("Codex 返回了无效的模型列表")
                for item in response.get("data") or []:
                    if not isinstance(item, dict):
                        continue
                    identifier = item.get("model") or item.get("id")
                    if not item.get("hidden") and _valid_id(identifier):
                        label = item.get("displayName")
                        models.append({"id": identifier,
                                       "label": label if _valid_id(label) else identifier,
                                       "default": bool(item.get("isDefault"))})
                following = response.get("nextCursor")
                if not following or following == cursor:
                    break
                cursor = following
    elif runtime == "opencode":
        env = {**request.env, "EASEL_ROOT": str(request.cwd.resolve()),
               "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        process = await asyncio.create_subprocess_exec(
            *base_command("opencode"), "models",
            cwd=str(request.cwd), env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=os.name != "nt")
        try:
            async def read_output():
                chunks = []
                size = 0
                while chunk := await process.stdout.read(65536):
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise HarnessError("OpenCode 模型列表过大")
                    chunks.append(chunk)
                return b"".join(chunks)

            output = await asyncio.wait_for(read_output(), 15)
            await asyncio.wait_for(process.wait(), 5)
            if process.returncode or len(output) > 1024 * 1024:
                raise HarnessError("OpenCode 模型列表读取失败，请检查原生 CLI 配置")
        finally:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                process.kill()
            await process.wait()
        models = [{"id": identifier, "label": identifier, "default": False}
                  for identifier in output.decode("utf-8").splitlines()
                  if _valid_id(identifier) and "/" in identifier and not any(
                      character.isspace() for character in identifier)]
    else:
        raise HarnessError("此底座不支持原生模型列表")
    unique = {}
    for item in models:
        unique.setdefault(item["id"], item)
    return list(unique.values())
