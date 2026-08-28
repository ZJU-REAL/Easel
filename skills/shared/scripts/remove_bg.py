#!/usr/bin/env python3
"""remove_bg.py — 图片去背景 / 抠图（rembg）的确定性封装。

"图片去背景 / 抠图换背景"类 SKILL（remove-bg）共用此脚本。用 rembg（u2net 系列模型）
把主体从背景中抠出，输出透明 PNG，或直接换成纯色 / 图片背景。

与 green-screen（chromakey）的区别：green-screen 处理绿幕**视频**（按颜色抠）；本脚本处理
**图片**且无需绿幕（AI 语义分割）。与 image-editing 的区别：那个做缩放/裁切/水印等常规处理，
本脚本专做去背景。

依赖：rembg + onnxruntime + Pillow。首次运行下载模型（~170MB），需外网代理（自动注入）。

子命令：
    remove    去背景（输出透明 PNG / 换纯色 / 换图片背景）
    check     检查依赖与模型可用性
    selftest  自检

用法举例：
    remove_bg.py remove -i product.jpg -o cutout.png                 # 透明背景
    remove_bg.py remove -i person.jpg -o out.jpg --bg-color white    # 白底（电商主图）
    remove_bg.py remove -i person.jpg -o out.png --bg-image scene.jpg # 换场景背景
    remove_bg.py check
    remove_bg.py selftest
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_DEFAULT_PROXY = os.environ.get("EASEL_PROXY", "")  # lab 在 .env 设 EASEL_PROXY；不设则不走代理
_MODELS = ["u2net", "u2netp", "u2net_human_seg", "isnet-general-use", "silueta"]


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


def _ensure_proxy() -> None:
    has = any(os.environ.get(k) for k in
              ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"))
    if not has and _DEFAULT_PROXY:
        os.environ["https_proxy"] = _DEFAULT_PROXY
        os.environ["http_proxy"] = _DEFAULT_PROXY
        print(f"[remove-bg] 未检测到代理，已注入默认代理 {_DEFAULT_PROXY}（供模型下载）。",
              file=sys.stderr)


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def _load_session(model: str):
    _ensure_proxy()
    try:
        from rembg import new_session
    except Exception as e:
        _die(f"未安装 rembg：{e}\n  pip install rembg onnxruntime", 3)
    try:
        return new_session(model)
    except Exception as e:
        _die(f"加载模型 {model} 失败（可能是下载失败/网络问题）：{e}", 3)


def cmd_remove(a) -> int:
    if a.bg_color and a.bg_image:
        _die("--bg-color 与 --bg-image 二选一。", 2)
    src = _require(a.input)
    out = _prep_out(a.output)
    from rembg import remove
    from PIL import Image

    session = _load_session(a.model)
    with Image.open(src) as im:
        im = im.convert("RGBA")
        cut = remove(im, session=session,
                     alpha_matting=a.alpha_matting,
                     post_process_mask=True)  # RGBA

    if a.bg_color:
        bg = Image.new("RGBA", cut.size, a.bg_color)
        bg.alpha_composite(cut)
        result = bg.convert("RGB")
    elif a.bg_image:
        bgi = Image.open(_require(a.bg_image)).convert("RGBA")
        # 背景等比覆盖裁切到主体尺寸
        tw, th = cut.size
        bw, bh = bgi.size
        scale = max(tw / bw, th / bh)
        bgi = bgi.resize((max(1, int(bw * scale)), max(1, int(bh * scale))))
        left = (bgi.size[0] - tw) // 2
        top = (bgi.size[1] - th) // 2
        bgi = bgi.crop((left, top, left + tw, top + th))
        bgi.alpha_composite(cut)
        result = bgi.convert("RGB") if out.suffix.lower() in (".jpg", ".jpeg") else bgi
    else:
        result = cut  # 透明 PNG
        if out.suffix.lower() in (".jpg", ".jpeg"):
            print("  (jpg 不支持透明，自动改用白底；要透明请输出 .png)", file=sys.stderr)
            bg = Image.new("RGBA", cut.size, "white")
            bg.alpha_composite(cut)
            result = bg.convert("RGB")

    result.save(out)
    bg_desc = (f"纯色 {a.bg_color}" if a.bg_color else
               f"背景图 {Path(a.bg_image).name}" if a.bg_image else "透明背景")
    _done(out, f"({a.model} → {bg_desc})")
    return 0


def cmd_check(a) -> int:
    ok = True
    try:
        import rembg  # noqa
        print(f"✅ rembg {getattr(rembg, '__version__', '?')}")
    except Exception as e:
        print(f"❌ rembg 未安装：{e}（pip install rembg onnxruntime）"); ok = False
    try:
        import onnxruntime  # noqa
        print(f"✅ onnxruntime {onnxruntime.__version__}")
    except Exception as e:
        print(f"❌ onnxruntime 未安装：{e}"); ok = False
    try:
        from PIL import Image  # noqa
        print("✅ Pillow")
    except Exception as e:
        print(f"❌ Pillow 未安装：{e}"); ok = False
    print(f"可用模型：{', '.join(_MODELS)}（默认 u2net）")
    print("模型缓存目录：~/.u2net/（首次运行自动下载，需外网代理）")
    return 0 if ok else 3


def cmd_selftest(_a) -> int:
    print("remove_bg 自检 ...", file=sys.stderr)
    from PIL import Image
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 造一张：白底中心一个红圆（主体）
        src = d / "src.png"
        im = Image.new("RGB", (256, 256), "white")
        from PIL import ImageDraw
        ImageDraw.Draw(im).ellipse((64, 64, 192, 192), fill=(220, 30, 30))
        im.save(src)

        out = d / "cut.png"
        ns = argparse.Namespace(input=str(src), output=str(out), model="u2netp",
                                bg_color=None, bg_image=None, alpha_matting=False)
        cmd_remove(ns)
        res = Image.open(out).convert("RGBA")
        assert res.size == (256, 256), "输出尺寸不对"
        # 应存在透明像素（背景被抠掉）
        alphas = res.getchannel("A").getextrema()
        assert alphas[0] < 250, f"未产生透明区域（alpha min={alphas[0]}），抠图可能未生效"

        # 换白底
        out2 = d / "white.jpg"
        ns2 = argparse.Namespace(input=str(src), output=str(out2), model="u2netp",
                                 bg_color="white", bg_image=None, alpha_matting=False)
        cmd_remove(ns2)
        assert out2.is_file(), "换纯色背景失败"

    print("✅ selftest 全部通过（去背景透明 + 换纯色背景）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="图片去背景 / 抠图（rembg，语义分割，无需绿幕）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("remove", help="去背景")
    p.add_argument("-i", "--input", required=True, help="输入图片")
    p.add_argument("-o", "--output", required=True, help="输出（透明背景用 .png）")
    p.add_argument("--model", default="u2net", choices=_MODELS,
                   help="模型：u2net(默认,通用) / u2netp(轻量快) / u2net_human_seg(人像) / "
                        "isnet-general-use(精细) / silueta")
    p.add_argument("--bg-color", help="换纯色背景，如 white / 0xffffff（电商白底常用）")
    p.add_argument("--bg-image", help="换图片背景（等比覆盖裁切到主体尺寸）")
    p.add_argument("--alpha-matting", action="store_true",
                   help="开启 alpha matting（边缘更细腻但更慢，适合毛发）")
    p.set_defaults(func=cmd_remove)

    sub.add_parser("check", help="检查依赖与模型").set_defaults(func=cmd_check)
    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
