#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端语音转录 API（硅基流动 · OpenAI 兼容）→ transcript.json。

【Easel 内置改造 · 三级转录 tier2】
无字幕稿、又不想下 3GB 本地 whisper 时，调云端 ASR。默认硅基流动 XingChenGSR。

鉴权/配置全从环境变量读（key 绝不写进代码/命令/仓库）:
  SILICONFLOW_API_KEY   必需，Bearer token
  SILICONFLOW_BASE_URL  可选，默认 https://api.siliconflow.cn/v1
  SILICONFLOW_ASR_MODEL 可选，默认 XingChenAGI/XingChenGSR-V1.0

用法:
  SILICONFLOW_API_KEY=... python transcribe_api.py --src voice.mp3 --out transcript.json [--lang zh]

返回处理:
  - 响应含 segments（verbose_json）→ 直接用。
  - 只有纯 text → 按中文标点切句 + 按音频时长比例估时间轴（近似，日志标注 approx=true）。
外网访问走系统代理（HTTPS_PROXY/HTTP_PROXY），与内网 MaaS 不同。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE = "https://api.siliconflow.cn/v1"
DEFAULT_MODEL = "XingChenAGI/XingChenGSR-V1.0"


def audio_duration(path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", path],
            capture_output=True, text=True, timeout=60).stdout.strip()
        return float(out)
    except (ValueError, OSError, subprocess.SubprocessError):
        return 0.0


def build_multipart(fields: dict, file_field: str, file_path: str) -> tuple[bytes, str]:
    boundary = "----EaselASR" + uuid.uuid4().hex
    crlf = b"\r\n"
    buf = bytearray()
    for name, value in fields.items():
        buf += b"--" + boundary.encode() + crlf
        buf += f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
        buf += str(value).encode() + crlf
    with open(file_path, "rb") as f:
        data = f.read()
    filename = os.path.basename(file_path)
    buf += b"--" + boundary.encode() + crlf
    buf += (f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"').encode() + crlf
    buf += b"Content-Type: application/octet-stream" + crlf + crlf
    buf += data + crlf
    buf += b"--" + boundary.encode() + b"--" + crlf
    return bytes(buf), boundary


def split_sentences(text: str) -> list[str]:
    # 中文按句末标点切；保留标点
    parts = re.split(r"(?<=[。！？!?…\.])\s*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def text_to_segments(text: str, duration: float) -> list[dict]:
    """无时间轴时：按句切分 + 按字数比例分配时长（近似）。"""
    sents = split_sentences(text) or ([text.strip()] if text.strip() else [])
    if not sents:
        return []
    total_chars = sum(len(s) for s in sents) or 1
    dur = duration if duration > 0 else float(total_chars)  # 无时长则用字数当伪秒
    segs, t = [], 0.0
    for s in sents:
        span = dur * (len(s) / total_chars)
        segs.append({"start": round(t, 3), "end": round(t + span, 3), "text": s,
                     "words": [{"word": s, "start": round(t, 3), "end": round(t + span, 3)}]})
        t += span
    return segs


def normalize_response(data: dict, text: str, duration: float) -> dict:
    """把 API 返回归一成 transcript.json（含 approx 标记）。"""
    segments = data.get("segments") if isinstance(data, dict) else None
    if isinstance(segments, list) and segments:
        norm, approx = [], False
        for s in segments:
            st, en = s.get("start"), s.get("end")
            body = str(s.get("text", "")).strip()
            if st is None or en is None:
                approx = True
                st, en = 0.0, 0.0
            norm.append({"start": round(float(st), 3), "end": round(float(en), 3), "text": body,
                         "words": [{"word": body, "start": round(float(st), 3), "end": round(float(en), 3)}]})
        return {"segments": norm, "approx_timeline": approx}
    # 只有纯文本
    return {"segments": text_to_segments(text, duration), "approx_timeline": True}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="音/视频源")
    ap.add_argument("--out", required=True, help="输出 transcript.json")
    ap.add_argument("--lang", default="zh")
    ap.add_argument("--model", default=os.environ.get("SILICONFLOW_ASR_MODEL", DEFAULT_MODEL))
    args = ap.parse_args()

    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not key:
        print("缺 SILICONFLOW_API_KEY（tier2 云端转录需要）；请 export 后重试。", file=sys.stderr)
        return 1
    base = os.environ.get("SILICONFLOW_BASE_URL", DEFAULT_BASE).rstrip("/")
    url = base + "/audio/transcriptions"

    if not os.path.isfile(args.src):
        print(f"源不存在：{args.src}", file=sys.stderr)
        return 1

    body, boundary = build_multipart(
        {"model": args.model, "language": args.lang, "response_format": "verbose_json"},
        "file", args.src)
    req = Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    print(f"调用 {url} · model={args.model} · {os.path.basename(args.src)}", flush=True)
    try:
        # 外网：默认 opener 尊重 HTTPS_PROXY/HTTP_PROXY
        with urlopen(req, timeout=600) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:1000]
        print(f"ASR API HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except (URLError, OSError) as exc:
        print(f"ASR API 网络错误：{exc}", file=sys.stderr)
        return 1

    try:
        data = json.loads(raw)
    except ValueError:
        data = {"text": raw}
    text = str((data.get("text") if isinstance(data, dict) else "") or "").strip()
    duration = audio_duration(args.src)
    norm = normalize_response(data if isinstance(data, dict) else {}, text, duration)
    if not norm["segments"]:
        print(f"API 返回无可用文本：{raw[:300]}", file=sys.stderr)
        return 1

    result = {
        "language": args.lang,
        "duration": round(duration, 3),
        "source_kind": "asr-api",
        "source": os.path.abspath(args.src),
        "asr_model": args.model,
        "approx_timeline": norm["approx_timeline"],
        "segments": norm["segments"],
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    flag = "（时间轴为近似估算）" if norm["approx_timeline"] else ""
    print(f"DONE ASR {len(result['segments'])} 段 · {duration:.2f}s → {args.out} {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
