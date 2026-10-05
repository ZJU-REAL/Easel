"""OpenAI-compatible chat without an OpenClaw installation or Gateway."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = (
    "你是 Easel 社媒内容助手，用用户的语言协助写作、策划和分析。"
    "当前是模型 API 直连模式，没有本机文件、命令、浏览器或技能执行工具。"
    "仅根据对话和提供的画像、附件内容回答；不能声称已读取其他文件、"
    "执行技能、生成本地文件或发布内容。需要用户补充的信息请用文字询问。"
)


class DirectAPIError(Exception):
    """Safe user-facing diagnostics; never include credentials or upstream bodies."""


def read_settings(env_file: Path | None = None) -> dict[str, str]:
    settings = {}
    path = env_file if env_file is not None else PROJECT_ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                settings[key.strip()] = value.strip().strip("\"'")
    settings.update(os.environ)
    return settings


def api_mode(settings: dict[str, str]) -> bool:
    return settings.get("EASEL_CHAT_TRANSPORT", "http").strip().lower() == "api"


def api_config(settings: dict[str, str]) -> tuple[str, str, str]:
    base = settings.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    model = settings.get("OPENAI_MODEL", "").strip()
    key = settings.get("OPENAI_API_KEY", "").strip()
    try:
        url = urlsplit(base)
        valid = (url.scheme in ("http", "https") and bool(url.hostname)
                 and url.port != 0 and not url.username and not url.password
                 and not url.query and not url.fragment
                 and not any(c.isspace() or ord(c) < 32 for c in base))
    except ValueError:
        valid = False
    if not valid:
        raise DirectAPIError("请填写有效的 OPENAI_BASE_URL，例如 http://localhost:50288/v1")
    if not model or any(c in model for c in "\r\n"):
        raise DirectAPIError("请填写 OPENAI_MODEL，例如 gpt-6.1-sol")
    if any(c.isspace() for c in key) or "REPLACE_ME" in key.upper():
        raise DirectAPIError("OPENAI_API_KEY 无效，请填写网关的真实 Key；无需鉴权时可留空")
    return base, model, key


def history_path(directory: Path, session: str) -> Path:
    return directory / "api" / f"{hashlib.sha256(session.encode()).hexdigest()}.json"


async def stream_chat(settings: dict[str, str], content: str | list, *,
                      system: str = SYSTEM_PROMPT, history_file: Path | None = None,
                      timeout: float = 300):
    """Yield (token/thinking/finish, text); persist only complete exchanges."""
    base, model, key = api_config(settings)
    history = []
    if history_file is not None and history_file.is_file():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                raise ValueError
        except (OSError, ValueError):
            raise DirectAPIError("直连会话历史损坏，请新建会话") from None
    user = {"role": "user", "content": content}
    body = {"model": model, "stream": True,
            "messages": [{"role": "system", "content": system}, *history, user]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    text = []
    finish_reason = None
    done = False
    try:
        # Local/private gateways must bypass inherited system HTTP proxies.
        # Redirects must never forward the credential to a different destination.
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(timeout, connect=10)) as client:
            async with client.stream("POST", base + "/chat/completions",
                                     json=body, headers=headers) as response:
                if response.status_code != 200:
                    raise DirectAPIError(f"API 返回 HTTP {response.status_code}，请检查地址、Key 和模型")
                data_lines = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    if line or not data_lines:
                        continue
                    payload = "\n".join(data_lines)
                    data_lines = []
                    if payload == "[DONE]":
                        done = True
                        break
                    try:
                        event = json.loads(payload)
                        if not isinstance(event, dict) or event.get("error"):
                            raise ValueError
                        choices = event.get("choices") or []
                        if not choices:
                            continue  # usage-only event
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        if delta.get("tool_calls"):
                            raise DirectAPIError("网关要求执行工具，但 API 直连模式没有本机执行工具")
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        if isinstance(reasoning, str) and reasoning:
                            yield "thinking", reasoning
                        token = delta.get("content")
                        if isinstance(token, str) and token:
                            text.append(token)
                            yield "token", token
                        finish_reason = choice.get("finish_reason") or finish_reason
                    except (ValueError, TypeError, KeyError, AttributeError):
                        raise DirectAPIError("API 返回了错误或无法解析的流数据") from None
    except httpx.TimeoutException:
        raise DirectAPIError("API 请求超时，请检查网关或重试") from None
    except httpx.HTTPError:
        raise DirectAPIError("API 连接失败，请确认网关正在运行且地址可达") from None
    if finish_reason == "length":
        raise DirectAPIError("回复达到模型长度上限，已保留收到的内容，请重试或缩小请求")
    if finish_reason not in (None, "stop"):
        raise DirectAPIError("模型未正常完成回复，请检查网关的 finish_reason")
    if not text or not (done or finish_reason == "stop"):
        raise DirectAPIError("API 流中断或返回空回复，请重试")
    if history_file is not None:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = history_file.with_suffix(".tmp")
        temporary.write_text(json.dumps([*history, user, {"role": "assistant", "content": "".join(text)}],
                                        ensure_ascii=False), encoding="utf-8")
        temporary.replace(history_file)
    yield "finish", "stop"
