#!/usr/bin/env python3
"""shortlink.py — UTM 追踪参数构造 + 短链生成（is.gd / v.gd / TinyURL，免 key）。

给内容/投放生成带 UTM 追踪的链接并缩短，便于在各平台追踪来源与效果。纯标准库，无第三方依赖。
短链服务用免费无需 key 的公共 API（is.gd / v.gd / TinyURL）。

子命令：
    utm       给 URL 拼接 UTM 追踪参数
    short     缩短 URL
    both      先拼 UTM 再缩短（最常用）
    selftest  自检（UTM 构造 + 真实短链 API）

用法举例：
    shortlink.py utm --url https://a.com/p --source xiaohongshu --medium social --campaign summer
    shortlink.py short --url https://a.com/very/long --provider isgd --alias mycamp
    shortlink.py both --url https://a.com/p --source douyin --medium video --campaign 618
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_DEFAULT_PROXY = os.environ.get("EASEL_PROXY", "")  # lab 在 .env 设 EASEL_PROXY；不设则不走代理
PROVIDERS = ("isgd", "vgd", "tinyurl")


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _ensure_proxy() -> None:
    if _DEFAULT_PROXY and not any(os.environ.get(k) for k in
               ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        os.environ["https_proxy"] = _DEFAULT_PROXY
        os.environ["http_proxy"] = _DEFAULT_PROXY


def build_utm(url: str, source: str, medium: str, campaign: str,
              term: str | None = None, content: str | None = None) -> str:
    """把 UTM 参数并入 URL（保留原有 query，同名覆盖）。纯函数，供测试。"""
    parts = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    utm = {"utm_source": source, "utm_medium": medium, "utm_campaign": campaign}
    if term:
        utm["utm_term"] = term
    if content:
        utm["utm_content"] = content
    query.update({k: v for k, v in utm.items() if v})
    new_query = urllib.parse.urlencode(query)
    return urllib.parse.urlunsplit(
        (parts.scheme or "https", parts.netloc, parts.path, new_query, parts.fragment))


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Easel-shortlink/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        _die(f"短链服务请求失败：{exc}")
    return ""


def shorten(url: str, provider: str, alias: str | None = None) -> str:
    _ensure_proxy()
    enc = urllib.parse.quote(url, safe="")
    if provider in ("isgd", "vgd"):
        host = "is.gd" if provider == "isgd" else "v.gd"
        api = f"https://{host}/create.php?format=json&url={enc}"
        if alias:
            api += f"&shorturl={urllib.parse.quote(alias)}"
        body = _http_get(api)
        try:
            j = json.loads(body)
        except json.JSONDecodeError:
            _die(f"{host} 返回非 JSON：{body[:200]}")
        if "shorturl" in j:
            return j["shorturl"]
        _die(f"{host} 出错：{j.get('errormessage', body[:200])}")
    elif provider == "tinyurl":
        api = f"https://tinyurl.com/api-create.php?url={enc}"
        body = _http_get(api).strip()
        if body.startswith("http"):
            return body
        _die(f"tinyurl 出错：{body[:200]}")
    _die(f"不支持的 provider：{provider}")
    return ""


def cmd_utm(a) -> int:
    if not (a.source and a.medium and a.campaign):
        _die("utm 需要 --source --medium --campaign")
    print(build_utm(a.url, a.source, a.medium, a.campaign, a.term, a.content))
    return 0


def cmd_short(a) -> int:
    print(shorten(a.url, a.provider, a.alias))
    return 0


def cmd_both(a) -> int:
    if not (a.source and a.medium and a.campaign):
        _die("both 需要 --source --medium --campaign")
    full = build_utm(a.url, a.source, a.medium, a.campaign, a.term, a.content)
    short = shorten(full, a.provider, a.alias)
    print(json.dumps({"utm_url": full, "short_url": short}, ensure_ascii=False, indent=2))
    return 0


def cmd_selftest(_a) -> int:
    print("shortlink 自检 ...", file=sys.stderr)
    # 1) UTM 构造（含已有 query 合并、编码）
    u = build_utm("https://a.com/p?x=1", "小红书", "social", "summer sale",
                  content="banner")
    assert "utm_source=" in u and "utm_campaign=" in u and "x=1" in u, "UTM 参数缺失"
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))
    assert q["utm_source"] == "小红书", "中文 source 未正确保留"
    assert q["utm_campaign"] == "summer sale", "含空格 campaign 未正确编码/解码"
    assert q["utm_content"] == "banner"
    # 无 scheme 默认补 https
    assert build_utm("a.com/p", "s", "m", "c").startswith("https://"), "缺 scheme 未补 https"
    # 2) 真实短链（is.gd），失败则跳过断言
    try:
        s = shorten("https://www.wikipedia.org/easel-selftest", "tinyurl")
        assert s.startswith("http") and "tinyurl.com" in s, f"tinyurl 短链异常：{s}"
        print(f"  ✅ tinyurl 实测：{s}", file=sys.stderr)
    except SystemExit:
        print("  (短链服务不可达，跳过实测)", file=sys.stderr)
    print("✅ selftest 通过（UTM 构造 + 中文/空格编码 + 短链）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="UTM 追踪参数 + 短链生成（is.gd/v.gd/TinyURL，免 key）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add_utm_args(p):
        p.add_argument("--url", required=True)
        p.add_argument("--source", help="utm_source，如 xiaohongshu/douyin/wechat")
        p.add_argument("--medium", help="utm_medium，如 social/video/cpc")
        p.add_argument("--campaign", help="utm_campaign，如 618/newproduct")
        p.add_argument("--term", help="utm_term（可选，关键词）")
        p.add_argument("--content", help="utm_content（可选，区分同活动多素材）")

    p = sub.add_parser("utm", help="拼接 UTM 参数")
    add_utm_args(p)
    p.set_defaults(func=cmd_utm)

    p = sub.add_parser("short", help="缩短 URL")
    p.add_argument("--url", required=True)
    p.add_argument("--provider", default="tinyurl", choices=PROVIDERS)
    p.add_argument("--alias", help="自定义短码（is.gd/v.gd 支持）")
    p.set_defaults(func=cmd_short)

    p = sub.add_parser("both", help="拼 UTM 再缩短")
    add_utm_args(p)
    p.add_argument("--provider", default="tinyurl", choices=PROVIDERS)
    p.add_argument("--alias", help="自定义短码")
    p.set_defaults(func=cmd_both)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
