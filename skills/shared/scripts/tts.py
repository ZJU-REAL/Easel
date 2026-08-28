#!/usr/bin/env python3
"""tts.py — 文字转语音（TTS）配音的确定性封装（subprocess 调 edge-tts）。

用 edge-tts（微软 Edge 在线 TTS 服务）把文本合成为语音，供 tts-voiceover 等
"配音 / 口播 / 旁白"类 SKILL 使用。avoiding 每次现场即兴拼命令导致参数写错、
静默失败、难以复现。合成后的语音可再交给 audio_ops.py / video_ops.py 做混音。

依赖：
    - edge-tts（`pip install edge-tts`，命令 `edge-tts`，微软在线 TTS，需外网）
    - 网络代理：edge-tts 走微软服务器，内网环境需设置
        export https_proxy=http://host:port http_proxy=http://host:port
      脚本会自动读环境变量代理并透传给 edge-tts（也可用 --proxy 覆盖）。
    - ffmpeg / ffprobe（可选）：--format wav/m4a 转码 + selftest 校验时长。

子命令（每个都支持 -h 查看参数）：
    speak      合成语音：--text/--file → --output（默认 mp3，可转 wav/m4a）
    voices     列出常用中文音色（zh-CN / zh-TW / zh-HK）

用法示例：
    tts.py speak --text "配音测试，你好" -o out.mp3
    tts.py speak --file script.txt -o out.mp3 --voice zh-CN-YunxiNeural --rate +10%
    tts.py speak --text "……" -o out.mp3 --subtitle out.srt   # 同时出字幕
    tts.py speak --text "……" -o out.wav --format wav          # 转 wav（需 ffmpeg）
    tts.py voices
    tts.py --selftest
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

# ── 常用中文音色（名称 → 简介）───────────────────────────────────────
# edge-tts --list-voices 里 zh- 开头的一批，挑最常用、素质好的列出。
COMMON_ZH_VOICES: list[tuple[str, str]] = [
    ("zh-CN-XiaoxiaoNeural", "晓晓 · 女声，温暖亲和，通用首选（默认）"),
    ("zh-CN-XiaoyiNeural", "晓伊 · 女声，活泼年轻，适合口播/种草"),
    ("zh-CN-YunxiNeural", "云希 · 男声，清朗自然，适合旁白/解说"),
    ("zh-CN-YunyangNeural", "云扬 · 男声，专业沉稳，适合新闻/播报"),
    ("zh-CN-YunjianNeural", "云健 · 男声，浑厚有力，适合体育/激情内容"),
    ("zh-CN-YunxiaNeural", "云夏 · 男童声，可爱，适合儿童/趣味内容"),
    ("zh-CN-liaoning-XiaobeiNeural", "晓北 · 女声，东北口音，方言趣味"),
    ("zh-CN-shaanxi-XiaoniNeural", "晓妮 · 女声，陕西口音，方言趣味"),
    ("zh-TW-HsiaoChenNeural", "曉臻 · 台湾女声，繁体/台式发音"),
    ("zh-TW-YunJheNeural", "雲哲 · 台湾男声，繁体/台式发音"),
    ("zh-HK-HiuMaanNeural", "曉曼 · 香港女声，粤语"),
    ("zh-HK-WanLungNeural", "雲龍 · 香港男声，粤语"),
]

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


# ── 基础设施 ────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _edge_tts_bin() -> str:
    """定位 edge-tts 命令；找不到给清晰安装提示。"""
    for cand in ("edge-tts", "/root/miniconda3/bin/edge-tts"):
        p = shutil.which(cand) or (cand if Path(cand).is_file() else None)
        if p:
            return p
    _die(
        "未找到 edge-tts 命令。请安装：`pip install edge-tts`，"
        "或确认它在 PATH 中（如 /root/miniconda3/bin/edge-tts）。",
        code=3,
    )


def _env_proxy() -> str | None:
    """从环境变量取外网代理（edge-tts 需访问微软服务器）。"""
    for k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        v = os.environ.get(k)
        if v:
            return v
    return None


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _probe_duration(path: Path) -> float:
    """ffprobe 取时长（秒）；无 ffprobe 或失败返回 -1。"""
    if shutil.which("ffprobe") is None:
        return -1.0
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return -1.0
    try:
        return float(json.loads(proc.stdout).get("format", {}).get("duration", 0) or 0)
    except (json.JSONDecodeError, ValueError):
        return -1.0


def _read_text(args) -> str:
    if args.file:
        p = Path(args.file).expanduser()
        if not p.is_file():
            _die(f"文本文件不存在: {p}", code=2)
        text = p.read_text(encoding="utf-8")
    else:
        text = args.text or ""
    text = text.strip()
    if not text:
        _die("待合成文本为空（--text 或 --file 至少给一个非空内容）", code=2)
    return text


def _run_edge_tts(
    text: str,
    media_out: Path,
    *,
    voice: str,
    rate: str | None,
    volume: str | None,
    pitch: str | None,
    subtitle: Path | None,
    proxy: str | None,
) -> None:
    """调 edge-tts 把 text 合成到 media_out（mp3）。"""
    binp = _edge_tts_bin()
    cmd = [binp, "--voice", voice, "--write-media", str(media_out)]
    # 长文本走 --file，避免 argv 过长 / 换行 / shell 转义问题。
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(text)
        text_file = tf.name
    cmd += ["--file", text_file]
    # 用等号形式传参，避免负值（如 -5%）被 edge-tts 的 argparse 误判为选项。
    if rate:
        cmd += [f"--rate={rate}"]
    if volume:
        cmd += [f"--volume={volume}"]
    if pitch:
        cmd += [f"--pitch={pitch}"]
    if subtitle:
        cmd += ["--write-subtitles", str(subtitle)]
    proxy = proxy or _env_proxy()
    if proxy:
        cmd += ["--proxy", proxy]

    print("  $ " + " ".join(cmd), file=sys.stderr)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        _die("edge-tts 合成超时（>300s）。文本过长或网络不通，请重试或分段。", code=4)
    finally:
        try:
            os.unlink(text_file)
        except OSError:
            pass

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        hint = ""
        low = err.lower()
        if any(k in low for k in ("timed out", "connection", "getaddrinfo",
                                  "network", "ssl", "proxy", "resolve",
                                  "cannot connect", "no route")):
            hint = (
                "\n提示：edge-tts 需访问微软在线服务，请确认已设置外网代理：\n"
                "  export https_proxy=http://host:port http_proxy=http://host:port"
            )
        _die(f"edge-tts 合成失败（退出码 {proc.returncode}）:\n{err}{hint}", code=4)

    if not media_out.is_file() or media_out.stat().st_size == 0:
        _die(
            "edge-tts 未产出有效音频（文件缺失或为空）。"
            "常见原因：网络/代理未通，或音色名无效（用 `voices` 查看）。",
            code=4,
        )


def _transcode(src: Path, dst: Path, fmt: str) -> None:
    """用 ffmpeg 把 mp3 转成目标格式（wav/m4a）。"""
    if not _has_ffmpeg():
        _die(f"--format {fmt} 需要 ffmpeg 转码，但未找到 ffmpeg。", code=3)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(src), str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        _die(f"ffmpeg 转码失败:\n{proc.stderr.strip()}", code=4)


# ── 闭源口播（好嗓子，优先）────────────────────────────────────────
# tts-voiceover 及所有用它的视频 SKILL(auto-short-video/paper-explainer…)的旁白，配了 VOICE_PROVIDER
# 就默认走闭源云 TTS(voice_clone.py，有情感、像真人)，edge 仅无 key 时兜底——避免"AI 味/生硬"。

class ClosedTTSError(Exception):
    """闭源 TTS 合成失败（用于 auto 模式回退 edge）。"""


def _closed_provider() -> str | None:
    p = (os.environ.get("VOICE_PROVIDER") or "").strip()
    return p or None


def _closed_voice_id(voice: str | None) -> str | None:
    """闭源音色 id：显式 voice 像闭源音色(含 : 或 /)就用它；否则 env VOICE_NARRATOR_VOICE_ID；
    再否则 openai-compatible 用 CosyVoice2 沉稳男声 alex 作旁白默认；其它 provider 交给 voice_clone 默认。"""
    if voice and (":" in voice or "/" in voice):
        return voice
    vid = (os.environ.get("VOICE_NARRATOR_VOICE_ID") or "").strip()
    if vid:
        return vid
    if _closed_provider() == "openai-compatible":
        model = (os.environ.get("VOICE_MODEL") or "").strip() or "FunAudioLLM/CosyVoice2-0.5B"
        return f"{model}:alex"
    return None


def _split_sentences(text: str) -> list[str]:
    """按中英文句末标点/换行切句（用于逐句闭源合成 + 生成分句 SRT）。"""
    import re
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    return [s.strip() for s in parts if s and s.strip()]


def _srt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _concat_mp3(parts: list[Path], out: Path) -> None:
    """拼接多个 mp3 到 out。单个直接复制；多个用 ffmpeg concat。"""
    if len(parts) == 1:
        shutil.copyfile(parts[0], out)
        return
    if not _has_ffmpeg():
        _die("闭源逐句合成后需 ffmpeg 拼接，但未找到 ffmpeg。", code=3)
    with tempfile.TemporaryDirectory() as d:
        lst = Path(d) / "list.txt"
        lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:  # -c copy 偶尔因编码不一致失败 → 重编码兜底
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "libmp3lame", str(out)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                _die(f"ffmpeg 拼接失败:\n{proc.stderr.strip()}", code=4)


def _run_closed(text: str, out: Path, fmt: str, subtitle: Path | None, voice: str | None) -> None:
    """闭源云 TTS 口播：按句 voice_clone 合成 → 拼接 → 按各句真实时长写分句 SRT。失败抛 ClosedTTSError。"""
    provider = _closed_provider()
    if not provider:
        raise ClosedTTSError("未配置 VOICE_PROVIDER")
    vc = Path(__file__).resolve().parent / "voice_clone.py"
    vid = _closed_voice_id(voice)
    sents = _split_sentences(text) or [text.strip()]
    with tempfile.TemporaryDirectory() as d:
        parts: list[Path] = []
        for i, s in enumerate(sents):
            pm = Path(d) / f"p{i:03d}.mp3"
            cmd = [sys.executable, str(vc), "clone", "--provider", provider,
                   "--text", s, "-o", str(pm)]
            if vid:
                cmd += ["--voice-id", vid]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not pm.is_file() or pm.stat().st_size == 0:
                raise ClosedTTSError((r.stderr or r.stdout or "voice_clone 无输出").strip()[-300:])
            parts.append(pm)
        target_mp3 = out if fmt == "mp3" else Path(d) / "joined.mp3"
        _concat_mp3(parts, target_mp3)
        if subtitle:
            lines_srt, t = [], 0.0
            for i, (s, pm) in enumerate(zip(sents, parts), 1):
                dur = _probe_duration(pm)
                if dur <= 0:  # 无 ffprobe → 按字数粗估（中文约 4.5 字/秒）
                    dur = max(1.0, len(s) / 4.5)
                lines_srt.append(f"{i}\n{_srt_ts(t)} --> {_srt_ts(t + dur)}\n{s}\n")
                t += dur
            subtitle.write_text("\n".join(lines_srt), encoding="utf-8")
        if fmt != "mp3":
            _transcode(target_mp3, out, fmt)


# ── 子命令 ──────────────────────────────────────────────────────────
def cmd_speak(args) -> int:
    text = _read_text(args)
    out = Path(args.output).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    fmt = args.format
    if fmt == "auto":
        fmt = out.suffix.lstrip(".").lower() or "mp3"
    if fmt not in ("mp3", "wav", "m4a"):
        _die(f"不支持的输出格式: {fmt}（支持 mp3/wav/m4a）", code=2)

    subtitle = Path(args.subtitle).expanduser().resolve() if args.subtitle else None
    if subtitle:
        subtitle.parent.mkdir(parents=True, exist_ok=True)

    # 闭源优先：配了 VOICE_PROVIDER(或 --engine closed) → 走闭源云 TTS(好嗓子)，edge 仅兜底。
    engine = getattr(args, "engine", "auto")
    use_closed = engine == "closed" or (engine == "auto" and _closed_provider())
    if use_closed:
        try:
            _run_closed(text, out, fmt, subtitle, args.voice)
            dur = _probe_duration(out)
            dur_str = f"{dur:.1f}s" if dur >= 0 else "时长未知(无 ffprobe)"
            print(f"✅ {out}  ({out.stat().st_size/1024:.0f} KB, {dur_str}, 闭源 {_closed_provider()})")
            if subtitle:
                print(f"✅ 字幕 {subtitle}")
            return 0
        except ClosedTTSError as e:
            if engine == "closed":
                _die(f"闭源配音失败：{e}\n（确认 VOICE_PROVIDER/VOICE_API_KEY/voice-id；或用 --engine edge）", code=4)
            print(f"⚠️ 闭源配音失败（{e}）→ 回退 edge-tts（AI 味，仅兜底）。", file=sys.stderr)

    # edge-tts 原生出 mp3；非 mp3 时先合成临时 mp3 再转码。
    if fmt == "mp3":
        _run_edge_tts(
            text, out, voice=args.voice, rate=args.rate, volume=args.volume,
            pitch=args.pitch, subtitle=subtitle, proxy=args.proxy,
        )
    else:
        with tempfile.TemporaryDirectory() as d:
            tmp_mp3 = Path(d) / "tts.mp3"
            _run_edge_tts(
                text, tmp_mp3, voice=args.voice, rate=args.rate,
                volume=args.volume, pitch=args.pitch, subtitle=subtitle,
                proxy=args.proxy,
            )
            _transcode(tmp_mp3, out, fmt)

    dur = _probe_duration(out)
    kb = out.stat().st_size / 1024
    dur_str = f"{dur:.1f}s" if dur >= 0 else "时长未知(无 ffprobe)"
    print(f"✅ {out}  ({kb:.0f} KB, {dur_str}, 音色 {args.voice})")
    if subtitle:
        print(f"✅ 字幕 {subtitle}")
    return 0


def cmd_voices(args) -> int:
    """列出常用中文音色。默认用内置精选表，--all 走 edge-tts 拉全量 zh-。"""
    if args.all:
        binp = _edge_tts_bin()
        cmd = [binp, "--list-voices"]
        proxy = args.proxy or _env_proxy()
        if proxy:
            cmd += ["--proxy", proxy]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _die(
                "edge-tts --list-voices 失败（可能网络/代理未通）:\n"
                + (proc.stderr or proc.stdout or "").strip(),
                code=4,
            )
        printed = False
        for line in proc.stdout.splitlines():
            if line.startswith("zh-") or line.startswith("Name") or not line.strip():
                print(line)
                printed = True
        if not printed:
            print(proc.stdout)
        return 0

    print("常用中文音色（--voice 传左侧名称；--all 查看全量 zh- 音色）：\n")
    for name, desc in COMMON_ZH_VOICES:
        mark = "  ← 默认" if name == DEFAULT_VOICE else ""
        print(f"  {name:<34} {desc}{mark}")
    print("\n语速/音量/音调示例：--rate +10% / --volume +20% / --pitch +2Hz")
    return 0


# ── 自检 ────────────────────────────────────────────────────────────
def cmd_selftest(_args=None) -> int:
    _edge_tts_bin()  # 确认命令存在
    if not _env_proxy():
        print(
            "[selftest] 警告：未检测到 http(s)_proxy 环境变量，"
            "edge-tts 需外网，可能失败。", file=sys.stderr,
        )
    print("[selftest] 合成一句中文「配音测试，你好」…")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "selftest.mp3"
        ns = argparse.Namespace(
            text="配音测试，你好", file=None, output=str(out),
            voice=DEFAULT_VOICE, rate=None, volume=None, pitch=None,
            subtitle=None, proxy=None, format="mp3", engine="edge",  # selftest 固定 edge，离线可测
        )
        cmd_speak(ns)
        if not out.is_file() or out.stat().st_size == 0:
            _die("selftest 失败：未产出 mp3 或文件为空", code=1)
        dur = _probe_duration(out)
        if shutil.which("ffprobe") is not None:
            if dur <= 0:
                _die(f"selftest 失败：ffprobe 探测时长非正 ({dur})", code=1)
            print(f"[selftest] mp3 时长 {dur:.2f}s（ffprobe 确认 > 0）")
        else:
            print("[selftest] 无 ffprobe，跳过时长断言（文件已确认 > 0 字节）")
    print("[PASS] selftest 通过：edge-tts 真实合成 mp3 成功")
    return 0


# ── argparse ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tts.py",
        description="文字转语音（TTS）配音：edge-tts 的确定性封装（子命令）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="合成一句中文并断言产出有效 mp3（需外网代理）")
    sub = ap.add_subparsers(dest="cmd", metavar="<子命令>")

    p = sub.add_parser("speak", help="合成语音：--text/--file → --output")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("-t", "--text", help="要合成的文本")
    g.add_argument("-f", "--file", help="从文本文件读取内容（长文本推荐）")
    p.add_argument("-o", "--output", required=True,
                   help="输出音频路径（扩展名决定格式，默认 mp3）")
    p.add_argument("-v", "--voice", default=DEFAULT_VOICE,
                   help=f"音色（edge 传音色名；闭源传 voice-id 如 FunAudioLLM/CosyVoice2-0.5B:alex）")
    p.add_argument("--engine", choices=["auto", "closed", "edge"], default="auto",
                   help="配音引擎：auto=配了 VOICE_PROVIDER 走闭源(好嗓子)否则 edge；closed=强制闭源；edge=强制 edge(AI 味)")
    p.add_argument("--rate", help="语速，如 +10%% / -20%%")
    p.add_argument("--volume", help="音量，如 +20%% / -10%%")
    p.add_argument("--pitch", help="音调，如 +2Hz / -5Hz")
    p.add_argument("--subtitle", help="同时输出 SRT 字幕到此路径")
    p.add_argument("--format", choices=["auto", "mp3", "wav", "m4a"],
                   default="auto",
                   help="输出格式（默认按扩展名；wav/m4a 需 ffmpeg 转码）")
    p.add_argument("--proxy", help="外网代理（默认读 https_proxy/http_proxy 环境变量）")
    p.set_defaults(func=cmd_speak)

    p = sub.add_parser("voices", help="列出常用中文音色")
    p.add_argument("--all", action="store_true",
                   help="调 edge-tts 拉取全量 zh- 音色（需外网）")
    p.add_argument("--proxy", help="外网代理（默认读环境变量）")
    p.set_defaults(func=cmd_voices)

    return ap


def main(argv: list[str] | None = None) -> int:
    # 加载 .env（VOICE_PROVIDER/VOICE_API_KEY 等常只写在 .env）——否则 auto 看不到闭源配置、误退 edge。
    try:
        import ai_video
        ai_video.load_env_file(ai_video.find_default_env_file())
    except Exception:  # noqa: BLE001
        pass
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.selftest:
        return cmd_selftest()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
