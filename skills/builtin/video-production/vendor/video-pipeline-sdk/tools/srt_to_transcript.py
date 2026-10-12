#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕（SRT / WebVTT）→ transcript.json（段级，兼容 transcribe.py 结构）。

【Easel 内置改造 · 三级转录 tier1】
口播剧/成片常自带带时间轴的字幕；有它就不必跑本地 whisper，也不必调 API。
把每条字幕转成一个 segment（start/end/text）；words 用整段近似（无词级时间轴时的降级）。

用法:
  python srt_to_transcript.py --src voice.srt --out transcript.json [--lang zh]

输出结构（与 tools/transcribe.py 一致）:
  {"language","duration","source_kind":"subtitle","segments":[{start,end,text,words:[...]}]}
"""
import argparse
import json
import os
import re


def _to_seconds(ts: str) -> float:
    # 支持 SRT "00:00:07,823" 与 VTT "00:00:07.823" / "01:02.345"
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return 0.0
    try:
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


_TIME_LINE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)


def parse_subtitle(text: str) -> list[dict]:
    """解析 SRT/VTT 文本为 [{start,end,text}]（忽略序号行、WEBVTT 头、样式行）。"""
    segments: list[dict] = []
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_idx = next((i for i, ln in enumerate(lines) if _TIME_LINE.search(ln)), None)
        if time_idx is None:
            continue  # WEBVTT 头 / NOTE / 纯序号块
        m = _TIME_LINE.search(lines[time_idx])
        start, end = _to_seconds(m.group(1)), _to_seconds(m.group(2))
        body = " ".join(ln.strip() for ln in lines[time_idx + 1:]).strip()
        # 去掉 VTT 内联标签，如 <c> <00:00:01.000>
        body = re.sub(r"<[^>]+>", "", body).strip()
        if body:
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": body})
    return segments


def to_transcript(segments: list[dict], lang: str, src: str) -> dict:
    duration = max((s["end"] for s in segments), default=0.0)
    return {
        "language": lang,
        "duration": round(duration, 3),
        "source_kind": "subtitle",
        "source": src,
        # 无词级时间轴：words 用整段近似（一个词=整段），下游只依赖 segment 的场景可用。
        "segments": [
            {**s, "words": [{"word": s["text"], "start": s["start"], "end": s["end"]}]}
            for s in segments
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="字幕文件 .srt/.vtt")
    ap.add_argument("--out", required=True, help="输出 transcript.json")
    ap.add_argument("--lang", default="zh")
    args = ap.parse_args()

    with open(args.src, encoding="utf-8-sig", errors="replace") as f:
        raw = f.read()
    segments = parse_subtitle(raw)
    if not segments:
        print(f"字幕解析出 0 段：{args.src}（不是有效 SRT/VTT？）")
        return 1
    result = to_transcript(segments, args.lang, os.path.abspath(args.src))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"DONE 字幕 {len(segments)} 段 · {result['duration']:.2f}s → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
