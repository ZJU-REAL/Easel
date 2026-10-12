#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ⑦ 音频响度：交付物必须"够响"——max ≥ -3dB 且 mean ≥ -20dB
用法：python check_audio.py <final.mp4>
教训（2026.9.16）：>-60dB 只证明"不是静音"，不是"听得到"。
口播成片必须：原声放大（原片轻时 1.8-2.0×）→ loudnorm I=-16:TP=-1.5:LRA=11 → 过本门。
exit 0=过；1=不过（不许交付）
"""
import argparse, re, subprocess, sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--min-max", type=float, default=-3.0, help="max_volume 下限（dB）")
    ap.add_argument("--min-mean", type=float, default=-20.0, help="mean_volume 下限（dB）")
    args = ap.parse_args()
    r = subprocess.run(["ffmpeg", "-i", args.file, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    mm = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    mx = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    if not (mm and mx):
        print(f"FAIL  {args.file}: 读不到音频电平（无声轨？）")
        sys.exit(1)
    mean, maxv = float(mm.group(1)), float(mx.group(1))
    ok = maxv >= args.min_max and mean >= args.min_mean
    print(f"{'PASS' if ok else 'FAIL'}  {args.file}: mean={mean}dB (需≥{args.min_mean})  max={maxv}dB (需≥{args.min_max})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
