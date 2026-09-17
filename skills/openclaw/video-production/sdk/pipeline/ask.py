#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频产线 SDK · 问询卡面与问题协议工具

--emit   汇总待作答问题 -> <run-dir>/questions.json（交宿主渲染）
--serve  起本地卡面（默认 8898，占用自动 +1）-> 作答落 answers/<id>.json

协议是脊柱，界面只是渲染器：任何宿主只要能读 questions.json、写 answers/<id>.json，
就完成了对接（Easel 映射到 ask_user 卡片同理）。
"""
import argparse
import json
import re
import socket
import sys
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parent.parent
QID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def pending(rd: Path):
    qs = []
    for p in sorted((rd / "questions").glob("*.json")):
        if (rd / "answers" / p.name).exists():
            continue
        try:
            qs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return qs


def cmd_emit(rd: Path) -> int:
    qs = pending(rd)
    tgt = rd / "questions.json"
    tgt.write_text(json.dumps({"run_dir": str(rd), "generated_at": now_iso(), "questions": qs},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(qs)} 道待作答 -> {tgt}")
    return 0


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, run_dir: Path, cards: Path, **kw):
        self.run_dir = run_dir
        self.cards = cards
        super().__init__(*a, directory=str(run_dir), **kw)

    def _send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, self.cards.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/questions.json":
            data = {"questions": pending(self.run_dir), "generated_at": now_iso()}
            self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
            return
        if self.path == "/healthz":
            self._send(200, b"ok", "text/plain")
            return
        return super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path != "/answer":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:  # noqa: BLE001
            self.send_error(400)
            return
        qid = str(body.get("id") or "").strip()
        if not QID_RE.match(qid):
            self.send_error(400)
            return
        rec = {
            "id": qid,
            "values": body.get("values") or [],
            "notes": body.get("notes") or "",
            "answered_by": "card-serve",
            "answered_at": now_iso(),
        }
        (self.run_dir / "answers").mkdir(exist_ok=True)
        (self.run_dir / "answers" / f"{qid}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self._send(200, json.dumps({"ok": True}).encode(), "application/json")

    def log_message(self, *a):  # 静默
        pass


def cmd_serve(rd: Path, base_port: int) -> int:
    cards = SDK_ROOT / "assets" / "cards" / "index.html"
    if not cards.is_file():
        print(f"缺卡面文件：{cards}", file=sys.stderr)
        return 1
    BLACKLIST = {3000, 3001, 3002, 7860, 18789, 8822, 8899}  # 端口矩阵：不占
    port = base_port
    for _ in range(40):
        if port in BLACKLIST:
            port += 1
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                break
            except OSError:
                port += 1
    else:
        print("找不到可用端口", file=sys.stderr)
        return 1
    srv = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, run_dir=rd, cards=cards))
    print(f"卡面已起：http://127.0.0.1:{port}/  （作答落 {rd / 'answers'}）")
    print("提交后回终端/聊天执行 run.py resume 继续。Ctrl+C 停。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=8898)
    args = ap.parse_args()
    rd = Path(args.run_dir).resolve()
    if args.serve:
        sys.exit(cmd_serve(rd, args.port))
    sys.exit(cmd_emit(rd))


if __name__ == "__main__":
    main()
