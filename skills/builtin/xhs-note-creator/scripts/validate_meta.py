#!/usr/bin/env python3
"""Validate a Xiaohongshu meta.json against the schema in references/meta-schema.md.

Checks (fatal unless noted). Common to both post_format:
- JSON parses
- required top-level: title, platform=="小红书", created_at, caption, hashtags
- title length: 1..30 (warn if >20)
- caption length: 100..300 (code points)
- hashtags: 5..8 items, each startswith "#"

post_format == "image" (default when field absent):
- card_count + cards required
- card_count == len(cards) and in 3..9
- cards[0].type == "cover", cards[-1].type == "ending", middle all "content"
- every card: (title or content non-empty), cp_len(title)+cp_len(content) <= 80

post_format == "video":
- shots[] required, 6..12 items
- cards[] optional; if present, exactly 1 item with type=="cover"
- every shot: index int, duration_sec > 0, narration/on_screen_text/visual non-empty,
  cp_len(narration) <= 30, cp_len(on_screen_text) <= 15

Exit 0 clean, 1 on errors. Prints one "ERROR:" / "WARN:" per line.

Usage: python3 validate_meta.py path/to/meta.json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def cp_len(s: str) -> int:
    return len(s or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验小红书图文/视频 meta.json")
    parser.add_argument("meta", help="meta.json 路径")
    args = parser.parse_args()
    p = Path(args.meta)
    errors: list[str] = []
    warns: list[str] = []

    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: cannot parse json: {e}")
        return 1

    def err(m): errors.append(m)
    def warn(m): warns.append(m)

    for k in ("title", "platform", "created_at", "caption", "hashtags"):
        if k not in meta:
            err(f"missing field: {k}")

    if meta.get("platform") != "小红书":
        err(f"platform must be '小红书', got {meta.get('platform')!r}")

    post_format = meta.get("post_format", "image")
    if post_format not in ("image", "video"):
        err(f"post_format must be 'image' or 'video', got {post_format!r}")

    title = meta.get("title", "")
    if not title:
        err("title empty")
    elif cp_len(title) > 30:
        err(f"title too long ({cp_len(title)} > 30)")
    elif cp_len(title) > 20:
        warn(f"title {cp_len(title)} chars; Xiaohongshu feed prefers 10-20")

    cap = meta.get("caption", "")
    cl = cp_len(cap)
    if cl < 100:
        err(f"caption too short ({cl} < 100)")
    elif cl > 300:
        err(f"caption too long ({cl} > 300)")

    tags = meta.get("hashtags", [])
    if not isinstance(tags, list) or not (5 <= len(tags) <= 8):
        err(f"hashtags must have 5..8 items, got {len(tags) if isinstance(tags, list) else 'n/a'}")
    else:
        for t in tags:
            if not (isinstance(t, str) and t.startswith("#")):
                err(f"hashtag must be string starting with '#': {t!r}")

    if post_format == "image":
        if "card_count" not in meta:
            err("missing field: card_count (required for post_format=image)")
        if "cards" not in meta:
            err("missing field: cards (required for post_format=image)")
        cards = meta.get("cards", [])
        count = meta.get("card_count")
        if not isinstance(cards, list):
            err("cards must be list")
        else:
            if count is not None and count != len(cards):
                err(f"card_count={count} != len(cards)={len(cards)}")
            if not (3 <= len(cards) <= 9):
                err(f"cards count must be 3..9, got {len(cards)}")
            for i, c in enumerate(cards):
                t = c.get("type")
                if i == 0 and t != "cover":
                    err(f"cards[0].type must be 'cover', got {t!r}")
                elif i == len(cards) - 1 and t != "ending":
                    err(f"cards[-1].type must be 'ending', got {t!r}")
                elif 0 < i < len(cards) - 1 and t != "content":
                    err(f"cards[{i}].type must be 'content', got {t!r}")
                total = cp_len(c.get("title", "")) + cp_len(c.get("content", ""))
                if total == 0:
                    err(f"cards[{i}] has empty title+content")
                if total > 80:
                    err(f"cards[{i}] over 80 chars ({total})")
    else:  # video
        shots = meta.get("shots", [])
        if not isinstance(shots, list) or not shots:
            err("shots must be non-empty list for post_format=video")
        else:
            if not (6 <= len(shots) <= 12):
                err(f"shots count must be 6..12, got {len(shots)}")
            for i, s in enumerate(shots):
                if not isinstance(s.get("index"), int):
                    err(f"shots[{i}].index must be int")
                d = s.get("duration_sec")
                if not (isinstance(d, (int, float)) and d > 0):
                    err(f"shots[{i}].duration_sec must be > 0")
                for k, limit in (("narration", 30), ("on_screen_text", 15)):
                    v = s.get(k, "")
                    if not v:
                        err(f"shots[{i}].{k} empty")
                    elif cp_len(v) > limit:
                        err(f"shots[{i}].{k} over {limit} chars ({cp_len(v)})")
                if not s.get("visual"):
                    err(f"shots[{i}].visual empty")
        cards = meta.get("cards")
        if cards is not None:
            if not (isinstance(cards, list) and len(cards) == 1
                    and cards[0].get("type") == "cover"):
                err("for post_format=video, cards must be omitted or a single cover card")

    for w in warns:
        print(f"WARN:  {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print(f"\n{len(errors)} error(s), {len(warns)} warning(s)")
        return 1
    print(f"OK ({len(warns)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
