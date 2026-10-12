#!/usr/bin/env python3
"""Crop edge watermark off an image (deterministic wrapper over PIL).

Usage:
    python3 crop_watermark.py INPUT OUTPUT --edge bottom --pixels 40
    python3 crop_watermark.py INPUT OUTPUT --box LEFT TOP RIGHT BOTTOM
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--edge", choices=("top", "bottom", "left", "right"))
    ap.add_argument("--pixels", type=int, default=40)
    ap.add_argument("--box", nargs=4, type=int,
                    metavar=("L", "T", "R", "B"),
                    help="absolute crop box (overrides --edge)")
    args = ap.parse_args()

    img = Image.open(args.input)
    w, h = img.size

    if args.box:
        box = tuple(args.box)
    elif args.edge == "bottom":
        box = (0, 0, w, max(0, h - args.pixels))
    elif args.edge == "top":
        box = (0, min(h, args.pixels), w, h)
    elif args.edge == "left":
        box = (min(w, args.pixels), 0, w, h)
    elif args.edge == "right":
        box = (0, 0, max(0, w - args.pixels), h)
    else:
        print("ERROR: provide --edge or --box", file=sys.stderr)
        return 2

    out = img.crop(box)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.output, quality=92)
    print(f"OK: {args.output} ({w}x{h} -> {out.size[0]}x{out.size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
