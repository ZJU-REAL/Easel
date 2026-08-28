#!/usr/bin/env python3
"""asr.py — 语音转字幕（ASR）的确定性封装（faster-whisper + 标准库）。

所有"语音/视频 → 字幕文件"类 SKILL（auto-subtitle 等）共用此脚本，避免每次
现场即兴调 whisper 导致的模型选择、时间戳格式、中文断句不一致等问题。

与 video_ops.py 的边界：本脚本只负责"识别语音 → 生成字幕文件（SRT/ASS/TXT/JSON）"，
不负责把字幕烧录进视频；烧录用 video_ops.py 或 ffmpeg subtitles/ass 滤镜。

依赖：faster-whisper（`pip install faster-whisper`）+ ffmpeg（视频提取音轨）。
首次运行会从 HuggingFace 下载模型，需外网代理（见下方 _ensure_proxy）。

子命令（均支持 -h）：
    transcribe  音频/视频 → 字幕（--format srt/ass/txt/json）
    info        打印可用模型 / 语言提示

用法举例：
    asr.py transcribe -i talk.mp4 -o outputs/talk/talk.srt --language zh
    asr.py transcribe -i voice.mp3 --format ass --model small
    asr.py info
    asr.py --selftest
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

# ── 常量 ──────────────────────────────────────────────────────────────
# 默认外网代理（faster-whisper 首次从 HuggingFace 下模型时用）。
# 环境里已设 https_proxy/http_proxy 则优先用环境变量，不覆盖。
_DEFAULT_PROXY = os.environ.get("EASEL_PROXY", "")  # lab 在 .env 设 EASEL_PROXY；不设则不走代理

_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

# 视频容器（需先用 ffmpeg 提取音轨）
_VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".wmv"}

# 中文断句标点（这些之后可以切）
_ZH_PUNCT = "，。！？；、：,.!?;:）】》」"
# 硬切标点（句末，优先在这里断）
_ZH_END_PUNCT = "。！？!?…"


# ── 基础工具 ──────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_proxy() -> None:
    """若环境无代理，则注入默认代理（模型下载需外网）。已设则不动。"""
    has = any(os.environ.get(k) for k in
              ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"))
    if not has and _DEFAULT_PROXY:
        os.environ["https_proxy"] = _DEFAULT_PROXY
        os.environ["http_proxy"] = _DEFAULT_PROXY
        print(f"[asr] 未检测到代理环境变量，已注入默认代理 {_DEFAULT_PROXY}（供模型下载）。\n"
              f"      如需自定义，请先 export https_proxy=... http_proxy=...",
              file=sys.stderr)


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _extract_audio(video: Path) -> Path:
    """从视频提取 16kHz 单声道 wav（whisper 友好），返回临时 wav 路径。"""
    if not _has_ffmpeg():
        _die("处理视频需要 ffmpeg 提取音轨，但未找到 ffmpeg。", 3)
    tmp = Path(tempfile.mkdtemp(prefix="asr_")) / "audio.wav"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-f", "wav", str(tmp)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if proc.returncode != 0 or not tmp.is_file():
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-10:])
        _die(f"ffmpeg 提取音轨失败:\n{tail}", proc.returncode or 1)
    return tmp


# ── 时间戳格式化 ──────────────────────────────────────────────────────
def _fmt_srt_ts(sec: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm"""
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_ass_ts(sec: float) -> str:
    """秒 → ASS 时间戳 H:MM:SS.cc（百分秒）"""
    if sec < 0:
        sec = 0.0
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


# ── 中文友好断行 ──────────────────────────────────────────────────────
def _wrap_line(text: str, max_chars: int) -> str:
    r"""把一行长文本按 max_chars 断成多行（\N 连接，供字幕换行）。
    优先在标点后断；无标点则按长度硬断。中文按字符数，英文单词尽量不拆。"""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    lines: list[str] = []
    cur = ""
    for ch in text:
        cur += ch
        # 达到长度且落在标点后 → 断行；或严重超长（1.4x）强制断
        if len(cur) >= max_chars and (ch in _ZH_PUNCT or _is_ascii_space(ch)):
            lines.append(cur.strip())
            cur = ""
        elif len(cur) >= int(max_chars * 1.5):
            lines.append(cur.strip())
            cur = ""
    if cur.strip():
        lines.append(cur.strip())
    return "\\N".join(l for l in lines if l)


def _is_ascii_space(ch: str) -> bool:
    return ch == " "


def _split_long_segment(text: str, start: float, end: float,
                        max_chars: int) -> list[tuple[float, float, str]]:
    """一个 whisper segment 若过长（远超 max_chars），按句末标点切成多条字幕，
    时间按字符数比例分配。返回 [(start, end, text), ...]。"""
    text = text.strip()
    if not text:
        return []
    # 未超过 2 行的量级：不拆条，只在渲染时软换行
    if len(text) <= max_chars * 2:
        return [(start, end, text)]

    # 按句末标点切分成子句
    chunks: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in _ZH_END_PUNCT and len(buf.strip()) >= max(4, max_chars // 2):
            chunks.append(buf.strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())
    if len(chunks) <= 1:
        return [(start, end, text)]

    total = sum(len(c) for c in chunks) or 1
    out: list[tuple[float, float, str]] = []
    cursor = start
    span = max(end - start, 0.0)
    for c in chunks:
        seg = span * (len(c) / total)
        s, e = cursor, min(end, cursor + seg)
        out.append((s, e, c))
        cursor = e
    # 修正最后一条到 end
    if out:
        ls, _, lt = out[-1]
        out[-1] = (ls, end, lt)
    return out


# ── 渲染各格式 ────────────────────────────────────────────────────────
def _render_srt(cues: list[tuple[float, float, str]], max_chars: int) -> str:
    blocks = []
    for i, (s, e, t) in enumerate(cues, 1):
        body = _wrap_line(t, max_chars).replace("\\N", "\n")
        blocks.append(f"{i}\n{_fmt_srt_ts(s)} --> {_fmt_srt_ts(e)}\n{body}")
    return "\n\n".join(blocks) + "\n"


def _probe_video_wh(path: Path) -> tuple[int, int] | None:
    """探视频宽高（供字幕样式按横竖屏自适应）；无 ffprobe/非视频返回 None。"""
    if not shutil.which("ffprobe"):
        return None
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
                       capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().splitlines()[0].split("x")
        return int(w), int(h)
    except Exception:
        return None


def _ass_header(w: int, h: int) -> str:
    """按目标视频宽高生成 ASS 头：PlayRes=真实宽高，**字号按短边**(min(w,h)*0.05)——
    竖屏(1080x1920)与横屏(1920x1080)都得到合适字号(≈54)，不再横屏过大/竖屏错位；
    底边距按高、左右边距按宽，描边/阴影按短边缩放。"""
    short = min(w, h)
    fs = max(16, round(short * 0.05))
    outline = max(1, round(short * 0.004))
    shadow = max(0, round(short * 0.0015))
    mv = round(h * 0.06)
    mlr = round(w * 0.045)
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\n"
        "WrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Noto Sans CJK SC,{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,{mlr},{mlr},{mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _render_ass(cues: list[tuple[float, float, str]], max_chars: int,
                w: int = 1080, h: int = 1920) -> str:
    lines = [_ass_header(w, h)]
    for s, e, t in cues:
        body = _wrap_line(t, max_chars)  # ASS 用 \N 换行
        lines.append(
            f"Dialogue: 0,{_fmt_ass_ts(s)},{_fmt_ass_ts(e)},Default,,0,0,0,,{body}")
    return "\n".join(lines) + "\n"


def _render_txt(cues: list[tuple[float, float, str]]) -> str:
    return "\n".join(t for _, _, t in cues) + "\n"


def _render_json(cues: list[tuple[float, float, str]], meta: dict) -> str:
    data = {
        **meta,
        "segments": [
            {"index": i, "start": round(s, 3), "end": round(e, 3), "text": t}
            for i, (s, e, t) in enumerate(cues, 1)
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── 转录核心 ──────────────────────────────────────────────────────────
def _transcribe_audio(audio: Path, a) -> tuple[list[tuple[float, float, str]], dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        _die("未安装 faster-whisper。请运行：pip install faster-whisper", 3)

    _ensure_proxy()
    # 模型解析：若传的是裸名（base/small…）且本地缓存目录已存在，优先用本地，
    # 规避某些代理下 huggingface_hub 自动下载失败的问题；否则交给 faster-whisper 自动下载。
    model_ref = a.model
    if "/" not in a.model and not Path(a.model).exists():
        local = Path.home() / ".cache" / "easel-models" / f"faster-whisper-{a.model}"
        if (local / "model.bin").is_file():
            model_ref = str(local)
            print(f"[asr] 使用本地缓存模型 {local}", file=sys.stderr)
    print(f"[asr] 加载模型 {model_ref}（device={a.device} compute={a.compute_type}）"
          f"，首次会下载，请耐心等待……", file=sys.stderr)
    try:
        model = WhisperModel(model_ref, device=a.device, compute_type=a.compute_type)
    except Exception as e:  # noqa: BLE001
        _die(f"加载模型失败（可能是模型下载失败/网络/代理问题）: {e}"
             f"\n提示：可手动下载模型到 ~/.cache/easel-models/faster-whisper-{a.model}/"
             f"（config.json/model.bin/tokenizer.json/vocabulary.txt）", 4)

    language = None if a.language in (None, "", "auto") else a.language
    segments, tinfo = model.transcribe(
        str(audio),
        language=language,
        vad_filter=True,
        beam_size=a.beam_size,
    )
    detected = getattr(tinfo, "language", None)
    duration = getattr(tinfo, "duration", None)
    print(f"[asr] 检测语言={detected} 时长={duration}s，开始转录……", file=sys.stderr)

    cues: list[tuple[float, float, str]] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        for s, e, t in _split_long_segment(text, seg.start, seg.end, a.max_line_chars):
            cues.append((s, e, t))

    meta = {
        "source": str(audio),
        "model": a.model,
        "language": detected,
        "duration_sec": round(duration, 3) if duration else None,
        "num_segments": len(cues),
    }
    return cues, meta


def cmd_transcribe(a) -> int:
    src = _require_input(a.input)
    is_video = src.suffix.lower() in _VIDEO_EXT
    tmp_audio: Path | None = None
    try:
        audio = src
        if is_video:
            print(f"[asr] 视频输入，先提取音轨……", file=sys.stderr)
            tmp_audio = _extract_audio(src)
            audio = tmp_audio

        cues, meta = _transcribe_audio(audio, a)
        if not cues:
            print("[asr] 警告：未识别到任何语音内容（可能是静音或纯音乐）。",
                  file=sys.stderr)

        fmt = a.format
        if fmt == "srt":
            content = _render_srt(cues, a.max_line_chars)
        elif fmt == "ass":
            # 字幕样式按目标视频宽高自适应（横竖屏都合适）：--res 优先 > 视频输入探测 > 默认竖屏
            wh = None
            if getattr(a, "res", None):
                try:
                    ww, hh = str(a.res).lower().split("x")
                    wh = (int(ww), int(hh))
                except Exception:
                    _die("--res 格式应为 宽x高，如 1080x1920 或 1920x1080", 2)
            elif is_video:
                wh = _probe_video_wh(src)
            w, h = wh if wh else (1080, 1920)
            if not wh:
                print("[asr] 未探到目标视频尺寸，ASS 按竖屏 1080x1920 生成；横屏请加 --res 1920x1080。",
                      file=sys.stderr)
            content = _render_ass(cues, a.max_line_chars, w, h)
        elif fmt == "txt":
            content = _render_txt(cues)
        else:  # json
            content = _render_json(cues, meta)

        # 输出路径
        if a.output:
            out = _prep_out(a.output)
        else:
            out = _prep_out(f"outputs/{src.stem}/{src.stem}.{fmt}")
        out.write_text(content, encoding="utf-8")
        kb = out.stat().st_size / 1024
        print(f"✅ {out} ({kb:.1f} KB, {len(cues)} 条字幕, 语言={meta['language']})")
        return 0
    finally:
        if tmp_audio is not None:
            shutil.rmtree(tmp_audio.parent, ignore_errors=True)


def cmd_info(a) -> int:
    print("可用模型（--model，越大越准越慢，CPU 建议 base/small）：")
    for m in _MODELS:
        tag = "（默认）" if m == "base" else ""
        print(f"  - {m}{tag}")
    print("\n语言（--language）：")
    print("  - auto  自动检测（默认）")
    print("  - zh    中文 / en 英文 / ja 日文 / ko 韩文 ...（ISO 639-1 码）")
    print("\n输出格式（--format）：srt（默认）/ ass / txt / json")
    print("\nCPU 友好参数：--device cpu --compute-type int8")
    print("每行字数：--max-line-chars（中文默认 18，超长自动断行/拆条）")
    print("\n模型下载走 HuggingFace，需外网代理；脚本会自动注入默认代理，")
    print("也可先 export https_proxy=... http_proxy=... 覆盖。")
    return 0


# ── selftest ─────────────────────────────────────────────────────────
def _selftest() -> int:
    """用 edge-tts 合成一句中文语音，再 transcribe 出 srt，断言非空含时间戳。"""
    if shutil.which("edge-tts") is None:
        print("[FAIL] 未找到 edge-tts，无法自检（pip install edge-tts）", file=sys.stderr)
        return 1
    if not _has_ffmpeg():
        print("[WARN] 未找到 ffmpeg，仅在纯音频路径下自检", file=sys.stderr)

    with tempfile.TemporaryDirectory() as d:
        mp3 = Path(d) / "asr_test.mp3"
        print("[selftest] edge-tts 合成测试语音……")
        proc = subprocess.run(
            ["edge-tts", "--voice", "zh-CN-XiaoxiaoNeural",
             "--text", "这是一段字幕测试", "--write-media", str(mp3)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if proc.returncode != 0 or not mp3.is_file() or mp3.stat().st_size == 0:
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
            print(f"[FAIL] edge-tts 合成失败:\n{tail}", file=sys.stderr)
            return 1

        srt = Path(d) / "asr_test.srt"
        ns = argparse.Namespace(
            input=str(mp3), output=str(srt), format="srt",
            model="base", language="zh", device="cpu", compute_type="int8",
            max_line_chars=18, beam_size=5,
        )
        print("[selftest] transcribe → srt……")
        rc = cmd_transcribe(ns)
        if rc != 0:
            print("[FAIL] transcribe 返回非 0", file=sys.stderr)
            return 1
        text = srt.read_text(encoding="utf-8") if srt.is_file() else ""
        has_ts = "-->" in text and text.strip() != ""
        print("---- SRT 内容 ----")
        print(text.strip() or "(空)")
        print("------------------")
        if has_ts:
            print("[PASS] asr 自检通过（srt 非空且含时间戳）")
            return 0
        print("[FAIL] srt 为空或缺时间戳", file=sys.stderr)
        return 1


# ── argparse ─────────────────────────────────────────────────────────
def _add_transcribe_args(p) -> None:
    p.add_argument("-i", "--input", required=True, help="音频或视频文件路径")
    p.add_argument("-o", "--output",
                   help="输出路径（默认 outputs/<输入文件名>/<输入文件名>.<format>）")
    p.add_argument("--format", choices=["srt", "ass", "txt", "json"],
                   default="srt", help="输出格式（默认 srt）")
    p.add_argument("--model", default="base",
                   help=f"模型 {'/'.join(_MODELS)}（默认 base）")
    p.add_argument("--language", default="auto",
                   help="语言码如 zh/en，默认 auto 自动检测")
    p.add_argument("--device", default="cpu", help="cpu / cuda（默认 cpu）")
    p.add_argument("--compute-type", default="int8",
                   help="int8 / float16 / float32（CPU 建议 int8）")
    p.add_argument("--res", help="ASS 字幕目标视频宽高（宽x高，如 1080x1920/1920x1080）；"
                   "缺省时视频输入自动探测、纯音频按竖屏 1080x1920。字号/边距按此自适应")
    p.add_argument("--max-line-chars", type=int, default=18,
                   help="字幕每行字数，超长自动断行（中文默认 18）")
    p.add_argument("--beam-size", type=int, default=5, help="beam search 宽度（默认 5）")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="语音转字幕 ASR（faster-whisper 封装）。子命令均支持 -h。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="用 edge-tts 合成中文语音并转录，验证链路")
    sub = ap.add_subparsers(dest="cmd", metavar="<子命令>")

    p = sub.add_parser("transcribe", help="音频/视频 → 字幕文件")
    _add_transcribe_args(p)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("info", help="打印可用模型 / 语言提示")
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
