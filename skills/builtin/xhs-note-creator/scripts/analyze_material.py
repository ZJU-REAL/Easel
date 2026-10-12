#!/usr/bin/env python3
"""Scan user-provided materials and emit a materials.json manifest.

Multimodal analysis itself (caption, transcribe) is the AGENT's job using its
own vision/audio tools -- this script only does deterministic pre-work:
  - classify each path by extension (text / image / video / audio / unknown)
  - read basic metadata (size; for images: dimensions; for videos: duration
    + frame extraction via ffmpeg if available)
  - emit skeleton manifest that the agent fills in with captions/usages

Usage:
    python3 analyze_material.py PATH [PATH ...] --out reference/materials.json \
        [--frames-dir reference/frames] [--frames-per-video 6]
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

TEXT_EXT = {".txt", ".md", ".rtf", ".html", ".htm", ".json", ".csv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def classify(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in TEXT_EXT:
        return "text"
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return "unknown"


def image_info(p: Path) -> dict:
    try:
        from PIL import Image
    except ImportError:
        return {}
    try:
        with Image.open(p) as im:
            return {"width": im.width, "height": im.height,
                    "aspect": round(im.width / im.height, 3)}
    except Exception as e:
        return {"error": str(e)}


def video_info(p: Path) -> dict:
    if not shutil.which("ffprobe"):
        return {"note": "ffprobe not installed; duration unknown"}
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=width,height,codec_type",
             "-of", "json", str(p)],
            stderr=subprocess.STDOUT).decode()
        data = json.loads(out)
        dur = float(data.get("format", {}).get("duration", 0))
        v = next((s for s in data.get("streams", [])
                  if s.get("codec_type") == "video"), {})
        return {"duration_sec": round(dur, 2),
                "width": v.get("width"), "height": v.get("height")}
    except Exception as e:
        return {"error": str(e)}


def extract_frames(p: Path, out_dir: Path, n: int) -> list[str]:
    if not shutil.which("ffmpeg"):
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    info = video_info(p)
    dur = info.get("duration_sec", 0) or 0
    if dur <= 0:
        return []
    frames = []
    stem = p.stem.replace(" ", "_")
    for i in range(n):
        t = dur * (i + 0.5) / n
        out = out_dir / f"{stem}_f{i+1:02d}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                 "-i", str(p), "-frames:v", "1", "-q:v", "3", str(out)],
                check=True)
            frames.append(str(out))
        except Exception:
            pass
    return frames


def text_preview(p: Path, n: int = 400) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:n]
    except Exception as e:
        return f"<read error: {e}>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--frames-per-video", type=int, default=6)
    args = ap.parse_args()

    items = []
    for raw in args.paths:
        p = Path(raw).expanduser()
        if not p.exists():
            items.append({"path": raw, "error": "not found"})
            continue
        kind = classify(p)
        entry: dict = {
            "id": f"m{len(items)+1:03d}",
            "path": str(p),
            "kind": kind,
            "size_bytes": p.stat().st_size,
            "caption": "",          # agent fills via vision model
            "usage": "",            # cover / content-N / ending / reference
            "strategy": "",         # use_original | text_on_photo | collage | html_card
        }
        if kind == "image":
            entry.update(image_info(p))
        elif kind == "video":
            entry.update(video_info(p))
            if args.frames_dir:
                entry["frames"] = extract_frames(
                    p, Path(args.frames_dir), args.frames_per_video)
        elif kind == "text":
            entry["preview"] = text_preview(p)
        items.append(entry)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"materials": items}, ensure_ascii=False,
                              indent=2), encoding="utf-8")
    print(f"OK: {out} ({len(items)} item(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
