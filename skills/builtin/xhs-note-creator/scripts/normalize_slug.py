#!/usr/bin/env python3
"""Normalize a Chinese/English title into a file-system-safe slug.

Rules (aligned with references/output-spec.md):
- strip special chars 冒号/问号/感叹号/引号/斜杠/星号/尖括号/竖线/省略号/破折号
- replace space with "_"
- collapse consecutive "_"
- truncate to max 15 CJK-aware chars (default)
- emit slug on stdout; never exit non-zero on normal input

Usage:
    python3 normalize_slug.py "GPT-5.4深夜炸场：OpenAI 大一统模型来了" [--max 15]
    python3 normalize_slug.py --timestamp   # just print YYYYMMDDHHmm in Asia/Shanghai
    python3 normalize_slug.py "..." --with-ts   # "<slug>_YYYYMMDDHHmm"
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import datetime, timezone, timedelta

STRIP_CHARS = '：:？?！!""' + "''" + "/\\*<>|"
STRIP_SEQS = ("……", "...", "——", "--")
SHANGHAI = timezone(timedelta(hours=8))


def shanghai_ts() -> str:
    return datetime.now(SHANGHAI).strftime("%Y%m%d%H%M")


def normalize(title: str, max_chars: int = 15) -> str:
    s = title.strip()
    for seq in STRIP_SEQS:
        s = s.replace(seq, "_")
    s = "".join("_" if c in STRIP_CHARS else c for c in s)
    s = s.replace(" ", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    # CJK-aware truncation by code point count
    if len(s) > max_chars:
        s = s[:max_chars].rstrip("_")
    return s or "untitled"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("title", nargs="?", default="")
    p.add_argument("--max", type=int, default=15)
    p.add_argument("--timestamp", action="store_true",
                   help="only print YYYYMMDDHHmm")
    p.add_argument("--with-ts", action="store_true",
                   help="append _YYYYMMDDHHmm")
    args = p.parse_args()

    if args.timestamp:
        print(shanghai_ts())
        return 0
    if not args.title:
        print("error: title required", file=sys.stderr)
        return 2
    slug = normalize(args.title, args.max)
    if args.with_ts:
        slug = f"{slug}_{shanghai_ts()}"
    print(slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
