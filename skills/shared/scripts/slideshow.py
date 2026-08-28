#!/usr/bin/env python3
"""slideshow.py — 图片相册 → 视频的确定性封装（Ken Burns + 转场 + BGM + 字幕）。

"图片转视频 / 相册视频"类 SKILL（slideshow-video）共用此脚本。把一组图片做成一条
带缓慢缩放（Ken Burns）、图间转场、可选背景音乐与逐图字幕的视频，自动适配目标画幅。
避免手拼 zoompan/xfade 时算错帧数与转场偏移、音画对不齐。

与 auto-short-video 的边界：auto-short-video 是"一句话主题→AI 配图/配音/字幕→成片"的
完整流水线；本脚本只做"我已有一组图片 → 拼成视频"，不生成文案/配音。
与 video_ops.py：video_ops 处理已有视频，本脚本从静态图片生成视频。

依赖：ffmpeg + ffprobe。

子命令（每个都能 `-h`）：
    build     一组图片 → 视频
    selftest  自检（造图 → 成片 → 校验）

用法举例：
    slideshow.py build -i a.jpg b.jpg c.jpg -o out.mp4 --size 1080x1920 --per 3
    slideshow.py build --images-dir ./photos -o out.mp4 --transition fade --bgm bgm.mp3
    slideshow.py build -i a.jpg b.jpg -o out.mp4 --captions "第一张|第二张"
    slideshow.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
_TRANSITIONS = ("none", "fade", "fadeblack", "fadewhite", "wipeleft", "wiperight",
                "slideup", "slidedown", "circleopen", "dissolve")

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


# ── 基础工具 ──────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            _die(f"未找到 {t}，请先安装 ffmpeg（含 ffprobe）。", 3)


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-18:])
        _die(f"ffmpeg 执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)


def _find_font(explicit: str | None = None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            _die(f"指定字体文件不存在: {explicit}", 2)
        return explicit
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    _die("未找到可用字体，请用 --font 指定 .ttf/.ttc 路径。", 2)
    return ""


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%"))


def _probe_dur(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def _collect_images(a) -> list[Path]:
    imgs: list[Path] = []
    if a.images_dir:
        d = Path(a.images_dir).expanduser()
        if not d.is_dir():
            _die(f"图片目录不存在: {d}", 2)
        imgs = sorted(p for p in d.iterdir() if p.suffix.lower() in _IMG_EXT)
    elif a.input:
        for s in a.input:
            p = Path(s).expanduser()
            if not p.is_file():
                _die(f"图片不存在: {p}", 2)
            imgs.append(p)
    if not imgs:
        _die("没有图片输入。用 -i <图...> 或 --images-dir <目录>。", 2)
    return imgs


# ── 单图 → 片段（Ken Burns + 可选字幕，静音） ─────────────────────────
def _make_clip(img: Path, dur: float, w: int, h: int, idx: int, kenburns: bool,
               caption: str | None, font: str, fit: str, out: Path) -> None:
    frames = max(1, int(dur * 30))
    if kenburns:
        # 交替缩放方向增加变化：偶数放大、奇数保持轻微反向 pan
        if idx % 2 == 0:
            zexpr = "min(zoom+0.0010,1.12)"
            xexpr, yexpr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        else:
            zexpr = "min(zoom+0.0008,1.10)"
            xexpr, yexpr = "(iw-iw/zoom)", "(ih-ih/zoom)"
        vf = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
              f"crop={w*2}:{h*2},"
              f"zoompan=z='{zexpr}':x='{xexpr}':y='{yexpr}':d={frames}:s={w}x{h}:fps=30,"
              f"setsar=1")
    else:
        if fit == "crop":
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                  f"crop={w}:{h},setsar=1,fps=30")
        else:  # pad
            vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                  f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30")
    if caption:
        fs = max(20, h // 26)
        vf += (f",drawtext=fontfile='{font}':text='{_esc(caption)}':"
               f"fontcolor=white:fontsize={fs}:x=(w-text_w)/2:y=h-text_h-{int(h*0.08)}:"
               f"borderw=3:bordercolor=black@0.55:shadowx=2:shadowy=2")
    _run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-t", f"{dur:.3f}",
          "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out)])


def _xfade_chain(clips: list[Path], per: float, td: float, transition: str, out: Path) -> None:
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    chain = []
    cur = "[0:v]"
    offset = 0.0
    for i in range(1, len(clips)):
        offset += per - td
        label = f"[vx{i}]"
        chain.append(f"{cur}[{i}:v]xfade=transition={transition}:"
                     f"duration={td:.3f}:offset={offset:.3f}{label}")
        cur = label
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain),
          "-map", cur, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def _concat_hard(clips: list[Path], out: Path, workdir: Path) -> None:
    lst = workdir / "list.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def _add_audio(silent: Path, out: Path, bgm: str | None, vol: float) -> None:
    dur = _probe_dur(silent)
    if bgm:
        b = Path(bgm).expanduser()
        if not b.is_file():
            _die(f"BGM 文件不存在: {b}", 2)
        fade = min(2.0, dur / 4)
        af = f"volume={vol},afade=t=out:st={max(0.0, dur - fade):.3f}:d={fade:.3f}"
        _run(["ffmpeg", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(b),
              "-filter_complex", f"[1:a]{af}[a]", "-map", "0:v", "-map", "[a]",
              "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
              "-t", f"{dur:.3f}", str(out)])
    else:
        # 补静音轨，便于平台上传与后续拼接
        _run(["ffmpeg", "-y", "-i", str(silent),
              "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
              "-shortest", str(out)])


def cmd_build(a) -> int:
    _check_ffmpeg()
    imgs = _collect_images(a)
    try:
        w, h = (int(x) for x in a.size.lower().split("x"))
    except ValueError:
        _die(f"size 格式错误：{a.size}（应如 1080x1920）", 2)
    per = max(0.8, float(a.per))
    font = _find_font(a.font)

    captions: list[str | None] = [None] * len(imgs)
    if a.captions:
        parts = a.captions.split("|")
        for i in range(min(len(parts), len(imgs))):
            captions[i] = parts[i].strip() or None
    elif a.captions_file:
        cf = Path(a.captions_file).expanduser()
        if not cf.is_file():
            _die(f"字幕文件不存在: {cf}", 2)
        lines = [l.rstrip() for l in cf.read_text(encoding="utf-8").splitlines()]
        for i in range(min(len(lines), len(imgs))):
            captions[i] = lines[i].strip() or None

    out = _prep_out(a.output)
    with tempfile.TemporaryDirectory() as td_:
        workdir = Path(td_)
        clips = []
        for i, img in enumerate(imgs):
            clip = workdir / f"clip_{i:03d}.mp4"
            print(f"  处理第 {i+1}/{len(imgs)} 张（{per:.1f}s）...", file=sys.stderr)
            _make_clip(img, per, w, h, i, not a.no_kenburns, captions[i], font, a.fit, clip)
            clips.append(clip)

        silent = workdir / "silent.mp4"
        if a.transition == "none" or len(clips) == 1:
            _concat_hard(clips, silent, workdir)
            tinfo = "硬切"
        else:
            td = max(0.2, float(a.trans_duration))
            if td >= per:
                td = per / 2
            _xfade_chain(clips, per, td, a.transition, silent)
            tinfo = f"{a.transition} 转场"

        _add_audio(silent, out, a.bgm, a.bgm_volume)

    total = _probe_dur(out)
    _done(out, f"({len(imgs)} 图 / {total:.1f}s / {w}x{h} / {tinfo}"
               f"{' + BGM' if a.bgm else ''})")
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("slideshow 自检 ...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        imgs = []
        for i, color in enumerate(("red", "green", "blue")):
            p = d / f"img{i}.png"
            _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=800x600",
                  "-frames:v", "1", str(p)])
            imgs.append(str(p))
        bgm = d / "bgm.wav"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:d=12",
              str(bgm)])

        # 转场 + Ken Burns + 字幕 + BGM
        out1 = d / "show.mp4"
        ns = argparse.Namespace(
            input=imgs, images_dir=None, output=str(out1), size="720x1280", per=2.0,
            transition="fade", trans_duration=0.6, bgm=str(bgm), bgm_volume=0.7,
            captions="第一张|第二张|第三张", captions_file=None, no_kenburns=False,
            fit="pad", font=None)
        cmd_build(ns)
        dur1 = _probe_dur(out1)
        # 3×2 - 2×0.6 = 4.8s
        assert 4.3 < dur1 < 5.3, f"转场成片时长异常：{dur1:.2f}s（应≈4.8s）"
        # 校验有音轨
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", str(out1)],
                           stdout=subprocess.PIPE, text=True)
        assert (r.stdout or "").strip(), "成片缺音轨"

        # 硬切 + 无 Ken Burns + 无 BGM
        out2 = d / "hard.mp4"
        ns2 = argparse.Namespace(
            input=imgs, images_dir=None, output=str(out2), size="720x720", per=1.5,
            transition="none", trans_duration=0.6, bgm=None, bgm_volume=0.7,
            captions=None, captions_file=None, no_kenburns=True, fit="crop", font=None)
        cmd_build(ns2)
        dur2 = _probe_dur(out2)
        assert 4.0 < dur2 < 5.0, f"硬切成片时长异常：{dur2:.2f}s（应≈4.5s）"

        # 目录输入
        out3 = d / "dir.mp4"
        ns3 = argparse.Namespace(
            input=None, images_dir=str(d), output=str(out3), size="640x360", per=1.0,
            transition="none", trans_duration=0.5, bgm=None, bgm_volume=0.7,
            captions=None, captions_file=None, no_kenburns=True, fit="pad", font=None)
        cmd_build(ns3)
        assert out3.is_file(), "目录输入成片未生成"

    print("✅ selftest 全部通过（转场+KenBurns+字幕+BGM / 硬切 / 目录输入）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="图片相册 → 视频（Ken Burns + 转场 + BGM + 字幕，确定性 ffmpeg 封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("build", help="一组图片 → 视频")
    p.add_argument("-i", "--input", nargs="+", help="图片路径（按给定顺序）")
    p.add_argument("--images-dir", help="图片目录（按文件名排序，覆盖 -i）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--size", default="1080x1920", help="画幅 WxH（默认竖版 1080x1920）")
    p.add_argument("--per", type=float, default=3.0, help="每张图停留秒数（默认 3）")
    p.add_argument("--transition", default="fade", choices=list(_TRANSITIONS),
                   help="图间转场（默认 fade；none 硬切）")
    p.add_argument("--trans-duration", type=float, default=0.7, help="转场时长秒（默认 0.7）")
    p.add_argument("--bgm", help="背景音乐路径（自动循环/裁到片长/尾部淡出）")
    p.add_argument("--bgm-volume", type=float, default=0.8, help="BGM 音量（默认 0.8）")
    p.add_argument("--captions", help="逐图字幕，用 | 分隔，如 '图1|图2|图3'")
    p.add_argument("--captions-file", help="逐图字幕文件（每行一张图）")
    p.add_argument("--no-kenburns", action="store_true", help="关闭 Ken Burns 缩放（静止画面）")
    p.add_argument("--fit", default="pad", choices=["pad", "crop"],
                   help="非 Ken Burns 时的适配：pad 补边 / crop 裁切（默认 pad）")
    p.add_argument("--font", help="字幕字体路径（默认自动探测 CJK 字体）")
    p.set_defaults(func=cmd_build)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
