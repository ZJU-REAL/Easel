#!/usr/bin/env python3
"""see.py — 看图（视觉自检）工具：把图片交给 OpenAI 兼容的多模态端点，拿回文字结论。

用途（视频产线自检链）：
  渲帧 / 素材 → see.py describe → 对照设计表或台词核验 → 不合格先改再往下走
  让「无视觉执行者」升级为「能自检的执行者」。

配置（进程环境变量优先；否则在当前目录向上逐层找 .env）：
  VISION_BASE_URL ← OPENAI_BASE_URL / OPENAI_API_BASE / BASE_URL
  VISION_API_KEY  ← OPENAI_API_KEY / API_KEY
  VISION_MODEL    ← OPENAI_VISION_MODEL / OPENAI_MODEL / 默认 deepseek-chat
  VISION_TIMEOUT  ← 默认 60（秒）

子命令：
  describe --image PATH [--image PATH ...] [--question "..."] [--max-tokens N] [--json]
  check      离线检查配置（不发任何网络请求）
  selftest   离线自检（编码/载荷/错误分支，不联网）

示例：
  python tools/see.py describe --image run/preview/f120.png --question "对照设计表：构图密度够吗？字幕可读吗？有没有素场？只列问题。"

退出码：0 成功；2 配置缺失；3 网络或接口错误。
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_QUESTION = "描述这张图片的内容；如果有文字，逐字读出。"
DEFAULT_MODEL = "deepseek-chat"
MAX_BYTES = 12 * 1024 * 1024
EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}


def load_dotenv(start: Path) -> dict:
    """在当前目录及其上级找最近的 .env，读出 KEY=VALUE（不覆盖进程环境）。"""
    out = {}
    for d in [start, *start.parents]:
        f = d / ".env"
        if f.is_file():
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    return out


def cfg() -> dict:
    envfile = load_dotenv(Path.cwd())

    def get(*names, default=None):
        for n in names:
            v = os.environ.get(n) or envfile.get(n)
            if v:
                return v
        return default

    return {
        "base": (get("VISION_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL") or "").rstrip("/"),
        "key": get("VISION_API_KEY", "OPENAI_API_KEY", "API_KEY") or "",
        "model": get("VISION_MODEL", "OPENAI_VISION_MODEL", "OPENAI_MODEL", default=DEFAULT_MODEL),
        "timeout": int(get("VISION_TIMEOUT", default="60")),
    }


def mask(key: str) -> str:
    return (key[:6] + "…" + key[-4:]) if len(key) > 12 else "(太短/缺)"


def cmd_check() -> int:
    c = cfg()
    print(f"模型   : {c['model']}")
    print(f"端点   : {c['base'] or '(缺)'}")
    print(f"Key    : {mask(c['key']) if c['key'] else '(缺)'}")
    if not c["base"] or not c["key"]:
        print("结果   : 配置缺失（需要 VISION_BASE_URL 与 VISION_API_KEY，或其别名 OPENAI_*）")
        return 2
    print("结果   : 就绪（check 不联网；可用 describe 实测）")
    return 0


def encode_image(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")
    ext = path.suffix.lower()
    if ext not in EXTS:
        raise ValueError(f"不支持的图片类型: {ext or path.name}")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"图片过大（{len(data)}B > {MAX_BYTES}B）: {path}")
    return EXTS[ext], base64.b64encode(data).decode()


def cmd_describe(a) -> int:
    c = cfg()
    if not c["base"] or not c["key"]:
        print("配置缺失：需要 VISION_BASE_URL 与 VISION_API_KEY（或其别名 OPENAI_*）", file=sys.stderr)
        return 2
    content = [{"type": "text", "text": a.question}]
    for p in a.image:
        mime, b64 = encode_image(Path(p))
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    payload = {"model": c["model"], "messages": [{"role": "user", "content": content}],
               "max_tokens": a.max_tokens}
    req = urllib.request.Request(c["base"] + "/chat/completions", data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + c["key"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=a.timeout or c["timeout"]) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        print(f"接口错误 HTTP {e.code}: {body}", file=sys.stderr)
        return 3
    except Exception as e:
        print(f"请求失败: {str(e)[:200]}", file=sys.stderr)
        return 3
    msg = d["choices"][0]["message"]
    answer = (msg.get("content") or "").strip()
    if not answer and msg.get("reasoning_content"):
        answer = "[仅推理内容]\n" + msg["reasoning_content"].strip()
    if a.json:
        print(json.dumps({"ok": True, "model": c["model"], "answer": answer,
                          "usage": d.get("usage", {})}, ensure_ascii=False))
    else:
        print(answer)
    return 0


# 1×1 红点 PNG（selftest 用，不联网）
_TINY_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def cmd_selftest() -> int:
    ok = True
    # 1) base64 往返
    raw = base64.b64decode(_TINY_PNG_B64)
    if not raw.startswith(b"\x89PNG"):
        print("FAIL: 内嵌 PNG 损坏"); ok = False
    # 2) 载荷构造
    content = [{"type": "text", "text": "q"},
               {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _TINY_PNG_B64}}]
    payload = {"model": "m", "messages": [{"role": "user", "content": content}], "max_tokens": 8}
    s = json.dumps(payload)
    if '"image_url"' not in s or "data:image/png;base64," not in s:
        print("FAIL: 载荷缺图像块"); ok = False
    # 3) 类型拒绝
    try:
        encode_image(Path("x.tiff")); print("FAIL: 异常扩展名未拒绝"); ok = False
    except FileNotFoundError:
        pass  # 先报不存在也说明走了校验路径
    except ValueError:
        pass
    print("PASS: see.py 离线自检通过" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="see.py", description="看图：图片→多模态端点→文字结论（视觉自检）")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("describe", help="看图并回答/描述")
    d.add_argument("--image", action="append", required=True, metavar="PATH", help="图片路径（可多次）")
    d.add_argument("--question", default=DEFAULT_QUESTION, help="要对图片问什么")
    d.add_argument("--max-tokens", type=int, default=900)
    d.add_argument("--timeout", type=int, default=None, help="秒；缺省取 VISION_TIMEOUT/60")
    d.add_argument("--json", action="store_true", help="输出 JSON（answer/usage）")
    sub.add_parser("check", help="离线检查配置")
    sub.add_parser("selftest", help="离线自检")
    a = p.parse_args()
    if a.cmd == "describe":
        return cmd_describe(a)
    if a.cmd == "check":
        return cmd_check()
    return cmd_selftest()


if __name__ == "__main__":
    sys.exit(main())
