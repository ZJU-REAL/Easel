#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频产线 SDK · 环境自检（doctor）"""
import importlib.util
import shutil
import socket
import sys
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parent.parent
rows = []


def add(name, ok, detail, hard):
    rows.append((name, ok, detail, hard))


v = sys.version_info
add("Python >= 3.10", v >= (3, 10), f"{v.major}.{v.minor}.{v.micro}", True)
for tool in ("ffmpeg", "ffprobe"):
    p = shutil.which(tool)
    add(tool, bool(p), p or "未找到（PATH）", True)
for tool in ("node", "npx"):
    p = shutil.which(tool) or shutil.which(tool + ".cmd")
    add(tool, bool(p), p or "未找到", True)
d = SDK_ROOT / "deps" / "remotion" / "package.json"
add("deps/remotion 蓝本", d.is_file(), "在" if d.is_file() else "缺", True)
need_tools = ["tools/transcribe.py", "tools/check_sync.py", "tools/rvm_matte.py"]
missing = [t for t in need_tools if not (SDK_ROOT / t).is_file()]
add("SDK tools", not missing, "齐" if not missing else f"缺: {missing}", True)
add("faster-whisper", importlib.util.find_spec("faster_whisper") is not None,
    "转录链（有现成转录稿可忽略）", False)
try:
    import torch
    add("torch CUDA", True, f"cuda={torch.cuda.is_available()}", False)
except Exception as e:  # noqa: BLE001
    add("torch CUDA", False, f"{type(e).__name__}", False)


def port_free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


add("端口 8898 可用", port_free(8898), "卡面默认端口", False)

print("视频产线 SDK · doctor")
print("-" * 66)
for name, ok, detail, hard in rows:
    tag = "PASS" if ok else ("FAIL" if hard else "WARN")
    print(f"[{tag}] {name:<22} {detail}")
fails = [r for r in rows if not r[1] and r[3]]
print("-" * 66)
print("硬性检查全过 OK" if not fails else f"缺 {len(fails)} 项硬依赖，先补齐再跑")
sys.exit(0 if not fails else 1)
