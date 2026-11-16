"""MCP 节点配置管理 API（/api/mcp/*）。

读写 OpenClaw profile 的 mcp.servers（~/.openclaw-easel/openclaw.json）。状态所有权
在运行中的 gateway：所有变更走「gateway.sh stop → 改 JSON → gateway.sh start」
（约 20s）；列表与探测不碰 gateway——探测用直连 MCP 握手（HTTP 走 urllib，空响应
自动降级 curl；stdio 用子进程 JSON-RPC 行协议）。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import select
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENCLAW_JSON = Path.home() / ".openclaw-easel" / "openclaw.json"
GATEWAY_SH = PROJECT_ROOT / "scripts" / "gateway.sh"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MCP_INIT = {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "easel-mcp-panel", "version": "0.1"}}

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
_mutation_lock = asyncio.Lock()


# ── 配置读写 ─────────────────────────────────────────────

def _load_servers() -> dict[str, dict]:
    try:
        data = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"读取 openclaw.json 失败：{e}")
    return data.setdefault("mcp", {}).setdefault("servers", {})


def _save_servers(servers: dict[str, dict]) -> None:
    data = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8"))
    data.setdefault("mcp", {})["servers"] = servers
    tmp = OPENCLAW_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OPENCLAW_JSON)


def _gateway(action: str) -> str:
    proc = subprocess.run(["bash", str(GATEWAY_SH), action], capture_output=True,
                          text=True, timeout=180, cwd=str(PROJECT_ROOT))
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


async def _apply_mutation(mutate) -> dict:
    """gateway 停 → 改配置 → 起。mutate(servers) 原地修改并返回提示信息。"""
    async with _mutation_lock:
        status = await asyncio.to_thread(_gateway, "status")
        was_running = "running" in status
        if was_running:
            await asyncio.to_thread(_gateway, "stop")
        try:
            servers = await asyncio.to_thread(_load_servers)
            note = mutate(servers)
            await asyncio.to_thread(_save_servers, servers)
        finally:
            if was_running:
                await asyncio.to_thread(_gateway, "start")
        return {"ok": True, "note": note}


# ── HTTP 节点探测 ────────────────────────────────────────

def _parse_mcp_body(body: str) -> dict:
    if body.lstrip().startswith("{"):
        return json.loads(body)
    for line in body.splitlines():                       # SSE 帧
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def _probe_http(url: str, headers: dict[str, str] | None, timeout: int = 30) -> list[dict]:
    """streamable-HTTP MCP 握手：initialize → initialized → tools/list。

    urllib 先行；空响应（部分前置代理掐 HTTP/1.1 长请求）整段降级 curl 重走。
    """
    def urllib_post(payload: dict, sid: str | None):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if sid:
            req.add_header("Mcp-Session-Id", sid)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.headers.get("Mcp-Session-Id"), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:200]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"连接失败：{e.reason}")

    def curl_post(payload: dict, sid: str | None):
        cmd = ["curl", "-sk", "--max-time", str(timeout), url, "-X", "POST",
               "-H", "Content-Type: application/json",
               "-H", "Accept: application/json, text/event-stream",
               "-H", "User-Agent: easel-mcp-panel/0.1",
               "--data-binary", json.dumps(payload)]
        for k, v in (headers or {}).items():
            cmd += ["-H", f"{k}: {v}"]
        if sid:
            cmd += ["-H", f"Mcp-Session-Id: {sid}"]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
        out = proc.stdout.decode("utf-8", "replace")
        head, _, body = out.partition("\r\n\r\n")
        sid_out = None
        for line in head.splitlines():
            if line.lower().startswith("mcp-session-id:"):
                sid_out = line.split(":", 1)[1].strip()
        return sid_out, body

    def transport(payload: dict, sid: str | None):
        try:
            return urllib_post(payload, sid)
        except RuntimeError as e:
            if "HTTP 4" in str(e):                    # 4xx 是业务错误，不重试
                raise
            return curl_post(payload, sid)

    sid, body = transport({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": dict(_MCP_INIT)}, None)
    init = _parse_mcp_body(body) if body.strip() else {}
    if not init.get("result"):
        raise RuntimeError(f"握手无结果：{body[:200]}")
    transport({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, body = transport({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    resp = _parse_mcp_body(body) if body.strip() else {}
    tools = (resp.get("result") or {}).get("tools", [])
    if not tools:
        raise RuntimeError(f"tools/list 无工具：{body[:200]}")
    return tools


# ── stdio 节点探测 ────────────────────────────────────────

def _probe_stdio(command: str, args: list[str], env: dict[str, str] | None,
                 timeout: int = 25) -> list[dict]:
    """spawn 子进程，JSON-RPC 行协议：initialize → initialized → tools/list。"""
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.Popen([command, *args], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, env=full_env, bufsize=1)
    buf = ""

    def read_json(want_id: int, deadline: float) -> dict | None:
        nonlocal buf
        while time.time() < deadline:
            while "\n" in buf:                       # 先消化缓冲里的完整行
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line.startswith("{"):
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("id") == want_id:
                        return obj
            if proc.poll() is not None:
                return None                          # 进程已退出
            ready, _, _ = select.select([proc.stdout], [], [], 0.4)
            if not ready:
                continue
            chunk = proc.stdout.readline()
            if not chunk:
                return None
            buf += chunk
        return None

    try:
        deadline = time.time() + timeout
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                     "params": dict(_MCP_INIT)}) + "\n")
        proc.stdin.flush()
        if read_json(1, deadline) is None:
            raise RuntimeError("initialize 无响应（进程起不来或立即退出）")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        proc.stdin.flush()
        resp = read_json(2, deadline)
        if resp is None:
            raise RuntimeError("tools/list 无响应")
        tools = (resp.get("result") or {}).get("tools", [])
        if not tools:
            raise RuntimeError("节点未返回任何工具")
        return tools
    finally:
        try:
            proc.kill()
        except OSError:
            pass


def _probe_server(entry: dict) -> list[dict]:
    if entry.get("url"):
        return _probe_http(entry["url"], entry.get("headers") or {})
    command = entry.get("command")
    if not command:
        raise RuntimeError("节点既无 url 也无 command")
    return _probe_stdio(command, entry.get("args") or [], entry.get("env") or {})


# ── 路由 ─────────────────────────────────────────────

class McpServerUpsert(BaseModel):
    name: str = Field(description="节点名（字母数字与 ._-）")
    transport: str = Field(description="stdio 或 streamable-http")
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    disabled: bool = False


def _validate_entry(req: McpServerUpsert) -> dict:
    if not _NAME_RE.match(req.name):
        raise HTTPException(400, "节点名只能含字母数字与 ._-，长度 ≤64")
    entry: dict = {"disabled": req.disabled}
    if req.transport == "streamable-http":
        if not (req.url or "").startswith(("http://", "https://")):
            raise HTTPException(400, "HTTP 节点必须提供 http(s) URL")
        entry.update({"url": req.url, "transport": "streamable-http"})
        if req.headers:
            entry["headers"] = req.headers
    elif req.transport == "stdio":
        if not req.command:
            raise HTTPException(400, "stdio 节点必须提供 command")
        entry.update({"command": req.command, "args": req.args})
        if req.env:
            entry["env"] = req.env
    else:
        raise HTTPException(400, f"未知 transport：{req.transport}")
    return entry


@router.get("/servers")
async def list_servers():
    servers = _load_servers()
    rows = []
    for name, entry in sorted(servers.items()):
        rows.append({
            "name": name,
            "transport": "streamable-http" if entry.get("url") else "stdio",
            "target": entry.get("url") or entry.get("command") or "",
            "args": entry.get("args") or [],
            "hasEnv": bool(entry.get("env")),
            "hasHeaders": bool(entry.get("headers")),
            "disabled": bool(entry.get("disabled")),
        })
    return {"servers": rows}


@router.post("/servers")
async def upsert_server(req: McpServerUpsert):
    entry = _validate_entry(req)

    def mutate(servers: dict[str, dict]) -> str:
        existed = req.name in servers
        servers[req.name] = entry
        return f"{'更新' if existed else '新增'}节点 {req.name}"

    result = await _apply_mutation(mutate)
    return {**result, "entry": entry}


@router.delete("/servers/{name}")
async def delete_server(name: str):
    def mutate(servers: dict[str, dict]) -> str:
        if name not in servers:
            raise HTTPException(404, f"节点不存在：{name}")
        del servers[name]
        return f"删除节点 {name}"

    return await _apply_mutation(mutate)


@router.post("/servers/{name}/toggle")
async def toggle_server(name: str):
    def mutate(servers: dict[str, dict]) -> str:
        if name not in servers:
            raise HTTPException(404, f"节点不存在：{name}")
        servers[name]["disabled"] = not servers[name].get("disabled", False)
        state = "停用" if servers[name]["disabled"] else "启用"
        return f"{state}节点 {name}"

    return await _apply_mutation(mutate)


@router.post("/servers/{name}/probe")
async def probe_server(name: str):
    entry = _load_servers().get(name)
    if entry is None:
        raise HTTPException(404, f"节点不存在：{name}")
    if entry.get("disabled"):
        raise HTTPException(409, "节点已停用，先启用再探测")
    try:
        tools = await asyncio.to_thread(_probe_server, entry)
    except (RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        raise HTTPException(502, f"探测失败：{e}")
    return {"ok": True, "toolCount": len(tools),
            "tools": [{"name": t.get("name"), "description": (t.get("description") or "")[:120]}
                      for t in tools]}
