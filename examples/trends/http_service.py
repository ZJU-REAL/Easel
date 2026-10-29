"""Local demo HTTP collector (stdlib only), bound to loopback.

Run in this directory: python -X utf8 http_service.py --port 8766
Optional: set DEMO_TREND_TOKEN to require Authorization: Bearer <token>.
GET /trends and POST /trends return the same v1 contract as python_collector.py.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from python_collector import collect


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/trends":
            self.send_error(404)
            return
        token = os.environ.get("DEMO_TREND_TOKEN", "")
        if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
            self.send_error(401)
            return
        try:
            payload = {"version": 1, "fetched_at": datetime.now(timezone.utc).isoformat(), "items": collect()}
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except Exception:
            self.send_error(502, "collection failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Consume a small demo JSON body; a production service should validate its own inputs.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise ValueError()
            if length:
                json.loads(self.rfile.read(length))
        except ValueError:
            self.send_error(400)
            return
        self.do_GET()

    def log_message(self, format, *args):
        # Avoid logging URLs, request bodies or Authorization headers in the demo.
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
