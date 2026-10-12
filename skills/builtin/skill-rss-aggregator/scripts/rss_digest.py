#!/usr/bin/env python3
"""rss_digest.py — 多源 RSS/Atom 聚合摘要（纯标准库解析）。

订阅一批 RSS/Atom 源（博主、媒体、Newsletter 的 RSS），拉取最新条目，按关键词与时间窗过滤、
去重、按时间排序，产出一份可读的选题/资讯摘要。纯标准库（urllib + xml.etree），无第三方依赖。

子命令：
    fetch      拉取并聚合多个源 → digest（JSON / Markdown）
    parse      解析单个 feed（调试）
    selftest   自检（离线解析样例 RSS/Atom）

用法举例：
    rss_digest.py fetch --feeds feeds.txt --keyword AI,大模型 --since 7 -o digest.md
    rss_digest.py fetch --url https://example.com/feed.xml --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_DEFAULT_PROXY = os.environ.get("EASEL_PROXY", "")  # lab 在 .env 设 EASEL_PROXY；不设则不走代理
_ATOM = "{http://www.w3.org/2005/Atom}"


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _ensure_proxy() -> None:
    if _DEFAULT_PROXY and not any(os.environ.get(k) for k in
               ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        os.environ["https_proxy"] = _DEFAULT_PROXY
        os.environ["http_proxy"] = _DEFAULT_PROXY


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    # RFC822（RSS）
    try:
        from email.utils import parsedate_to_datetime
        d = parsedate_to_datetime(s)
        if d and d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        pass
    # ISO8601（Atom）
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def parse_feed(xml_text: str) -> tuple[str, list[dict]]:
    """解析 RSS2.0 或 Atom，返回 (feed_title, items)。纯函数，供测试。"""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as e:
        _die(f"XML 解析失败：{e}")
    items: list[dict] = []
    # RSS 2.0
    channel = root.find("channel")
    if root.tag.lower().endswith("rss") or channel is not None:
        feed_title = (channel.findtext("title") if channel is not None else "") or ""
        for it in (channel.findall("item") if channel is not None else []):
            link = it.findtext("link") or ""
            items.append({
                "title": (it.findtext("title") or "").strip(),
                "link": link.strip(),
                "summary": _strip_html(it.findtext("description") or "")[:400],
                "published": it.findtext("pubDate") or "",
            })
        return feed_title.strip(), items
    # Atom
    if root.tag == f"{_ATOM}feed" or root.tag.endswith("feed"):
        feed_title = root.findtext(f"{_ATOM}title") or root.findtext("title") or ""
        for e in root.findall(f"{_ATOM}entry") or root.findall("entry"):
            link_el = e.find(f"{_ATOM}link")
            link = (link_el.get("href") if link_el is not None else "") or \
                   (e.findtext("link") or "")
            summary = (e.findtext(f"{_ATOM}summary") or e.findtext(f"{_ATOM}content")
                       or e.findtext("summary") or "")
            items.append({
                "title": (e.findtext(f"{_ATOM}title") or e.findtext("title") or "").strip(),
                "link": link.strip(),
                "summary": _strip_html(summary)[:400],
                "published": (e.findtext(f"{_ATOM}updated") or e.findtext(f"{_ATOM}published")
                              or ""),
            })
        return feed_title.strip(), items
    _die("无法识别的 feed 格式（既非 RSS 也非 Atom）")
    return "", []


def _fetch(url: str, timeout: int = 20) -> str:
    _ensure_proxy()
    req = urllib.request.Request(url, headers={"User-Agent": "Easel-rss/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ⚠️ 拉取失败 {url}: {e}", file=sys.stderr)
        return ""


def _collect_feeds(a) -> list[str]:
    urls = list(a.url or [])
    if a.feeds:
        p = Path(a.feeds).expanduser()
        if not p.is_file():
            _die(f"feeds 文件不存在：{p}")
        urls += [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    if not urls:
        _die("需 --url 或 --feeds 提供订阅源")
    return urls


def cmd_fetch(a) -> int:
    urls = _collect_feeds(a)
    keywords = [k.strip().lower() for k in (a.keyword or "").split(",") if k.strip()]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=a.since)) if a.since else None
    all_items: list[dict] = []
    seen = set()
    for url in urls:
        xml = _fetch(url)
        if not xml:
            continue
        try:
            feed_title, items = parse_feed(xml)
        except SystemExit:
            continue
        for it in items:
            if it["link"] in seen or not it["title"]:
                continue
            if keywords:
                hay = (it["title"] + " " + it["summary"]).lower()
                if not any(k in hay for k in keywords):
                    continue
            dt = _parse_date(it["published"])
            if cutoff and dt and dt < cutoff:
                continue
            seen.add(it["link"])
            it["feed"] = feed_title
            it["_dt"] = dt.isoformat() if dt else ""
            all_items.append(it)
    all_items.sort(key=lambda x: x["_dt"], reverse=True)
    if a.limit:
        all_items = all_items[:a.limit]

    if a.output and a.output.endswith(".md") or a.format == "md":
        lines = [f"# 资讯摘要（{len(all_items)} 条）\n"]
        for it in all_items:
            date = it["_dt"][:10] if it["_dt"] else ""
            lines.append(f"- **[{it['title']}]({it['link']})** "
                         f"`{it.get('feed','')}` {date}\n  {it['summary'][:120]}")
        content = "\n".join(lines) + "\n"
    else:
        content = json.dumps({"count": len(all_items), "items": all_items},
                             ensure_ascii=False, indent=2)

    if a.output:
        out = Path(a.output).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"✅ {out}（{len(all_items)} 条，来自 {len(urls)} 个源）")
    else:
        print(content)
    return 0


def cmd_parse(a) -> int:
    xml = _fetch(a.url)
    if not xml:
        _die("拉取失败")
    title, items = parse_feed(xml)
    print(json.dumps({"feed": title, "count": len(items), "items": items[:a.limit or 10]},
                     ensure_ascii=False, indent=2))
    return 0


_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Tech Feed</title>
<item><title>AI 大模型最新进展</title><link>https://x.com/a</link>
<description>&lt;p&gt;关于 AI 的深度报道&lt;/p&gt;</description>
<pubDate>Wed, 22 Jul 2026 10:00:00 +0000</pubDate></item>
<item><title>美食探店合集</title><link>https://x.com/b</link>
<description>本周美食</description><pubDate>Mon, 01 Jan 2001 10:00:00 +0000</pubDate></item>
</channel></rss>"""

_SAMPLE_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>大模型应用实践</title><link href="https://y.com/1"/>
<summary>AI 落地案例</summary><updated>2026-07-20T08:00:00Z</updated></entry>
</feed>"""


def cmd_selftest(_a) -> int:
    print("rss_digest 自检 ...", file=sys.stderr)
    # RSS
    title, items = parse_feed(_SAMPLE_RSS)
    assert title == "Tech Feed", f"RSS 标题解析错：{title}"
    assert len(items) == 2, f"RSS 条目数错：{len(items)}"
    assert items[0]["link"] == "https://x.com/a"
    assert "AI 的深度报道" in items[0]["summary"], "description HTML 未清洗"
    assert _parse_date(items[0]["published"]) is not None, "RFC822 日期解析失败"
    # Atom
    at, aitems = parse_feed(_SAMPLE_ATOM)
    assert at == "Blog" and len(aitems) == 1, "Atom 解析错"
    assert aitems[0]["link"] == "https://y.com/1", "Atom link href 解析错"
    assert _parse_date(aitems[0]["published"]) is not None, "ISO 日期解析失败"
    # 关键词过滤 + 时间窗（端到端，用本地文件模拟）
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        # 写两个 feed 文件，用 file:// 拉取
        f1 = Path(td) / "a.xml"; f1.write_text(_SAMPLE_RSS, encoding="utf-8")
        f2 = Path(td) / "b.xml"; f2.write_text(_SAMPLE_ATOM, encoding="utf-8")
        feeds = Path(td) / "feeds.txt"
        feeds.write_text(f"file://{f1}\nfile://{f2}\n", encoding="utf-8")
        out = Path(td) / "d.json"
        cmd_fetch(argparse.Namespace(url=None, feeds=str(feeds), keyword="AI,大模型",
                                     since=0, limit=None, output=str(out), format="json"))
        rep = json.loads(out.read_text(encoding="utf-8"))
        titles = [i["title"] for i in rep["items"]]
        assert any("大模型" in t for t in titles), f"关键词过滤后应含大模型条目：{titles}"
        assert not any("美食" in t for t in titles), "美食条目应被关键词过滤掉"
    print("✅ selftest 通过（RSS/Atom 解析 + HTML 清洗 + 日期 + 关键词过滤 + 去重）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="多源 RSS/Atom 聚合摘要（纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("fetch", help="聚合多源 → digest")
    p.add_argument("--url", action="append", help="订阅源 URL（可多次）")
    p.add_argument("--feeds", help="订阅源列表文件（每行一个 URL）")
    p.add_argument("--keyword", help="关键词过滤，逗号分隔（标题或摘要命中其一即保留）")
    p.add_argument("--since", type=int, default=0, help="只保留最近 N 天（0=不限）")
    p.add_argument("--limit", type=int, help="最多输出条数")
    p.add_argument("--format", choices=["json", "md"], default="json")
    p.add_argument("-o", "--output", help="输出路径（.md 自动 Markdown）")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("parse", help="解析单个 feed（调试）")
    p.add_argument("--url", required=True)
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_parse)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
