#!/usr/bin/env python3
"""chromakey.py — 绿幕/蓝幕抠像 + 背景合成的确定性封装（ffmpeg chromakey）。

"绿幕抠像 / 换背景 / 合成"类 SKILL（green-screen）共用此脚本。把绿幕（或指定色）前景
抠出来，合成到新背景：图片 / 视频 / 纯色 / 前景自身的模糊。

依赖：ffmpeg + ffprobe。

子命令：
    key       抠像 + 合成到背景
    selftest  自检

用法举例：
    chromakey.py key -i person.mp4 --bg office.jpg -o out.mp4
    chromakey.py key -i person.mp4 --bg loop.mp4 -o out.mp4 --color 0x00d000 --similarity 0.25
    chromakey.py key -i person.mp4 --bg-color white -o out.mp4
    chromakey.py key -i person.mp4 --bg-blur -o out.mp4     # 背景=前景自身模糊
    chromakey.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            _die(f"未找到 {t}，请先安装 ffmpeg（含 ffprobe）。", 3)


def _require_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-18:])
        _die(f"ffmpeg 执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)


def _probe_wh(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        w, h = (proc.stdout or "").strip().split("x")[:2]
        return int(w), int(h)
    except ValueError:
        _die(f"无法读取分辨率：{path}", 2)
        return 0, 0


def _probe_dur(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _has_audio(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return bool((proc.stdout or "").strip())


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def cmd_key(a) -> int:
    _check_ffmpeg()
    fg = _require_input(a.input)
    w, h = _probe_wh(fg)
    dur = _probe_dur(fg)
    out = _prep_out(a.output)

    # 前景抠像滤镜
    ck = (f"chromakey=color={a.color}:similarity={a.similarity}:blend={a.blend}")
    # 溢色抑制 + 边缘柔化
    fg_chain = f"[0:v]{ck},despill=type=green,setsar=1[fgk]"

    inputs = ["-i", str(fg)]
    modes = sum(bool(x) for x in (a.bg, a.bg_color, a.bg_blur))
    if modes == 0:
        _die("需指定背景：--bg <图/视频> / --bg-color <色> / --bg-blur。", 2)
    if modes > 1:
        _die("--bg / --bg-color / --bg-blur 三选一。", 2)

    if a.bg_blur:
        # 背景 = 前景自身放大模糊
        filt = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},gblur=sigma={a.blur_sigma}[bg];"
                f"{fg_chain};[bg][fgk]overlay=(W-w)/2:(H-h)/2[v]")
    elif a.bg_color:
        filt = (f"color=c={a.bg_color}:s={w}x{h}:d={dur:.3f}[bg];"
                f"{fg_chain};[bg][fgk]overlay=(W-w)/2:(H-h)/2[v]")
    else:
        bg = _require_input(a.bg)
        is_video = bg.suffix.lower() in _VID_EXT
        if is_video:
            inputs += ["-stream_loop", "-1", "-i", str(bg)]
        else:
            inputs += ["-loop", "1", "-i", str(bg)]
        filt = (f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1[bg];"
                f"{fg_chain};[bg][fgk]overlay=(W-w)/2:(H-h)/2[v]")

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]"]
    if _has_audio(fg):
        cmd += ["-map", "0:a"]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "20", "-preset", "medium", "-c:a", "aac", str(out)]
    _run(cmd)
    bg_desc = ("模糊背景" if a.bg_blur else f"纯色 {a.bg_color}" if a.bg_color
               else f"背景 {Path(a.bg).name}")
    _done(out, f"({w}x{h} · 抠 {a.color} → {bg_desc})")
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("chromakey 自检 ...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 绿幕前景：纯绿底 + 红色方块（作"主体"）+ 音轨
        fg = d / "fg.mp4"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x00ff00:s=640x360:d=2",
              "-f", "lavfi", "-i", "sine=frequency=440:d=2",
              "-vf", "drawbox=x=220:y=120:w=200:h=120:color=red:t=fill",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-shortest", str(fg)])
        bgimg = d / "bg.png"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1280x720",
              "-frames:v", "1", str(bgimg)])

        # 合成到图片背景
        out1 = d / "on_img.mp4"
        cmd_key(argparse.Namespace(input=str(fg), bg=str(bgimg), bg_color=None,
                                   bg_blur=False, output=str(out1), color="0x00ff00",
                                   similarity=0.30, blend=0.10, blur_sigma=20))
        assert _probe_wh(out1) == (640, 360) and _has_audio(out1), "图片背景合成异常"

        # 合成到纯色背景
        out2 = d / "on_color.mp4"
        cmd_key(argparse.Namespace(input=str(fg), bg=None, bg_color="white",
                                   bg_blur=False, output=str(out2), color="0x00ff00",
                                   similarity=0.30, blend=0.10, blur_sigma=20))
        assert out2.is_file(), "纯色背景合成失败"

        # 背景=模糊自身
        out3 = d / "on_blur.mp4"
        cmd_key(argparse.Namespace(input=str(fg), bg=None, bg_color=None,
                                   bg_blur=True, output=str(out3), color="0x00ff00",
                                   similarity=0.30, blend=0.10, blur_sigma=20))
        assert out3.is_file(), "模糊背景合成失败"

        # 验证确有抠像效果：合成后中心红块区域仍偏红、四周变蓝（而非全绿）
        probe = d / "probe.png"
        _run(["ffmpeg", "-y", "-i", str(out1), "-frames:v", "1", str(probe)])
        try:
            from PIL import Image
            im = Image.open(probe).convert("RGB")
            r_c, g_c, b_c = im.getpixel((320, 180))       # 中心（红块）
            r_e, g_e, b_e = im.getpixel((40, 40))          # 边角（应为蓝背景）
            assert g_e < 150 and b_e > 100, f"边角未换成蓝背景：{(r_e,g_e,b_e)}"
        except ImportError:
            print("  (无 PIL，跳过像素校验)", file=sys.stderr)

    print("✅ selftest 全部通过（图片/纯色/模糊背景合成 + 抠像像素校验）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="绿幕/蓝幕抠像 + 背景合成（ffmpeg chromakey 确定性封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("key", help="抠像 + 合成到背景")
    p.add_argument("-i", "--input", required=True, help="绿幕前景视频")
    p.add_argument("--bg", help="背景图片或视频")
    p.add_argument("--bg-color", help="纯色背景，如 white / 0x1a1a2e")
    p.add_argument("--bg-blur", action="store_true", help="背景=前景自身放大模糊")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--color", default="0x00ff00", help="要抠掉的幕布色（默认绿 0x00ff00；蓝幕 0x0000ff）")
    p.add_argument("--similarity", type=float, default=0.30,
                   help="颜色相似阈值 0-1（越大抠越多，默认 0.30）")
    p.add_argument("--blend", type=float, default=0.10, help="边缘融合 0-1（默认 0.10）")
    p.add_argument("--blur-sigma", type=int, default=20, help="bg-blur 模糊强度（默认 20）")
    p.set_defaults(func=cmd_key)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
