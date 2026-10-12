#!/usr/bin/env python3
"""notify.py — 发布通知推送（飞书/钉钉/企业微信/Telegram/Slack/通用 webhook）。

内容发布成功/失败后，把结果推送到团队 IM 群机器人或任意 webhook。纯标准库实现，无第三方依赖。

支持渠道：
    feishu     飞书/Lark 群机器人（text / 富文本 post）
    dingtalk   钉钉群机器人（text，支持加签 secret）
    wecom      企业微信群机器人（text）
    telegram   Telegram Bot（sendMessage，需 token + chat_id）
    slack      Slack Incoming Webhook
    generic    任意 webhook：发 {"text": ...} 或自定义 JSON

子命令：
    send       发送通知
    selftest   自检（各渠道 payload 构造 + 可选 httpbin 实测）

用法举例：
    notify.py send --channel feishu --webhook https://open.feishu.cn/... --text "已发布：本期视频"
    notify.py send --channel dingtalk --webhook https://oapi.dingtalk.com/... --secret SECxxx --text "..."
    notify.py send --channel telegram --token 123:ABC --chat-id 456 --text "..."
    notify.py send --channel generic --webhook https://example.com/hook --text "..." --dry-run
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_PROXY = os.environ.get("EASEL_PROXY", "")  # lab 在 .env 设 EASEL_PROXY；不设则不走代理
CHANNELS = ("feishu", "dingtalk", "wecom", "telegram", "slack", "generic")


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _ensure_proxy() -> None:
    if _DEFAULT_PROXY and not any(os.environ.get(k) for k in
               ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        os.environ["https_proxy"] = _DEFAULT_PROXY
        os.environ["http_proxy"] = _DEFAULT_PROXY


def _dingtalk_sign(secret: str) -> str:
    """钉钉加签：返回 &timestamp=..&sign=.. 查询串。"""
    ts = str(round(time.time() * 1000))
    string_to_sign = f"{ts}\n{secret}"
    h = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(h).decode())
    return f"&timestamp={ts}&sign={sign}"


def build_payload(channel: str, text: str, title: str | None) -> dict:
    """构造各渠道消息体（纯函数，供测试）。"""
    if channel == "feishu":
        if title:
            return {"msg_type": "post", "content": {"post": {"zh_cn": {
                "title": title,
                "content": [[{"tag": "text", "text": text}]]}}}}
        return {"msg_type": "text", "content": {"text": text}}
    if channel == "dingtalk":
        body = text if not title else f"{title}\n{text}"
        return {"msgtype": "text", "text": {"content": body}}
    if channel == "wecom":
        body = text if not title else f"{title}\n{text}"
        return {"msgtype": "text", "text": {"content": body}}
    if channel == "telegram":
        body = text if not title else f"*{title}*\n{text}"
        return {"text": body, "parse_mode": "Markdown"}  # chat_id 运行时补
    if channel == "slack":
        return {"text": text if not title else f"*{title}*\n{text}"}
    # generic
    return {"text": text if not title else f"{title}\n{text}"}


def _post_json(url: str, payload: dict, timeout: int = 20) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Easel-notify/0.1"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        _die(f"推送失败（网络）：{exc}")
    return 0, ""


def cmd_send(a) -> int:
    if a.channel not in CHANNELS:
        _die(f"--channel 需为 {CHANNELS} 之一")
    if not a.text:
        _die("--text 通知内容必填")

    if a.channel == "telegram":
        if not a.token or not a.chat_id:
            _die("telegram 需 --token 与 --chat-id")
        url = f"https://api.telegram.org/bot{a.token}/sendMessage"
        payload = build_payload("telegram", a.text, a.title)
        payload["chat_id"] = a.chat_id
    else:
        if not a.webhook:
            _die(f"{a.channel} 需 --webhook")
        url = a.webhook
        payload = build_payload(a.channel, a.text, a.title)
        if a.channel == "dingtalk" and a.secret:
            url += _dingtalk_sign(a.secret)

    if a.dry_run:
        print(json.dumps({"url": url.split("&sign=")[0], "payload": payload},
                         ensure_ascii=False, indent=2))
        return 0

    _ensure_proxy()
    status, body = _post_json(url, payload)
    ok = status == 200 and _is_ok(a.channel, body)
    print(f"{'✅' if ok else '⚠️'} HTTP {status} · {body[:200]}")
    return 0 if ok else 1


def _is_ok(channel: str, body: str) -> bool:
    """各家成功判定（尽力，返回体差异大时以 HTTP 200 为准）。"""
    try:
        j = json.loads(body)
    except Exception:
        return True  # 非 JSON 且 200 视为成功（slack 返回 "ok"）
    if channel in ("feishu",):
        return j.get("StatusCode", j.get("code", 0)) == 0
    if channel in ("dingtalk", "wecom"):
        return j.get("errcode", 0) == 0
    if channel == "telegram":
        return bool(j.get("ok", False))
    return True


def cmd_selftest(_a) -> int:
    print("notify 自检 ...", file=sys.stderr)
    # 1) payload 构造
    p = build_payload("feishu", "hello", None)
    assert p["msg_type"] == "text" and p["content"]["text"] == "hello"
    p = build_payload("feishu", "body", "标题")
    assert p["msg_type"] == "post", "飞书带标题应为 post 富文本"
    assert build_payload("dingtalk", "x", None)["msgtype"] == "text"
    assert build_payload("wecom", "x", None)["msgtype"] == "text"
    assert build_payload("slack", "x", None)["text"] == "x"
    assert build_payload("generic", "x", "T")["text"] == "T\nx"
    tg = build_payload("telegram", "x", None)
    assert tg["parse_mode"] == "Markdown"
    # 2) 钉钉签名格式
    sig = _dingtalk_sign("SECtest")
    assert sig.startswith("&timestamp=") and "&sign=" in sig, "钉钉签名格式错误"
    # 3) 尽力做一次真实 POST 到 httpbin（失败则跳过）
    try:
        _ensure_proxy()
        status, body = _post_json("https://httpbin.org/post",
                                  build_payload("generic", "easel-selftest", None),
                                  timeout=12)
        if status == 200 and "easel-selftest" in body:
            print("  ✅ httpbin 实测回显 OK", file=sys.stderr)
        else:
            print(f"  (httpbin 返回 {status}，跳过实测断言)", file=sys.stderr)
    except SystemExit:
        print("  (httpbin 不可达，跳过实测)", file=sys.stderr)
    print("✅ selftest 通过（6 渠道 payload 构造 + 钉钉签名）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="发布通知推送（飞书/钉钉/企微/Telegram/Slack/通用 webhook）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("send", help="发送通知")
    p.add_argument("--channel", required=True, choices=CHANNELS)
    p.add_argument("--webhook", help="webhook URL（telegram 除外）")
    p.add_argument("--text", help="通知正文")
    p.add_argument("--title", help="标题（可选）")
    p.add_argument("--secret", help="钉钉加签 secret（可选）")
    p.add_argument("--token", help="telegram bot token")
    p.add_argument("--chat-id", help="telegram chat id")
    p.add_argument("--dry-run", action="store_true", help="只打印将发送的 payload，不真发")
    p.set_defaults(func=cmd_send)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
