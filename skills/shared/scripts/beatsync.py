#!/usr/bin/env python3
"""beatsync.py — 音乐卡点视频（节拍驱动的图片/片段切换）确定性封装。

"卡点视频"类 SKILL（beat-sync-video）共用此脚本。用 librosa 检测背景音乐的节拍点，
让画面在节拍上切换，配 punch/flash 效果，做出"踩点"燃系短视频。

与 slideshow.py 的区别：slideshow 每图固定时长、柔和转场；本脚本切换点由音乐节拍决定、
硬切卡点、带节拍特效。与 auto-short-video 的区别：后者是"主题→AI 配图配音成片"完整流水线。

依赖：ffmpeg + ffprobe + librosa + numpy。节拍检测失败时退化为等间隔切换。

子命令：
    build     图片/片段 + 音乐 → 卡点视频
    beats     只检测并打印节拍点（调试用）
    selftest  自检

用法举例：
    beatsync.py build -i a.jpg b.jpg c.jpg --music bgm.mp3 -o out.mp4 --every 2 --effect zoom
    beatsync.py beats --music bgm.mp3
    beatsync.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff"}
_VID_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


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


# ── 节拍检测 ──────────────────────────────────────────────────────────
def _detect_beats(music: Path, fallback_interval: float) -> tuple[list[float], float, bool]:
    """返回 (节拍时间点列表, tempo, 是否用了 fallback)。"""
    dur = _probe_dur(music)
    try:
        import librosa
        import numpy as np
        y, sr = librosa.load(str(music), mono=True)
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        times = librosa.frames_to_time(frames, sr=sr)
        times = [float(t) for t in times]
        tempo_v = float(np.atleast_1d(tempo)[0])
        if len(times) >= 2:
            return times, tempo_v, False
    except Exception as e:
        print(f"  (节拍检测不可用：{e} → 退化为等间隔)", file=sys.stderr)
    # fallback：等间隔切换
    n = max(2, int(dur / max(0.15, fallback_interval)))
    times = [i * dur / n for i in range(n + 1)]
    return times, 60.0 / max(0.15, fallback_interval), True


def _collect(paths, images_dir):
    items: list[Path] = []
    if images_dir:
        d = Path(images_dir).expanduser()
        if not d.is_dir():
            _die(f"目录不存在: {d}", 2)
        items = sorted(p for p in d.iterdir()
                       if p.suffix.lower() in _IMG_EXT | _VID_EXT)
    elif paths:
        for s in paths:
            p = Path(s).expanduser()
            if not p.is_file():
                _die(f"素材不存在: {p}", 2)
            items.append(p)
    if not items:
        _die("没有素材。用 -i <图/片...> 或 --images-dir <目录>。", 2)
    return items


# ── 单段片段 ──────────────────────────────────────────────────────────
def _seg_clip(src: Path, dur: float, w: int, h: int, effect: str, out: Path) -> None:
    frames = max(1, int(dur * 30))
    is_video = src.suffix.lower() in _VID_EXT
    if is_video:
        base = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{h},setsar=1,fps=30")
        inp = ["-i", str(src), "-t", f"{dur:.3f}"]
    else:
        if effect == "zoom":
            base = (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
                    f"crop={w*2}:{h*2},"
                    f"zoompan=z='min(zoom+0.006,1.18)':d={frames}:s={w}x{h}:fps=30,"
                    f"setsar=1")
        else:
            base = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{h},setsar=1,fps=30")
        inp = ["-loop", "1", "-i", str(src), "-t", f"{dur:.3f}"]
    # flash：段首白闪
    if effect == "flash":
        base += ",fade=t=in:st=0:d=0.08:color=white"
    _run(["ffmpeg", "-y", *inp, "-vf", base, "-an",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def cmd_build(a) -> int:
    _check_ffmpeg()
    music = Path(a.music).expanduser()
    if not music.is_file():
        _die(f"音乐文件不存在: {music}", 2)
    items = _collect(a.input, a.images_dir)
    try:
        w, h = (int(x) for x in a.size.lower().split("x"))
    except ValueError:
        _die(f"size 格式错误：{a.size}", 2)

    beats, tempo, used_fallback = _detect_beats(music, a.fallback_interval)
    mdur = _probe_dur(music)
    # 按 --every 抽取切换点
    switch = beats[::max(1, a.every)]
    if switch and switch[-1] < mdur:
        switch = switch + [mdur]
    # 生成段区间 [t_i, t_{i+1})
    segs = [(switch[i], switch[i + 1]) for i in range(len(switch) - 1)
            if switch[i + 1] - switch[i] >= 0.12]
    if a.max_duration:
        segs = [(s, e) for (s, e) in segs if s < a.max_duration]
        if segs and segs[-1][1] > a.max_duration:
            segs[-1] = (segs[-1][0], a.max_duration)
    if not segs:
        _die("未得到有效卡点区间（音乐太短或节拍太稀）。", 2)

    out = _prep_out(a.output)
    with tempfile.TemporaryDirectory() as td_:
        workdir = Path(td_)
        clips = []
        for i, (s, e) in enumerate(segs):
            clip = workdir / f"seg_{i:03d}.mp4"
            src = items[i % len(items)]  # 素材循环使用
            _seg_clip(src, e - s, w, h, a.effect, clip)
            clips.append(clip)
            print(f"  卡点段 {i+1}/{len(segs)} @{s:.2f}s ({e-s:.2f}s) ← {src.name}",
                  file=sys.stderr)

        lst = workdir / "list.txt"
        lst.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
        silent = workdir / "silent.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)])
        vdur = _probe_dur(silent)
        # 混入音乐，裁到画面长度，尾部淡出
        fade = min(1.5, vdur / 4)
        _run(["ffmpeg", "-y", "-i", str(silent), "-i", str(music),
              "-filter_complex",
              f"[1:a]afade=t=out:st={max(0.0, vdur - fade):.3f}:d={fade:.3f}[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
              "-t", f"{vdur:.3f}", str(out)])

    total = _probe_dur(out)
    tag = "等间隔(无明显节拍)" if used_fallback else f"{tempo:.0f}BPM"
    _done(out, f"({len(segs)} 段卡点 / {total:.1f}s / {w}x{h} / {tag} / 特效 {a.effect})")
    return 0


def cmd_beats(a) -> int:
    music = Path(a.music).expanduser()
    if not music.is_file():
        _die(f"音乐文件不存在: {music}", 2)
    beats, tempo, fb = _detect_beats(music, a.fallback_interval)
    print(f"tempo≈{tempo:.1f} BPM, {len(beats)} 个节拍点"
          f"{'（等间隔回退）' if fb else ''}")
    print(", ".join(f"{t:.2f}" for t in beats[:40]) + (" ..." if len(beats) > 40 else ""))
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("beatsync 自检 ...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 120BPM 衰减脉冲（每 0.5s 一拍），供 librosa 检测
        music = d / "beat.wav"
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", "aevalsrc=0.6*sin(2*PI*880*t)*exp(-16*mod(t\\,0.5)):d=8:s=22050",
              str(music)])
        imgs = []
        for i, c in enumerate(("red", "green", "blue", "yellow")):
            p = d / f"i{i}.png"
            _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={c}:s=640x640",
                  "-frames:v", "1", str(p)])
            imgs.append(str(p))

        out = d / "bs.mp4"
        ns = argparse.Namespace(input=imgs, images_dir=None, music=str(music),
                                output=str(out), size="480x854", every=2,
                                effect="zoom", fallback_interval=0.5, max_duration=None)
        cmd_build(ns)
        total = _probe_dur(out)
        assert out.is_file() and total > 1.0, f"卡点成片异常：{total:.2f}s"
        # 有音轨
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=index", "-of", "csv=p=0", str(out)],
                           stdout=subprocess.PIPE, text=True)
        assert (r.stdout or "").strip(), "成片缺音轨"

        # flash 特效 + 目录输入 + max-duration
        out2 = d / "bs2.mp4"
        ns2 = argparse.Namespace(input=None, images_dir=str(d), music=str(music),
                                 output=str(out2), size="480x480", every=1,
                                 effect="flash", fallback_interval=0.5, max_duration=4.0)
        cmd_build(ns2)
        assert _probe_dur(out2) <= 4.5, "max-duration 未生效"

    print("✅ selftest 全部通过（节拍检测 + zoom/flash + 目录 + max-duration）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="音乐卡点视频（librosa 节拍检测 + 画面踩点切换）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("build", help="图片/片段 + 音乐 → 卡点视频")
    p.add_argument("-i", "--input", nargs="+", help="图片/片段路径（循环使用）")
    p.add_argument("--images-dir", help="素材目录（按文件名排序，覆盖 -i）")
    p.add_argument("--music", required=True, help="背景音乐（决定卡点）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--size", default="1080x1920", help="画幅 WxH（默认竖版 1080x1920）")
    p.add_argument("--every", type=int, default=2, help="每几拍切一次画面（默认 2）")
    p.add_argument("--effect", default="zoom", choices=["none", "zoom", "flash"],
                   help="节拍特效：none / zoom 推进(默认) / flash 白闪")
    p.add_argument("--fallback-interval", type=float, default=0.5,
                   help="无明显节拍时的等间隔秒数（默认 0.5）")
    p.add_argument("--max-duration", type=float, help="成片最长秒数（默认跟音乐）")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("beats", help="只检测并打印节拍点")
    p.add_argument("--music", required=True)
    p.add_argument("--fallback-interval", type=float, default=0.5)
    p.set_defaults(func=cmd_beats)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
