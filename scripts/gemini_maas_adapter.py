#!/usr/bin/env python3
"""Expose a Gemini-compatible endpoint as OpenAI Chat Completions."""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_ENDPOINT = ""
DEFAULT_MODEL = "gemini-3.1-pro-preview"
SIGNATURES: dict[str, str] = {}


def text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    texts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(str(item.get("text", "")))
    return "\n".join(texts)


def encode_signature(signature: str) -> str:
    # OpenClaw normalizes tool-call IDs to at most 40 alphanumeric characters.
    call_id = "call" + uuid.uuid4().hex
    SIGNATURES[call_id] = signature
    if len(SIGNATURES) > 4096:
        for old_id in list(SIGNATURES)[:1024]:
            SIGNATURES.pop(old_id, None)
    return call_id


def decode_signature(call_id: object) -> str | None:
    return SIGNATURES.get(call_id) if isinstance(call_id, str) else None


def openai_to_gemini(body: dict) -> dict:
    system_parts: list[dict] = []
    contents: list[dict] = []
    call_names: dict[str, str] = {}
    call_id_debug: list[str] = []

    for message in body.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role in ("system", "developer"):
            text = text_content(message.get("content"))
            if text:
                system_parts.append({"text": text})
            continue

        if role == "tool":
            call_id = str(message.get("tool_call_id", ""))
            name = str(message.get("name") or call_names.get(call_id) or "tool")
            raw_result = text_content(message.get("content"))
            try:
                result = json.loads(raw_result)
            except (TypeError, json.JSONDecodeError):
                result = raw_result
            contents.append({
                "role": "user",
                "parts": [{"functionResponse": {"name": name, "response": {"result": result}}}],
            })
            continue

        parts: list[dict] = []
        text = text_content(message.get("content"))
        if text:
            parts.append({"text": text})
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            name = str(function.get("name") or "tool")
            call_id = str(call.get("id") or "")
            call_id_debug.append(f"{len(call_id)}:{call_id[:12]}")
            call_names[call_id] = name
            try:
                args = json.loads(function.get("arguments") or "{}")
            except (TypeError, json.JSONDecodeError):
                args = {"raw": function.get("arguments")}
            part = {"functionCall": {"name": name, "args": args}}
            signature = decode_signature(call_id)
            if signature:
                part["thoughtSignature"] = signature
            parts.append(part)
        if parts:
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})

    generation = {
        "temperature": body.get("temperature", 1),
        "maxOutputTokens": body.get("max_tokens", 65535),
        "topP": body.get("top_p", 0.95),
        "thinkingConfig": {
            "thinkingLevel": os.environ.get("GEMINI_THINKING_LEVEL", "HIGH"),
            "includeThoughts": os.environ.get("GEMINI_INCLUDE_THOUGHTS", "true").lower() == "true",
        },
    }
    payload = {
        "model": os.environ.get("GEMINI_MAAS_MODEL", DEFAULT_MODEL),
        "contents": contents or [{"role": "user", "parts": [{"text": " "}]}],
        "generationConfig": generation,
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}
    tools = body.get("tools") or []
    declarations = []
    for tool in tools:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        if function.get("name"):
            declarations.append({
                "name": function["name"],
                "description": function.get("description", ""),
                "parameters": function.get("parameters", {"type": "object", "properties": {}}),
            })
    if declarations:
        payload["tools"] = [{"functionDeclarations": declarations}]
    payload["_adapterDebug"] = call_id_debug
    return payload


def gemini_to_openai(data: dict, model: str) -> dict:
    candidates = data.get("candidates") or []
    candidate = candidates[0] if candidates else {}
    parts = (candidate.get("content") or {}).get("parts") or []
    text_parts: list[str] = []
    thought_parts: list[str] = []
    tool_calls: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if "text" in part:
            target = thought_parts if part.get("thought") else text_parts
            target.append(str(part["text"]))
        function = part.get("functionCall")
        if isinstance(function, dict):
            signature = part.get("thoughtSignature")
            call_id = encode_signature(signature) if isinstance(signature, str) else "call_" + uuid.uuid4().hex
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": function.get("name", "tool"),
                    "arguments": json.dumps(function.get("args") or {}, ensure_ascii=False, separators=(",", ":")),
                },
            })
    message: dict = {"role": "assistant", "content": "".join(text_parts) or None}
    if thought_parts:
        message["reasoning_content"] = "".join(thought_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = data.get("usageMetadata") or {}
    return {
        "id": data.get("responseId") or "chatcmpl-" + uuid.uuid4().hex,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": data.get("modelVersion") or model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "EaselGeminiAdapter/1.0"

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health", "/v1/models"):
            self.send_json(200, {"ok": True, "data": [{"id": DEFAULT_MODEL, "object": "model"}]})
        else:
            self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_json(404, {"error": {"message": "not found"}})
            return
        payload: dict = {}
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
            api_key = os.environ.get("GEMINI_MAAS_API_KEY", "")
            if not api_key:
                raise RuntimeError("GEMINI_MAAS_API_KEY is not configured")
            payload = openai_to_gemini(body)
            call_id_debug = payload.pop("_adapterDebug", [])
            request = Request(
                os.environ.get("GEMINI_MAAS_ENDPOINT", DEFAULT_ENDPOINT),
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={"api-key": api_key, "Content-Type": "application/json"},
                method="POST",
            )
            # Internal MaaS must bypass any workstation-wide outbound proxy.
            with build_opener(ProxyHandler({})).open(request, timeout=600) as response:
                result = gemini_to_openai(json.load(response), body.get("model", DEFAULT_MODEL))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                choice = result["choices"][0]
                chunk = {k: result[k] for k in ("id", "created", "model")}
                chunk.update({"object": "chat.completion.chunk", "choices": [{
                    "index": 0, "delta": choice["message"], "finish_reason": choice["finish_reason"]
                }]})
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode())
                self.wfile.write(b"data: [DONE]\n\n")
            else:
                self.send_json(200, result)
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:2000]
            calls = [
                part
                for content in payload.get("contents", [])
                for part in content.get("parts", [])
                if "functionCall" in part
            ]
            signature_count = sum("thoughtSignature" in part for part in calls)
            self.send_json(exc.code, {"error": {"message": (
                f"Gemini MaaS HTTP {exc.code}: {detail} "
                f"[adapter functionCalls={len(calls)}, thoughtSignatures={signature_count}, "
                f"callIds={call_id_debug}]"
            )}})
        except (URLError, OSError, ValueError, RuntimeError) as exc:
            self.send_json(502, {"error": {"message": str(exc)}})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[gemini-adapter] {self.address_string()} {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18790)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
