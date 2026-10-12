#!/usr/bin/env python3
"""音画同步核验：互相关测「测试音频相对参考音频」的毫秒级偏移。

用法:
  python check_sync.py --ref ref.wav --test out.mp4 [--windows 8-14,30-36] [--max-lag 120] [--tol 15]

说明:
  - ref 建议从原片直接抽：ffmpeg -i src.mp4 -vn -ac 1 -ar 48000 -c:a pcm_s16le ref.wav
  - test 可以是任意音视频文件（自动抽音频）；也可以直接给 48k WAV。
  - 正偏移 = 测试音频比参考「晚」（声音滞后于画面时为正）。
  - 退出码：0 = 全部窗 |偏移| ≤ tol；1 = 超差。
依赖: numpy
"""
import argparse
import os
import subprocess
import sys
import tempfile
import wave

try:
    import numpy as np
except ImportError:
    print('需要 numpy: pip install numpy')
    sys.exit(2)


def load_wav(path):
    w = wave.open(path, 'rb')
    n = w.getnframes()
    sr = w.getframerate()
    ch = w.getnchannels()
    d = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64)
    if ch > 1:
        d = d.reshape(-1, ch).mean(axis=1)
    w.close()
    return d, sr


def ensure_wav(path, sr=48000):
    if path.lower().endswith('.wav'):
        return path
    outp = os.path.join(tempfile.gettempdir(), f'_sync_{abs(hash(path)) % 10**8}.wav')
    subprocess.run(
        ['ffmpeg', '-y', '-v', 'error', '-i', path, '-vn', '-ac', '1', '-ar', str(sr), '-c:a', 'pcm_s16le', outp],
        check=True,
    )
    return outp


def lag_ms(a, b, sr, t0, t1, max_lag_ms):
    A = a[int(t0 * sr):int(t1 * sr)].copy()
    B = b[int(t0 * sr):int(t1 * sr)].copy()
    if len(A) < sr or len(B) < sr:
        return None, None
    A -= A.mean()
    B -= B.mean()
    n = int(max_lag_ms / 1000 * sr)
    best = (0, -2.0)
    for s in range(-n, n + 1):
        if s >= 0:
            x, y = (A[:len(A) - s] if s else A), B[s:]
        else:
            x, y = A[-s:], B[:len(B) + s]
        if len(x) < sr // 2:
            continue
        c = float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-9))
        if c > best[1]:
            best = (s, c)
    return best[0] / sr * 1000.0, best[1]


def main():
    ap = argparse.ArgumentParser(description='audio/video sync checker (cross-correlation)')
    ap.add_argument('--ref', required=True, help='参考音频（建议原片直抽的 48k WAV）')
    ap.add_argument('--test', required=True, help='待测文件（成片/片段）')
    ap.add_argument('--windows', default='8-14,30-36', help='检测窗(秒)，逗号分隔，如 8-14,30-36')
    ap.add_argument('--max-lag', type=float, default=120.0, help='最大搜索偏移 (ms)')
    ap.add_argument('--tol', type=float, default=15.0, help='合格阈值 (ms)')
    args = ap.parse_args()

    ref, ref_sr = load_wav(ensure_wav(args.ref))
    test = load_wav(ensure_wav(args.test))[0]

    ok = True
    for wnd in args.windows.split(','):
        t0, t1 = (float(x) for x in wnd.split('-'))
        d, c = lag_ms(ref, test, ref_sr, t0, t1, args.max_lag)
        if d is None:
            print(f'  {wnd}s: 窗口越界或音频过短')
            ok = False
            continue
        flag = 'OK' if abs(d) <= args.tol else 'FAIL'
        print(f'  {wnd}s: {d:+.1f} ms (corr {c:.3f}) [{flag}]')
        ok = ok and abs(d) <= args.tol
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
