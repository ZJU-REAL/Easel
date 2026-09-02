#!/usr/bin/env python3
"""ai_image.py — 通用 AI 文生图 / 图生图 / 图像变体（纯标准库，无第三方依赖）。

复用 Easel 已验证的 ecom-details-image/scripts/generate_image.py 约定：
  - OpenAI 兼容同步 API（/images/generations、/images/edits、/images/variations）
  - apimart.ai 异步轮询 API（提交任务 → 轮询 /tasks/<id> → 下载）
  - 自动检测模式：base_url 含 "apimart" → async，其他 → sync；也可 --mode 强制指定

配置来自环境变量或就近的 .env 文件（当前目录向上查找）：
  - IMG_BASE_URL: API 根地址
  - IMG_MODEL:    图片模型名
  - IMG_API_KEY:  API key
兼容别名：
  - IMG_BASE_URL ← OPENAI_BASE_URL / OPENAI_API_BASE / BASE_URL
  - IMG_MODEL    ← OPENAI_IMAGE_MODEL / IMAGE_MODEL / OPENAI_MODEL
  - IMG_API_KEY  ← OPENAI_API_KEY / API_KEY

子命令：
  text2img    文生图：--prompt → 图片
  img2img     图生图/图像编辑：--prompt + --image → 新图
  variations  图像变体：--image → 多个变体
  check       离线校验配置状态（不发起任何网络请求）
"""

from __future__ import annotations

import argparse
import base64
import binascii
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

from output_paths import validate_output_path


ENV_BASE_URL = "IMG_BASE_URL"
ENV_MODEL = "IMG_MODEL"
ENV_API_KEY = "IMG_API_KEY"
ENV_ALIASES = {
    ENV_BASE_URL: ("OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL"),
    ENV_MODEL: ("OPENAI_IMAGE_MODEL", "IMAGE_MODEL", "OPENAI_MODEL"),
    ENV_API_KEY: ("OPENAI_API_KEY", "API_KEY"),
}

VALID_RATIOS = ("auto", "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
                "16:9", "9:16", "2:1", "1:2", "21:9", "9:21")
VALID_RESOLUTIONS = ("1k", "2k", "4k")

PIXEL_TO_RATIO: dict[str, str] = {
    "1024x1024": "1:1", "2048x2048": "1:1",
    "1536x1024": "3:2", "2048x1360": "3:2",
    "1024x1536": "2:3", "1360x2048": "2:3",
    "1024x768": "4:3", "2048x1536": "4:3",
    "768x1024": "3:4", "1536x2048": "3:4",
    "1280x1024": "5:4", "2560x2048": "5:4",
    "1024x1280": "4:5", "2048x2560": "4:5",
    "1536x864": "16:9", "2048x1152": "16:9", "3840x2160": "16:9",
    "864x1536": "9:16", "1152x2048": "9:16", "2160x3840": "9:16",
    "2048x1024": "2:1", "2688x1344": "2:1", "3840x1920": "2:1",
    "1024x2048": "1:2", "1344x2688": "1:2", "1920x3840": "1:2",
    "2016x864": "21:9", "2688x1152": "21:9", "3840x1648": "21:9",
    "864x2016": "9:21", "1152x2688": "9:21", "1648x3840": "9:21",
}

MIME_MAP = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

MISSING_KEY_HINT = (
    "未配置 IMG_API_KEY，请在 .env 填入你的图像生成 API key"
    "（支持 OpenAI 兼容 / apimart）。示例 .env：\n"
    "  IMG_BASE_URL=https://api.openai.com/v1\n"
    "  IMG_MODEL=gpt-image-1\n"
    "  IMG_API_KEY=sk-你的key\n"
    "apimart 异步服务示例：\n"
    "  IMG_BASE_URL=https://api.apimart.ai/v1\n"
    "  IMG_MODEL=<apimart 图片模型>\n"
    "  IMG_API_KEY=<apimart key>"
)


def fail(message: str, exit_code: int = 1) -> None:
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
        # 宽松解析：跳过不符合 KEY=value 的行（不中断 check），只发警告。
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


def resolve_config(name: str) -> tuple[str, str | None]:
    """返回 (值, 命中的变量名)；未配置时返回 ("", None)。不报错，供 check 复用。"""
    for candidate in (name, *ENV_ALIASES.get(name, ())):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value, candidate
    return "", None


def require_config(name: str) -> str:
    value, _ = resolve_config(name)
    if value:
        return value
    if name == ENV_API_KEY:
        fail(MISSING_KEY_HINT)
    accepted = "、".join((name, *ENV_ALIASES.get(name, ())))
    fail(
        f"缺少配置 {name}。请在 .env 中设置 IMG_BASE_URL、IMG_MODEL、IMG_API_KEY；"
        f"也兼容这些变量名：{accepted}。"
    )
    return ""  # 不可达，安抚类型检查


def load_and_require() -> tuple[str, str, str, argparse.Namespace | None]:
    """加载 .env + 校验三项必需配置，返回 (base_url, model, api_key)。"""
    base_url = require_config(ENV_BASE_URL).rstrip("/")
    model = require_config(ENV_MODEL)
    api_key = require_config(ENV_API_KEY)
    return base_url, model, api_key, None


# ── 模式检测 / 尺寸 ──────────────────────────────────────────

def detect_mode(base_url: str, explicit_mode: str | None) -> str:
    if explicit_mode in ("sync", "async"):
        return explicit_mode
    if "apimart" in base_url.lower():
        return "async"
    return "sync"


def size_to_ratio(size: str) -> str:
    if ":" in size:
        return size
    lower = size.lower()
    if lower in PIXEL_TO_RATIO:
        return PIXEL_TO_RATIO[lower]
    fail(f"无法将像素尺寸 '{size}' 转换为比例。请直接使用比例格式，如 1:1、16:9、2:3。")
    return ""


# ── 图片编码 ──────────────────────────────────────────────

def _check_image(image_path: str) -> tuple[Path, str]:
    path = Path(image_path)
    if not path.is_file():
        fail(f"输入图片不存在：{image_path}")
    suffix = path.suffix.lower().lstrip(".")
    mime = MIME_MAP.get(suffix)
    if not mime:
        fail(f"不支持的图片格式：.{suffix}，仅支持 png/jpg/jpeg/webp/gif。")
    return path, mime


def encode_image_data_uri(image_path: str) -> str:
    path, mime = _check_image(image_path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        fail(f"无法读取输入图片：{exc}")
        return ""
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ── HTTP 工具 ──────────────────────────────────────────────

# 内网直连 opener（绕过环境代理）——外网代理常挡内网 MaaS
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _use_direct() -> bool:
    return os.environ.get("IMG_NO_PROXY", "").strip().lower() in ("1", "true", "yes", "on")


def _open(req: urllib.request.Request, timeout: int):
    fn = _NO_PROXY_OPENER.open if _use_direct() else urllib.request.urlopen
    return fn(req, timeout=timeout)


def _auth_header(api_key: str) -> dict[str, str]:
    """鉴权头：默认 Authorization: Bearer；IMG_API_KEY_HEADER 指定别的头名（如 api-key）则用原始 key。"""
    hdr = os.environ.get("IMG_API_KEY_HEADER", "").strip()
    if hdr and hdr.lower() != "authorization":
        return {hdr: api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _api_url(base_url: str, path: str) -> str:
    """拼端点并按需追加 ?api-version=（IMG_API_VERSION，如 Azure/xhs-maas 网关需要）。"""
    url = f"{base_url}/{path.lstrip('/')}"
    ver = os.environ.get("IMG_API_VERSION", "").strip()
    if ver:
        url += ("&" if "?" in url else "?") + f"api-version={ver}"
    return url


def http_post(url: str, api_key: str, payload: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={**_auth_header(api_key),
                 "Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    try:
        with _open(request, timeout) as response:
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
        return {}
    if not isinstance(parsed, dict):
        fail("接口返回格式不正确：顶层结果不是对象。")
    return parsed


def http_get(url: str, api_key: str, timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={**_auth_header(api_key), "User-Agent": UA}, method="GET",
    )
    try:
        with _open(request, timeout) as response:
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
        return {}
    return parsed


# ── 结果保存 ──────────────────────────────────────────────

def _suffix_from_url(url: str, fallback: str) -> str:
    path = urllib.parse.urlparse(url).path
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix in {"png", "jpg", "jpeg", "webp"}:
        return "jpg" if suffix == "jpeg" else suffix
    return fallback


def _download_to(image_url: str, out_path: Path) -> None:
    parsed = urllib.parse.urlparse(image_url)
    if parsed.scheme not in ("http", "https"):
        fail(f"拒绝下载非 http(s) 协议的 URL：{parsed.scheme}")
    dl_req = urllib.request.Request(image_url, headers={"User-Agent": UA})
    try:
        with _open(dl_req, 120) as resp:
            out_path.write_bytes(resp.read())
    except urllib.error.URLError as exc:
        fail(f"无法下载图片：{getattr(exc, 'reason', exc)}")
    except TimeoutError:
        fail("下载图片超时。")


def _out_paths(output: str, count: int, fmt: str) -> list[Path]:
    """根据 --output 与数量生成输出路径列表。

    output 视为目录（不含扩展名）或单文件（含扩展名）。多张时以序号命名。
    """
    out = Path(output)
    is_file = out.suffix.lower().lstrip(".") in MIME_MAP or out.suffix != ""
    ts = time.strftime("%Y%m%d-%H%M%S")
    paths: list[Path] = []
    if count == 1 and is_file:
        out.parent.mkdir(parents=True, exist_ok=True)
        return [out]
    # 目录模式（或多张）
    base_dir = out if not is_file else out.parent
    base_dir.mkdir(parents=True, exist_ok=True)
    stem = out.stem if is_file else "image"
    ext = out.suffix.lstrip(".") if is_file else fmt
    for i in range(count):
        paths.append(base_dir / f"{stem}-{ts}-{i + 1:02d}.{ext}")
    return paths


def save_sync_data(result: dict[str, Any], output: str, fmt: str) -> list[Path]:
    """保存 OpenAI 同步风格返回（data: [{b64_json | url}]）。"""
    data = result.get("data")
    if not isinstance(data, list) or not data:
        fail(f"接口返回中没有 data 图片数组：{json.dumps(result)[:300]}")
    paths = _out_paths(output, len(data), fmt)
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            fail("接口返回格式不正确：data 中包含非对象项目。")
        target = paths[index]
        if item.get("b64_json"):
            try:
                image_bytes = base64.b64decode(item["b64_json"])
            except (binascii.Error, ValueError) as exc:
                fail(f"无法解码 b64_json 图片：{exc}")
                return []
            target.write_bytes(image_bytes)
        elif item.get("url"):
            image_url = item["url"]
            # 用 URL 后缀修正扩展名
            suffix = _suffix_from_url(image_url, fmt)
            target = target.with_suffix(f".{suffix}")
            paths[index] = target
            _download_to(image_url, target)
        else:
            fail("图片结果既没有 b64_json，也没有 url。")
    return paths


# ── apimart 异步 ──────────────────────────────────────────

def run_async(base_url: str, api_key: str, payload: dict[str, Any],
              output: str, fmt: str, poll_interval: int, timeout: int) -> list[Path]:
    endpoint = _api_url(base_url, "images/generations")
    print(f"[async] 提交异步任务到 {endpoint}...", file=sys.stderr)
    result = http_post(endpoint, api_key, payload, timeout=30)

    code = result.get("code")
    if code and code != 200:
        error = result.get("error", {})
        fail(f"提交失败（code={code}）：{error.get('message', json.dumps(result))}")

    data = result.get("data")
    if not isinstance(data, list) or not data:
        fail(f"提交响应缺少 data 数组：{json.dumps(result)[:300]}")
    task_id = data[0].get("task_id")
    if not task_id:
        fail(f"提交响应缺少 task_id：{json.dumps(data[0])[:300]}")

    print(f"[async] 任务已提交: {task_id}，等待 15s 后开始轮询...", file=sys.stderr)
    time.sleep(15)

    task_data = _poll_task(base_url, api_key, task_id, poll_interval, timeout)
    actual_time = task_data.get("actual_time", 0)
    cost = task_data.get("cost", 0)
    print(f"[async] 任务完成，耗时 {actual_time}s，费用 ${cost:.4f}", file=sys.stderr)

    return _save_async_images(task_data, output, fmt)


def _poll_task(base_url: str, api_key: str, task_id: str,
               poll_interval: int, timeout: int) -> dict[str, Any]:
    url = _api_url(base_url, f"tasks/{task_id}")
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            fail(f"任务 {task_id} 超时（{timeout}s），请稍后手动查询。")
        result = http_get(url, api_key)
        task_data = result.get("data", {})
        status = task_data.get("status", "")
        if status == "completed":
            return task_data
        if status == "failed":
            error = task_data.get("error", {})
            fail(f"任务 {task_id} 失败：{error.get('message', json.dumps(task_data)[:300])}")
        progress = task_data.get("progress", 0)
        print(f"  轮询中... 状态={status} 进度={progress}% 耗时={elapsed:.0f}s", file=sys.stderr)
        time.sleep(poll_interval)


def _save_async_images(task_data: dict[str, Any], output: str, fmt: str) -> list[Path]:
    result = task_data.get("result", {})
    images = result.get("images")
    if not isinstance(images, list) or not images:
        fail(f"任务结果中缺少 images 数组：{json.dumps(task_data)[:300]}")
    paths = _out_paths(output, len(images), fmt)
    for index, img_item in enumerate(images):
        url_list = img_item.get("url")
        if not isinstance(url_list, list) or not url_list:
            fail(f"图片结果缺少 url 数组：{json.dumps(img_item)[:300]}")
        image_url = url_list[0]
        suffix = _suffix_from_url(image_url, fmt)
        target = paths[index].with_suffix(f".{suffix}")
        paths[index] = target
        print(f"  下载图片: {image_url}", file=sys.stderr)
        _download_to(image_url, target)
    return paths


# ── 子命令：text2img ──────────────────────────────────────

def cmd_text2img(args: argparse.Namespace) -> None:
    prompt = (args.prompt or "").strip()
    if not prompt:
        fail("prompt 不能为空。")
    base_url, model, api_key, _ = load_and_require()
    mode = detect_mode(base_url, args.mode)
    print(f"[text2img] 模式={mode} base_url={base_url} model={model}", file=sys.stderr)

    if mode == "async":
        payload: dict[str, Any] = {
            "model": model, "prompt": prompt, "n": args.n,
            "size": size_to_ratio(args.size), "resolution": args.resolution,
        }
        paths = run_async(base_url, api_key, payload, args.output, args.format,
                          args.poll_interval, args.timeout)
    else:
        payload = {"model": model, "prompt": prompt, "n": args.n, "size": args.size}
        if args.quality:
            payload["quality"] = args.quality
        endpoint = _api_url(base_url, "images/generations")
        print(f"[sync] 提交生成请求到 {endpoint}...", file=sys.stderr)
        result = http_post(endpoint, api_key, payload, timeout=180)
        paths = save_sync_data(result, args.output, args.format)

    _print_results(paths)


# ── 子命令：img2img ───────────────────────────────────────

def cmd_img2img(args: argparse.Namespace) -> None:
    prompt = (args.prompt or "").strip()
    if not prompt:
        fail("prompt 不能为空。")
    base_url, model, api_key, _ = load_and_require()
    mode = detect_mode(base_url, args.mode)
    print(f"[img2img] 模式={mode} base_url={base_url} model={model} image={args.image}",
          file=sys.stderr)

    if mode == "async":
        # apimart：把参考图作为 image_urls 传入生成端点
        payload: dict[str, Any] = {
            "model": model, "prompt": prompt, "n": args.n,
            "size": size_to_ratio(args.size), "resolution": args.resolution,
            "image_urls": [encode_image_data_uri(args.image)],
        }
        paths = run_async(base_url, api_key, payload, args.output, args.format,
                          args.poll_interval, args.timeout)
    else:
        # OpenAI 兼容 /images/edits：优先 multipart，失败时回退 JSON data-uri
        result = _post_edits_multipart(base_url, api_key, model, prompt, args)
        paths = save_sync_data(result, args.output, args.format)

    _print_results(paths)


def _post_edits_multipart(base_url: str, api_key: str, model: str,
                          prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    """OpenAI /images/edits multipart 上传。纯标准库手工拼 multipart body。"""
    path, mime = _check_image(args.image)
    try:
        img_bytes = path.read_bytes()
    except OSError as exc:
        fail(f"无法读取输入图片：{exc}")
        return {}
    fields = {"model": model, "prompt": prompt, "n": str(args.n), "size": args.size}
    files = [("image", path.name, mime, img_bytes)]
    if args.mask:
        mpath, mmime = _check_image(args.mask)
        try:
            files.append(("mask", mpath.name, mmime, mpath.read_bytes()))
        except OSError as exc:
            fail(f"无法读取 mask 图片：{exc}")
    body, content_type = _encode_multipart(fields, files)
    endpoint = _api_url(base_url, "images/edits")
    print(f"[sync] 提交图生图请求到 {endpoint}（multipart）...", file=sys.stderr)
    request = urllib.request.Request(
        endpoint, data=body,
        headers={**_auth_header(api_key),
                 "Content-Type": content_type, "User-Agent": UA},
        method="POST",
    )
    try:
        with _open(request, 180) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        fail(f"图生图接口返回 HTTP {exc.code}：{detail}")
    except urllib.error.URLError as exc:
        fail(f"无法连接图生图接口：{exc.reason}")
    except (http.client.RemoteDisconnected, TimeoutError):
        fail("图生图接口连接失败或超时。")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        fail(f"图生图接口返回的不是有效 JSON：{raw[:500]}")
        return {}
    if not isinstance(parsed, dict):
        fail("图生图接口返回格式不正确：顶层不是对象。")
    return parsed


def _encode_multipart(fields: dict[str, str],
                      files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----EaselBoundary{int(time.time() * 1000)}"
    buf = bytearray()
    for name, value in fields.items():
        buf += f"--{boundary}\r\n".encode()
        buf += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        buf += f"{value}\r\n".encode()
    for field, filename, mime, data in files:
        buf += f"--{boundary}\r\n".encode()
        buf += (f'Content-Disposition: form-data; name="{field}"; '
                f'filename="{filename}"\r\n').encode()
        buf += f"Content-Type: {mime}\r\n\r\n".encode()
        buf += data
        buf += b"\r\n"
    buf += f"--{boundary}--\r\n".encode()
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


# ── 子命令：variations ────────────────────────────────────

def cmd_variations(args: argparse.Namespace) -> None:
    base_url, model, api_key, _ = load_and_require()
    mode = detect_mode(base_url, args.mode)
    print(f"[variations] 模式={mode} base_url={base_url} model={model} image={args.image}",
          file=sys.stderr)

    if mode == "async":
        # apimart 无独立 variations 端点：用空/通用 prompt + 参考图走生成端点
        payload: dict[str, Any] = {
            "model": model,
            "prompt": args.prompt or "generate a variation of the reference image",
            "n": args.n, "size": size_to_ratio(args.size), "resolution": args.resolution,
            "image_urls": [encode_image_data_uri(args.image)],
        }
        paths = run_async(base_url, api_key, payload, args.output, args.format,
                          args.poll_interval, args.timeout)
    else:
        path, mime = _check_image(args.image)
        try:
            img_bytes = path.read_bytes()
        except OSError as exc:
            fail(f"无法读取输入图片：{exc}")
            return
        fields = {"model": model, "n": str(args.n), "size": args.size}
        body, content_type = _encode_multipart(fields, [("image", path.name, mime, img_bytes)])
        endpoint = _api_url(base_url, "images/variations")
        print(f"[sync] 提交变体请求到 {endpoint}（multipart）...", file=sys.stderr)
        request = urllib.request.Request(
            endpoint, data=body,
            headers={**_auth_header(api_key),
                     "Content-Type": content_type, "User-Agent": UA},
            method="POST",
        )
        try:
            with _open(request, 180) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            fail(f"变体接口返回 HTTP {exc.code}：{detail}")
        except urllib.error.URLError as exc:
            fail(f"无法连接变体接口：{exc.reason}")
        except (http.client.RemoteDisconnected, TimeoutError):
            fail("变体接口连接失败或超时。")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            fail(f"变体接口返回的不是有效 JSON：{raw[:500]}")
            return
        paths = save_sync_data(result, args.output, args.format)

    _print_results(paths)


# ── 子命令：check（离线，不发请求）──────────────────────────

def cmd_check(args: argparse.Namespace) -> None:
    base_url, base_from = resolve_config(ENV_BASE_URL)
    model, model_from = resolve_config(ENV_MODEL)
    api_key, key_from = resolve_config(ENV_API_KEY)

    print("=== ai-image 配置检查（离线，不发起任何请求）===")
    _report("IMG_BASE_URL", base_url, base_from, mask=False)
    _report("IMG_MODEL", model, model_from, mask=False)
    _report("IMG_API_KEY", api_key, key_from, mask=True)

    missing = [n for n, v in (("IMG_BASE_URL", base_url),
                              ("IMG_MODEL", model), ("IMG_API_KEY", api_key)) if not v]

    if base_url:
        mode = detect_mode(base_url.rstrip("/"), None)
        print(f"\n自动检测模式：{mode}"
              f"（base_url 含 apimart → async，否则 → sync；可用 --mode 覆盖）")

    if missing:
        print("\n[未就绪] 缺少：" + "、".join(missing))
        print("\n请在项目根目录 .env 中补齐：")
        print(MISSING_KEY_HINT)
        raise SystemExit(2)
    print("\n[就绪] 三项配置均已设置，可执行 text2img / img2img / variations。")


def _report(name: str, value: str, source: str | None, mask: bool) -> None:
    if not value:
        print(f"  [缺失] {name}：未设置")
        return
    shown = _mask(value) if mask else value
    via = "" if source == name else f"（来自别名 {source}）"
    print(f"  [已设置] {name} = {shown}{via}")


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}（长度 {len(value)}）"


# ── 公共 ──────────────────────────────────────────────────

def _print_results(paths: list[Path]) -> None:
    print("生成完成：")
    for path in paths:
        print(path)


# ── CLI ───────────────────────────────────────────────────

def _add_common_output(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--output", "-o", required=True,
                    help="输出路径：目录（多张自动编号）或含扩展名的单文件；必须位于 outputs/<人类可读主题>/。")
    sp.add_argument("--n", type=int, default=1, help="生成数量，默认 1。")
    sp.add_argument("--size", default="1024x1024",
                    help="尺寸。同步用像素（1024x1024 等），异步用比例（1:1、16:9 等）。默认 1024x1024。")
    sp.add_argument("--mode", choices=("sync", "async"),
                    help="API 模式。默认按 base_url 自动检测（含 apimart → async）。")
    sp.add_argument("--resolution", default="2k", choices=VALID_RESOLUTIONS,
                    help="异步模式分辨率档位，默认 2k。")
    sp.add_argument("--format", choices=("png", "jpeg", "webp"), default="png",
                    help="保存格式（无 URL 后缀时的兜底），默认 png。")
    sp.add_argument("--poll-interval", type=int, default=5, help="异步轮询间隔秒，默认 5。")
    sp.add_argument("--timeout", type=int, default=180, help="异步轮询超时秒，默认 180。")
    sp.add_argument("--env-file", help="指定 .env；默认从当前目录向上查找。")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通用 AI 文生图 / 图生图 / 图像变体（OpenAI 兼容同步 + apimart 异步，纯标准库）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    p_t2i = sub.add_parser("text2img", help="文生图：--prompt → 图片")
    p_t2i.add_argument("--prompt", required=True, help="图片生成 Prompt。")
    p_t2i.add_argument("--quality", help="同步模式质量参数，如 low/medium/high。")
    _add_common_output(p_t2i)
    p_t2i.set_defaults(func=cmd_text2img)

    p_i2i = sub.add_parser("img2img", help="图生图/图像编辑：--prompt + --image → 新图")
    p_i2i.add_argument("--prompt", required=True, help="编辑/改图指令 Prompt。")
    p_i2i.add_argument("--image", required=True, help="输入图片路径。")
    p_i2i.add_argument("--mask", help="可选遮罩图（仅 OpenAI 同步 /images/edits 局部编辑用）。")
    _add_common_output(p_i2i)
    p_i2i.set_defaults(func=cmd_img2img)

    p_var = sub.add_parser("variations", help="图像变体：--image → 多个变体")
    p_var.add_argument("--image", required=True, help="输入图片路径。")
    p_var.add_argument("--prompt", help="可选：异步模式下的变体引导 Prompt。")
    _add_common_output(p_var)
    p_var.set_defaults(func=cmd_variations)

    p_chk = sub.add_parser("check", help="离线校验配置状态（不发起请求）")
    p_chk.add_argument("--env-file", help="指定 .env；默认从当前目录向上查找。")
    p_chk.set_defaults(func=cmd_check)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if getattr(args, "output", None):
        args.output = str(validate_output_path(args.output))
    env_file = Path(args.env_file) if getattr(args, "env_file", None) else find_default_env_file()
    load_env_file(env_file)
    args.func(args)


if __name__ == "__main__":
    main()
