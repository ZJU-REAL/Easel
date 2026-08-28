#!/usr/bin/env python3
"""video_ops.py — 通用视频处理的确定性封装（subprocess 调 ffmpeg / ffprobe）。

所有"视频剪辑处理"类 SKILL（video-editing 等）共用此脚本，避免每次现场
即兴拼 ffmpeg 命令导致的滤镜链写错、音画不同步、字体路径找不到等问题。

与 clipify 的边界：clipify 是"长视频智能切片 + 人脸 pan + 字幕烧录"的特化
流程（自带 analyze/build_pan/build_ass 脚本）；本脚本只做通用剪辑处理，不做
人脸追踪、不做字幕烧录。

依赖：ffmpeg + ffprobe（系统 PATH 中）。

子命令（每个都能 `-h`）：
    cut        按起止时间裁剪
    concat     多段视频拼接（同参数 concat demuxer / 异参数 filter）
    speed      变速（setpts + atempo 同步音频）
    silence-cut  检测静音段并去除（跳切去静音，别名 mute-cut）
    text       文字覆盖（drawtext，位置/字号/颜色/时间段）
    aspect     横竖比转换（pad 补边 / crop 裁切）
    frame      抽取指定时间的帧为图片（封面）
    gif        视频转 GIF（时间段/帧率/宽度）
    compress   压缩（crf / 目标码率）
    bgm        加背景音乐（混音，可调原声/BGM 音量比）
    watermark  加图片水印（位置）
    info       ffprobe 输出时长/分辨率/帧率/码率（json）

用法举例：
    video_ops.py cut  -i in.mp4 -o out.mp4 --start 00:00:05 --end 00:00:20
    video_ops.py aspect -i in.mp4 -o out.mp4 --ratio 9:16 --mode pad
    video_ops.py frame -i in.mp4 -o cover.jpg --time 00:00:03
    video_ops.py gif  -i in.mp4 -o out.gif --start 2 --end 6 --fps 12 --width 480
    video_ops.py info -i in.mp4
    video_ops.py --selftest
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────────────────────
# 中文字体候选（drawtext 需要显式字体路径）
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",  # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # 兜底（无中文）
]

# 常见宽高比 → 数值（W/H），用于 aspect 转换
_RATIOS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "4:5": (4, 5),  # Instagram 竖版
    "21:9": (21, 9),
}

# drawtext / overlay / watermark 位置 → 表达式
_POSITIONS = {
    "center": ("(w-text_w)/2", "(h-text_h)/2"),
    "top": ("(w-text_w)/2", "{m}"),
    "bottom": ("(w-text_w)/2", "h-text_h-{m}"),
    "top-left": ("{m}", "{m}"),
    "top-right": ("w-text_w-{m}", "{m}"),
    "bottom-left": ("{m}", "h-text_h-{m}"),
    "bottom-right": ("w-text_w-{m}", "h-text_h-{m}"),
}

# overlay（图片水印）位置：用 overlay_w/overlay_h 表示叠加层尺寸
_OVERLAY_POS = {
    "center": ("(W-w)/2", "(H-h)/2"),
    "top": ("(W-w)/2", "{m}"),
    "bottom": ("(W-w)/2", "H-h-{m}"),
    "top-left": ("{m}", "{m}"),
    "top-right": ("W-w-{m}", "{m}"),
    "bottom-left": ("{m}", "H-h-{m}"),
    "bottom-right": ("W-w-{m}", "H-h-{m}"),
}


# ── 基础工具 ──────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            _die(f"未找到 {tool}，请先安装 ffmpeg（含 ffprobe）。", 3)


def _require_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess:
    """执行 ffmpeg/ffprobe，失败时打印 stderr 尾部并退出。"""
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(err[-15:]) if err else "(无 stderr 输出)"
        _die(f"ffmpeg/ffprobe 执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)
    return proc


def _run_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    """执行并捕获 stderr（供需要解析 stderr 的场景，如 silencedetect）。"""
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _find_font(explicit: str | None = None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            _die(f"指定字体文件不存在: {explicit}", 2)
        return explicit
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    _die("未找到可用字体（含中文），请用 --font 显式指定 .ttf/.ttc 路径。", 2)
    return ""  # unreachable


def _escape_drawtext(text: str) -> str:
    """drawtext text 值转义：反斜杠、冒号、单引号、百分号。"""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def _ffprobe_json(path: Path) -> dict:
    proc = _run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture=True,
    )
    return json.loads(proc.stdout or "{}")


def _has_audio(path: Path) -> bool:
    data = _ffprobe_json(path)
    return any(s.get("codec_type") == "audio" for s in data.get("streams", []))


def _done(out: Path) -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB)")


# ── 子命令实现 ────────────────────────────────────────────────────────
def cmd_cut(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    cmd = ["ffmpeg", "-y"]
    # -ss 放 -i 前更快（关键帧定位）；精确裁剪用 -accurate_seek + 重编码
    if a.start:
        cmd += ["-ss", a.start]
    cmd += ["-i", str(src)]
    if a.end:
        cmd += ["-to", a.end]
    elif a.duration:
        cmd += ["-t", a.duration]
    if a.reencode:
        cmd += ["-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
                "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c", "copy"]
    cmd += [str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_concat(a) -> int:
    inputs = [_require_input(p) for p in a.inputs]
    out = _prep_out(a.output)
    if len(inputs) < 2:
        _die("concat 至少需要 2 个输入文件。", 2)
    if a.mode == "demuxer":
        # 同编码/同分辨率，无损快速拼接
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for p in inputs:
                f.write(f"file '{p.resolve()}'\n")
            listfile = f.name
        try:
            _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                  "-i", listfile, "-c", "copy", str(out)])
        finally:
            Path(listfile).unlink(missing_ok=True)
    else:
        # filter 模式：统一到同分辨率/帧率再拼，兼容异参数源
        n = len(inputs)
        cmd = ["ffmpeg", "-y"]
        for p in inputs:
            cmd += ["-i", str(p)]
        w, h = a.width, a.height
        parts = []
        for i in range(n):
            parts.append(
                f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={a.fps}[v{i}];"
            )
            parts.append(f"[{i}:a]aresample=async=1[a{i}];")
        streams = "".join(f"[v{i}][a{i}]" for i in range(n))
        filt = "".join(parts) + f"{streams}concat=n={n}:v=1:a=1[v][a]"
        cmd += ["-filter_complex", filt, "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
                "-c:a", "aac", "-b:a", "192k", str(out)]
        _run(cmd)
    _done(out)
    return 0


def cmd_speed(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    factor = a.factor
    if factor <= 0:
        _die("变速倍率必须 > 0。", 2)
    vpts = round(1.0 / factor, 6)
    has_audio = _has_audio(src)
    if has_audio:
        # atempo 单次范围 0.5-2.0，超出用链式拆分
        atempo = _atempo_chain(factor)
        filt = f"[0:v]setpts={vpts}*PTS[v];[0:a]{atempo}[a]"
        cmd = ["ffmpeg", "-y", "-i", str(src), "-filter_complex", filt,
               "-map", "[v]", "-map", "[a]",
               "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
               "-c:a", "aac", "-b:a", "192k", str(out)]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(src), "-filter:v", f"setpts={vpts}*PTS",
               "-an", "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset, str(out)]
    _run(cmd)
    _done(out)
    return 0


def _atempo_chain(factor: float) -> str:
    """把任意变速倍率拆成多个 atempo（每个限定 0.5-2.0）串联。"""
    parts = []
    f = factor
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={round(f, 6)}")
    return ",".join(parts)


def _parse_silences(stderr: str) -> list[tuple[float, float]]:
    """从 silencedetect 的 stderr 解析出 [(start, end), ...] 静音段。"""
    starts, silences = [], []
    for line in stderr.splitlines():
        if "silence_start:" in line:
            try:
                starts.append(float(line.split("silence_start:")[1].strip().split()[0]))
            except (ValueError, IndexError):
                pass
        elif "silence_end:" in line:
            try:
                end = float(line.split("silence_end:")[1].strip().split("|")[0].strip().split()[0])
                if starts:
                    silences.append((starts.pop(0), end))
            except (ValueError, IndexError):
                pass
    return silences


def cmd_silence_cut(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    if not _has_audio(src):
        _die("输入无音轨，无法做静音检测跳切。", 2)
    # 1) 检测静音段
    detect = _run_quiet(
        ["ffmpeg", "-i", str(src), "-af",
         f"silencedetect=noise={a.noise}dB:d={a.min_silence}", "-f", "null", "-"]
    )
    silences = _parse_silences(detect.stderr)
    dur = float(_ffprobe_json(src).get("format", {}).get("duration", 0) or 0)
    if not silences:
        print("未检测到静音段（阈值可能过严），直接复制原视频。", file=sys.stderr)
        _run(["ffmpeg", "-y", "-i", str(src), "-c", "copy", str(out)])
        _done(out)
        return 0
    # 2) 反推非静音（keep）段，加边距 pad
    keeps: list[tuple[float, float]] = []
    cursor = 0.0
    pad = a.pad
    for s, e in silences:
        seg_end = max(cursor, s + pad)
        if seg_end - cursor > 0.05:
            keeps.append((cursor, seg_end))
        cursor = max(cursor, e - pad)
    if dur > cursor + 0.05:
        keeps.append((cursor, dur))
    if not keeps:
        _die("去静音后无剩余片段，请放宽阈值。", 1)
    # 3) 用 filter 一次性拼接（select + aselect，重编码保证准确）
    vsel = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in keeps)
    filt = (
        f"[0:v]select='{vsel}',setpts=N/FRAME_RATE/TB[v];"
        f"[0:a]aselect='{vsel}',asetpts=N/SR/TB[a]"
    )
    _run(["ffmpeg", "-y", "-i", str(src), "-filter_complex", filt,
          "-map", "[v]", "-map", "[a]",
          "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset,
          "-c:a", "aac", "-b:a", "192k", str(out)])
    removed = dur - sum(e - s for s, e in keeps)
    print(f"检测到 {len(silences)} 段静音，保留 {len(keeps)} 段，去除约 {removed:.1f}s。",
          file=sys.stderr)
    _done(out)
    return 0


def cmd_text(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    font = _find_font(a.font)
    xtpl, ytpl = _POSITIONS[a.position]
    x = xtpl.format(m=a.margin)
    y = ytpl.format(m=a.margin)
    draw = (
        f"drawtext=fontfile='{font}':text='{_escape_drawtext(a.text)}':"
        f"fontsize={a.fontsize}:fontcolor={a.color}:x={x}:y={y}"
    )
    if a.box:
        draw += f":box=1:boxcolor={a.boxcolor}:boxborderw={a.boxborderw}"
    if a.start is not None or a.end is not None:
        s = a.start if a.start is not None else 0
        if a.end is not None:
            draw += f":enable='between(t,{s},{a.end})'"
        else:
            draw += f":enable='gte(t,{s})'"
    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", draw,
           "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset]
    cmd += (["-c:a", "copy"] if _has_audio(src) else ["-an"])
    cmd += [str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_aspect(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    if a.ratio not in _RATIOS:
        _die(f"未知比例 {a.ratio}，支持: {', '.join(_RATIOS)}", 2)
    rw, rh = _RATIOS[a.ratio]
    # 目标宽度基准（竖版默认 1080 宽；用户可 --width 覆盖）
    tw = a.width
    th = round(tw * rh / rw)
    # 保证偶数（libx264 要求）
    tw -= tw % 2
    th -= th % 2
    if a.mode == "pad":
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
              f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:{a.padcolor},setsar=1")
    else:  # crop
        vf = (f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
              f"crop={tw}:{th},setsar=1")
    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset]
    cmd += (["-c:a", "copy"] if _has_audio(src) else ["-an"])
    cmd += [str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_frame(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    cmd = ["ffmpeg", "-y", "-ss", a.time, "-i", str(src), "-frames:v", "1"]
    if a.width:
        cmd += ["-vf", f"scale={a.width}:-2"]
    cmd += ["-q:v", str(a.quality), str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_gif(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    trim = []
    if a.start:
        trim += ["-ss", a.start]
    if a.end:
        trim += ["-to", a.end]
    elif a.duration:
        trim += ["-t", a.duration]
    # 两遍：生成调色板再应用，质量高、体积小
    vf = f"fps={a.fps},scale={a.width}:-1:flags=lanczos"
    with tempfile.TemporaryDirectory() as d:
        palette = str(Path(d) / "palette.png")
        _run(["ffmpeg", "-y", *trim, "-i", str(src),
              "-vf", f"{vf},palettegen=stats_mode=diff", palette])
        _run(["ffmpeg", "-y", *trim, "-i", str(src), "-i", palette,
              "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer", str(out)])
    _done(out)
    return 0


def cmd_compress(a) -> int:
    src = _require_input(a.input)
    out = _prep_out(a.output)
    cmd = ["ffmpeg", "-y", "-i", str(src), "-c:v", "libx264", "-preset", a.preset]
    if a.bitrate:
        cmd += ["-b:v", a.bitrate, "-maxrate", a.bitrate,
                "-bufsize", a.bitrate]
    else:
        cmd += ["-crf", str(a.crf)]
    if a.scale:
        cmd += ["-vf", f"scale={a.scale}:-2"]
    cmd += ["-pix_fmt", "yuv420p"]
    cmd += (["-c:a", "aac", "-b:a", str(a.audio_bitrate)]
            if _has_audio(src) else ["-an"])
    cmd += [str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_bgm(a) -> int:
    src = _require_input(a.input)
    music = _require_input(a.music)
    out = _prep_out(a.output)
    src_has_audio = _has_audio(src)
    if src_has_audio:
        # 原声 + BGM 混音，各自音量可调；BGM 循环并在视频结束时截断
        filt = (
            f"[0:a]volume={a.voice_volume}[a0];"
            f"[1:a]volume={a.music_volume}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        cmd = ["ffmpeg", "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(music),
               "-filter_complex", filt, "-map", "0:v", "-map", "[a]",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
               "-shortest", str(out)]
    else:
        # 视频无声：直接把 BGM 作为音轨
        cmd = ["ffmpeg", "-y", "-i", str(src), "-stream_loop", "-1", "-i", str(music),
               "-filter_complex", f"[1:a]volume={a.music_volume}[a]",
               "-map", "0:v", "-map", "[a]", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_watermark(a) -> int:
    src = _require_input(a.input)
    logo = _require_input(a.logo)
    out = _prep_out(a.output)
    xtpl, ytpl = _OVERLAY_POS[a.position]
    x = xtpl.format(m=a.margin)
    y = ytpl.format(m=a.margin)
    scale = ""
    if a.width:
        scale = f"[1:v]scale={a.width}:-1[wm];"
        base = "[0:v][wm]"
    else:
        base = "[0:v][1:v]"
    filt = f"{scale}{base}overlay={x}:{y}:format=auto"
    if a.opacity < 1.0:
        # 用 format=rgba + colorchannelmixer 调透明度
        filt = (f"[1:v]scale={a.width if a.width else 'iw'}:-1,"
                f"format=rgba,colorchannelmixer=aa={a.opacity}[wm];"
                f"[0:v][wm]overlay={x}:{y}")
    cmd = ["ffmpeg", "-y", "-i", str(src), "-i", str(logo),
           "-filter_complex", filt,
           "-c:v", "libx264", "-crf", str(a.crf), "-preset", a.preset]
    cmd += (["-c:a", "copy"] if _has_audio(src) else ["-an"])
    cmd += [str(out)]
    _run(cmd)
    _done(out)
    return 0


def cmd_info(a) -> int:
    src = _require_input(a.input)
    data = _ffprobe_json(src)
    fmt = data.get("format", {})
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    au = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})

    def _fps(stream: dict) -> float:
        rate = stream.get("r_frame_rate", "0/1")
        try:
            n, d = rate.split("/")
            return round(int(n) / int(d), 3) if int(d) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    out = {
        "path": str(src),
        "duration_sec": round(float(fmt.get("duration", 0) or 0), 3),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "bitrate_kbps": round(int(fmt.get("bit_rate", 0) or 0) / 1000, 1),
        "format": fmt.get("format_name", ""),
        "video": {
            "codec": v.get("codec_name", ""),
            "width": v.get("width"),
            "height": v.get("height"),
            "fps": _fps(v),
            "pix_fmt": v.get("pix_fmt", ""),
        } if v else None,
        "audio": {
            "codec": au.get("codec_name", ""),
            "sample_rate": au.get("sample_rate", ""),
            "channels": au.get("channels"),
        } if au else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ── selftest ─────────────────────────────────────────────────────────
def _selftest() -> int:
    _check_tools()
    with tempfile.TemporaryDirectory() as d:
        dd = Path(d)
        vid = dd / "test.mp4"
        # 生成 5 秒测试视频（testsrc 640x360 30fps + sine 音）
        print("[selftest] 生成测试视频 (testsrc + sine, 5s)...")
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
            "-c:a", "aac", "-pix_fmt", "yuv420p", str(vid),
        ])
        checks: list[tuple[str, Path]] = []

        cut_out = dd / "cut.mp4"
        cmd_cut(argparse.Namespace(input=str(vid), output=str(cut_out),
                start="00:00:01", end="00:00:03", duration=None,
                reencode=True, crf=23, preset="ultrafast"))
        checks.append(("cut", cut_out))

        asp_out = dd / "aspect.mp4"
        cmd_aspect(argparse.Namespace(input=str(vid), output=str(asp_out),
                ratio="9:16", mode="pad", width=1080, padcolor="black",
                crf=23, preset="ultrafast"))
        checks.append(("aspect 16:9→9:16", asp_out))

        frm_out = dd / "frame.jpg"
        cmd_frame(argparse.Namespace(input=str(vid), output=str(frm_out),
                time="00:00:02", width=None, quality=2))
        checks.append(("frame", frm_out))

        gif_out = dd / "out.gif"
        cmd_gif(argparse.Namespace(input=str(vid), output=str(gif_out),
                start="1", end="3", duration=None, fps=10, width=320))
        checks.append(("gif", gif_out))

        ok = True
        for name, p in checks:
            good = p.is_file() and p.stat().st_size > 0
            print(f"  {'[PASS]' if good else '[FAIL]'} {name} → {p.name} "
                  f"({p.stat().st_size / 1024:.0f} KB)" if good else f"  [FAIL] {name}")
            ok = ok and good

    if ok:
        print("[PASS] video_ops 自检通过（cut / aspect / frame / gif）")
        return 0
    print("[FAIL] video_ops 自检失败", file=sys.stderr)
    return 1


# ── argparse ─────────────────────────────────────────────────────────
def _add_common_encode(sp, crf_default: int = 20) -> None:
    sp.add_argument("--crf", type=int, default=crf_default,
                    help=f"libx264 质量（越小越清晰，默认 {crf_default}）")
    sp.add_argument("--preset", default="medium",
                    help="libx264 preset（ultrafast..veryslow，默认 medium）")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="通用视频处理（ffmpeg/ffprobe 封装）。子命令均支持 -h。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="用 ffmpeg 生成测试视频跑通 cut/aspect/frame/gif")
    sub = ap.add_subparsers(dest="cmd", metavar="<子命令>")

    # cut
    p = sub.add_parser("cut", help="按起止时间裁剪")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--start", help="起始时间 HH:MM:SS 或 秒")
    p.add_argument("--end", help="结束时间 HH:MM:SS 或 秒")
    p.add_argument("--duration", help="时长（与 --end 二选一）")
    p.add_argument("--reencode", action="store_true",
                   help="重编码（精确裁剪；默认 -c copy 关键帧对齐更快）")
    _add_common_encode(p)
    p.set_defaults(func=cmd_cut)

    # concat
    p = sub.add_parser("concat", help="多段视频拼接")
    p.add_argument("-i", "--inputs", nargs="+", required=True, help="多个输入文件")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--mode", choices=["demuxer", "filter"], default="demuxer",
                   help="demuxer=同参数无损快拼；filter=异参数统一后拼")
    p.add_argument("--width", type=int, default=1920, help="filter 模式统一宽")
    p.add_argument("--height", type=int, default=1080, help="filter 模式统一高")
    p.add_argument("--fps", type=int, default=30, help="filter 模式统一帧率")
    _add_common_encode(p)
    p.set_defaults(func=cmd_concat)

    # speed
    p = sub.add_parser("speed", help="变速（音画同步）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--factor", type=float, required=True,
                   help="倍率（2.0=两倍速，0.5=半速）")
    _add_common_encode(p)
    p.set_defaults(func=cmd_speed)

    # silence-cut / mute-cut
    for name in ("silence-cut", "mute-cut"):
        p = sub.add_parser(name, help="检测静音并去除（跳切）")
        p.add_argument("-i", "--input", required=True)
        p.add_argument("-o", "--output", required=True)
        p.add_argument("--noise", type=float, default=-30,
                       help="静音阈值 dB（默认 -30）")
        p.add_argument("--min-silence", type=float, default=0.5,
                       help="最短静音时长 秒（默认 0.5）")
        p.add_argument("--pad", type=float, default=0.05,
                       help="保留段边距 秒，避免切太紧（默认 0.05）")
        _add_common_encode(p)
        p.set_defaults(func=cmd_silence_cut)

    # text
    p = sub.add_parser("text", help="文字覆盖（drawtext）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--position", choices=list(_POSITIONS), default="bottom")
    p.add_argument("--fontsize", type=int, default=48)
    p.add_argument("--color", default="white", help="字体颜色（默认 white）")
    p.add_argument("--font", help="字体文件路径（默认自动找中文字体）")
    p.add_argument("--margin", type=int, default=40, help="边距 px（默认 40）")
    p.add_argument("--start", type=float, help="出现起始秒")
    p.add_argument("--end", type=float, help="消失结束秒")
    p.add_argument("--box", action="store_true", help="加文字背景框")
    p.add_argument("--boxcolor", default="black@0.5", help="背景框颜色")
    p.add_argument("--boxborderw", type=int, default=10)
    _add_common_encode(p)
    p.set_defaults(func=cmd_text)

    # aspect
    p = sub.add_parser("aspect", help="横竖比转换")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--ratio", required=True,
                   help=f"目标比例，支持: {', '.join(_RATIOS)}")
    p.add_argument("--mode", choices=["pad", "crop"], default="pad",
                   help="pad=补边不裁剪；crop=裁切填满")
    p.add_argument("--width", type=int, default=1080, help="目标宽（默认 1080）")
    p.add_argument("--padcolor", default="black", help="pad 补边颜色")
    _add_common_encode(p)
    p.set_defaults(func=cmd_aspect)

    # frame
    p = sub.add_parser("frame", help="抽取指定时间的帧为图片")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True, help="图片输出 .jpg/.png")
    p.add_argument("--time", default="00:00:01", help="时间点（默认 00:00:01）")
    p.add_argument("--width", type=int, help="缩放宽（等比）")
    p.add_argument("--quality", type=int, default=2, help="jpg 质量 2-31，越小越好")
    p.set_defaults(func=cmd_frame)

    # gif
    p = sub.add_parser("gif", help="视频转 GIF")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--start", help="起始时间")
    p.add_argument("--end", help="结束时间")
    p.add_argument("--duration", help="时长（与 --end 二选一）")
    p.add_argument("--fps", type=int, default=12, help="帧率（默认 12）")
    p.add_argument("--width", type=int, default=480, help="宽（默认 480）")
    p.set_defaults(func=cmd_gif)

    # compress
    p = sub.add_parser("compress", help="压缩（crf 或目标码率）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--bitrate", help="目标视频码率如 2M（给了则用 ABR，否则用 crf）")
    p.add_argument("--scale", type=int, help="缩放宽（等比降分辨率）")
    p.add_argument("--audio-bitrate", default="128k", help="音频码率（默认 128k）")
    _add_common_encode(p, crf_default=26)
    p.set_defaults(func=cmd_compress)

    # bgm
    p = sub.add_parser("bgm", help="加背景音乐（混音）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--music", required=True, help="BGM 音频文件")
    p.add_argument("--voice-volume", type=float, default=1.0, help="原声音量（默认 1.0）")
    p.add_argument("--music-volume", type=float, default=0.3, help="BGM 音量（默认 0.3）")
    p.set_defaults(func=cmd_bgm)

    # watermark
    p = sub.add_parser("watermark", help="加图片水印")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--logo", required=True, help="水印图片（png 带透明最佳）")
    p.add_argument("--position", choices=list(_OVERLAY_POS), default="bottom-right")
    p.add_argument("--margin", type=int, default=20, help="边距 px（默认 20）")
    p.add_argument("--width", type=int, help="水印缩放宽（等比）")
    p.add_argument("--opacity", type=float, default=1.0, help="透明度 0-1（默认 1.0）")
    _add_common_encode(p)
    p.set_defaults(func=cmd_watermark)

    # info
    p = sub.add_parser("info", help="ffprobe 输出时长/分辨率/帧率/码率 json")
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
    _check_tools()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
