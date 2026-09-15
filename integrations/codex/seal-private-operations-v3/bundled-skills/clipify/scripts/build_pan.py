#!/usr/bin/env python
"""Build a speaker-pan expression and optionally render it with FFmpeg."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def build_expression(segments: list[dict], left_x: int, right_x: int) -> str:
    if not segments:
        raise ValueError("segments.json 不能为空")

    def x_for(speaker: str) -> int:
        if speaker not in {"left", "right"}:
            raise ValueError(f"未知 speaker: {speaker}")
        return left_x if speaker == "left" else right_x

    expr = str(x_for(segments[-1]["speaker"]))
    for segment in reversed(segments[:-1]):
        expr = f"if(lt(t\\,{float(segment['end']):.4f})\\,{x_for(segment['speaker'])}\\,{expr})"
    return expr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("segments")
    parser.add_argument("left_x", type=int)
    parser.add_argument("right_x", type=int)
    parser.add_argument("--render-input")
    parser.add_argument("--output")
    parser.add_argument("--crop-width", type=int, default=608)
    parser.add_argument("--crop-height", type=int, default=1080)
    parser.add_argument("--target-width", type=int, default=1080)
    parser.add_argument("--target-height", type=int, default=1920)
    args = parser.parse_args()

    segments = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    expr = build_expression(segments, args.left_x, args.right_x)
    if not args.render_input:
        print(expr)
        return 0
    if not args.output:
        parser.error("使用 --render-input 时必须提供 --output")
    if not shutil.which("ffmpeg"):
        raise SystemExit("未找到 FFmpeg，请重新运行 Seal V3 安装脚本")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        f"[0:v]crop={args.crop_width}:{args.crop_height}:x='{expr}':y=0,"
        f"scale={args.target_width}:{args.target_height}:flags=lanczos[v]"
    )
    result = subprocess.run([
        "ffmpeg", "-y", "-i", args.render_input, "-filter_complex", filter_graph,
        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        str(output),
    ], check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
