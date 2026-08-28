#!/usr/bin/env python3
"""audio_ops.py — 通用音频处理的确定性封装（subprocess 调 ffmpeg / ffprobe）。

所有"音频剪辑 / 转码 / 音量 / 提取音轨 / 拼接 / 淡入淡出 / 变速 / 降噪"类 SKILL
（audio-editing / audio-denoise）共用此脚本，避免每次现场即兴拼 ffmpeg 命令导致
参数写错、静默失败、难以复现。

依赖：系统已安装 ffmpeg + ffprobe（`apt install ffmpeg` / `brew install ffmpeg`）。

子命令（每个都支持 -h 查看参数）：
    trim       按起止时间裁剪
    convert    格式转换（mp3/wav/m4a/aac）+ 码率
    normalize  音量归一化（loudnorm，社媒响度标准）
    extract    从视频提取音轨
    concat     多段音频拼接
    fade       淡入 / 淡出
    speed      变速（保持音高 atempo）
    denoise    降噪（三级方案 Tier1/2/3）
    info       ffprobe 输出时长 / 码率 / 声道（json）

用法示例：
    audio_ops.py info in.mp3
    audio_ops.py trim in.mp3 -o out.mp3 --start 00:00:05 --end 00:00:20
    audio_ops.py convert in.wav -o out.mp3 --bitrate 192k
    audio_ops.py normalize in.mp3 -o out.mp3
    audio_ops.py extract video.mp4 -o audio.m4a
    audio_ops.py concat a.mp3 b.mp3 c.mp3 -o all.mp3
    audio_ops.py fade in.mp3 -o out.mp3 --fade-in 2 --fade-out 3
    audio_ops.py speed in.mp3 -o out.mp3 --factor 1.5
    audio_ops.py denoise in.wav -o out.wav --tier 2
    audio_ops.py --selftest
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── 社媒响度标准（EBU R128 / loudnorm）─────────────────────────────
# 大多数平台把响度归一到 -14 LUFS 左右（播客 / 短视频常用），峰值留 -1.5 dBTP。
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.5
LOUDNORM_LRA = 11.0

# RNNoise 模型（arnndn，Tier3 使用）；不存在时降级 Tier2。
_RNNOISE_MODEL_URL = (
    "https://github.com/GregorR/rnnoise-models/raw/master/"
    "somnolent-hogwash-2018-09-01/sh.rnnn"
)


# ── 基础设施 ────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_tools() -> None:
    """确认 ffmpeg / ffprobe 可用，否则给清晰错误。"""
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        _die(
            f"未找到 {' 和 '.join(missing)}。请安装 ffmpeg："
            "Debian/Ubuntu `apt install ffmpeg`，macOS `brew install ffmpeg`。",
            code=3,
        )


def _check_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", code=2)
    return p.resolve()


def _prep_output(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _run_ffmpeg(cmd: list[str], *, quiet: bool = False) -> None:
    """运行 ffmpeg，捕获非零退出并打印 stderr。"""
    full = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *cmd]
    if not quiet:
        print("  $ " + " ".join(full), file=sys.stderr)
    proc = subprocess.run(full, capture_output=True, text=True)
    if proc.returncode != 0:
        _die(
            "ffmpeg 执行失败（退出码 "
            f"{proc.returncode}）:\n{proc.stderr.strip()}",
            code=4,
        )


def _probe(path: Path) -> dict:
    """ffprobe → dict（format + streams）。"""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        _die(f"ffprobe 探测失败:\n{proc.stderr.strip()}", code=4)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:  # noqa: BLE001
        _die(f"ffprobe 输出无法解析: {e}", code=4)


def _summary(path: Path) -> dict:
    """从 ffprobe 结果提炼时长 / 码率 / 声道 / 采样率。"""
    data = _probe(path)
    fmt = data.get("format", {})
    audio = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {},
    )
    return {
        "file": str(path),
        "duration_sec": round(float(fmt.get("duration", 0) or 0), 3),
        "bit_rate": fmt.get("bit_rate"),
        "format_name": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "codec": audio.get("codec_name"),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
    }


def _report(out: Path) -> None:
    s = _summary(out)
    kb = s["size_bytes"] / 1024
    dur = s["duration_sec"]
    print(
        f"✅ {out}  ({kb:.0f} KB, {dur}s, {s.get('codec')}, "
        f"{s.get('channels')}ch @ {s.get('sample_rate')}Hz)"
    )


# ── 子命令实现 ──────────────────────────────────────────────────────
def cmd_info(args) -> int:
    inp = _check_input(args.input)
    if args.raw:
        print(json.dumps(_probe(inp), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(_summary(inp), ensure_ascii=False, indent=2))
    return 0


def cmd_trim(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    cmd = ["-i", str(inp)]
    if args.start:
        cmd += ["-ss", args.start]
    if args.end:
        cmd += ["-to", args.end]
    elif args.duration:
        cmd += ["-t", args.duration]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def cmd_convert(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    cmd = ["-i", str(inp), "-vn"]
    if args.bitrate:
        cmd += ["-b:a", args.bitrate]
    if args.sample_rate:
        cmd += ["-ar", str(args.sample_rate)]
    if args.channels:
        cmd += ["-ac", str(args.channels)]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def cmd_normalize(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    ln = f"loudnorm=I={args.i}:TP={args.tp}:LRA={args.lra}"
    cmd = ["-i", str(inp), "-af", ln]
    if args.bitrate:
        cmd += ["-b:a", args.bitrate]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def cmd_extract(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    # -vn 去视频轨；根据输出容器决定编码，默认让 ffmpeg 按扩展名选。
    cmd = ["-i", str(inp), "-vn"]
    if args.copy:
        cmd += ["-acodec", "copy"]
    elif args.bitrate:
        cmd += ["-b:a", args.bitrate]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def cmd_concat(args) -> int:
    if len(args.inputs) < 2:
        _die("concat 至少需要 2 个输入文件", code=2)
    inps = [_check_input(p) for p in args.inputs]
    out = _prep_output(args.output)
    # 用 concat filter（重编码），比 demuxer 更稳，允许不同容器 / 采样率。
    n = len(inps)
    cmd: list[str] = []
    for p in inps:
        cmd += ["-i", str(p)]
    streams = "".join(f"[{i}:a]" for i in range(n))
    filt = f"{streams}concat=n={n}:v=0:a=1[out]"
    cmd += ["-filter_complex", filt, "-map", "[out]"]
    if args.bitrate:
        cmd += ["-b:a", args.bitrate]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def cmd_fade(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    if args.fade_in <= 0 and args.fade_out <= 0:
        _die("fade 需要 --fade-in 或 --fade-out 至少一个 > 0", code=2)
    filters = []
    if args.fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={args.fade_in}")
    if args.fade_out > 0:
        dur = _summary(inp)["duration_sec"]
        st = max(dur - args.fade_out, 0)
        filters.append(f"afade=t=out:st={st}:d={args.fade_out}")
    cmd = ["-i", str(inp), "-af", ",".join(filters), str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def _atempo_chain(factor: float) -> str:
    """atempo 单次只支持 0.5-2.0，超范围时级联。"""
    if factor <= 0:
        _die("speed --factor 必须 > 0", code=2)
    chain: list[str] = []
    remaining = factor
    while remaining > 2.0:
        chain.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        chain.append("atempo=0.5")
        remaining /= 0.5
    chain.append(f"atempo={remaining:.6f}")
    return ",".join(chain)


def cmd_speed(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    cmd = ["-i", str(inp), "-af", _atempo_chain(args.factor), str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


def _ensure_rnnoise_model(explicit: str | None) -> str | None:
    """定位 RNNoise 模型：显式路径 > 脚本旁 models/ 目录。找不到返回 None。"""
    if explicit:
        p = Path(explicit).expanduser()
        return str(p) if p.is_file() else None
    local = Path(__file__).resolve().parent / "models" / "sh.rnnn"
    return str(local) if local.is_file() else None


def _denoise_filter(tier: int, model: str | None, mix: float) -> tuple[str, int]:
    """返回 (滤镜链, 实际使用 tier)。tier3 无模型时降级 tier2。"""
    if tier == 1:
        # Tier1 — ffmpeg 内置滤波：切高低频 + FFT 降噪，无外部依赖。
        return ("highpass=f=80,lowpass=f=8000,afftdn=nr=12:nf=-40:tn=1", 1)
    if tier == 2:
        # Tier2 — 更强的 FFT + 非局部均值降噪，仍纯 ffmpeg。
        return ("highpass=f=70,afftdn=nr=24:nf=-30:tn=1,anlmdn=s=0.0005", 2)
    # Tier3 — RNNoise 神经网络降噪 + 预处理 + 压缩 + 归一化。
    if model is None:
        print(
            "WARN: 未找到 RNNoise 模型（sh.rnnn），Tier3 降级为 Tier2。"
            "下载模型可启用：\n  mkdir -p "
            f"{Path(__file__).resolve().parent / 'models'}\n  curl -L "
            f"{_RNNOISE_MODEL_URL} -o "
            f"{Path(__file__).resolve().parent / 'models' / 'sh.rnnn'}",
            file=sys.stderr,
        )
        return _denoise_filter(2, None, mix)
    chain = (
        f"highpass=f=60,arnndn=m={model}:mix={mix},"
        "acompressor=threshold=-20dB:ratio=3:attack=5:release=50,"
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
    )
    return (chain, 3)


def cmd_denoise(args) -> int:
    inp = _check_input(args.input)
    out = _prep_output(args.output)
    model = _ensure_rnnoise_model(args.model) if args.tier == 3 else None
    filt, used = _denoise_filter(args.tier, model, args.mix)
    print(f"  降噪 Tier{used}: {filt}", file=sys.stderr)
    cmd = ["-i", str(inp), "-af", filt]
    # 视频输入只处理音轨，视频轨原样保留。
    probe = _probe(inp)
    has_video = any(
        s.get("codec_type") == "video" for s in probe.get("streams", [])
    )
    if has_video:
        cmd += ["-c:v", "copy"]
    cmd += [str(out)]
    _run_ffmpeg(cmd)
    _report(out)
    return 0


# ── 自检 ────────────────────────────────────────────────────────────
def _gen_sine(path: Path, seconds: int = 3) -> None:
    """用 ffmpeg sine 滤镜生成一段测试音。"""
    _run_ffmpeg(
        [
            "-f", "lavfi", "-i",
            f"sine=frequency=440:duration={seconds}:sample_rate=44100",
            "-ac", "1", str(path),
        ],
        quiet=True,
    )


def cmd_selftest(_args=None) -> int:
    _require_tools()
    print("[selftest] ffmpeg/ffprobe 就位，生成测试音…")
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        src = base / "sine.wav"
        _gen_sine(src, seconds=3)
        if not src.is_file() or src.stat().st_size == 0:
            _die("生成测试音失败", code=1)
        print(f"[selftest] 测试音 OK: {_summary(src)['duration_sec']}s")

        # trim
        trimmed = base / "trim.wav"
        cmd_trim(argparse.Namespace(
            input=str(src), output=str(trimmed),
            start="00:00:00.5", end="00:00:02", duration=None,
        ))
        assert trimmed.is_file() and trimmed.stat().st_size > 0

        # convert → mp3
        mp3 = base / "conv.mp3"
        cmd_convert(argparse.Namespace(
            input=str(trimmed), output=str(mp3),
            bitrate="128k", sample_rate=None, channels=None,
        ))
        assert mp3.is_file() and mp3.stat().st_size > 0

        # normalize
        norm = base / "norm.mp3"
        cmd_normalize(argparse.Namespace(
            input=str(mp3), output=str(norm),
            i=LOUDNORM_I, tp=LOUDNORM_TP, lra=LOUDNORM_LRA, bitrate="128k",
        ))
        assert norm.is_file() and norm.stat().st_size > 0

    print("[PASS] selftest 通过：trim / convert / normalize 全部产出音频文件")
    return 0


# ── argparse ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="audio_ops.py",
        description="通用音频处理：ffmpeg/ffprobe 的确定性封装（子命令）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="生成测试音并跑通 trim/convert/normalize")
    sub = ap.add_subparsers(dest="cmd", metavar="<子命令>")

    p = sub.add_parser("info", help="ffprobe 输出时长/码率/声道（json）")
    p.add_argument("input")
    p.add_argument("--raw", action="store_true", help="输出 ffprobe 完整 json")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("trim", help="按起止时间裁剪")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--start", help="起始时间 HH:MM:SS(.ms) 或秒")
    p.add_argument("--end", help="结束时间（与 --duration 二选一）")
    p.add_argument("--duration", help="裁剪时长（与 --end 二选一）")
    p.set_defaults(func=cmd_trim)

    p = sub.add_parser("convert", help="格式转换 + 码率（mp3/wav/m4a/aac）")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True, help="输出（扩展名决定格式）")
    p.add_argument("--bitrate", help="音频码率，如 192k")
    p.add_argument("--sample-rate", type=int, help="采样率，如 44100")
    p.add_argument("--channels", type=int, help="声道数，如 1/2")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("normalize", help="音量归一化（loudnorm，社媒响度）")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--i", type=float, default=LOUDNORM_I, help="目标 LUFS（默认 -14）")
    p.add_argument("--tp", type=float, default=LOUDNORM_TP, help="峰值 dBTP（默认 -1.5）")
    p.add_argument("--lra", type=float, default=LOUDNORM_LRA, help="响度范围（默认 11）")
    p.add_argument("--bitrate", help="输出码率，如 192k")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("extract", help="从视频提取音轨")
    p.add_argument("input", help="视频文件")
    p.add_argument("-o", "--output", required=True, help="输出音频（mp3/m4a/aac/wav）")
    p.add_argument("--copy", action="store_true", help="直接拷贝音轨不重编码")
    p.add_argument("--bitrate", help="重编码码率，如 192k")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("concat", help="多段音频拼接")
    p.add_argument("inputs", nargs="+", help="按顺序的多个音频文件")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--bitrate", help="输出码率，如 192k")
    p.set_defaults(func=cmd_concat)

    p = sub.add_parser("fade", help="淡入 / 淡出")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--fade-in", type=float, default=0, help="淡入秒数")
    p.add_argument("--fade-out", type=float, default=0, help="淡出秒数")
    p.set_defaults(func=cmd_fade)

    p = sub.add_parser("speed", help="变速（保持音高 atempo）")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--factor", type=float, required=True,
                   help="倍速，>1 加快 <1 放慢（自动级联超 0.5-2.0 范围）")
    p.set_defaults(func=cmd_speed)

    p = sub.add_parser("denoise", help="降噪（三级 Tier1/2/3）")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--tier", type=int, choices=[1, 2, 3], default=2,
                   help="1=内置滤波 2=更强FFT/anlmdn 3=RNNoise(无模型降级2)")
    p.add_argument("--mix", type=float, default=0.8, help="RNN 降噪强度 0-1（仅 tier3）")
    p.add_argument("--model", help="RNNoise 模型路径（默认脚本旁 models/sh.rnnn）")
    p.set_defaults(func=cmd_denoise)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.selftest:
        return cmd_selftest()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0
    # info 之外的子命令都需要 ffmpeg；统一先检查工具。
    _require_tools()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
