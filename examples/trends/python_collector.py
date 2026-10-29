"""Runnable stdlib-only example. Replace collect() with your own collection logic.

Run: python -X utf8 examples/trends/python_collector.py
stdout: exactly one UTF-8 JSON document; diagnostic messages go to stderr.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def collect() -> list[dict]:
    # Fetch an API, parse RSS, query a database, or use your own browser here.
    # Return [] only for a successful collection with no results.
    # Raise on collection failure so Easel can retain the previous good result.
    return [{
        "id": "example-topic-1",
        "title": "示例热点：替换 collect() 即可接入自己的数据",
        "url": "https://example.com/topics/1",
        "published_at": None,
        "heat": {"value": 12345, "text": "1.23万", "unit": "阅读"},
    }]


def main() -> int:
    try:
        items = collect()
        # Use the actual data collection time if your upstream is itself cached.
        payload = {"version": 1, "fetched_at": datetime.now(timezone.utc).isoformat(), "items": items}
        print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        return 0
    except Exception:
        # Put useful diagnostics here, but never print credentials.
        print("collection failed; check your upstream and local configuration", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
