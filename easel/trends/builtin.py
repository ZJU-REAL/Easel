"""Bundled Python collector. It obeys exactly the same v1 stdout contract as user scripts."""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from easel.trends.protocol import MAX_BYTES, utc_now, validate_payload
from easel.timeouts import TIMEOUT_TREND_UPSTREAM

SOURCES: dict[str, tuple[str, str]] = {
    "weibo": ("https://v2.xxapi.cn/api/weibohot", "https://60s.viki.moe/v2/weibo"),
    "douyin": ("https://v2.xxapi.cn/api/douyinhot", "https://60s.viki.moe/v2/douyin"),
    "zhihu": ("https://api.zhihu.com/topstory/hot-list?limit=50", "https://60s.viki.moe/v2/zhihu"),
    "bilibili": ("https://v2.xxapi.cn/api/bilibilihot", "https://60s.viki.moe/v2/bili"),
    "baidu": ("https://v2.xxapi.cn/api/baiduhot", "https://60s.viki.moe/v2/baidu/hot"),
    "toutiao": ("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", "https://60s.viki.moe/v2/toutiao"),
}


def _pick(data: object, keys: tuple[str, ...]) -> str:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if type(value) in (int, float):
                return str(value)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def parse_upstream(obj: object) -> list[dict]:
    data = obj.get("data") if isinstance(obj, dict) else None
    if isinstance(data, dict):
        data = data.get("data") or data.get("list") or []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, str):
            item = {"title": item}
        if not isinstance(item, dict):
            continue
        target = item.get("target") if isinstance(item.get("target"), dict) else {}
        title = _pick(item, ("title", "Title", "word", "name", "keyword")) or _pick(target, ("title",))
        if not title:
            continue
        hot = _pick(item, ("hot", "hot_value", "HotValue", "hotValue", "num", "detail_text")) or _pick(target.get("metrics_area"), ("text",))
        url = _pick(item, ("url", "Url", "link", "mobil_url")) or _pick(target, ("url",))
        match = re.fullmatch(r"https?://api\.zhihu\.com/questions/(\d+)", url)
        if match:
            url = f"https://www.zhihu.com/question/{match.group(1)}"
        out.append({"title": title, "url": url, "heat": {"text": hot}})
    return out


def fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_TREND_UPSTREAM) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("upstream output too large")
        return json.loads(raw.decode("utf-8"))


def collect_platform(platform: str) -> dict:
    for url in SOURCES[platform]:
        try:
            items = parse_upstream(fetch_json(url))
            if items:
                payload = {"version": 1, "fetched_at": utc_now(), "items": items}
                validate_payload(payload)
                return payload
        except Exception:
            continue
    # An upstream outage must never look like a successful empty collection.
    raise RuntimeError("all upstream sources unavailable")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in SOURCES:
        print("usage: builtin.py <weibo|douyin|zhihu|bilibili|baidu|toutiao>", file=sys.stderr)
        return 2
    try:
        print(json.dumps(collect_platform(sys.argv[1]), ensure_ascii=False))
        return 0
    except Exception:
        print("all upstream sources unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
