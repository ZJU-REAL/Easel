#!/usr/bin/env python3
"""素材批量转码 → 渲染就绪（30fps / 1080p / 每秒关键帧）。

关键点：-g 30（每秒一个关键帧）是 OffthreadVideo 逐帧 seek 精确且快的前提；
等比缩放 + 补边（不拉伸）。4K60 HEVC 等重源解码慢，建议逐个过、放后台队列。

用法:
  python transcode_material.py --src-dir raw/ --out-dir proj/public/mat clip1.mp4=mat_a clip2.mp4=mat_b
  python transcode_material.py --list jobs.json
  # jobs.json: {"src_dir":"...", "out_dir":"...", "items":[["clip1.mp4","mat_a"], ...]}
"""
import argparse
import json
import os
import subprocess
import sys

VF = ('fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,'
      'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black')
VENC = ['-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast',
        '-g', '30', '-keyint_min', '30', '-sc_threshold', '0', '-an', '-movflags', '+faststart']


def one(src_dir, out_dir, src, name):
    srcp = os.path.join(src_dir, src)
    os.makedirs(out_dir, exist_ok=True)
    outp = os.path.join(out_dir, name + '.mp4')
    if not os.path.exists(srcp):
        print(f'{name}: FAIL src missing: {srcp}')
        return False
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', srcp, '-vf', VF, *VENC, outp],
                       capture_output=True, text=True)
    if os.path.exists(outp) and os.path.getsize(outp) > 100000:
        dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', outp],
                             capture_output=True, text=True).stdout.strip()
        print(f'{name}: OK {os.path.getsize(outp) // 1024 // 1024}MB {dur}s')
        return True
    print(f'{name}: FAIL {r.stderr[-200:]}')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src-dir', default='.')
    ap.add_argument('--out-dir')
    ap.add_argument('--list', help='jobs.json 批量清单')
    ap.add_argument('pairs', nargs='*', help='src=name 对（可多个）')
    args = ap.parse_args()

    jobs = []
    if args.list:
        j = json.load(open(args.list, encoding='utf-8'))
        src_dir, out_dir = j.get('src_dir', '.'), j.get('out_dir')
        if not out_dir:
            print('jobs.json 需含 out_dir')
            sys.exit(2)
        jobs = [(src_dir, out_dir, it[0], it[1]) for it in j['items']]
    else:
        if not args.out_dir:
            print('需要 --out-dir')
            sys.exit(2)
        for p in args.pairs:
            s, n = p.split('=')
            jobs.append((args.src_dir, args.out_dir, s, n))

    if not jobs:
        print('没有任务（给 src=name 对或 --list）')
        sys.exit(2)
    results = [one(*j) for j in jobs]
    print('ALL OK' if all(results) else 'HAS FAILURES')
    sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
