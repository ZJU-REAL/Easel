"""MCP 节点配置管理 API（/api/mcp/*）。

单一通讯录（设置 → MCP 节点），分发到 Easel 支持的各 agent 运行时：

- **openclaw**：改 profile 的 openclaw.json（``easel.openclaw_workspace.config_path()``），
  变更走 ``scripts/gateway.sh`` stop→start（状态所有权在 gateway）。启动前检查活跃任务
  （app 注入的探针读 ``_RUNNING_CHAT`` 等登记表），有进行中会话时拒绝，除非显式 force。
- **opencode**：合并进项目级 ``opencode.json`` 的 ``mcp`` 段（OpenCode 每次会话新起进程，
  无需重启）。仅管理通讯录管理的名字（``mcp.easelManaged``），用户手工条目不动。
- **codex**：改 ``~/.codex/config.toml`` 的 ``[mcp_servers.*]`` 表（tomllib 读 + 表块重建写；
  无 config.toml 则跳过并注明）。
- **acp / hermes**：MCP 配置由具体 CLI 决定，无通用分发机制，状态报告为 skipped。

探测不碰任何运行时：直连 MCP 握手（HTTP 走 urllib，空响应整段降级 curl HTTP/2；
stdio 用子进程 JSON-RPC 行协议）。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import select
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from easel.openclaw_workspace import config_path  # noqa: E402 — 复用既有 profile 路径解析

OPENCLAW_JSON = config_path()
GATEWAY_SH = PROJECT_ROOT / "scripts" / "gateway.sh"
OPENCODE_JSON = PROJECT_ROOT / "opencode.json"
CODEX_TOML = Path.home() / ".codex" / "config.toml"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MCP_INIT = {"protocolVersion": "2025-03-26", "capabilities": {},
             "clientInfo": {"name": "easel-mcp-panel", "version": "0.2"}}
_GATEWAY_RUNNING_RE = re.compile(r"Gateway running \(PID (\d+)\)")

router = APIRouter(prefix="/api/mcp", tags=["mcp"])
_mutation_lock = asyncio.Lock()

# 活跃任务探针：app.py 在定义 _RUNNING_CHAT 等登记表后调用 set_busy_probe 注入
_BUSY_PROBE = None


def set_busy_probe(fn) -> None:
    global _BUSY_PROBE
    _BUSY_PROBE = fn


def _busy() -> bool:
    return bool(_BUSY_PROBE and _BUSY_PROBE())


# ── OpenClaw 配置读写（profile 解析复用 easel.openclaw_workspace） ─────────

def _load_doc() -> tuple[dict, dict[str, dict], list[str]]:
    """读 openclaw.json → (完整文档, servers 视图, 面板托管名单 easelManaged)。"""
    try:
        data = json.loads(OPENCLAW_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"读取 {OPENCLAW_JSON} 失败：{e}")
    mcp = data.setdefault("mcp", {})
    servers = mcp.setdefault("servers", {})
    managed = mcp.setdefault("easelManaged", [])
    return data, servers, managed


def _save_doc(data: dict) -> None:
    tmp = OPENCLAW_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OPENCLAW_JSON)


def _gateway(action: str) -> tuple[int, str]:
    proc = subprocess.run(["bash", str(GATEWAY_SH), action], capture_output=True,
                          text=True, timeout=180, cwd=str(PROJECT_ROOT))
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()


def _gateway_pid(status: str) -> int | None:
    match = _GATEWAY_RUNNING_RE.search(status)
    return int(match.group(1)) if match else None


# ── 分发器 ─────────────────────────────────────────────

def _opencode_entry(entry: dict) -> dict:
    if entry.get("url"):
        result: dict = {"type": "remote", "url": entry["url"], "enabled": not entry.get("disabled")}
        if entry.get("headers"):
            result["headers"] = entry["headers"]
        return result
    result = {"type": "local", "command": [entry["command"], *entry.get("args", [])],
              "enabled": not entry.get("disabled")}
    if entry.get("env"):
        result["environment"] = entry["env"]
    return result


def _dist_opencode(servers: dict[str, dict], managed: list[str]) -> list[dict]:
    managed_set = set(managed)
    try:
        existing = json.loads(OPENCODE_JSON.read_text(encoding="utf-8")) if OPENCODE_JSON.is_file() else {}
    except (OSError, json.JSONDecodeError) as e:
        return [{"runtime": "opencode", "status": f"failed: 项目 opencode.json 解析失败（{e}）"}]
    mcp = existing.setdefault("mcp", {})
    for name in [n for n in mcp if n in managed_set and n not in servers]:
        del mcp[name]                                    # 通讯录已删除 → 各运行时孤儿一并清除
    for name, entry in servers.items():
        if name in managed_set:
            mcp[name] = _opencode_entry(entry)
    tmp = OPENCODE_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OPENCODE_JSON)
    return [{"runtime": "opencode", "status": "applied（下次会话生效）"}]


def _toml_inline_table(env: dict[str, str]) -> str:
    inner = ", ".join(f'{k} = "{v}"' for k, v in env.items())
    return "{ " + inner + " }" if inner else "{}"


def _codex_table(name: str, entry: dict) -> list[str]:
    if entry.get("disabled"):
        return [f"# [mcp_servers.{name}]（已停用）",
                *[f"# {line}" for line in _codex_table(name, {**entry, "disabled": False})[1:]]]
    lines = [f"[mcp_servers.{name}]"]
    if entry.get("url"):
        lines.append(f'url = "{entry["url"]}"')
    else:
        lines.append(f'command = "{entry["command"]}"')
        if entry.get("args"):
            rendered = ", ".join(f'"{arg}"' for arg in entry["args"])
            lines.append(f"args = [{rendered}]")
        if entry.get("env"):
            lines.append(f"env = {_toml_inline_table(entry['env'])}")
    return lines


def _dist_codex(servers: dict[str, dict], managed: list[str]) -> list[dict]:
    managed_set = set(managed)
    live = {n: e for n, e in servers.items() if n in managed_set}
    if not CODEX_TOML.is_file():
        return [{"runtime": "codex", "status": "skipped: 未找到 ~/.codex/config.toml（codex 未配置）"}]
    try:
        import tomllib
        tomllib.loads(CODEX_TOML.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [{"runtime": "codex", "status": f"failed: config.toml 解析失败（{e}）"}]
    lines = CODEX_TOML.read_text(encoding="utf-8").splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if re.match(r"^\[mcp_servers[.\]]", line) or line.strip() == "[mcp_servers]":
            start = i
            end = i + 1
            for j in range(i + 1, len(lines)):
                if re.match(r"^\[", lines[j]) and not lines[j].startswith("[mcp_servers"):
                    end = j
                    break
                end = j + 1
            break
    block: list[str] = []
    if live:
        block.append("# [easel] 由 设置 → MCP 节点 管理，手工改动会被覆盖")
        for name, entry in sorted(live.items()):
            block += _codex_table(name, entry)
            block.append("")
    if start is None:
        if block:
            lines += ["", *block]
    else:
        lines[start:end] = block
    CODEX_TOML.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return [{"runtime": "codex", "status": "applied（下次会话生效）"}]


# ── 变更应用（守卫 → OpenClaw 周期 → 各运行时分发） ────────────────

async def _apply_everything(mutate, force: bool) -> dict:
    async with _mutation_lock:
        rc, status = await asyncio.to_thread(_gateway, "status")
        running_pid = _gateway_pid(status)
        if running_pid and _busy() and not force:
            raise HTTPException(409, "有进行中的任务（对话/后台任务），变更会中断它们。"
                                     "等待完成后再试，或显式 force。")
        distribution: list[dict] = []
        note = ""
        managed_before = list(managed)                   # mutate 前快照：分发要据此清除已删节点
        if running_pid:
            rc_stop, out_stop = await asyncio.to_thread(_gateway, "stop")
            if rc_stop != 0:
                raise HTTPException(502, f"gateway 停止失败（exit {rc_stop}）：{out_stop[:200]}")
        try:
            data, servers, managed = await asyncio.to_thread(_load_doc)
            note = mutate(servers, managed)
            await asyncio.to_thread(_save_doc, data)
            distribution += await asyncio.to_thread(_dist_opencode, servers, managed_before)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 — 分发失败不影响配置已写的事实，如实报告
            distribution.append({"runtime": "opencode", "status": f"failed: {e}"})
        finally:
            if running_pid:
                rc_start, out_start = await asyncio.to_thread(_gateway, "start")
                if rc_start != 0:
                    distribution.append({"runtime": "openclaw",
                                         "status": f"failed: gateway 启动失败（exit {rc_start}）：{out_start[:150]}"})
                else:
                    pid = None
                    deadline = time.time() + 15
                    while time.time() < deadline and not pid:
                        _, status_v = await asyncio.to_thread(_gateway, "status")
                        pid = _gateway_pid(status_v)
                        if not pid:
                            time.sleep(3)
                    distribution.append({"runtime": "openclaw",
                                         "status": f"applied（gateway 已重启，PID {pid}）" if pid
                                         else "failed: 重启后 15s 未确认 PID，请查 gateway 日志"})
        distribution += await asyncio.to_thread(_dist_codex, servers, managed_before)
        distribution += [{"runtime": "acp", "status": "skipped: 工具集由具体 CLI 决定"},
                         {"runtime": "hermes", "status": "skipped: 待接入"}]
        return {"ok": True, "note": note, "distribution": distribution}


# ── 探测（不碰任何运行时） ────────────────────────────────────────

def _parse_mcp_body(body: str) -> dict:
    if body.lstrip().startswith("{"):
        return json.loads(body)
    for line in body.splitlines():                       # SSE 帧
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def _probe_http(url: str, headers: dict[str, str] | None, timeout: int = 30) -> list[dict]:
    """streamable-HTTP MCP 握手：initialize → initialized → tools/list。

    urllib 先行；空响应（部分前置代理掐 HTTP/1.1 长请求）整段降级 curl 重走
    （curl 用 -o/-D 分离正文与头，绝不做流式解析）。
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
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            body_path = Path(td) / "body"
            head_path = Path(td) / "head"
            cmd = ["curl", "-sk", "--max-time", str(timeout), url, "-X", "POST",
                   "-H", "Content-Type: application/json",
                   "-H", "Accept: application/json, text/event-stream",
                   "--data-binary", json.dumps(payload),
                   "-o", str(body_path), "-D", str(head_path)]
            for k, v in (headers or {}).items():
                cmd += ["-H", f"{k}: {v}"]
            if sid:
                cmd += ["-H", f"Mcp-Session-Id: {sid}"]
            subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
            sid_out = None
            try:
                for line in head_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.lower().startswith("mcp-session-id:"):
                        sid_out = line.split(":", 1)[1].strip()
            except OSError:
                pass
            try:
                return sid_out, body_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return sid_out, ""

    def transport(payload: dict, sid: str | None):
        try:
            sid_out, body = urllib_post(payload, sid)
            if body.strip():
                return sid_out, body
            return curl_post(payload, sid)               # 空响应 → 整段降级 curl
        except RuntimeError as e:
            if "HTTP 4" in str(e):                       # 4xx 是业务错误，不重试
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
            while "\n" in buf:
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
                return None
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
    force: bool = Field(default=False, description="忽略活跃任务守卫，强制应用")


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
    _, servers, _ = _load_doc()
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

    def mutate(servers: dict[str, dict], managed: list[str]) -> str:
        existed = req.name in servers
        servers[req.name] = entry
        if req.name not in managed:
            managed.append(req.name)
        return f"{'更新' if existed else '新增'}节点 {req.name}"

    return await _apply_everything(mutate, req.force)


@router.delete("/servers/{name}")
async def delete_server(name: str, force: bool = False):
    def mutate(servers: dict[str, dict], managed: list[str]) -> str:
        if name not in servers:
            raise HTTPException(404, f"节点不存在：{name}")
        del servers[name]
        if name in managed:
            managed.remove(name)
        return f"删除节点 {name}"

    return await _apply_everything(mutate, force)


@router.post("/servers/{name}/toggle")
async def toggle_server(name: str, force: bool = False):
    def mutate(servers: dict[str, dict], managed: list[str]) -> str:
        if name not in managed:
            managed.append(name)
        if name not in servers:
            raise HTTPException(404, f"节点不存在：{name}")
        servers[name]["disabled"] = not servers[name].get("disabled", False)
        state = "停用" if servers[name]["disabled"] else "启用"
        return f"{state}节点 {name}"

    return await _apply_everything(mutate, force)


@router.post("/servers/{name}/probe")
async def probe_server(name: str):
    _, servers, _ = _load_doc()
    entry = servers.get(name)
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
