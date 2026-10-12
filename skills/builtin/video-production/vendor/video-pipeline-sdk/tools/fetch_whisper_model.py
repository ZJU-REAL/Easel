#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载 faster-whisper large-v3 到本地（hf-mirror 直拉，不依赖 huggingface_hub 库）
用法：python tools/fetch_whisper_model.py [--dest <目标目录>]
说明：hub 库走不通（墙），curl 直拉镜像可行；文件清单里**没有** vocabulary.txt（是 vocabulary.json）。
完成后：WhisperModel('<dest>', device='cuda', compute_type='float16') 直读。
"""
import argparse, os, subprocess, sys

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
BASE = "https://hf-mirror.com/Systran/faster-whisper-large-v3/resolve/main"
FILES = ["config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json", "model.bin"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=os.path.expanduser("~/models/faster-whisper-large-v3"))
    a = ap.parse_args()
    os.makedirs(a.dest, exist_ok=True)
    for f in FILES:
        out = os.path.join(a.dest, f)
        if os.path.exists(out) and os.path.getsize(out) > 1000:
            print(f"skip {f}（已存在 {os.path.getsize(out)} bytes）")
            continue
        print(f"downloading {f} ...", flush=True)
        r = subprocess.run(["curl", "-L", "-A", UA, "--retry", "3", "-o", out, f"{BASE}/{f}"])
        size = os.path.getsize(out) if os.path.exists(out) else 0
        print(f"  -> {size} bytes (curl exit {r.returncode})")
        if size < 1000:
            print("  !! 失败，检查网络/镜像"); sys.exit(1)
    print(f"完成。WhisperModel('{a.dest}') 即可直读。")


if __name__ == "__main__":
    main()
