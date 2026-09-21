"""OpenCode 配置读写：经本机 OpenCode server 管理供应商凭证与默认模型。

从 runtimes/opencode.py 分出的配置层（对应 openclaw_config.py 的角色）：适配器负责跑
agent、探测环境，这里只回答「配置是什么、怎么写」。web 设置面板从这里取 OpenCode 的
配置真值。

- API Key 只经 server 的 `/auth/{id}` 写入 OpenCode 原生凭证库，不回传前端、不写 .env。
- 默认模型直接读改写项目 opencode.json，不走 server 的 `PATCH /config`：1.18.31 起该
  端点把内容写到项目根 `config.json`，而配置加载器从不读它（anomalyco/opencode#4194、
  #28966），既不改 opencode.json 也不生效。
"""

from __future__ import annotations

import json
import re
import shutil

from . import opencode
from .common import PROJECT_ROOT

PROJECT_CONFIG = PROJECT_ROOT / "opencode.json"
_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_MAX_KEY = 400


def _request(method: str, path: str, body: dict | None = None):
    return opencode.request(method, path, body)


def server_ready() -> bool:
    try:
        data = _request("GET", "/global/health")
    except Exception:  # noqa: BLE001
        return False
    return isinstance(data, dict) and data.get("healthy") is True


def primary_model() -> str:
    """项目 opencode.json 的 model（Easel 在本项目目录运行 opencode）。"""
    try:
        data = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("model") or "") if isinstance(data, dict) else ""


def _providers() -> list[dict]:
    data = _request("GET", "/config/providers")
    items = data.get("providers") if isinstance(data, dict) else None
    rows = []
    for p in items or []:
        if not isinstance(p, dict):
            continue
        models = p.get("models") if isinstance(p.get("models"), dict) else {}
        rows.append({
            "id": str(p.get("id") or ""),
            "name": str(p.get("name") or p.get("id") or ""),
            "source": str(p.get("source") or ""),
            "hasKey": bool(str(p.get("key") or "").strip()),
            "modelCount": len(models),
        })
    rows.sort(key=lambda r: r["id"])
    return rows


def _models() -> list[dict]:
    data = _request("GET", "/api/model")
    items = data.get("data") if isinstance(data, dict) else None
    rows = []
    for m in items or []:
        if not isinstance(m, dict):
            continue
        mid, pid = str(m.get("id") or ""), str(m.get("providerID") or "")
        if not mid or not pid:
            continue
        rows.append({"id": mid, "providerID": pid, "name": str(m.get("name") or mid)})
    rows.sort(key=lambda r: (r["providerID"], r["id"]))
    return rows


def _auth_methods() -> dict[str, list[str]]:
    data = _request("GET", "/provider/auth")
    if not isinstance(data, dict):
        return {}
    result: dict[str, list[str]] = {}
    for pid, methods in data.items():
        if isinstance(methods, list):
            result[str(pid)] = [str(m.get("type") or "") for m in methods if isinstance(m, dict)]
    return result


def snapshot() -> dict:
    """设置面板快照；server 不可用时降级为只读空表（不抛异常）。"""
    base = {"serverReady": False, "primary": primary_model(), "providers": [], "models": [],
            "authMethods": {}, "message": ""}
    if not server_ready():
        base["message"] = "OpenCode server 未就绪；先运行 easel gateway start"
        return base
    try:
        return {"serverReady": True, "primary": base["primary"], "providers": _providers(),
                "models": _models(), "authMethods": _auth_methods(), "message": ""}
    except Exception as exc:  # noqa: BLE001
        base["message"] = f"OpenCode server 读取失败：{type(exc).__name__}: {exc}"[:200]
        return base


# ---- 校验（只读，不产生写入；保存端点先全部校验再落任何改动）----

def _valid_provider_id(provider_id: str) -> str:
    pid = provider_id or ""
    if not _PROVIDER_ID.fullmatch(pid):
        raise ValueError("供应商标识不合法（需小写字母/数字/连字符，最长 64 位）")
    return pid


def validate_provider_key(provider_id: str, key: str) -> tuple[str, str]:
    pid = _valid_provider_id(provider_id)
    value = key or ""
    if not value or any(ch.isspace() for ch in value) or len(value) > _MAX_KEY:
        raise ValueError("API Key 不能为空、不能包含空白字符，且不超过 400 字符")
    return pid, value


def validate_removal(provider_id: str) -> str:
    pid = _valid_provider_id(provider_id)
    provider = next((p for p in _providers() if p["id"] == pid), None)
    if provider is None:
        raise ValueError(f"供应商不存在：{pid}")
    if provider["source"] == "env":
        raise ValueError(f"「{pid}」的凭证由环境变量提供，无法在面板清除")
    return pid


def validate_model(ref: str) -> str:
    value = (ref or "").strip()
    refs = {f'{m["providerID"]}/{m["id"]}' for m in _models()}
    if value not in refs:
        raise ValueError(f"模型不在 OpenCode 目录中：{value[:80] or '（空）'}")
    return value


# ---- 写入 ----

def set_provider_key(provider_id: str, key: str) -> None:
    pid, value = validate_provider_key(provider_id, key)
    _request("PUT", f"/auth/{pid}", {"type": "api", "key": value})


def remove_provider_key(provider_id: str) -> None:
    pid = validate_removal(provider_id)
    _request("DELETE", f"/auth/{pid}")


def set_primary_model(ref: str) -> None:
    value = validate_model(ref)
    if not PROJECT_CONFIG.is_file():
        raise ValueError("项目 opencode.json 不存在，请先运行 setup")
    try:
        data = json.loads(PROJECT_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"项目 opencode.json 读取失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("项目 opencode.json 结构异常")
    if data.get("model") == value:
        return
    data["model"] = value
    shutil.copy2(PROJECT_CONFIG, PROJECT_CONFIG.with_name(PROJECT_CONFIG.name + ".bak-web"))
    tmp = PROJECT_CONFIG.with_name(PROJECT_CONFIG.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(PROJECT_CONFIG)
