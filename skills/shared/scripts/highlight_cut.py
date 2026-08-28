#!/usr/bin/env python3
"""highlight_cut.py — 长视频/直播录像高光切片的确定性封装。

"直播切片 / 长视频切片"类 SKILL（video-highlights）共用此脚本。两条能力：
    energy  用 librosa 分析音频能量，找出"高光候选时间段"（情绪高涨/大声/欢呼处）
    cut     按给定切片清单（JSON）把长视频切成若干独立短视频，可选转竖版 + 加片段字幕

典型链路：energy 找候选（或 ASR 转录后由 LLM 选段）→ 汇成切片清单 → cut 出片。

与 clipify 的区别：clipify 是英文口播找笑点 + 逐段动态人脸 pan 的特化流程；本脚本更通用
（中文/直播/口播皆可），用音频能量或转录选段，切片时静态转竖版，更稳更快。

依赖：ffmpeg + ffprobe；energy 需 librosa + numpy；转竖版复用同目录 reframe.py。

子命令：
    energy    分析音频能量 → 高光候选段 JSON
    cut       按切片清单 JSON → 多条短视频
    selftest  自检

用法举例：
    highlight_cut.py energy -i live.mp4 --top 5 --clip-len 20 -o cand.json
    highlight_cut.py cut -i live.mp4 --segments cand.json -o outputs/video-highlights \
        --reframe 9:16 --reframe-mode blur
    highlight_cut.py selftest
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SELF_DIR = Path(__file__).resolve().parent


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


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-18:])
        _die(f"命令执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)


def _probe_dur(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _fmt(t: float) -> str:
    return f"{int(t//60):02d}:{t%60:05.2f}"


# ── energy：音频能量找高光 ────────────────────────────────────────────
def _energy_candidates(video: Path, top: int, clip_len: float,
                       min_gap: float) -> list[dict]:
    try:
        import librosa
        import numpy as np
    except Exception as e:
        _die(f"energy 需要 librosa + numpy：{e}", 3)
    dur = _probe_dur(video)
    with tempfile.TemporaryDirectory() as td_:
        wav = Path(td_) / "a.wav"
        _run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "22050",
              str(wav)])
        y, sr = librosa.load(str(wav), sr=22050, mono=True)
    hop = 1024
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop)
    if rms.max() <= 0:
        return []
    norm = rms / rms.max()
    # 贪心挑峰：按能量降序，保证峰间隔 ≥ min_gap
    order = np.argsort(norm)[::-1]
    picked: list[float] = []
    scores: list[float] = []
    gap = max(min_gap, clip_len * 0.6)
    for i in order:
        t = float(times[i])
        if all(abs(t - p) >= gap for p in picked):
            picked.append(t)
            scores.append(float(norm[i]))
        if len(picked) >= top:
            break
    cands = []
    for c, sc in sorted(zip(picked, scores)):
        s = max(0.0, c - clip_len / 2)
        e = min(dur, s + clip_len)
        s = max(0.0, e - clip_len)
        cands.append({"start": round(s, 2), "end": round(e, 2),
                      "score": round(sc, 3), "label": f"高光@{_fmt(c)}"})
    return cands


def cmd_energy(a) -> int:
    _check_ffmpeg()
    video = _require_input(a.input)
    cands = _energy_candidates(video, a.top, a.clip_len, a.min_gap)
    if not cands:
        _die("未找到高光候选（音频过静或无音轨）。", 2)
    payload = json.dumps({"source": str(video), "segments": cands},
                         ensure_ascii=False, indent=2)
    if a.output:
        Path(a.output).expanduser().parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).expanduser().write_text(payload, encoding="utf-8")
        print(f"✅ {a.output}（{len(cands)} 个候选）")
        for c in cands:
            print(f"   {_fmt(c['start'])}–{_fmt(c['end'])}  score={c['score']}  {c['label']}",
                  file=sys.stderr)
    else:
        print(payload)
    return 0


# ── cut：按清单切片 ───────────────────────────────────────────────────
def _reframe(clip: Path, ratio: str, mode: str, out: Path) -> None:
    """调用同目录 reframe.py 转竖版。"""
    _run([sys.executable, str(_SELF_DIR / "reframe.py"), "reframe",
          "-i", str(clip), "-o", str(out), "--ratio", ratio, "--mode", mode])


def cmd_cut(a) -> int:
    _check_ffmpeg()
    video = _require_input(a.input)
    raw = sys.stdin.read() if a.segments == "-" else _require_input(a.segments).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"切片清单不是有效 JSON：{e}", 2)
    segs = data.get("segments") if isinstance(data, dict) else data
    if not segs:
        _die("切片清单为空（需 segments: [{start,end,label?}]）。", 2)
    outdir = Path(a.output).expanduser()
    outdir.mkdir(parents=True, exist_ok=True)
    dur = _probe_dur(video)

    results = []
    for i, seg in enumerate(segs, 1):
        try:
            s = max(0.0, float(seg["start"]) - a.pad)
            e = min(dur, float(seg["end"]) + a.pad)
        except (KeyError, ValueError, TypeError):
            _die(f"第 {i} 段缺 start/end 或格式错误：{seg}", 2)
        if e - s < 0.3:
            print(f"  跳过第 {i} 段（时长 <0.3s）", file=sys.stderr)
            continue
        stem = f"highlight_{i:02d}"
        with tempfile.TemporaryDirectory() as td_:
            raw_clip = Path(td_) / "raw.mp4"
            # 精确裁切（-ss 在 -i 后，重编码保证关键帧对齐）
            _run(["ffmpeg", "-y", "-i", str(video), "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                  "-preset", "medium", "-c:a", "aac", str(raw_clip)])
            final = outdir / f"{stem}.mp4"
            if a.reframe:
                _reframe(raw_clip, a.reframe, a.reframe_mode, final)
            else:
                shutil.copy(raw_clip, final)
        results.append({"file": str(final), "start": round(s, 2), "end": round(e, 2),
                        "duration": round(e - s, 2), "label": seg.get("label", stem)})
        print(f"  ✅ {final.name} ({_fmt(s)}–{_fmt(e)}, {e-s:.1f}s)")

    if not results:
        _die("没有生成任何切片。", 2)
    manifest = outdir / "highlights.json"
    manifest.write_text(json.dumps({"source": str(video), "clips": results},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 共 {len(results)} 条切片 → {outdir}/（清单 {manifest.name}）")
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("highlight_cut 自检 ...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        video = d / "live.mp4"
        # 10s 视频，音频在 5-6s 有明显能量爆发
        aud = ("0.08*sin(2*PI*300*t)+"
               "between(t\\,5\\,6)*0.8*sin(2*PI*600*t)")
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:d=10",
              "-f", "lavfi", "-i", f"aevalsrc={aud}:d=10:s=22050",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-shortest", str(video)])

        # energy：top1 应落在 ~5.5s 附近
        cands = _energy_candidates(video, top=1, clip_len=4.0, min_gap=2.0)
        assert cands, "未找到候选"
        c = cands[0]
        assert c["start"] <= 5.5 <= c["end"], f"高光段未覆盖能量爆发点：{c}"

        # cut：用显式清单切 2 段 + 转竖版
        segs = d / "segs.json"
        segs.write_text(json.dumps({"segments": [
            {"start": 1.0, "end": 3.0, "label": "seg1"},
            {"start": 5.0, "end": 7.0, "label": "seg2"}]}), encoding="utf-8")
        outdir = d / "out"
        ns = argparse.Namespace(input=str(video), segments=str(segs), output=str(outdir),
                                pad=0.0, reframe="9:16", reframe_mode="blur")
        cmd_cut(ns)
        clips = sorted(outdir.glob("highlight_*.mp4"))
        assert len(clips) == 2, f"应切出 2 段，实得 {len(clips)}"
        assert (outdir / "highlights.json").is_file(), "缺清单文件"
        # 校验转竖版尺寸
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "csv=s=x:p=0", str(clips[0])],
            stdout=subprocess.PIPE, text=True)
        w, h = (proc.stdout or "").strip().split("x")[:2]
        assert int(h) > int(w), f"切片未转成竖版：{w}x{h}"

    print("✅ selftest 全部通过（energy 定位 + cut 切片 + 转竖版）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="长视频/直播高光切片（音频能量选段 + 切片 + 转竖版）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("energy", help="音频能量找高光候选段")
    p.add_argument("-i", "--input", required=True, help="长视频/直播录像")
    p.add_argument("--top", type=int, default=5, help="返回候选数（默认 5）")
    p.add_argument("--clip-len", type=float, default=20.0, help="每段候选时长秒（默认 20）")
    p.add_argument("--min-gap", type=float, default=10.0, help="候选间最小间隔秒（默认 10）")
    p.add_argument("-o", "--output", help="候选 JSON 输出（省略打印 stdout）")
    p.set_defaults(func=cmd_energy)

    p = sub.add_parser("cut", help="按切片清单切成多条短视频")
    p.add_argument("-i", "--input", required=True, help="源长视频")
    p.add_argument("--segments", required=True, help="切片清单 JSON（- 为 stdin）")
    p.add_argument("-o", "--output", required=True, help="输出目录")
    p.add_argument("--pad", type=float, default=0.3, help="每段前后各留白秒数（默认 0.3）")
    p.add_argument("--reframe", help="切片同时转比例，如 9:16（省略保持原比例）")
    p.add_argument("--reframe-mode", default="blur", choices=["blur", "crop", "smart"],
                   help="转比例策略（默认 blur）")
    p.set_defaults(func=cmd_cut)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
