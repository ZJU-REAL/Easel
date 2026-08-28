#!/usr/bin/env python3
"""image_ops.py — 通用图像处理的确定性封装（纯 Pillow + 标准库）。

所有"已有图片的处理加工"类 SKILL（image-editing 等）共用此脚本，把缩放/裁剪/
补边/转格式/压缩/水印/圆角/拼接/缩略图/取信息等操作固化为确定性命令，避免
LLM 现场写一次性脚本导致不稳定。

依赖：Pillow（`pip install Pillow`）。无需其他第三方库。

argparse 顶层 + 子命令，每个子命令都能 `-h`：
    resize     按宽/高/百分比缩放（可保持宽高比）
    crop       按坐标或居中裁剪到指定尺寸
    pad        补边到目标宽高比（1:1 / 9:16 / 16:9 ...，社媒适配）
    convert    格式转换（png/jpg/webp）
    compress   压缩到指定质量或目标文件大小上限（jpg/webp 质量循环逼近）
    watermark  文字水印（位置/透明度/字号）或图片水印（右下角等）
    round      圆角处理（输出带透明通道 png）
    collage    多图拼接（横向/纵向/网格 NxM）
    thumbnail  生成缩略图
    info       输出图片尺寸/格式/大小（json）

自检：
    image_ops.py --selftest      # 用 Pillow 生成测试图跑通关键子命令
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: 未安装 Pillow。请运行：pip install Pillow", file=sys.stderr)
    sys.exit(3)


# ── 通用工具 ────────────────────────────────────────────────────────────────

# 系统中文字体候选（找不到降级到 PIL 默认位图字体）
_CN_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # 无中文时的兜底拉丁字体
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _open(path: str) -> "Image.Image":
    p = Path(path)
    if not p.is_file():
        _die(f"文件不存在: {p}")
    try:
        return Image.open(p)
    except Exception as e:  # noqa: BLE001
        _die(f"无法打开图片 {p}: {e}")


def _load_font(font_path: str | None, size: int) -> "ImageFont.FreeTypeFont":
    """加载字体。优先用户指定 → 系统中文字体候选 → PIL 默认（并告警）。"""
    tried: list[str] = []
    if font_path:
        tried.append(font_path)
    tried.extend(_CN_FONT_CANDIDATES)
    for fp in tried:
        if fp and Path(fp).is_file():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:  # noqa: BLE001
                continue
    print("WARN: 未找到可用 TrueType 字体（含中文字体），降级到 PIL 默认位图字体，"
          "中文可能显示为方块。可用 --font 指定字体路径。", file=sys.stderr)
    return ImageFont.load_default()


def _parse_color(s: str) -> tuple:
    """解析颜色：#RRGGBB / #RRGGBBAA / r,g,b / r,g,b,a / 颜色名。"""
    s = s.strip()
    if "," in s:
        parts = [int(x) for x in s.split(",")]
        if len(parts) in (3, 4):
            return tuple(parts)
        _die(f"非法颜色: {s}")
    try:
        from PIL import ImageColor
        return ImageColor.getrgb(s) if not s.startswith("#") or len(s) != 9 \
            else ImageColor.getcolor(s, "RGBA")
    except Exception:  # noqa: BLE001
        _die(f"非法颜色: {s}")


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _save(img: "Image.Image", out: str, *, quality: int | None = None,
          fmt: str | None = None) -> None:
    _ensure_parent(out)
    save_kwargs: dict = {}
    ext = (fmt or Path(out).suffix.lstrip(".")).lower()
    if ext in ("jpg", "jpeg"):
        ext = "jpeg"
        if img.mode in ("RGBA", "P", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            img_rgb = img.convert("RGBA")
            bg.paste(img_rgb, mask=img_rgb.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
        save_kwargs["quality"] = quality if quality is not None else 90
        save_kwargs["optimize"] = True
    elif ext == "webp":
        save_kwargs["quality"] = quality if quality is not None else 90
    elif ext == "png":
        save_kwargs["optimize"] = True
    img.save(out, **save_kwargs)


def _report(out: str) -> None:
    kb = Path(out).stat().st_size / 1024
    w, h = Image.open(out).size
    print(f"✅ {out} ({w}x{h}, {kb:.0f} KB)")


# ── 子命令实现 ──────────────────────────────────────────────────────────────

def cmd_resize(args) -> int:
    img = _open(args.input)
    w0, h0 = img.size
    if args.percent is not None:
        if args.percent <= 0:
            _die("--percent 必须 > 0")
        w = max(1, round(w0 * args.percent / 100))
        h = max(1, round(h0 * args.percent / 100))
    elif args.width and args.height:
        if args.keep_ratio:
            # 在框内等比缩放
            ratio = min(args.width / w0, args.height / h0)
            w, h = max(1, round(w0 * ratio)), max(1, round(h0 * ratio))
        else:
            w, h = args.width, args.height
    elif args.width:
        ratio = args.width / w0
        w, h = args.width, max(1, round(h0 * ratio))
    elif args.height:
        ratio = args.height / h0
        w, h = max(1, round(w0 * ratio)), args.height
    else:
        _die("需要 --width / --height / --percent 之一")
    out_img = img.resize((w, h), Image.LANCZOS)
    _save(out_img, args.output, quality=args.quality)
    _report(args.output)
    return 0


def cmd_crop(args) -> int:
    img = _open(args.input)
    w0, h0 = img.size
    if args.box:
        try:
            l, t, r, b = [int(x) for x in args.box.split(",")]
        except Exception:  # noqa: BLE001
            _die("--box 格式应为 left,top,right,bottom")
        if not (0 <= l < r <= w0 and 0 <= t < b <= h0):
            _die(f"裁剪框超出图片范围（图片 {w0}x{h0}）")
        out_img = img.crop((l, t, r, b))
    elif args.width and args.height:
        tw, th = args.width, args.height
        if tw > w0 or th > h0:
            _die(f"居中裁剪尺寸 {tw}x{th} 超过原图 {w0}x{h0}")
        l = (w0 - tw) // 2
        t = (h0 - th) // 2
        out_img = img.crop((l, t, l + tw, t + th))
    else:
        _die("需要 --box 或 --width+--height（居中裁剪）")
    _save(out_img, args.output, quality=args.quality)
    _report(args.output)
    return 0


def _parse_ratio(s: str) -> float:
    if ":" in s:
        a, b = s.split(":")
        return float(a) / float(b)
    return float(s)


def cmd_pad(args) -> int:
    img = _open(args.input).convert("RGBA")
    w0, h0 = img.size
    target = _parse_ratio(args.ratio)  # 宽/高
    cur = w0 / h0
    bg = _parse_color(args.background)
    if len(bg) == 3:
        bg = bg + (255,)
    if cur > target:
        # 太宽 → 上下补边
        new_w = w0
        new_h = round(w0 / target)
    else:
        # 太高 → 左右补边
        new_h = h0
        new_w = round(h0 * target)
    canvas = Image.new("RGBA", (new_w, new_h), bg)
    ox = (new_w - w0) // 2
    oy = (new_h - h0) // 2
    canvas.paste(img, (ox, oy), img)
    _save(canvas, args.output, quality=args.quality)
    _report(args.output)
    return 0


def cmd_convert(args) -> int:
    img = _open(args.input)
    fmt = args.format.lower()
    if fmt not in ("png", "jpg", "jpeg", "webp"):
        _die("--format 仅支持 png/jpg/webp")
    _save(img, args.output, quality=args.quality, fmt=fmt)
    _report(args.output)
    return 0


def cmd_compress(args) -> int:
    img = _open(args.input)
    ext = Path(args.output).suffix.lstrip(".").lower()
    if ext in ("jpg", "jpeg"):
        ext = "jpeg"
    if ext not in ("jpeg", "webp"):
        _die("compress 仅支持输出 jpg/webp（png 无损，用 convert）")
    if img.mode in ("RGBA", "P", "LA") and ext == "jpeg":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif ext == "jpeg":
        img = img.convert("RGB")

    def _bytes(q: int) -> bytes:
        buf = io.BytesIO()
        kw = {"quality": q}
        if ext == "jpeg":
            kw["optimize"] = True
        img.save(buf, format=ext.upper(), **kw)
        return buf.getvalue()

    if args.max_kb:
        # 二分/递减逼近目标大小
        limit = args.max_kb * 1024
        best = None
        for q in range(args.quality, 9, -5):
            data = _bytes(q)
            if len(data) <= limit:
                best = data
                break
            best = data  # 记录最后一个（即使超限也保留最小）
        data = best
        if len(data) > limit:
            print(f"WARN: 即使 quality=10 仍为 {len(data)/1024:.0f}KB，"
                  f"超过目标 {args.max_kb}KB。可先 resize 缩小尺寸。", file=sys.stderr)
    else:
        data = _bytes(args.quality)
    _ensure_parent(args.output)
    Path(args.output).write_bytes(data)
    _report(args.output)
    return 0


def _anchor_xy(pos: str, cw: int, ch: int, ew: int, eh: int, margin: int) -> tuple:
    m = margin
    table = {
        "top-left": (m, m),
        "top-right": (cw - ew - m, m),
        "bottom-left": (m, ch - eh - m),
        "bottom-right": (cw - ew - m, ch - eh - m),
        "center": ((cw - ew) // 2, (ch - eh) // 2),
    }
    if pos not in table:
        _die(f"非法位置: {pos}（可选 {'/'.join(table)}）")
    return table[pos]


def cmd_watermark(args) -> int:
    base = _open(args.input).convert("RGBA")
    cw, ch = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    alpha = max(0, min(255, round(args.opacity * 255)))

    if args.image:
        wm = _open(args.image).convert("RGBA")
        if args.scale != 1.0:
            wm = wm.resize((max(1, round(wm.width * args.scale)),
                            max(1, round(wm.height * args.scale))), Image.LANCZOS)
        # 应用透明度
        if alpha < 255:
            a = wm.split()[-1].point(lambda p: round(p * args.opacity))
            wm.putalpha(a)
        x, y = _anchor_xy(args.position, cw, ch, wm.width, wm.height, args.margin)
        overlay.paste(wm, (x, y), wm)
    elif args.text:
        font = _load_font(args.font, args.size)
        draw = ImageDraw.Draw(overlay)
        bbox = draw.textbbox((0, 0), args.text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x, y = _anchor_xy(args.position, cw, ch, tw, th, args.margin)
        color = _parse_color(args.color)
        if len(color) == 3:
            color = color + (alpha,)
        else:
            color = color[:3] + (alpha,)
        draw.text((x - bbox[0], y - bbox[1]), args.text, font=font, fill=color)
    else:
        _die("需要 --text 或 --image 之一")

    out_img = Image.alpha_composite(base, overlay)
    _save(out_img, args.output, quality=args.quality)
    _report(args.output)
    return 0


def cmd_round(args) -> int:
    img = _open(args.input).convert("RGBA")
    w, h = img.size
    radius = args.radius
    if args.radius_percent is not None:
        radius = round(min(w, h) * args.radius_percent / 100)
    radius = max(0, min(radius, min(w, h) // 2))
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    out_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out_img.paste(img, (0, 0), mask)
    out = args.output
    if not out.lower().endswith(".png"):
        print("WARN: 圆角需透明通道，强制输出 png。", file=sys.stderr)
        out = str(Path(out).with_suffix(".png"))
    _save(out_img, out)
    _report(out)
    return 0


def cmd_collage(args) -> int:
    imgs = [_open(p).convert("RGBA") for p in args.inputs]
    n = len(imgs)
    if n == 0:
        _die("collage 需要至少一张图片")
    gap = args.gap
    bg = _parse_color(args.background)
    if len(bg) == 3:
        bg = bg + (255,)

    if args.grid:
        try:
            cols, rows = [int(x) for x in args.grid.lower().split("x")]
        except Exception:  # noqa: BLE001
            _die("--grid 格式应为 NxM，如 3x2")
    elif args.mode == "horizontal":
        cols, rows = n, 1
    elif args.mode == "vertical":
        cols, rows = 1, n
    else:
        _die("需要 --mode horizontal/vertical 或 --grid NxM")

    if cols * rows < n:
        _die(f"网格 {cols}x{rows}={cols*rows} 容不下 {n} 张图")

    # 统一单元格尺寸：用指定 cell 或第一张图尺寸
    cw = args.cell_width or imgs[0].width
    ch = args.cell_height or imgs[0].height

    def _fit(im: "Image.Image") -> "Image.Image":
        ratio = min(cw / im.width, ch / im.height)
        nw, nh = max(1, round(im.width * ratio)), max(1, round(im.height * ratio))
        resized = im.resize((nw, nh), Image.LANCZOS)
        cell = Image.new("RGBA", (cw, ch), bg)
        cell.paste(resized, ((cw - nw) // 2, (ch - nh) // 2), resized)
        return cell

    total_w = cols * cw + (cols + 1) * gap
    total_h = rows * ch + (rows + 1) * gap
    canvas = Image.new("RGBA", (total_w, total_h), bg)
    for idx, im in enumerate(imgs):
        r, c = divmod(idx, cols)
        x = gap + c * (cw + gap)
        y = gap + r * (ch + gap)
        canvas.paste(_fit(im), (x, y))
    _save(canvas, args.output, quality=args.quality)
    _report(args.output)
    return 0


def cmd_thumbnail(args) -> int:
    img = _open(args.input)
    img = img.copy()
    img.thumbnail((args.size, args.size), Image.LANCZOS)
    _save(img, args.output, quality=args.quality)
    _report(args.output)
    return 0


def cmd_info(args) -> int:
    p = Path(args.input)
    if not p.is_file():
        _die(f"文件不存在: {p}")
    with Image.open(p) as img:
        data = {
            "path": str(p),
            "format": img.format,
            "mode": img.mode,
            "width": img.width,
            "height": img.height,
            "ratio": round(img.width / img.height, 4) if img.height else None,
            "size_bytes": p.stat().st_size,
            "size_kb": round(p.stat().st_size / 1024, 1),
            "has_alpha": img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info,
        }
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


# ── selftest ────────────────────────────────────────────────────────────────

def _selftest() -> int:
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        # 生成三张测试图
        colors = [(220, 90, 90), (90, 180, 120), (90, 120, 220)]
        srcs = []
        for i, col in enumerate(colors):
            im = Image.new("RGB", (400, 300), col)
            dr = ImageDraw.Draw(im)
            dr.rectangle((40, 40, 360, 260), outline=(255, 255, 255), width=6)
            p = dd / f"src{i}.png"
            im.save(p)
            srcs.append(str(p))

        def _run(name, ns, checker):
            nonlocal ok
            try:
                fn = globals()[f"cmd_{name}"]
                fn(ns)
                if checker():
                    print(f"[PASS] {name}")
                else:
                    print(f"[FAIL] {name}: 输出校验未通过", file=sys.stderr)
                    ok = False
            except SystemExit as e:
                print(f"[FAIL] {name}: 退出码 {e.code}", file=sys.stderr)
                ok = False
            except Exception as e:  # noqa: BLE001
                print(f"[FAIL] {name}: {e}", file=sys.stderr)
                ok = False

        NS = argparse.Namespace

        out = dd / "resize.png"
        _run("resize", NS(input=srcs[0], output=str(out), width=200, height=None,
                          percent=None, keep_ratio=False, quality=None),
             lambda: Image.open(out).size == (200, 150))

        out = dd / "crop.png"
        _run("crop", NS(input=srcs[0], output=str(out), box=None, width=100,
                        height=100, quality=None),
             lambda: Image.open(out).size == (100, 100))

        out = dd / "pad.png"
        _run("pad", NS(input=srcs[0], output=str(out), ratio="9:16",
                       background="#000000", quality=None),
             lambda: abs(Image.open(out).width / Image.open(out).height
                         - 9 / 16) < 0.02)

        out = dd / "conv.webp"
        _run("convert", NS(input=srcs[0], output=str(out), format="webp",
                           quality=80),
             lambda: out.is_file() and Image.open(out).format == "WEBP")

        out = dd / "comp.jpg"
        _run("compress", NS(input=srcs[0], output=str(out), quality=85,
                            max_kb=None),
             lambda: out.is_file() and Image.open(out).format == "JPEG")

        out = dd / "wm.png"
        _run("watermark", NS(input=srcs[0], output=str(out), text="Easel",
                             image=None, position="bottom-right", opacity=0.5,
                             size=28, margin=20, color="#ffffff", font=None,
                             scale=1.0, quality=None),
             lambda: out.is_file())

        out = dd / "round.png"
        _run("round", NS(input=srcs[0], output=str(out), radius=40,
                         radius_percent=None),
             lambda: Image.open(out).mode == "RGBA")

        out = dd / "collage.png"
        _run("collage", NS(inputs=srcs, output=str(out), mode="horizontal",
                           grid=None, gap=10, background="#ffffff",
                           cell_width=None, cell_height=None, quality=None),
             lambda: Image.open(out).width > 400)

        out = dd / "grid.png"
        _run("collage", NS(inputs=srcs, output=str(out), mode=None,
                           grid="2x2", gap=8, background="#eeeeee",
                           cell_width=None, cell_height=None, quality=None),
             lambda: out.is_file())

        out = dd / "thumb.png"
        _run("thumbnail", NS(input=srcs[0], output=str(out), size=100,
                             quality=None),
             lambda: max(Image.open(out).size) == 100)

        _run("info", NS(input=srcs[0]), lambda: True)

    print("=" * 40)
    if ok:
        print("[PASS] image_ops 全部子命令自检通过")
        return 0
    print("[FAIL] 存在失败的子命令", file=sys.stderr)
    return 1


# ── argparse 顶层 ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="通用图像处理（纯 Pillow）：resize/crop/pad/convert/compress/"
                    "watermark/round/collage/thumbnail/info",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="用 Pillow 生成测试图跑通关键子命令")
    sub = ap.add_subparsers(dest="cmd")

    def _q(p):
        p.add_argument("--quality", type=int, default=None,
                       help="jpg/webp 质量 1-100（默认 90）")

    # resize
    p = sub.add_parser("resize", help="按宽/高/百分比缩放（可保持宽高比）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--percent", type=float, help="按百分比缩放，如 50")
    p.add_argument("--keep-ratio", action="store_true",
                   help="同时给 width+height 时，在框内等比缩放不拉伸")
    _q(p)
    p.set_defaults(func=cmd_resize)

    # crop
    p = sub.add_parser("crop", help="按坐标或居中裁剪")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--box", help="left,top,right,bottom 坐标裁剪")
    p.add_argument("--width", type=int, help="居中裁剪宽")
    p.add_argument("--height", type=int, help="居中裁剪高")
    _q(p)
    p.set_defaults(func=cmd_crop)

    # pad
    p = sub.add_parser("pad", help="补边到目标宽高比（社媒适配）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--ratio", required=True, help="目标宽高比，如 1:1 / 9:16 / 16:9")
    p.add_argument("--background", default="#ffffff",
                   help="补边背景色 #RRGGBB / r,g,b / 颜色名（默认白）")
    _q(p)
    p.set_defaults(func=cmd_pad)

    # convert
    p = sub.add_parser("convert", help="格式转换 png/jpg/webp")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--format", required=True, help="目标格式 png/jpg/webp")
    _q(p)
    p.set_defaults(func=cmd_convert)

    # compress
    p = sub.add_parser("compress", help="压缩到指定质量或目标文件大小上限（jpg/webp）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--quality", type=int, default=85, help="起始/目标质量（默认 85）")
    p.add_argument("--max-kb", type=int, help="目标文件大小上限 KB，质量循环逼近")
    p.set_defaults(func=cmd_compress)

    # watermark
    p = sub.add_parser("watermark", help="文字或图片水印")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--text", help="文字水印内容")
    p.add_argument("--image", help="图片水印路径")
    p.add_argument("--position", default="bottom-right",
                   help="位置 top-left/top-right/bottom-left/bottom-right/center")
    p.add_argument("--opacity", type=float, default=0.5, help="透明度 0-1（默认 0.5）")
    p.add_argument("--size", type=int, default=36, help="文字字号（默认 36）")
    p.add_argument("--margin", type=int, default=24, help="边距 px（默认 24）")
    p.add_argument("--color", default="#ffffff", help="文字颜色（默认白）")
    p.add_argument("--font", help="字体路径（默认自动找系统中文字体）")
    p.add_argument("--scale", type=float, default=1.0, help="图片水印缩放倍数")
    _q(p)
    p.set_defaults(func=cmd_watermark)

    # round
    p = sub.add_parser("round", help="圆角处理（输出透明 png）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--radius", type=int, default=40, help="圆角半径 px（默认 40）")
    p.add_argument("--radius-percent", type=float,
                   help="圆角半径按短边百分比，如 50 得圆形")
    p.set_defaults(func=cmd_round)

    # collage
    p = sub.add_parser("collage", help="多图拼接（横向/纵向/网格）")
    p.add_argument("-i", "--inputs", nargs="+", required=True, help="多张输入图片")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--mode", choices=["horizontal", "vertical"],
                   help="横向或纵向拼接")
    p.add_argument("--grid", help="网格 NxM，如 3x2（列x行）")
    p.add_argument("--gap", type=int, default=10, help="间隙 px（默认 10）")
    p.add_argument("--background", default="#ffffff", help="背景/间隙色（默认白）")
    p.add_argument("--cell-width", type=int, help="单元格宽（默认取第一张图宽）")
    p.add_argument("--cell-height", type=int, help="单元格高（默认取第一张图高）")
    _q(p)
    p.set_defaults(func=cmd_collage)

    # thumbnail
    p = sub.add_parser("thumbnail", help="生成缩略图")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--size", type=int, default=256, help="最长边像素（默认 256）")
    _q(p)
    p.set_defaults(func=cmd_thumbnail)

    # info
    p = sub.add_parser("info", help="输出图片尺寸/格式/大小（json）")
    p.add_argument("-i", "--input", required=True)
    p.set_defaults(func=cmd_info)

    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
