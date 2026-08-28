#!/usr/bin/env python3
"""img_enhance.py — 图片增强 / 放大的确定性封装（Pillow + OpenCV）。

"图片增强 / 放大 / 变清晰"类 SKILL（image-enhance）共用此脚本。做 Lanczos 高质量放大、
去噪、锐化、自动对比度/饱和度提升，改善偏糊/偏暗/噪点多的图片。

⚠️ 这是**确定性传统增强**，不是 AI 超分辨率——能显著改善轻中度模糊/噪点，但无法凭空生成
细节。要 AI 超分/重绘请用 ai-image-gen（图生图）或专用超分 provider。

依赖：Pillow（必需）；OpenCV（可选，用于去噪，无则自动跳过）。

子命令：
    enhance   放大 + 增强
    selftest  自检

用法举例：
    img_enhance.py enhance -i blurry.jpg -o out.jpg --scale 2 --auto
    img_enhance.py enhance -i photo.jpg -o out.png --scale 4 --denoise --sharpen 1.5
    img_enhance.py selftest
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


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


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def _denoise(im):
    """用 OpenCV fastNlMeans 去噪；无 cv2 则原样返回。"""
    try:
        import cv2
        import numpy as np
    except Exception:
        print("  (无 OpenCV，跳过去噪)", file=sys.stderr)
        return im
    arr = np.array(im.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    out = cv2.fastNlMeansDenoisingColored(bgr, None, 5, 5, 7, 21)
    from PIL import Image
    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def cmd_enhance(a) -> int:
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    src = _require(a.input)
    out = _prep_out(a.output)
    im = Image.open(src).convert("RGB")
    w0, h0 = im.size

    steps = []
    # 1) 去噪（放大前做，避免噪点被放大）
    if a.denoise:
        im = _denoise(im)
        steps.append("去噪")
    # 2) 放大（Lanczos 高质量重采样）
    scale = a.scale
    if scale and abs(scale - 1.0) > 1e-6:
        nw, nh = max(1, int(w0 * scale)), max(1, int(h0 * scale))
        im = im.resize((nw, nh), Image.LANCZOS)
        steps.append(f"放大x{scale:g}")
    # 3) 自动对比度
    if a.auto or a.autocontrast:
        im = ImageOps.autocontrast(im, cutoff=1)
        steps.append("自动对比")
    # 4) 锐化（UnsharpMask）
    sharpen = a.sharpen if a.sharpen is not None else (1.0 if a.auto else 0.0)
    if sharpen and sharpen > 0:
        radius = 2
        percent = int(80 * sharpen)
        im = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=2))
        steps.append(f"锐化x{sharpen:g}")
    # 5) 对比度 / 饱和度微调
    contrast = a.contrast if a.contrast is not None else (1.05 if a.auto else 1.0)
    if abs(contrast - 1.0) > 1e-6:
        im = ImageEnhance.Contrast(im).enhance(contrast)
        steps.append(f"对比{contrast:g}")
    sat = a.saturation if a.saturation is not None else (1.08 if a.auto else 1.0)
    if abs(sat - 1.0) > 1e-6:
        im = ImageEnhance.Color(im).enhance(sat)
        steps.append(f"饱和{sat:g}")

    if out.suffix.lower() in (".jpg", ".jpeg"):
        im.save(out, quality=94)
    else:
        im.save(out)
    _done(out, f"({w0}x{h0}→{im.size[0]}x{im.size[1]} · {'/'.join(steps) or '无操作'})")
    return 0


def cmd_selftest(_a) -> int:
    print("img_enhance 自检 ...", file=sys.stderr)
    from PIL import Image, ImageFilter
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 造一张带纹理并模糊的小图
        src = d / "src.jpg"
        im = Image.new("RGB", (200, 150))
        px = im.load()
        for y in range(150):
            for x in range(200):
                px[x, y] = ((x * 7) % 256, (y * 11) % 256, ((x + y) * 5) % 256)
        im.filter(ImageFilter.GaussianBlur(2)).save(src)

        # 2x + auto
        out1 = d / "2x.jpg"
        cmd_enhance(argparse.Namespace(input=str(src), output=str(out1), scale=2.0,
                                       denoise=False, auto=True, autocontrast=False,
                                       sharpen=None, contrast=None, saturation=None))
        assert Image.open(out1).size == (400, 300), "2x 放大尺寸不对"

        # 4x + denoise + 强锐化
        out2 = d / "4x.png"
        cmd_enhance(argparse.Namespace(input=str(src), output=str(out2), scale=4.0,
                                       denoise=True, auto=False, autocontrast=True,
                                       sharpen=1.5, contrast=1.1, saturation=1.1))
        assert Image.open(out2).size == (800, 600), "4x 放大尺寸不对"

        # 不放大只增强
        out3 = d / "same.jpg"
        cmd_enhance(argparse.Namespace(input=str(src), output=str(out3), scale=1.0,
                                       denoise=False, auto=True, autocontrast=False,
                                       sharpen=None, contrast=None, saturation=None))
        assert Image.open(out3).size == (200, 150), "1x 尺寸应不变"

    print("✅ selftest 全部通过（2x+auto / 4x+去噪锐化 / 仅增强）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="图片增强 / 放大（Lanczos 放大 + 去噪 + 锐化 + 对比/饱和，非 AI 超分）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("enhance", help="放大 + 增强")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--scale", type=float, default=2.0, help="放大倍数（默认 2；1 表示不放大）")
    p.add_argument("--denoise", action="store_true", help="去噪（需 OpenCV，放大前执行）")
    p.add_argument("--auto", action="store_true",
                   help="一键增强（自动对比+适度锐化+轻微对比/饱和）")
    p.add_argument("--autocontrast", action="store_true", help="仅自动对比度")
    p.add_argument("--sharpen", type=float, help="锐化强度（0 关闭；--auto 默认 1.0）")
    p.add_argument("--contrast", type=float, help="对比度系数（1.0 不变）")
    p.add_argument("--saturation", type=float, help="饱和度系数（1.0 不变）")
    p.set_defaults(func=cmd_enhance)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
