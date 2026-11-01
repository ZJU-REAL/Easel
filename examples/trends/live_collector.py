"""Real public API collectors. No fixtures, API keys or Easel imports required.

python -X utf8 live_collector.py --provider hackernews --limit 20
python -X utf8 live_collector.py --provider github --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone

PROVIDERS = {
    "hackernews": "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=",
    "github": "https://api.github.com/repos/cli/cli/releases?per_page=",
}


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={
        "User-Agent": "Easel-public-collector-example/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("upstream response exceeds 2 MiB")
        return json.loads(raw.decode("utf-8"))


def collect(provider: str = "hackernews", limit: int = 20) -> dict:
    if provider not in PROVIDERS or not 1 <= limit <= 30:
        raise ValueError("unsupported provider or limit")
    data = fetch_json(PROVIDERS[provider] + str(limit))
    items = []
    if provider == "hackernews":
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise ValueError("unexpected Hacker News response")
        for hit in data["hits"]:
            if not hit.get("title"):
                continue
            identifier = str(hit["objectID"])
            points = hit.get("points")
            items.append({"id": identifier, "title": hit["title"],
                          "url": hit.get("url") or f"https://news.ycombinator.com/item?id={identifier}",
                          "published_at": hit.get("created_at"),
                          "heat": {"value": points, "text": str(points) if points is not None else "",
                                   "unit": "points"}})
    else:
        if not isinstance(data, list):
            raise ValueError("unexpected GitHub releases response")
        for release in data:
            if release.get("draft"):
                continue
            downloads = sum(asset.get("download_count", 0) for asset in release.get("assets", []))
            name = release.get("name") or release["tag_name"]
            title = name if name.startswith("GitHub CLI ") else "GitHub CLI " + name
            items.append({"id": str(release["id"]), "title": title,
                          "url": release["html_url"], "published_at": release.get("published_at"),
                          "heat": {"value": downloads, "text": f"{downloads:,} 次下载", "unit": "downloads"}})
    return {"version": 1, "fetched_at": datetime.now(timezone.utc).isoformat(), "items": items}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=PROVIDERS, default="hackernews")
    parser.add_argument("--limit", type=int, default=20, choices=range(1, 31), metavar="1..30")
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.provider, args.limit), ensure_ascii=False, allow_nan=False))
        return 0
    except Exception as error:
        # Avoid logging URLs with credentials or inherited environment values.
        print(f"{args.provider}: live collection failed ({type(error).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
