#!/usr/bin/env python3
"""audio_viz.py — 音频可视化视频（波形/频谱/CQT）的确定性封装。

"音频可视化"类 SKILL（audio-visualizer）共用此脚本。把纯音频（播客片段、音乐、口播金句）
渲染成带动态波形/频谱的视频，配封面与标题，好发到抖音/B站/视频号等视频平台。

依赖：ffmpeg + ffprobe。

子命令：
    render    音频 → 可视化视频
    selftest  自检

可视化模式：
    waves     动态波形线（底部条带，简洁通用）
    bars      频谱柱状（底部条带，律动感强）
    spectrum  滚动声谱图（全屏，科技感）
    cqt       音乐频谱（全屏，随音符跳动，最好看，适合音乐）

用法举例：
    audio_viz.py render -i clip.mp3 -o out.mp4 --mode cqt --title "本期金句"
    audio_viz.py render -i song.mp3 -o out.mp4 --mode bars --cover cover.jpg --size 1080x1920
    audio_viz.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            _die(f"未找到 {t}，请先安装 ffmpeg（含 ffprobe）。", 3)


def _require(path: str) -> Path:
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


def _dur(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _find_font(explicit=None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            _die(f"字体不存在: {explicit}", 2)
        return explicit
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    _die("未找到字体，请用 --font 指定。", 2)
    return ""


def _esc(t: str) -> str:
    return (t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            .replace("%", "\\%"))


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def cmd_render(a) -> int:
    _check_ffmpeg()
    audio = _require(a.input)
    dur = _dur(audio)
    if dur <= 0:
        _die("无法读取音频时长。", 2)
    try:
        w, h = (int(x) for x in a.size.lower().split("x"))
    except ValueError:
        _die(f"size 格式错误：{a.size}", 2)
    out = _prep_out(a.output)
    color = a.color

    inputs = ["-i", str(audio)]
    idx = 1
    bg_idx = cover_idx = None
    if a.bg_image:
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(_require(a.bg_image))]
        bg_idx = idx; idx += 1
    if a.cover:
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(_require(a.cover))]
        cover_idx = idx; idx += 1

    filt: list[str] = []
    full = a.mode in ("spectrum", "cqt")
    # 背景（仅在会被用到时创建：非全屏模式，或全屏模式且有背景图）
    need_bg = (not full) or (bg_idx is not None)
    if need_bg:
        if bg_idx is not None:
            filt.append(f"[{bg_idx}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                        f"crop={w}:{h},setsar=1[bg]")
        else:
            filt.append(f"color=c={color}:s={w}x{h}:d={dur:.3f}[bg]")

    if a.mode == "spectrum":
        filt.append(f"[0:a]showspectrum=s={w}x{h}:mode=combined:color=intensity:"
                    f"scale=cbrt:slide=scroll[viz]")
    elif a.mode == "cqt":
        filt.append(f"[0:a]showcqt=s={w}x{h}:count=6:gamma=5[viz]")
    elif a.mode == "bars":
        vh = int(h * 0.34)
        filt.append(f"[0:a]showfreqs=s={w}x{vh}:mode=bar:ascale=cbrt:"
                    f"colors={a.wave_color}[viz]")
    else:  # waves
        vh = int(h * 0.30)
        filt.append(f"[0:a]showwaves=s={w}x{vh}:mode=cline:draw=full:"
                    f"colors={a.wave_color}[viz]")

    # 合成基底
    if full:
        if bg_idx is not None:
            # 有背景图：把频谱以 60% 透明叠加在图上
            filt.append("[viz]format=rgba,colorchannelmixer=aa=0.6[vizt]")
            filt.append("[bg][vizt]overlay=0:0[base]")
        else:
            filt.append("[viz]copy[base]")
    else:
        y = int(h * 0.66) if a.mode == "waves" else int(h * 0.62)
        filt.append(f"[bg][viz]overlay=0:{y}[base]")

    cur = "[base]"
    # 封面（居中偏上）
    if cover_idx is not None:
        cw = int(w * 0.5)
        filt.append(f"[{cover_idx}:v]scale={cw}:-1[cov]")
        filt.append(f"{cur}[cov]overlay=(W-w)/2:{int(h*0.16)}[b_cov]")
        cur = "[b_cov]"
    # 标题
    if a.title:
        font = _find_font(a.font)
        fs = max(28, h // 22)
        yy = f"{int(h*0.06)}" if cover_idx is None else f"{int(h*0.50)}"
        filt.append(f"{cur}drawtext=fontfile='{font}':text='{_esc(a.title)}':"
                    f"fontcolor=white:fontsize={fs}:x=(w-text_w)/2:y={yy}:"
                    f"borderw=3:bordercolor=black@0.5[final]")
        cur = "[final]"

    _run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt),
          "-map", cur, "-map", "0:a",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", str(out)])
    _done(out, f"({a.mode} / {dur:.1f}s / {w}x{h})")
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("audio_viz 自检 ...", file=sys.stderr)
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        audio = d / "a.mp3"
        _run(["ffmpeg", "-y", "-f", "lavfi",
              "-i", "sine=frequency=440:d=3", "-q:a", "4", str(audio)])
        cover = d / "cover.png"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=orange:s=400x400",
              "-frames:v", "1", str(cover)])

        for mode in ("waves", "bars", "spectrum", "cqt"):
            out = d / f"{mode}.mp4"
            ns = argparse.Namespace(input=str(audio), output=str(out), mode=mode,
                                    size="480x854", color="0x101020",
                                    wave_color="cyan", bg_image=None,
                                    cover=None, title=None, font=None)
            cmd_render(ns)
            assert out.is_file() and _dur(out) > 2.0, f"{mode} 输出异常"
            # 有视频+音频轨
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "stream=codec_type", "-of", "csv=p=0", str(out)],
                               stdout=subprocess.PIPE, text=True)
            types = (r.stdout or "").split()
            assert any("video" in t for t in types) and any("audio" in t for t in types), \
                f"{mode} 缺视频或音频轨"

        # 封面 + 标题
        out = d / "titled.mp4"
        ns = argparse.Namespace(input=str(audio), output=str(out), mode="bars",
                                size="480x854", color="0x101020", wave_color="cyan",
                                bg_image=None, cover=str(cover), title="测试标题",
                                font=None)
        cmd_render(ns)
        assert out.is_file(), "封面+标题渲染失败"

    print("✅ selftest 全部通过（waves/bars/spectrum/cqt + 封面标题）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="音频可视化视频（波形/频谱/CQT，ffmpeg 确定性封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("render", help="音频 → 可视化视频")
    p.add_argument("-i", "--input", required=True, help="音频文件")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--mode", default="cqt", choices=["waves", "bars", "spectrum", "cqt"],
                   help="waves 波形 / bars 频谱柱 / spectrum 声谱 / cqt 音乐频谱(默认)")
    p.add_argument("--size", default="1080x1920", help="画幅 WxH（默认竖版 1080x1920）")
    p.add_argument("--color", default="0x101020", help="背景色（默认深色）")
    p.add_argument("--wave-color", default="cyan", help="波形/柱状颜色（默认 cyan）")
    p.add_argument("--bg-image", help="背景图（覆盖背景色）")
    p.add_argument("--cover", help="封面图（居中偏上叠加，如专辑封面/头像）")
    p.add_argument("--title", help="标题文字")
    p.add_argument("--font", help="字体路径（默认自动探测 CJK）")
    p.set_defaults(func=cmd_render)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
