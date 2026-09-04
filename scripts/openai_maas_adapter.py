#!/usr/bin/env python3
"""Transparent OpenAI Chat Completions proxy for a MaaS URL with fixed query params."""

from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_ENDPOINT = ""
DEFAULT_MODEL = "gpt-5.5"


def load_env_file(path: str) -> None:
    """Load only this adapter's variables without executing shell-formatted .env content."""
    try:
        lines = open(path, encoding="utf-8")
    except OSError:
        return
    with lines:
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.startswith("OPENAI_MAAS_"):
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))


class Handler(BaseHTTPRequestHandler):
    server_version = "EaselOpenAIMaaSAdapter/1.0"

    def send_json(self, status: int, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("", "/health"):
            self.send_json(200, {"ok": True})
        elif self.path.rstrip("/") == "/v1/models":
            model = os.environ.get("OPENAI_MAAS_MODEL", DEFAULT_MODEL)
            self.send_json(200, {"object": "list", "data": [{"id": model, "object": "model"}]})
        else:
            self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_json(404, {"error": {"message": "not found"}})
            return

        try:
            api_key = os.environ.get("OPENAI_MAAS_API_KEY", "")
            if not api_key:
                raise RuntimeError("OPENAI_MAAS_API_KEY is not configured")

            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length)
            request = Request(
                os.environ.get("OPENAI_MAAS_ENDPOINT", DEFAULT_ENDPOINT),
                data=raw_body,
                headers={
                    # Standard OpenAI-compatible authentication, configurable for
                    # gateways that require a different header (e.g. api-key).
                    os.environ.get("OPENAI_MAAS_API_KEY_HEADER", "Authorization"): (
                        f"Bearer {api_key}" if os.environ.get("OPENAI_MAAS_API_KEY_HEADER", "Authorization").lower() == "authorization" else api_key
                    ),
                    "Content-Type": self.headers.get("Content-Type", "application/json"),
                    "Accept": self.headers.get("Accept", "*/*"),
                },
                method="POST",
            )

            # Internal MaaS should not inherit workstation-wide outbound proxies.
            with build_opener(ProxyHandler({})).open(request, timeout=600) as response:
                self.send_response(response.status)
                self.send_header(
                    "Content-Type",
                    response.headers.get("Content-Type", "application/json"),
                )
                self.send_header("Cache-Control", response.headers.get("Cache-Control", "no-cache"))
                request_id = response.headers.get("x-request-id")
                if request_id:
                    self.send_header("x-request-id", request_id)
                self.end_headers()

                # readline preserves SSE event boundaries and forwards each event immediately.
                while chunk := response.readline():
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except HTTPError as exc:
            detail = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(detail)))
            self.end_headers()
            self.wfile.write(detail)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (URLError, OSError, ValueError, RuntimeError) as exc:
            self.log_message("upstream adapter error: %s", exc)
            self.send_json(502, {"error": {"message": str(exc)}})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[openai-maas-adapter] {self.address_string()} {fmt % args}", flush=True)


class Server(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    port = args.port or int(os.environ.get("OPENAI_MAAS_ADAPTER_PORT", "18791"))
    Server((args.host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
