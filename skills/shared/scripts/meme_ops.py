#!/usr/bin/env python3
"""meme_ops.py — 表情包 / Meme 生成的确定性封装（Pillow）。

"表情包 / meme"类 SKILL（meme-generator）共用此脚本。经典上下大字（白字黑边）叠在图上，
或在图上/下加纯色配文条（中文常见"当…的时候"反应图格式）。中英文均支持，自动换行与字号自适应。

依赖：Pillow。中文字体自动探测。

子命令：
    make      生成表情包
    selftest  自检

用法举例：
    meme_ops.py make -i cat.jpg -o out.jpg --top "老板说" --bottom "这个需求很简单"
    meme_ops.py make -i react.jpg -o out.jpg --layout top-bar --caption "当我周一早上打开电脑"
    meme_ops.py selftest
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _find_font(explicit=None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            _die(f"字体不存在: {explicit}", 2)
        return explicit
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    _die("未找到字体，请用 --font 指定 .ttf/.ttc。", 2)
    return ""


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def _wrap(draw, text, font, max_w):
    """按最大宽度换行：含空格按词，其余按字符。返回行列表。"""
    text = text.strip()
    if not text:
        return []
    lines, cur = [], ""
    # 以空格分词但保留中文逐字
    tokens = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append(buf); buf = ""
            tokens.append(" ")
        elif ord(ch) > 0x2E7F:  # CJK 及全角 → 单字成 token
            if buf:
                tokens.append(buf); buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    for tk in tokens:
        trial = cur + tk
        w = draw.textlength(trial, font=font)
        if w <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur.rstrip())
            cur = tk.lstrip() if tk != " " else ""
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def _fit_font(draw, text, font_path, max_w, start_size, min_size=14, max_lines=4):
    """从 start_size 递减，直到文本换行后行数 ≤ max_lines。返回 (font, lines)。"""
    from PIL import ImageFont
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, max_w)
        if len(lines) <= max_lines:
            return font, lines
        size -= 2
    font = ImageFont.truetype(font_path, min_size)
    return font, _wrap(draw, text, font, max_w)


def _draw_block(draw, lines, font, img_w, y, fill, stroke_fill, stroke_w, align_top=True):
    """把多行文本居中绘制，返回占用的总高度。"""
    ascent, descent = font.getmetrics()
    lh = ascent + descent + 6
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        x = (img_w - w) / 2
        yy = y + i * lh
        draw.text((x, yy), line, font=font, fill=fill,
                  stroke_width=stroke_w, stroke_fill=stroke_fill)
    return len(lines) * lh


def cmd_make(a) -> int:
    from PIL import Image, ImageDraw
    src = _require(a.input)
    out = _prep_out(a.output)
    font_path = _find_font(a.font)
    im = Image.open(src).convert("RGB")
    W, H = im.size
    upper = not a.no_upper

    def prep(t):
        if not t:
            return t
        return t.upper() if upper else t

    if a.layout == "overlay":
        draw = ImageDraw.Draw(im)
        max_w = int(W * 0.92)
        base = max(20, int(W / 9))
        stroke = a.stroke if a.stroke is not None else max(2, base // 12)
        if a.top:
            font, lines = _fit_font(draw, prep(a.top), font_path, max_w, base)
            _draw_block(draw, lines, font, W, int(H * 0.03), "white", "black", stroke)
        if a.bottom:
            font, lines = _fit_font(draw, prep(a.bottom), font_path, max_w, base)
            ascent, descent = font.getmetrics()
            lh = ascent + descent + 6
            total = len(lines) * lh
            _draw_block(draw, lines, font, W, H - total - int(H * 0.03),
                        "white", "black", stroke)
        result = im
    else:  # top-bar / bottom-bar：加纯色配文条
        cap = a.caption or a.top or a.bottom
        if not cap:
            _die("bar 布局需要 --caption（或 --top/--bottom）。", 2)
        tmp = Image.new("RGB", (10, 10))
        d0 = ImageDraw.Draw(tmp)
        max_w = int(W * 0.92)
        base = max(20, int(W / 14))
        font, lines = _fit_font(d0, cap, font_path, max_w, base, max_lines=3)
        ascent, descent = font.getmetrics()
        lh = ascent + descent + 6
        pad = int(H * 0.03)
        bar_h = len(lines) * lh + pad * 2
        bar = Image.new("RGB", (W, bar_h), a.bar_color)
        bd = ImageDraw.Draw(bar)
        _draw_block(bd, lines, font, W, pad, a.text_color, None, 0)
        if a.layout == "top-bar":
            result = Image.new("RGB", (W, H + bar_h), a.bar_color)
            result.paste(bar, (0, 0)); result.paste(im, (0, bar_h))
        else:
            result = Image.new("RGB", (W, H + bar_h), a.bar_color)
            result.paste(im, (0, 0)); result.paste(bar, (0, H))

    if out.suffix.lower() in (".jpg", ".jpeg"):
        result.save(out, quality=92)
    else:
        result.save(out)
    _done(out, f"({a.layout} · {result.size[0]}x{result.size[1]})")
    return 0


def cmd_selftest(_a) -> int:
    print("meme_ops 自检 ...", file=sys.stderr)
    from PIL import Image
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        src = d / "base.jpg"
        Image.new("RGB", (600, 500), (90, 140, 200)).save(src)

        # 经典上下字（中英混合，测换行）
        out1 = d / "overlay.jpg"
        cmd_make(argparse.Namespace(input=str(src), output=str(out1), layout="overlay",
                                    top="老板说这个需求很简单", bottom="one more thing before friday",
                                    caption=None, font=None, stroke=None, no_upper=False,
                                    bar_color="white", text_color="black"))
        assert Image.open(out1).size == (600, 500), "overlay 尺寸应不变"

        # 顶部配文条（应变高）
        out2 = d / "topbar.jpg"
        cmd_make(argparse.Namespace(input=str(src), output=str(out2), layout="top-bar",
                                    top=None, bottom=None,
                                    caption="当我周一早上打开电脑看到一堆消息的时候",
                                    font=None, stroke=None, no_upper=False,
                                    bar_color="white", text_color="black"))
        assert Image.open(out2).size[1] > 500, "top-bar 应增加高度"

        # 底部配文条
        out3 = d / "botbar.png"
        cmd_make(argparse.Namespace(input=str(src), output=str(out3), layout="bottom-bar",
                                    top=None, bottom=None, caption="这就是生活",
                                    font=None, stroke=None, no_upper=False,
                                    bar_color="black", text_color="white"))
        assert Image.open(out3).size[1] > 500, "bottom-bar 应增加高度"

    print("✅ selftest 全部通过（overlay 上下字 + top-bar/bottom-bar 配文条）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="表情包 / Meme 生成（Pillow，上下大字 / 配文条）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("make", help="生成表情包")
    p.add_argument("-i", "--input", required=True, help="底图")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--layout", default="overlay",
                   choices=["overlay", "top-bar", "bottom-bar"],
                   help="overlay 上下字叠图(默认) / top-bar 顶部配文条 / bottom-bar 底部配文条")
    p.add_argument("--top", help="顶部文字（overlay）")
    p.add_argument("--bottom", help="底部文字（overlay）")
    p.add_argument("--caption", help="配文（bar 布局用）")
    p.add_argument("--stroke", type=int, help="描边粗细（overlay，默认按字号自适应）")
    p.add_argument("--no-upper", action="store_true", help="不把英文转大写（默认转）")
    p.add_argument("--bar-color", default="white", help="配文条底色（bar 布局，默认白）")
    p.add_argument("--text-color", default="black", help="配文条文字色（bar 布局，默认黑）")
    p.add_argument("--font", help="字体路径（默认自动探测 CJK 粗体）")
    p.set_defaults(func=cmd_make)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
