#!/usr/bin/env python3
"""Draw Chinese text on top of an existing image (for xhs cover / ending cards).

Typical use: user provides a real photo, we overlay a hook line as a cover card.

- Preserves aspect ratio; optional center-crop + resize to 3:4 (900x1200 default)
- Text box with semi-transparent backdrop for legibility
- Expects a CJK-capable font in assets/fonts/ (falls back to PIL default w/ warning)

Usage:
    python3 text_on_image.py INPUT OUTPUT --text "一句钩子" \
        [--position top|center|bottom] [--font PATH] [--size 72] \
        [--color "#FFFFFF"] [--bg "#000000AA"] [--fit 3x4]
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow required (pip install Pillow)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FONT_CANDIDATES = [
    REPO_ROOT / "assets" / "fonts" / "SourceHanSansCN-Bold.otf",
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
]


def load_font(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates: list[Path] = []
    if path:
        candidates.append(Path(path))
    candidates.extend(DEFAULT_FONT_CANDIDATES)
    for p in candidates:
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    print("WARN: no CJK font found, using PIL default (CJK may render as boxes)",
          file=sys.stderr)
    return ImageFont.load_default()


def fit_aspect(img: Image.Image, ratio: str) -> Image.Image:
    if not ratio:
        return img
    w_r, h_r = map(int, ratio.lower().replace("x", ":").split(":"))
    target = w_r / h_r
    w, h = img.size
    cur = w / h
    if abs(cur - target) < 0.01:
        return img
    if cur > target:  # too wide -> crop sides
        new_w = int(h * target)
        off = (w - new_w) // 2
        return img.crop((off, 0, off + new_w, h))
    # too tall -> crop top/bottom
    new_h = int(w / target)
    off = (h - new_h) // 2
    return img.crop((0, off, w, off + new_h))


def parse_color(s: str) -> tuple[int, int, int, int]:
    s = s.lstrip("#")
    if len(s) == 6:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        return r, g, b, 255
    if len(s) == 8:
        return (int(s[0:2], 16), int(s[2:4], 16),
                int(s[4:6], 16), int(s[6:8], 16))
    raise ValueError(f"bad color {s!r}")


def wrap_cjk(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines, buf = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(buf)
            buf = ""
            continue
        trial = buf + ch
        w = draw.textlength(trial, font=font)
        if w > max_width and buf:
            lines.append(buf)
            buf = ch
        else:
            buf = trial
    if buf:
        lines.append(buf)
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--text", required=True)
    ap.add_argument("--position", choices=("top", "center", "bottom"),
                    default="bottom")
    ap.add_argument("--font", default=None)
    ap.add_argument("--size", type=int, default=72)
    ap.add_argument("--color", default="#FFFFFF")
    ap.add_argument("--bg", default="#000000AA",
                    help="backdrop color w/ alpha; empty to disable")
    ap.add_argument("--fit", default="3:4",
                    help="target aspect ratio, e.g. 3:4; empty to skip")
    ap.add_argument("--padding", type=int, default=48)
    args = ap.parse_args()

    src = Image.open(args.input).convert("RGBA")
    src = fit_aspect(src, args.fit)
    W, H = src.size

    overlay = Image.new("RGBA", src.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_font(args.font, args.size)

    max_w = W - 2 * args.padding
    lines = wrap_cjk(args.text, font, max_w, draw)
    line_h = args.size + 12
    block_h = line_h * len(lines)

    if args.position == "top":
        y0 = args.padding
    elif args.position == "center":
        y0 = (H - block_h) // 2
    else:
        y0 = H - block_h - args.padding

    if args.bg:
        bg = parse_color(args.bg)
        draw.rectangle(
            (args.padding // 2, y0 - 24,
             W - args.padding // 2, y0 + block_h + 24),
            fill=bg,
        )

    color = parse_color(args.color)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        x = (W - w) / 2
        draw.text((x, y0 + i * line_h), line, font=font, fill=color)

    out = Image.alpha_composite(src, overlay).convert("RGB")
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.save(args.output, quality=92)
    print(f"OK: {args.output} ({W}x{H}, {len(lines)} line(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
