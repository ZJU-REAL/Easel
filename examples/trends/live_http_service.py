"""HTTP v1 adapter that fetches real public upstream data on every request.

python -X utf8 live_http_service.py --provider github --limit 10 --port 8766
Easel HTTP source URL: http://127.0.0.1:8766/trends
The upstream requests follow the standard proxy environment variables.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from live_collector import PROVIDERS, collect


def handler_for(provider: str, limit: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/trends":
                self.send_error(404)
                return
            try:
                body = json.dumps(collect(provider, limit), ensure_ascii=False, allow_nan=False).encode("utf-8")
            except Exception:
                self.send_error(502, "live upstream collection failed")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS, default="github")
    parser.add_argument("--limit", type=int, choices=range(1, 31), default=10, metavar="1..30")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(args.provider, args.limit)).serve_forever()
