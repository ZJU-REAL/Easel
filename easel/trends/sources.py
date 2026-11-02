"""Load trusted, local-only collector configuration; never accept commands over HTTP."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from easel.timeouts import TIMEOUT_TREND_COLLECT, TIMEOUT_TREND_MAX

from .protocol import CollectorError, bounded_text, safe_json, web_url

MAX_CONFIG_BYTES = 128 * 1024


def display_label(label: str) -> str:
    return re.sub(r"(?:\s*[·•|]\s*(?:python|http|rss|atom))+$", "", label.strip(), flags=re.I).strip() or "未命名来源"


def config_path(root: Path, environment: dict[str, str]) -> Path:
    configured = environment.get("EASEL_TREND_SOURCES_CONFIG", "").strip()
    return (root / configured).resolve() if configured else root / "config" / "trend-sources.json"


def read_document(path: Path) -> dict:
    try:
        with path.open("rb") as file:
            document = safe_json(file.read(MAX_CONFIG_BYTES + 1), MAX_CONFIG_BYTES)
    except (OSError, CollectorError):
        raise ConfigError("热点数据源配置无法读取或超过 128 KiB 限制") from None
    if (not isinstance(document, dict) or type(document.get("version")) is not int
            or document["version"] != 1 or not isinstance(document.get("sources", []), list)
            or len(document.get("sources", [])) > 64):
        raise ConfigError("配置需要 version: 1 和最多 64 项的 sources 数组")
    _boolean(document, "include_builtin", True)
    return document

LABELS = {"weibo": "微博", "douyin": "抖音", "zhihu": "知乎",
          "bilibili": "B站", "baidu": "百度", "toutiao": "头条"}


class ConfigError(ValueError):
    pass


@dataclass
class Source:
    id: str
    label: str
    type: str
    default: bool
    timeout: float
    refresh: float
    max_stale: float
    options: dict

    def public(self) -> dict:
        return {"id": self.id, "label": display_label(self.label), "type": self.type,
                "default": self.default, "refresh_seconds": self.refresh}

    def cache_key(self, environment: dict[str, str]) -> str:
        # Changes to credentials, interpreter, script or configuration invalidate cached results.
        stamp = None
        if self.type == "python":
            try:
                stat = Path(self.options["script"]).stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                pass
        raw = json.dumps([self.__dict__, environment, stamp], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


def _expand(value: object, environment: dict[str, str]) -> object:
    if isinstance(value, str):
        def replace(match):
            name = match.group(1)
            if not environment.get(name):
                raise CollectorError("missing_environment")
            return environment[name]
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)
    if isinstance(value, list):
        return [_expand(item, environment) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item, environment) for key, item in value.items()}
    return value


def expanded_options(source: Source, environment: dict[str, str]) -> dict:
    return _expand(source.options, environment)


def _number(row: dict, key: str, default: float, low: float, high: float) -> float:
    value = row.get(key, default)
    if type(value) not in (int, float) or not low <= value <= high:
        raise ConfigError(f"{key} 必须在 {low:g} 到 {high:g} 之间")
    return float(value)


def _boolean(row: dict, key: str, default: bool) -> bool:
    value = row.get(key, default)
    if type(value) is not bool:
        raise ConfigError(f"{key} 必须为布尔值")
    return value


def _strings(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str)
                                          for k, v in value.items())


def _source(row: dict, base: Path) -> Source:
    identifier, label, kind = row.get("id"), row.get("label"), row.get("type")
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier):
        raise ConfigError("数据源 id 只能包含小写字母、数字、下划线或连字符（1–64 字符）")
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise ConfigError(f"数据源 {identifier} 缺少有效 label")
    try:
        bounded_text(label, 80, empty=False)
    except CollectorError:
        raise ConfigError(f"数据源 {identifier} 的名称包含无效字符") from None
    if kind not in ("python", "http", "rss"):
        raise ConfigError(f"数据源 {identifier} 的 type 必须是 python、http 或 rss")
    refresh = _number(row, "refresh_seconds", 300, 1, 86400)
    stale = _number(row, "max_stale_seconds", 86400, refresh, 604800)
    options = {key: row[key] for key in ("script", "python", "args", "env", "url", "method", "headers", "body")
               if key in row}
    options["memory_mb"] = _number(row, "memory_mb", 256, 64, 512)
    if not _strings(options.get("env", {})):
        raise ConfigError(f"数据源 {identifier} 的 env 必须是字符串映射")
    for mapping in (options.get("env", {}), options.get("headers", {})):
        if not _strings(mapping) or len(mapping) > 32 or any(len(k) > 128 or len(v) > 8192 for k, v in mapping.items()):
            raise ConfigError(f"数据源 {identifier} 的环境变量或请求头过多或过长")
    if any(not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or any(ord(c) < 32 or ord(c) == 127 for c in value)
           for key, value in options.get("headers", {}).items()):
        raise ConfigError(f"数据源 {identifier} 的请求头包含无效字符")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\x00" in value
           for key, value in options.get("env", {}).items()):
        raise ConfigError(f"数据源 {identifier} 的环境变量包含无效字符")
    if kind == "python":
        script = options.get("script")
        if not isinstance(script, str) or not script or len(script) > 2048 or "${" in script or "\x00" in script:
            raise ConfigError(f"数据源 {identifier} 需要固定的本地 script 路径")
        options["script"] = str((base / script).resolve())
        interpreter = options.setdefault("python", sys.executable)
        if not isinstance(interpreter, str) or not interpreter or len(interpreter) > 2048 or "${" in interpreter or "\x00" in interpreter:
            raise ConfigError(f"数据源 {identifier} 的 python 必须为解释器路径或名称")
        if "/" in interpreter or "\\" in interpreter:
            options["python"] = str((base / interpreter).resolve())
        args = options.setdefault("args", [])
        if (not isinstance(args, list) or len(args) > 32
                or not all(isinstance(arg, str) and len(arg) <= 2048 and "\x00" not in arg for arg in args)):
            raise ConfigError(f"数据源 {identifier} 的 args 必须是字符串数组")
    else:
        try:
            web_url(options.get("url"))
        except CollectorError:
            raise ConfigError(f"数据源 {identifier} 需要不含账号密码的 HTTP(S) URL") from None
        method = options.setdefault("method", "GET")
        if method not in ("GET", "POST") or not _strings(options.get("headers", {})):
            raise ConfigError(f"数据源 {identifier} 需要 GET/POST 和字符串 headers")
        if method == "GET" and "body" in options:
            raise ConfigError(f"数据源 {identifier} 的 GET 不能包含 body")
        if kind == "rss" and method != "GET":
            raise ConfigError(f"RSS 数据源 {identifier} 只支持 GET")
    return Source(identifier, label.strip(), kind, _boolean(row, "default", True),
                  _number(row, "timeout_seconds", TIMEOUT_TREND_COLLECT, 0.1, TIMEOUT_TREND_MAX), refresh, stale, options)


def load_sources(root: Path, environment: dict[str, str], *, warnings: list[str] | None = None) -> list[Source]:
    configured = environment.get("EASEL_TREND_SOURCES_CONFIG", "").strip()
    path = config_path(root, environment)
    document = {}
    if path.is_file():
        document = read_document(path)
    elif configured:
        raise ConfigError("EASEL_TREND_SOURCES_CONFIG 指定的文件不存在")
    rows = document.get("sources", [])
    if not isinstance(rows, list) or len(rows) > 64:
        raise ConfigError("sources 必须为数组，最多 64 个数据源")
    registry = {}
    if _boolean(document, "include_builtin", True):
        for identifier, label in LABELS.items():
            row = {"id": identifier, "label": label, "type": "python",
                   "script": str(Path(__file__).with_name("builtin.py")), "args": [identifier],
                   "default": identifier in ("weibo", "douyin", "zhihu")}
            registry[identifier] = _source(row, root)
    seen = set()
    for index, row in enumerate(rows):
        try:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ConfigError("每个数据源必须是包含 id 的对象")
            identifier = row["id"]
            if identifier in seen:
                raise ConfigError("数据源 ID 重复")
            seen.add(identifier)
            enabled = _boolean(row, "enabled", True)
            if not enabled:
                registry.pop(identifier, None)
                continue
            registry[identifier] = _source(row, path.parent)
        except (ValueError, TypeError, OSError, OverflowError):
            if warnings is None:
                raise ConfigError(f"第 {index + 1} 项数据源配置无效") from None
            warnings.append(f"第 {index + 1} 项数据源配置无效，已跳过，其余来源继续工作。")
    return list(registry.values())
