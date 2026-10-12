#!/usr/bin/env python3
"""auto-short-video 合成器：分镜素材（图/片段 + 配音 + BGM + 字幕）→ 成品短视频。

这是端到端"主题→成片"流程里【确定性合成】的一环（ffmpeg）。上游的文案/配图/配音/
字幕/BGM 由各自 SKILL 生成（video-script / ai-image-gen / tts-voiceover / auto-subtitle
/ ai-music），本脚本负责把它们**可靠地拼成一条竖版短视频**。

输入 storyboard JSON（--storyboard 文件 或 stdin）：
{
  "size": "1080x1920",              // 可选，默认 1080x1920（9:16）
  "image_motion": "ken-burns",      // 可选；static 为完全静止、等比适配
  "shots": [
    {"image": "shot1.png", "duration": 3.0, "caption": "第一句话", "motion": "static"},
    {"video": "clip2.mp4", "caption": "第二句"},   // image 或 video 二选一
    ...
  ],
  "narration": "voice.mp3",         // 可选，整条配音；给了则总时长跟随它
  "bgm": "bgm.mp3",                 // 可选，背景音乐（自动压低音量混音）
  "subtitle": "sub.srt",            // 可选，烧录字幕；没给则用各 shot 的 caption 自动生成
  "bgm_volume": 0.25                 // 可选，BGM 相对音量（默认 0.25）
}

用法：
    assemble.py assemble --storyboard sb.json -o outputs/xxx/final.mp4
    assemble.py --selftest
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(msg: str, code: int = 1):
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            fail(f"未找到 {tool}，请先安装 ffmpeg。", 3)


def _run(cmd: list[str]):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").splitlines()[-12:])
        fail(f"ffmpeg 执行失败：\n{tail}", 4)


def _probe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _has_audio(path: str) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", path],
        capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


def _fmt_ts(sec: float) -> str:
    h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _auto_srt(shots: list[dict], durations: list[float], srt_path: Path):
    """用各 shot 的 caption + 时长自动生成 SRT。"""
    lines = []
    t = 0.0
    idx = 1
    for shot, dur in zip(shots, durations):
        cap = (shot.get("caption") or "").strip()
        if cap:
            lines.append(f"{idx}\n{_fmt_ts(t)} --> {_fmt_ts(t + dur)}\n{cap}\n")
            idx += 1
        t += dur
    srt_path.write_text("\n".join(lines), encoding="utf-8")


DEFAULT_SUB_FONT = "Noto Sans CJK SC"   # 环境已装 fonts-noto-cjk；缺则 libass 回退系统字体


def _ass_ts(srt_ts: str) -> str:
    """SRT 时间戳 HH:MM:SS,mmm → ASS H:MM:SS.cs（厘秒）。"""
    srt_ts = srt_ts.strip().replace(".", ",")
    hms, _, ms = srt_ts.partition(",")
    h, m, s = (hms.split(":") + ["0", "0", "0"])[:3]
    cs = int(round(int((ms or "0").ljust(3, "0")[:3]) / 10))
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def _char_units(ch: str) -> float:
    """单字符占的横向宽度单位：CJK/全角 ≈ 1 字号，拉丁/数字/空格/标点 ≈ 0.5。"""
    return 1.0 if ord(ch) > 0x2E80 else 0.5


def wrap_caption(text: str, max_units: float) -> list[str]:
    """按显示宽度把一行字幕**确定性**折成多行（CJK 逐字、拉丁尽量按空格断），每行 ≤ max_units。

    纯函数、可测。保证不超视频宽度、随宽度自适应；不依赖 libass 折行启发式。
    先并掉原有的软换行（统一按当前视频宽度重排），单个超长 token 也会被强制断开。
    """
    flat = " ".join(seg.strip() for seg in str(text).replace("\\N", "\n").split("\n") if seg.strip())
    if not flat:
        return []
    out: list[str] = []
    cur = ""
    cur_u = 0.0
    for ch in flat:
        cu = _char_units(ch)
        if cur and cur_u + cu > max_units:
            # 拉丁词内断行优化：尽量回退到最近空格处再断（CJK 无空格则原地断）
            if ch != " " and " " in cur.rstrip():
                head, _, tail = cur.rstrip().rpartition(" ")
                if head:
                    out.append(head)
                    cur = tail
                    cur_u = sum(_char_units(c) for c in tail)
                else:
                    out.append(cur); cur = ""; cur_u = 0.0
            else:
                out.append(cur); cur = ""; cur_u = 0.0
        if ch == " " and not cur:
            continue  # 行首不留空格
        cur += ch
        cur_u += cu
    if cur.strip():
        out.append(cur.rstrip())
    return out or [flat]


def _srt_to_ass(srt_path: Path, ass_path: Path, w: int, h: int,
                font: str = DEFAULT_SUB_FONT, font_size: int | None = None,
                margin_v: int | None = None) -> Path:
    """把 SRT 转成带完整样式的 ASS，尺寸/位置/折行**确定可控**（治「字幕过大 / 超出边界 / 挤成一行」）。

    关键：显式 PlayResX/Y = 视频尺寸，字号就是像素级别、不再被 libass 按默认 288 放大。
    默认字号 ≈ **短边***0.05（min(w,h)：竖屏 1080×1920→54、横屏 1920×1080→54，横竖屏都合适、
    不再横屏字号翻倍过大），Alignment=2 底部居中，MarginV≈高*0.07，MarginL/R≈宽*0.06。
    **长行按可用宽度确定性折行**（wrap_caption，CJK 逐字），保证不超边界、自适应视频宽度、可多行。
    白字黑描边（Outline=2, Shadow=0）竖/横屏可读。
    """
    fs = int(font_size if font_size else round(min(w, h) * 0.05))
    mv = int(margin_v if margin_v is not None else round(h * 0.07))
    mh = int(round(w * 0.06))
    # 每行最大宽度单位 = 可用像素宽 / 字号；留 6% 安全余量防描边/字距溢出。
    max_units = max(6.0, (w - 2 * mh) / fs * 0.94)
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,2,{mh},{mh},{mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    # 解析 SRT 块
    events: list[str] = []
    blocks = [b for b in srt_path.read_text(encoding="utf-8").replace("\r", "").split("\n\n") if b.strip()]
    for b in blocks:
        rows = [r for r in b.split("\n") if r.strip() != ""]
        ts_line = next((r for r in rows if "-->" in r), None)
        if not ts_line:
            continue
        start, _, end = ts_line.partition("-->")
        txt_rows = rows[rows.index(ts_line) + 1:]
        raw = " ".join(t.strip() for t in txt_rows) if txt_rows else ""
        wrapped = wrap_caption(raw, max_units)
        if not wrapped:
            continue
        text = "\\N".join(wrapped)
        events.append(f"Dialogue: 0,{_ass_ts(start)},{_ass_ts(end)},Default,,0,0,0,,{text}")
    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path


MAX_STRETCH = 2.0   # 慢放填满的最大倍数；超过则改用循环（避免过度慢动作）。仅 auto/stretch 模式用；trim 禁止填充。


def _image_filter(motion: str, w: int, h: int, frames: int) -> str:
    if motion == "static":
        return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30")
    if motion == "ken-burns":
        return (f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
                f"crop={w*2}:{h*2},"
                f"zoompan=z='min(zoom+0.0008,1.08)':d={frames}:s={w}x{h}:fps=30,"
                f"setsar=1")
    fail(f"shot motion 不支持：{motion}（只能是 static / ken-burns）")


def _make_shot_clip(shot: dict, dur: float, w: int, h: int, out: Path, workdir: Path,
                    pad_mode: str = "auto", include_audio: bool = False,
                    preserve_audio: bool = False, image_motion: str = "ken-burns"):
    """把单个 shot（图或视频）做成 w×h、时长 dur 的片段。

    视频短于 dur 时如何补足（pad_mode）：
      trim（自然，短剧默认）= **绝不慢放/循环/冻结**。够长裁到 dur；片段比 dur 短 → **直接硬失败**
        （让上游按真实片段重跑 align 或用更大档重生成，而不是冻结凑台词长度、破坏流畅度）。
      auto = 差得不多就慢放拉伸(setpts，≤MAX_STRETCH 倍)、差很多就循环(loop)；
      stretch = 一律慢放填满；loop = 一律循环填满；freeze = 一律冻结末帧（仅显式要求时）。
    视频长于 dur → 裁到 dur。
    """
    base_vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
               f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1")

    def audio_args(src: str | None) -> tuple[list[str], list[str]]:
        if not include_audio:
            return [], ["-an"]
        if preserve_audio:
            if not src or not _has_audio(src):
                fail(f"镜头声明 audio_mode=native，但源片段没有可用音轨：{src}")
            return [], ["-map", "0:v:0", "-map", "0:a:0", "-af",
                        "aresample=48000,aformat=channel_layouts=stereo,apad",
                        "-c:a", "aac", "-b:a", "192k"]
        return (["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"],
                ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"])

    if shot.get("video"):
        src = shot["video"]
        if not Path(src).is_file():
            fail(f"shot 视频不存在：{src}")
        src_dur = _probe_duration(src)
        extra_inputs, audio_out = audio_args(src)
        if src_dur >= dur - 0.05 or src_dur <= 0:
            # 够长（或探测不到）→ 裁到 dur
            _run(["ffmpeg", "-y", "-i", src, *extra_inputs, "-t", f"{dur:.3f}",
                  "-vf", f"{base_vf},fps=30", *audio_out,
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
            return
        factor = dur / src_dur
        mode = pad_mode
        if mode == "trim":
            # 自然模式：**绝不冻结/拉伸/循环**。片段比所需短 = 画面盖不住 → 直接硬失败，
            # 让上游按真实片段重跑 dubbing align（画面时长=真实片段长）或用更大档重生成该镜片段，
            # 而不是冻结末帧凑台词长度（那会让画面停住、割裂、不流畅）。
            fail(f"视频片段仅 {src_dur:.2f}s 但该镜要 {dur:.2f}s（差 {dur - src_dur:.2f}s）——"
                 f"trim(自然)模式禁止冻结/拉伸/循环。\n"
                 f"根因通常是：align 没在**真实视频片段都生成好之后**跑（用了台词长度当画面时长）。"
                 f"请先确保每镜 clip 已生成，重跑 `dubbing.py align`（按真实片段对齐），再合成；"
                 f"或用更大片段档重生成该镜。", 4)
        if mode == "auto":
            mode = "stretch" if factor <= MAX_STRETCH else "loop"
        if mode == "stretch":
            # 慢放：拉伸 PTS 到 dur，画面持续运动、无跳变、无停顿
            _run(["ffmpeg", "-y", "-i", src,
                  *extra_inputs, "-vf", f"{base_vf},setpts={factor:.4f}*PTS,fps=30", "-t", f"{dur:.3f}",
                  *audio_out, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
        elif mode == "freeze":
            # 冻结末帧（旧行为，仅当显式要求）
            _run(["ffmpeg", "-y", "-i", src,
                  *extra_inputs, "-vf", f"{base_vf},fps=30,tpad=stop_mode=clone:stop_duration={dur:.3f}",
                  "-t", f"{dur:.3f}", *audio_out, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
        else:  # loop：循环填满，画面持续运动（循环点有轻微跳变）
            _run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", src, *extra_inputs, "-t", f"{dur:.3f}",
                  "-vf", f"{base_vf},fps=30", *audio_out,
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
    else:
        src = shot.get("image")
        if not src or not Path(src).is_file():
            fail(f"shot 图片不存在：{src}")
        frames = max(1, int(dur * 30))
        extra_inputs, audio_out = audio_args(None)
        motion = str(shot.get("motion") or image_motion)
        # static 用于文字卡/slide/图表；Ken Burns 只用于适合裁切的照片。
        vf = _image_filter(motion, w, h, frames)
        _run(["ffmpeg", "-y", "-loop", "1", "-i", src, *extra_inputs, "-t", f"{dur:.3f}",
              "-vf", vf, *audio_out, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])


def cmd_assemble(args) -> int:
    _check_ffmpeg()
    raw = sys.stdin.read() if args.storyboard == "-" else Path(args.storyboard).read_text(encoding="utf-8")
    try:
        sb = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"storyboard 不是有效 JSON：{e}")

    shots = sb.get("shots") or []
    if not shots:
        fail("storyboard.shots 为空。")
    image_motion = str(sb.get("image_motion") or "ken-burns")
    if image_motion not in {"static", "ken-burns"}:
        fail("storyboard.image_motion 只能是 static / ken-burns")
    size = str(sb.get("size") or "1080x1920")
    try:
        w, h = (int(x) for x in size.lower().split("x"))
    except ValueError:
        fail(f"size 格式错误：{size}（应如 1080x1920）")

    narration = sb.get("narration")
    if narration and not Path(narration).is_file():
        fail(f"配音文件不存在：{narration}")

    # 决定每个 shot 时长：有显式 duration 用之；否则若有配音则均分配音时长；否则默认 3s
    durations: list[float] = []
    explicit = [float(s["duration"]) for s in shots if s.get("duration")]
    if narration and len(explicit) < len(shots):
        total = _probe_duration(narration)
        per = max(1.0, total / len(shots)) if total > 0 else 3.0
        durations = [float(s.get("duration") or per) for s in shots]
    else:
        durations = [float(s.get("duration") or 3.0) for s in shots]

    # 原生音频处理：**只有 native 镜**（audit 判「原声可用」）直通其原生音轨（人声+环境音）；
    # **dub 镜的原生音轨整轨丢弃、改由独立 TTS 配音替代**——因为无人声分离时原生轨里的完整人声无法只去人声、
    # 留了就会和 TTS **双重人声/回声**（真机踩过）。代价是 dub 镜丢失环境音（重复比丢环境音严重得多）。
    # 只有源片段无音轨（图片/静音 clip）也补静音。
    def _shot_keeps_audio(s: dict) -> bool:
        v = s.get("video")
        # dub 镜：视频模型原生音轨（含模型生成人声）不并入 abase，
        # 完全由独立 TTS 配音替代，防止双重人声。只有 native 镜的原轨直通。
        return (s.get("audio_mode") == "native"
                and bool(v) and Path(v).is_file() and _has_audio(v))
    keeps_audio = [_shot_keeps_audio(s) for s in shots]
    native_audio = any(keeps_audio)   # 是否存在「环境音底」（下方 abase 用它拼接，而非全程静音）

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)
        # 视频短于所需时长时如何填满：优先命令行，其次 storyboard，默认 auto（慢放/循环，保持画面运动）
        pad_mode = getattr(args, "pad_mode", None) or str(sb.get("pad_mode") or "auto")
        clips = []
        for i, (shot, dur) in enumerate(zip(shots, durations)):
            clip = workdir / f"clip_{i:03d}.mp4"
            print(f"  合成分镜 {i+1}/{len(shots)}（{dur:.1f}s）...", file=sys.stderr)
            _make_shot_clip(shot, dur, w, h, clip, workdir, pad_mode,
                            include_audio=native_audio,
                            preserve_audio=keeps_audio[i],
                            image_motion=image_motion)
            clips.append(clip)

        # 拼接
        concat_list = workdir / "list.txt"
        concat_list.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
        silent = workdir / "silent.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)])

        video_dur = sum(durations)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)

        # 字幕：优先用户给的 srt，否则用 caption 自动生成
        sub_path = None
        if sb.get("subtitle") and Path(sb["subtitle"]).is_file():
            sub_path = Path(sb["subtitle"])
        elif any(s.get("caption") for s in shots):
            sub_path = workdir / "auto.srt"
            _auto_srt(shots, durations, sub_path)

        # 音效轨：storyboard.sfx = [{"file": 路径, "at": 全局秒, "volume": 相对音量}]
        # （枪声/椅子移动/脚步/开门…按时间点叠进成片音轨，占用非台词时间，让画面有声音层次）
        sfx_list = [s for s in (sb.get("sfx") or []) if s.get("file") and Path(s["file"]).is_file()]
        for s in (sb.get("sfx") or []):
            if s.get("file") and not Path(s["file"]).is_file():
                print(f"  ⚠️ 音效文件不存在，跳过：{s['file']}", file=sys.stderr)

        # 音频：配音 + BGM + 定时音效 混音
        stage = silent
        if narration or sb.get("bgm") or sfx_list:
            stage2 = workdir / "with_audio.mp4"
            inputs = ["-i", str(silent)]
            filters = []
            amix_srcs = []
            ai = 1
            # 原生音频片段已与静音片段拼成一条连续底轨；无原生音频时才创建静音基底。
            if native_audio:
                filters.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[abase]")
            else:
                inputs += ["-f", "lavfi", "-t", f"{video_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
                filters.append(f"[{ai}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[abase]")
                ai += 1
            # 配音轨（旁白 + 未通过审计需换的对白；align 已把通过审计的 native 画内对白移除）
            has_voice = False
            if narration:
                inputs += ["-i", narration]
                filters.append(f"[{ai}:a]aresample=48000[voice]")
                has_voice = True
                ai += 1
            # 侧链闪避：有配音且存在原生底轨（来自 native 镜）时，用 TTS/旁白作侧链把底轨在**说话瞬间**压低，
            # 让旁白/配音干净盖在 native 镜的环境音之上；native 镜自身对白处配音轨为静音→不触发压低。
            # （dub 镜已不并入原生轨，这里不涉及 dub 的人声——双重人声从源头避免。）
            if has_voice and native_audio:
                filters.append("[voice]asplit=2[voicemix][voicekey]")
                filters.append("[abase][voicekey]sidechaincompress="
                               "threshold=0.03:ratio=8:attack=20:release=300[abaseduck]")
                amix_srcs.append("[abaseduck]")
                amix_srcs.append("[voicemix]")
            else:
                amix_srcs.append("[abase]")
                if has_voice:
                    amix_srcs.append("[voice]")
            if sb.get("bgm"):
                bgm = sb["bgm"]
                if not Path(bgm).is_file():
                    fail(f"BGM 文件不存在：{bgm}")
                vol = float(sb.get("bgm_volume") or 0.25)
                inputs += ["-stream_loop", "-1", "-i", bgm]
                filters.append(f"[{ai}:a]aresample=44100,volume={vol}[bgm]")
                amix_srcs.append("[bgm]")
                ai += 1
            for si, s in enumerate(sfx_list):
                ms = max(0, int(round(float(s.get("at") or 0.0) * 1000)))
                vol = float(s.get("volume") or 0.9)
                inputs += ["-i", str(s["file"])]
                filters.append(f"[{ai}:a]aresample=44100,volume={vol},adelay={ms}|{ms}[sfx{si}]")
                amix_srcs.append(f"[sfx{si}]")
                ai += 1
            # 基底在首位 → duration=first=视频时长；normalize=0 保各轨原音量（不因轨数被均分压低）。
            filters.append(f"{''.join(amix_srcs)}amix=inputs={len(amix_srcs)}:duration=first:normalize=0[aout]")
            _run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filters),
                  "-map", "0:v", "-map", "[aout]", "-t", f"{video_dur:.3f}",
                  "-c:v", "copy", "-c:a", "aac", str(stage2)])
            stage = stage2

        # 烧字幕：SRT → 带完整样式的 ASS（尺寸/位置可控，底部居中、字号合适），再烧录
        if sub_path:
            if sub_path.suffix.lower() == ".ass":
                ass_path = sub_path
            else:
                ass_path = workdir / "sub.ass"
                _srt_to_ass(sub_path, ass_path, w, h,
                            font=getattr(args, "sub_font", None) or DEFAULT_SUB_FONT,
                            font_size=getattr(args, "sub_size", None),
                            margin_v=getattr(args, "sub_margin_v", None))
            escaped = str(ass_path).replace("'", "\\'").replace(":", "\\:")
            _run(["ffmpeg", "-y", "-i", str(stage),
                  "-vf", f"subtitles='{escaped}'",
                  "-c:a", "copy", str(out)])
        else:
            shutil.copy(str(stage), str(out))

    print(f"✅ 成片已生成：{out}（{video_dur:.1f}s，{w}x{h}）")
    return 0


def cmd_selftest(_args) -> int:
    _check_ffmpeg()
    static_vf = _image_filter("static", 1080, 1920, 60)
    kenburns_vf = _image_filter("ken-burns", 1080, 1920, 60)
    if "zoompan" in static_vf or "crop=" in static_vf or "pad=" not in static_vf:
        fail("自检失败：static 图片过滤器发生裁切或移动", 1)
    if "zoompan" not in kenburns_vf:
        fail("自检失败：Ken Burns 过滤器未生效", 1)
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        # 造两张测试图（ffmpeg lavfi）
        imgs = []
        for i, color in enumerate(("red", "blue")):
            p = wd / f"img{i}.png"
            _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:d=1",
                  "-frames:v", "1", str(p)])
            imgs.append(str(p))
        # 造一段配音（正弦音代替）
        voice = wd / "v.mp3"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
              "-q:a", "5", str(voice)])
        sb = {"size": "1080x1920", "narration": str(voice),
              "shots": [{"image": imgs[0], "duration": 2, "caption": "第一句字幕测试"},
                        {"image": imgs[1], "duration": 2, "caption": "第二句字幕测试",
                         "motion": "static"}]}
        sbf = wd / "sb.json"
        sbf.write_text(json.dumps(sb), encoding="utf-8")
        out = wd / "final.mp4"
        ns = argparse.Namespace(storyboard=str(sbf), output=str(out))
        cmd_assemble(ns)
        if not (out.is_file() and out.stat().st_size > 0 and _probe_duration(str(out)) > 3):
            fail("自检失败：成片未正确生成", 1)
        print("[PASS] assemble 自检通过（真出成片，含 Ken Burns/static + 配音 + 字幕）")

        # 字幕 ASS：显式 PlayRes + 底部居中 + 字号按分辨率（治「字幕过大」）
        srt = wd / "t.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\n第一句\n\n"
                       "2\n00:00:01,500 --> 00:00:03,000\n第二句\n", encoding="utf-8")
        ass = wd / "t.ass"
        _srt_to_ass(srt, ass, 1080, 1920)
        at = ass.read_text(encoding="utf-8")
        ok_ass = ("PlayResX: 1080" in at and "PlayResY: 1920" in at
                  and f"Default,{DEFAULT_SUB_FONT},54," in at   # 1080*0.05=54，不再等效 106
                  and at.count("Dialogue:") == 2
                  and ",2,"  # Alignment=2 底部居中（样式行倒数第 4 组）
                  in at.split("Style: Default,")[1])
        print(f"[{'PASS' if ok_ass else 'FAIL'}] 字幕 ASS：PlayRes=视频尺寸/字号54/底部居中/2段")
        if not ok_ass:
            fail("ASS 样式不正确", 1)

        # 视频镜精确到 dur 且**保持画面运动**（不冻结）：源 1s
        vid = wd / "clip1s.mp4"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=1080x1920:d=1",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid)])
        def _wsb(wd, vid, d):
            p = wd / f"sb_{d}.json"
            p.write_text(json.dumps({"size": "1080x1920",
                                     "shots": [{"video": str(vid), "duration": d}]}), encoding="utf-8")
            return p
        # a) 要求 1.8s → factor 1.8≤2 → 慢放拉伸填满
        out_s = wd / "stretch.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(_wsb(wd, vid, 1.8)), output=str(out_s)))
        ds = _probe_duration(str(out_s))
        # b) 要求 3s → factor 3>2 → 循环填满
        out_l = wd / "loop.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(_wsb(wd, vid, 3.0)), output=str(out_l), pad_mode="auto"))
        dl = _probe_duration(str(out_l))
        ok_pad = (1.6 <= ds <= 2.0) and (2.7 <= dl <= 3.3)
        print(f"[{'PASS' if ok_pad else 'FAIL'}] 视频保持运动填满：慢放 1s→{ds:.2f}s(目标1.8) / 循环 1s→{dl:.2f}s(目标3)")
        if not ok_pad:
            fail("视频未按 dur 精确填满", 1)

        # c) trim（自然）模式：够长→裁到 dur（1s 片段要 0.8s → 裁到 0.8s，自然，不填充）
        out_t = wd / "trim.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(_wsb(wd, vid, 0.8)), output=str(out_t), pad_mode="trim"))
        dt = _probe_duration(str(out_t))
        ok_trim = 0.6 <= dt <= 1.0
        print(f"[{'PASS' if ok_trim else 'FAIL'}] trim 够长裁到 dur：1s→{dt:.2f}s(目标0.8，不填充)")
        if not ok_trim:
            fail("trim 裁剪异常", 1)
        # d) trim 模式片段比 dur 短 → **硬失败**（绝不冻结/拉伸/循环）
        import subprocess as _sp
        r = _sp.run([sys.executable, __file__, "assemble",
                     "--storyboard", str(_wsb(wd, vid, 3.0)), "-o", str(wd / "x.mp4"),
                     "--pad-mode", "trim"], capture_output=True, text=True)
        ok_trim_fail = r.returncode != 0 and "禁止冻结" in (r.stderr + r.stdout)
        print(f"[{'PASS' if ok_trim_fail else 'FAIL'}] trim 片段不足→硬失败(不冻结)：rc={r.returncode}")
        if not ok_trim_fail:
            fail("trim 片段不足未硬失败", 1)

        # 字幕折行：长中文行按视频宽度确定性折成多行（不超边界、不挤成一行）
        long_units = max(6.0, (1080 - 2 * int(round(1080 * 0.06))) / 54 * 0.94)
        wrapped = wrap_caption("这是一句非常非常长的中文字幕需要按视频宽度自动折行绝不能超出画面边界挤成一行", long_units)
        ok_wrap = (len(wrapped) >= 2
                   and all(sum(_char_units(c) for c in ln) <= long_units + 0.5 for ln in wrapped)
                   and "".join(wrapped).replace(" ", "").startswith("这是一句非常"))
        print(f"[{'PASS' if ok_wrap else 'FAIL'}] 字幕按宽度折行：长行→{len(wrapped)}行，每行≤{long_units:.1f}单位、不超边界")
        if not ok_wrap:
            fail("字幕折行不正确", 1)
        # 短行不折
        chk_short = wrap_caption("你好", long_units)
        if chk_short != ["你好"]:
            fail(f"短行被误折：{chk_short}", 1)

        # 定时音效轨：图片 4s + 一个在 2s 处的音效，应正常出片且时长≈4s（音效叠进音轨）
        sfx = wd / "ding.wav"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.4",
              str(sfx)])
        sbx = wd / "sbx.json"
        sbx.write_text(json.dumps({"size": "1080x1920",
            "shots": [{"image": imgs[0], "duration": 4.0, "caption": "音效测试"}],
            "sfx": [{"file": str(sfx), "at": 2.0, "volume": 0.8}]}), encoding="utf-8")
        out_x = wd / "sfx.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(sbx), output=str(out_x)))
        dx = _probe_duration(str(out_x))
        ok_sfx = out_x.is_file() and 3.6 <= dx <= 4.4
        print(f"[{'PASS' if ok_sfx else 'FAIL'}] 定时音效轨：图4s + 2s处音效 → 成片 {dx:.2f}s（音效已叠入音轨）")
        if not ok_sfx:
            fail("定时音效轨合成异常", 1)

        # 原生音频直通：有声视频标 native 后，最终文件必须仍有音轨（不再被 -an 删除）。
        native_src = wd / "native.mp4"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=yellow:s=320x568:d=1.2",
              "-f", "lavfi", "-i", "sine=frequency=660:duration=1.2",
              "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(native_src)])
        native_sb = wd / "native.json"
        native_sb.write_text(json.dumps({"size": "320x568", "pad_mode": "trim",
            "shots": [{"video": str(native_src), "duration": 1.0, "audio_mode": "native"}]}),
            encoding="utf-8")
        native_out = wd / "native-final.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(native_sb), output=str(native_out)))
        ok_native = _has_audio(str(native_out)) and 0.8 <= _probe_duration(str(native_out)) <= 1.2
        print(f"[{'PASS' if ok_native else 'FAIL'}] native 原生 AAC 经裁剪/拼接后仍保留")
        if not ok_native:
            fail("原生音频未正确保留", 1)
        native_mix_sb = wd / "native-mix.json"
        native_mix_sb.write_text(json.dumps({"size": "320x568", "pad_mode": "trim",
            "narration": str(voice),
            "shots": [{"video": str(native_src), "duration": 1.0, "audio_mode": "native"}]}),
            encoding="utf-8")
        native_mix_out = wd / "native-mix-final.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(native_mix_sb), output=str(native_mix_out)))
        if not (_has_audio(str(native_mix_out)) and 0.8 <= _probe_duration(str(native_mix_out)) <= 1.2):
            fail("原生音频与独立配音轨混音异常", 1)

        # dub 镜**不得**把视频模型原生人声并入成片（否则会与 TTS 配音**重复/回声**——真机踩过）。
        # 一个 dub 镜（源片自带人声）、无独立配音/BGM → 成片应**无音轨**（原生人声被丢弃，而非混进去）。
        # 旧的「dub 保留原生轨当环境音底」行为下此断言会失败——正是那次重复 bug 的回归防线。
        dub_sb = wd / "dub-drop-native.json"
        dub_sb.write_text(json.dumps({"size": "320x568", "pad_mode": "trim",
            "shots": [{"video": str(native_src), "duration": 1.0, "audio_mode": "dub"}]}),
            encoding="utf-8")
        dub_out = wd / "dub-drop-native.mp4"
        cmd_assemble(argparse.Namespace(storyboard=str(dub_sb), output=str(dub_out)))
        ok_dub = not _has_audio(str(dub_out))   # dub 镜原生人声未并入 → 该无声成片无音轨
        print(f"[{'PASS' if ok_dub else 'FAIL'}] dub 镜原生人声被丢弃（不与 TTS 配音重复）")
        if not ok_dub:
            fail("dub 镜原生人声未被丢弃（会与 TTS 配音重复！）", 1)

        print("[PASS] assemble 全部自检通过")
        return 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="短视频合成器（分镜素材→成片）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("assemble", help="按 storyboard 合成成片")
    p.add_argument("--storyboard", required=True, help="storyboard JSON 文件路径（- 表示 stdin）")
    p.add_argument("-o", "--output", required=True,
                   help="成片输出路径；必须位于 outputs/<人类可读主题>/")
    p.add_argument("--sub-font", dest="sub_font", default=None,
                   help=f"字幕字体（默认 {DEFAULT_SUB_FONT}）")
    p.add_argument("--sub-size", dest="sub_size", type=int, default=None,
                   help="字幕字号（默认按宽度 ≈w*0.05，1080→54）")
    p.add_argument("--sub-margin-v", dest="sub_margin_v", type=int, default=None,
                   help="字幕距底边距（默认按高度 ≈h*0.07）")
    p.add_argument("--pad-mode", dest="pad_mode", default=None,
                   choices=["trim", "auto", "stretch", "loop", "freeze"],
                   help="视频短于所需时长时填满方式：trim=自然(裁/仅冻结尾巴,不慢放不循环,短剧默认)、"
                        "auto=慢放/循环、stretch/loop/freeze=强制。默认读 storyboard.pad_mode，缺则 auto")
    p.set_defaults(func=cmd_assemble)
    p2 = sub.add_parser("selftest", help="自检（生成测试成片）")
    p2.set_defaults(func=cmd_selftest)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
