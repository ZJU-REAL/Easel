#!/usr/bin/env python3
"""ai_music.py — AI 音乐 / BGM 生成的可插拔客户端（纯标准库，无第三方依赖）。

给短视频 / 社媒内容生成原创背景音乐（BGM / 配乐 / 纯音乐），支持可插拔 provider：

  - dashscope        阿里云 DashScope（百炼）音频/音乐生成，异步任务 + 轮询
  - suno-compatible  Suno 类第三方 API 的通用格式（异步提交 → 轮询 → 下载）

统一流程：异步提交任务 → 轮询任务状态 → 下载生成的音频到 --output。

配置来自环境变量或 .env 文件（脚本会从当前目录向上查找 .env）：

  【通用】
    MUSIC_PROVIDER       选择 provider（dashscope / suno-compatible），也可用 --provider

  【dashscope】
    DASHSCOPE_API_KEY    API key（别名：DASHSCOPE_KEY / ALIYUN_API_KEY）
    DASHSCOPE_MUSIC_MODEL 模型名（可选；兼容旧名 DASHSCOPE_MODEL）
    DASHSCOPE_BASE_URL   API 根地址（可选，默认官方地址）

  【suno-compatible】
    MUSIC_API_KEY        API key
    MUSIC_BASE_URL       API 根地址（如 https://api.example.com/v1）
    MUSIC_MODEL          模型名（可选，默认见 DEFAULT_SUNO_MODEL）

子命令：
    generate   生成音乐（--prompt 风格/情绪 + 可选 --lyrics/--duration/--instrumental）
    check      离线校验当前 provider 所需 env 是否配好（不发任何请求）

用法示例：
    ai_music.py check
    ai_music.py check --provider suno-compatible
    ai_music.py generate --provider dashscope \\
        --prompt "轻快的 lo-fi 嘻哈，适合 vlog 片头，钢琴 + 鼓点" \\
        --duration 30 --instrumental -o outputs/ai-music/bgm.mp3
    ai_music.py generate --provider suno-compatible \\
        --prompt "史诗感电影配乐，弦乐渐强" --lyrics "..." -o outputs/ai-music/track.mp3

说明：每个 provider 的实现"依据公开 API 文档实现，未用真实 key 实测"，
模型名 / 端点路径均可通过 env 或 --model 覆盖，以适配各家实际参数。
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from model_registry import env_aliases, provider_ids, provider_required_env

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# provider 默认值（可被 env / --model 覆盖）
DEFAULT_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_DASHSCOPE_MODEL = "audio-generation"
DEFAULT_SUNO_MODEL = "music-1"

# 每个 provider 声明所需 env（主名 → 别名元组）。check / 报错都基于这份声明。
PROVIDERS = provider_ids("music")
ENV_ALIASES = env_aliases("music")


def fail(message: str, exit_code: int = 1) -> "None":
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(exit_code)


# ── 配置与环境 ──────────────────────────────────────────────

def strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def find_default_env_file() -> Path | None:
    for directory in (Path.cwd(), *Path.cwd().parents):
        env_file = directory / ".env"
        if env_file.is_file():
            return env_file
    return None


def load_env_file(env_file: Path | None) -> None:
    if env_file is None:
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"无法读取 .env 文件：{exc}")
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            print(f"警告：.env 第 {line_number} 行不是 KEY=value，已跳过。", file=sys.stderr)
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            print(f"警告：.env 第 {line_number} 行缺少变量名，已跳过。", file=sys.stderr)
            continue
        if key not in os.environ:
            os.environ[key] = strip_env_value(value)


def env_lookup(name: str) -> str:
    """按主名 + 别名查找 env，返回去空白后的值（找不到返回空串）。"""
    for candidate in (name, *ENV_ALIASES.get(name, ())):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    return ""


def require_env(name: str) -> str:
    value = env_lookup(name)
    if not value:
        accepted = "、".join((name, *ENV_ALIASES.get(name, ())))
        fail(f"缺少配置 {name}。请在 .env 或环境变量中设置（兼容变量名：{accepted}）。")
    return value


def resolve_provider(explicit: str | None) -> str:
    provider = (explicit or os.environ.get("MUSIC_PROVIDER", "") or "").strip()
    if not provider:
        fail(
            "未指定 provider。请用 --provider 或设置 env MUSIC_PROVIDER。"
            f"可选：{ '、'.join(PROVIDERS) }。"
        )
    if provider not in PROVIDERS:
        fail(f"不支持的 provider：{provider}。可选：{ '、'.join(PROVIDERS) }。")
    return provider


# ── HTTP 工具 ──────────────────────────────────────────────

def http_post(url: str, headers: dict[str, str], payload: dict[str, Any],
              timeout: int = 60) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    base_headers = {"Content-Type": "application/json", "User-Agent": UA}
    base_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=base_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"接口返回 HTTP {exc.code}：{detail}")
    except urllib.error.URLError as exc:
        fail(f"无法连接接口：{exc.reason}")
    except (http.client.RemoteDisconnected, TimeoutError):
        fail("接口连接失败或超时，请稍后重试。")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"接口返回的不是有效 JSON：{raw[:500]}")
    if not isinstance(parsed, dict):
        fail("接口返回格式不正确：顶层结果不是对象。")
    return parsed


def http_get(url: str, headers: dict[str, str], timeout: int = 30) -> dict[str, Any]:
    base_headers = {"User-Agent": UA}
    base_headers.update(headers)
    request = urllib.request.Request(url, headers=base_headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"查询接口返回 HTTP {exc.code}：{detail}")
    except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError):
        fail("查询接口连接失败或超时。")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"查询接口返回的不是有效 JSON：{raw[:500]}")
    if not isinstance(parsed, dict):
        fail("查询接口返回格式不正确：顶层结果不是对象。")
    return parsed


def download_audio(url: str, output: Path, timeout: int = 180) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    # 若 output 未带扩展名，从 URL 推断（默认 mp3）
    if not output.suffix:
        suffix = Path(urllib.parse.urlparse(url).path).suffix or ".mp3"
        output = output.with_suffix(suffix)
    print(f"  下载音频：{url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            output.write_bytes(resp.read())
    except urllib.error.URLError as exc:
        fail(f"无法下载音频：{exc.reason}")
    except TimeoutError:
        fail("下载音频超时。")
    return output


def _find_audio_url(obj: Any) -> str | None:
    """在任意嵌套 dict/list 中找第一个像音频 URL 的字符串。

    兼容各家返回结构差异（audio_url / url / output.audio 等常见字段命名）。
    """
    audio_keys = ("audio_url", "audio", "audio_file", "url", "file_url",
                  "song_url", "stream_audio_url", "mp3", "output_url")
    if isinstance(obj, dict):
        # 优先命中明确的音频字段
        for key in audio_keys:
            val = obj.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
        for val in obj.values():
            found = _find_audio_url(val)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_audio_url(item)
            if found:
                return found
    elif isinstance(obj, str):
        low = obj.lower()
        if obj.startswith("http") and (
            low.endswith((".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"))
        ):
            return obj
    return None


# ── provider: dashscope ────────────────────────────────────
# 依据阿里云 DashScope（百炼）公开的异步任务规范实现：
#   提交时带 header  X-DashScope-Async: enable  → 返回 output.task_id / task_status
#   轮询 GET {base}/tasks/{task_id} → task_status PENDING/RUNNING/SUCCEEDED/FAILED
# 音乐生成的具体 model 名 / 输入字段各版本略有差异，故 model 与 base_url 均可用 env 覆盖。
# 未用真实 key 实测。

def generate_dashscope(args: argparse.Namespace) -> Path:
    api_key = require_env("DASHSCOPE_API_KEY")
    base_url = (os.environ.get("DASHSCOPE_BASE_URL", "").strip()
                or DEFAULT_DASHSCOPE_BASE).rstrip("/")
    model = args.model or env_lookup("DASHSCOPE_MUSIC_MODEL") or DEFAULT_DASHSCOPE_MODEL

    endpoint = f"{base_url}/services/aigc/text2audio/generation"
    input_block: dict[str, Any] = {"prompt": args.prompt}
    if args.lyrics:
        input_block["lyrics"] = args.lyrics
    parameters: dict[str, Any] = {}
    if args.duration:
        parameters["duration"] = args.duration
    # 纯音乐（无人声）；DashScope 用布尔开关表达
    parameters["instrumental"] = bool(args.instrumental)

    payload = {"model": model, "input": input_block, "parameters": parameters}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }
    print(f"[dashscope] 提交任务到 {endpoint}（model={model}）...", file=sys.stderr)
    result = http_post(endpoint, headers, payload, timeout=60)

    output = result.get("output", {})
    if not isinstance(output, dict):
        fail(f"提交响应缺少 output 对象：{json.dumps(result)[:300]}")
    task_id = output.get("task_id")
    if not task_id:
        # 有些错误直接在顶层带 code/message
        code = result.get("code")
        message = result.get("message", json.dumps(result)[:300])
        fail(f"提交失败：{message}（code={code}）")

    print(f"[dashscope] 任务已提交：{task_id}", file=sys.stderr)
    task_url = f"{base_url}/tasks/{task_id}"
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    task_output = _poll_dashscope(task_url, poll_headers, args.poll_interval, args.timeout)

    audio_url = _find_audio_url(task_output)
    if not audio_url:
        fail(f"任务完成但未找到音频 URL：{json.dumps(task_output)[:300]}")
    return download_audio(audio_url, Path(args.output))


def _poll_dashscope(task_url: str, headers: dict[str, str],
                    poll_interval: int, timeout: int) -> dict[str, Any]:
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            fail(f"任务超时（{timeout}s），可稍后用 task_id 手动查询。")
        result = http_get(task_url, headers)
        output = result.get("output", {})
        status = str(output.get("task_status", "")).upper()
        if status == "SUCCEEDED":
            return output
        if status in ("FAILED", "CANCELED", "UNKNOWN"):
            fail(f"任务失败：状态={status}，{json.dumps(output)[:300]}")
        print(f"  轮询中... 状态={status or '?'} 耗时={elapsed:.0f}s", file=sys.stderr)
        time.sleep(poll_interval)


# ── provider: suno-compatible ──────────────────────────────
# 依据 Suno 类第三方 API 的通用格式实现（各家网关多兼容此形态）：
#   POST {base}/generate  →  返回任务 id（id / task_id / data.id）
#   轮询 GET {base}/feed/{id} 或 {base}/tasks/{id} → status complete/failed + audio_url
# base_url / model 均由 env 提供。未用真实 key 实测。

def generate_suno(args: argparse.Namespace) -> Path:
    api_key = require_env("MUSIC_API_KEY")
    base_url = require_env("MUSIC_BASE_URL").rstrip("/")
    model = args.model or os.environ.get("MUSIC_MODEL", "").strip() or DEFAULT_SUNO_MODEL

    endpoint = f"{base_url}/generate"
    payload: dict[str, Any] = {
        "model": model,
        "prompt": args.prompt,
        "make_instrumental": bool(args.instrumental),
    }
    if args.lyrics:
        # 有歌词 → 关闭纯音乐，走自定义歌词模式
        payload["lyrics"] = args.lyrics
        payload["make_instrumental"] = False
    if args.duration:
        payload["duration"] = args.duration
    headers = {"Authorization": f"Bearer {api_key}"}

    print(f"[suno] 提交任务到 {endpoint}（model={model}）...", file=sys.stderr)
    result = http_post(endpoint, headers, payload, timeout=60)
    task_id = _extract_suno_id(result)
    if not task_id:
        fail(f"提交响应缺少任务 id：{json.dumps(result)[:300]}")

    print(f"[suno] 任务已提交：{task_id}", file=sys.stderr)
    audio_url = _poll_suno(base_url, headers, task_id, args.poll_interval, args.timeout)
    return download_audio(audio_url, Path(args.output))


def _extract_suno_id(result: dict[str, Any]) -> str | None:
    for key in ("task_id", "id", "request_id"):
        val = result.get(key)
        if isinstance(val, (str, int)):
            return str(val)
    data = result.get("data")
    if isinstance(data, dict):
        return _extract_suno_id(data)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _extract_suno_id(data[0])
    return None


def _poll_suno(base_url: str, headers: dict[str, str], task_id: str,
               poll_interval: int, timeout: int) -> str:
    task_url = f"{base_url}/feed/{task_id}"
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            fail(f"任务超时（{timeout}s），可稍后用任务 id 手动查询。")
        result = http_get(task_url, headers)
        status = _extract_suno_status(result)
        if status in ("complete", "completed", "succeeded", "success"):
            audio_url = _find_audio_url(result)
            if not audio_url:
                fail(f"任务完成但未找到音频 URL：{json.dumps(result)[:300]}")
            return audio_url
        if status in ("failed", "error"):
            fail(f"任务失败：{json.dumps(result)[:300]}")
        print(f"  轮询中... 状态={status or '?'} 耗时={elapsed:.0f}s", file=sys.stderr)
        time.sleep(poll_interval)


def _extract_suno_status(result: dict[str, Any]) -> str:
    for key in ("status", "task_status", "state"):
        val = result.get(key)
        if isinstance(val, str):
            return val.lower()
    data = result.get("data")
    if isinstance(data, dict):
        return _extract_suno_status(data)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _extract_suno_status(data[0])
    return ""


# ── 子命令 ──────────────────────────────────────────────

# 每个 provider 需要哪些 env（用于 check + 分发）
PROVIDER_REQUIRED_ENV = provider_required_env("music")

PROVIDER_GENERATORS = {
    "dashscope": generate_dashscope,
    "suno-compatible": generate_suno,
}


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


def cmd_check(args: argparse.Namespace) -> int:
    """离线校验：不发任何请求，只检查所需 env 是否配好。"""
    provider = resolve_provider(args.provider)
    print(f"provider = {provider}")
    required = PROVIDER_REQUIRED_ENV[provider]
    all_required_ok = True
    for name, is_required in required:
        value = env_lookup(name)
        aliases = ENV_ALIASES.get(name, ())
        alias_hint = f"（别名：{ '、'.join(aliases) }）" if aliases else ""
        tag = "必填" if is_required else "可选"
        if value:
            print(f"  [OK]   {name} [{tag}] = {_mask(value)}")
        elif is_required:
            all_required_ok = False
            print(f"  [缺失] {name} [{tag}] 未设置{alias_hint}")
        else:
            default = {
                "DASHSCOPE_MUSIC_MODEL": DEFAULT_DASHSCOPE_MODEL,
                "DASHSCOPE_BASE_URL": DEFAULT_DASHSCOPE_BASE,
                "MUSIC_MODEL": DEFAULT_SUNO_MODEL,
            }.get(name, "")
            hint = f"（将用默认值：{default}）" if default else ""
            print(f"  [默认] {name} [{tag}] 未设置{hint}")
    if all_required_ok:
        print("结果：配置完整，可以执行 generate。")
        return 0
    print("结果：缺少必填配置，请补齐后再执行 generate。", file=sys.stderr)
    return 1


def cmd_generate(args: argparse.Namespace) -> int:
    if not args.prompt or not args.prompt.strip():
        fail("--prompt 不能为空，请描述音乐的风格 / 情绪 / 乐器。")
    provider = resolve_provider(args.provider)
    generator = PROVIDER_GENERATORS[provider]
    output = generator(args)
    print("生成完成：")
    print(output)
    return 0


# ── CLI ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai_music.py",
        description="AI 音乐 / BGM 生成的可插拔客户端（dashscope / suno-compatible），纯标准库。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<子命令>")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--provider", choices=PROVIDERS,
                        help="选择 provider；不指定时读 env MUSIC_PROVIDER。")
    common.add_argument("--env-file", help="指定 .env；不指定时从当前目录向上查找。")

    pc = sub.add_parser("check", parents=[common],
                        help="离线校验所需 env 是否配好（不发请求）")
    pc.set_defaults(func=cmd_check)

    pg = sub.add_parser("generate", parents=[common], help="生成音乐 / BGM")
    pg.add_argument("--prompt", required=True, help="风格 / 情绪 / 乐器描述")
    pg.add_argument("--lyrics", help="可选歌词（有歌词时不再是纯音乐）")
    pg.add_argument("--duration", type=int, help="时长（秒），部分 provider 支持")
    pg.add_argument("--instrumental", action="store_true",
                    help="纯音乐（无人声 BGM）")
    pg.add_argument("--model", help="覆盖模型名（默认读 env / 内置默认）")
    pg.add_argument("-o", "--output", required=True,
                    help="输出音频路径（无扩展名时按返回类型补 .mp3）")
    pg.add_argument("--poll-interval", type=int, default=5, help="轮询间隔秒，默认 5")
    pg.add_argument("--timeout", type=int, default=300, help="轮询超时秒，默认 300")
    pg.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 0
    env_file = Path(args.env_file) if getattr(args, "env_file", None) else find_default_env_file()
    load_env_file(env_file)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
