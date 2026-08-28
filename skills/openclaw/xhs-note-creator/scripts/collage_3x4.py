#!/usr/bin/env python3
"""Compose 2-4 user-provided images into a single 3:4 card (900x1200 by default).

Layouts:
- 2v : two images stacked vertically (top/bottom)
- 2h : two images side by side (left/right) -- rare for 3:4, use for narrow pairs
- 3  : one big on top + two small on bottom (2:1 + 1:1 + 1:1)
- 4  : 2x2 grid

Usage:
    python3 collage_3x4.py OUTPUT --layout 2v --inputs a.jpg b.jpg [--gap 12] \
        [--bg "#FFFFFF"] [--size 900x1200]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow required", file=sys.stderr)
    sys.exit(2)


def parse_size(s: str) -> tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def parse_color(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    src_w, src_h = img.size
    tgt = w / h
    cur = src_w / src_h
    if cur > tgt:
        new_w = int(src_h * tgt)
        off = (src_w - new_w) // 2
        img = img.crop((off, 0, off + new_w, src_h))
    else:
        new_h = int(src_w / tgt)
        off = (src_h - new_h) // 2
        img = img.crop((0, off, src_w, off + new_h))
    return img.resize((w, h), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--layout", required=True,
                    choices=("2v", "2h", "3", "4"))
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--gap", type=int, default=12)
    ap.add_argument("--bg", default="#FFFFFF")
    ap.add_argument("--size", default="900x1200")
    args = ap.parse_args()

    W, H = parse_size(args.size)
    canvas = Image.new("RGB", (W, H), parse_color(args.bg))
    gap = args.gap
    imgs = [Image.open(p).convert("RGB") for p in args.inputs]

    need = {"2v": 2, "2h": 2, "3": 3, "4": 4}[args.layout]
    if len(imgs) != need:
        print(f"ERROR: layout {args.layout} needs {need} inputs, got {len(imgs)}",
              file=sys.stderr)
        return 1

    if args.layout == "2v":
        h_each = (H - gap) // 2
        canvas.paste(fit_cover(imgs[0], W, h_each), (0, 0))
        canvas.paste(fit_cover(imgs[1], W, h_each), (0, h_each + gap))
    elif args.layout == "2h":
        w_each = (W - gap) // 2
        canvas.paste(fit_cover(imgs[0], w_each, H), (0, 0))
        canvas.paste(fit_cover(imgs[1], w_each, H), (w_each + gap, 0))
    elif args.layout == "3":
        top_h = int(H * 2 / 3) - gap // 2
        bot_h = H - top_h - gap
        w_each = (W - gap) // 2
        canvas.paste(fit_cover(imgs[0], W, top_h), (0, 0))
        canvas.paste(fit_cover(imgs[1], w_each, bot_h), (0, top_h + gap))
        canvas.paste(fit_cover(imgs[2], w_each, bot_h),
                     (w_each + gap, top_h + gap))
    else:  # 4
        w_each = (W - gap) // 2
        h_each = (H - gap) // 2
        positions = [(0, 0), (w_each + gap, 0),
                     (0, h_each + gap), (w_each + gap, h_each + gap)]
        for im, pos in zip(imgs, positions):
            canvas.paste(fit_cover(im, w_each, h_each), pos)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, quality=92)
    print(f"OK: {args.output} ({W}x{H}, layout={args.layout})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
