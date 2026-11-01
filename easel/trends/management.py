"""Local operator source management; browser requests never provide executable code/commands."""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from easel.timeouts import TIMEOUT_TREND_CONFIG_LOCK, TIMEOUT_TREND_SCRIPT_CHECK, TREND_POLL_INTERVAL

from .protocol import MAX_SCRIPT_BYTES, CollectorError, bounded_text, safe_json
from .sources import (LABELS, MAX_CONFIG_BYTES, ConfigError, _source, config_path,
                      display_label, load_sources, read_document)

_LOCK = threading.RLock()


@contextmanager
def _file_lock(path: Path):
    """Serialize writers across Web processes too; OS releases the lock on process exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a+b") as file:
        if file.seek(0, os.SEEK_END) == 0:
            file.write(b"0")
            file.flush()
        deadline = time.monotonic() + TIMEOUT_TREND_CONFIG_LOCK
        while True:
            try:
                file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConfigError("其他进程正在更新数据源，请稍后重试") from None
                time.sleep(TREND_POLL_INTERVAL)
        try:
            yield
        finally:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file, fcntl.LOCK_UN)


def script_catalog(root: Path) -> dict[str, dict]:
    rows = [
        {"id": "example", "label": "Python 采集示例", "script": str(root / "examples/trends/python_collector.py")},
        {"id": "hackernews", "label": "Hacker News", "script": str(root / "examples/trends/live_collector.py"),
         "args": ["--provider", "hackernews", "--limit", "20"]},
        {"id": "github-releases", "label": "GitHub CLI Releases", "script": str(root / "examples/trends/live_collector.py"),
         "args": ["--provider", "github", "--limit", "10"]},
    ]
    path = root / "config/trend-scripts.json"
    if path.is_file():
        try:
            with path.open("rb") as file:
                document = safe_json(file.read(MAX_CONFIG_BYTES + 1), MAX_CONFIG_BYTES)
            if (not isinstance(document, dict) or type(document.get("version")) is not int or document.get("version") != 1
                    or not isinstance(document.get("scripts"), list) or len(document["scripts"]) > 64):
                raise ValueError()
            for row in document["scripts"]:
                if not isinstance(row, dict):
                    raise ValueError()
                # Validate script paths/options using exactly the same collector schema.
                source = _source({**row, "type": "python"}, path.parent)
                rows.append({"id": source.id, "label": source.label,
                             **{key: value for key, value in source.options.items() if key != "memory_mb"}})
        except (ValueError, OSError, CollectorError):
            raise ConfigError("本地脚本登记文件无效，请修复 config/trend-scripts.json") from None
    return {row["id"]: row for row in rows if Path(row["script"]).is_file() and Path(row["script"]).suffix.lower() == ".py"}


def describe(root: Path, environment: dict[str, str]) -> dict:
    path = config_path(root, environment)
    document = read_document(path) if path.exists() else {"version": 1, "sources": []}
    warnings = []
    active = {s.id: s for s in load_sources(root, environment, warnings=warnings)}
    custom = {row["id"]: row for row in document.get("sources", [])
              if isinstance(row, dict) and isinstance(row.get("id"), str)
              and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", row["id"])}
    rows = []
    for identifier in dict.fromkeys([*LABELS, *custom]):
        source, raw = active.get(identifier), custom.get(identifier, {})
        kind = source.type if source else raw.get("type", "python")
        label = source.label if source else raw.get("label", LABELS.get(identifier, identifier))
        try:
            bounded_text(label, 80, empty=False)
        except CollectorError:
            label = "无效来源"
        rows.append({"id": identifier, "label": display_label(label[:80]) if isinstance(label, str) else "无效来源",
                     "type": kind if kind in ("python", "http", "rss") else "unknown",
                     "enabled": source is not None, "default": source.default if source else False,
                     "builtin": identifier in LABELS})
    try:
        scripts = [{"id": row["id"], "label": display_label(row["label"])} for row in script_catalog(root).values()]
    except ConfigError:
        scripts = []
        warnings.append("本地脚本登记无效，脚本选项已停用，订阅与 HTTP 来源仍可配置。")
    template = Path(__file__).with_name("template.py").read_text(encoding="utf-8")
    return {"sources": rows, "scripts": scripts, "warnings": warnings, "python_template": template,
            "script_max_bytes": MAX_SCRIPT_BYTES}


def _prepare_script(row: dict, value: dict, base: Path, environment: dict[str, str]) -> Path:
    name, code = value.get("script_name", "collector.py"), value.get("script_code")
    try:
        bounded_text(name, 128, empty=False)
        bounded_text(code, MAX_SCRIPT_BYTES, empty=False)
        if not name.lower().endswith(".py") or any(c in name for c in "/\\\r\n\t"):
            raise ValueError()
        raw = code.lstrip("\ufeff").encode("utf-8")
        if len(raw) > MAX_SCRIPT_BYTES:
            raise ValueError()
    except (CollectorError, ValueError, UnicodeError):
        raise ConfigError("请选择 UTF-8 的 .py 文件或填写代码，脚本上限为 64 KiB") from None
    directory = base / "trend-collectors"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (row["id"] + ".py")
    created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as file:
            file.write(raw)
        row.update(script=path.relative_to(base).as_posix(), script_name=name, uploaded_script=True)
        source = _source({**row, "timeout_seconds": TIMEOUT_TREND_SCRIPT_CHECK}, base)
        source.options["validate_only"] = True
        from .runner import collect
        collect(source, environment)  # compile only, in a limited worker; never import uploaded code here.
    except Exception as error:
        if created:
            path.unlink(missing_ok=True)
        if isinstance(error, CollectorError):
            raise ConfigError("Python 语法校验失败或校验进程不可用，请检查代码后重试") from None
        raise
    return path


def _owned_script(row: dict, base: Path) -> Path | None:
    if row.get("uploaded_script") is not True or not isinstance(row.get("script"), str):
        return None
    path = (base / row["script"]).resolve()
    if path.parent == (base / "trend-collectors").resolve() and path.name == row.get("id", "") + ".py":
        return path
    return None


def _write(path: Path, document: dict):
    # Preserve an unrelated malformed row as escaped JSON so it can still be removed via the manager.
    encoded = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8", "backslashreplace")
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ConfigError("数据源配置超过 128 KiB 限制")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".trend-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def update(root: Path, environment: dict[str, str], value: dict) -> dict:
    with _LOCK, _file_lock(config_path(root, environment)):
        path = config_path(root, environment)
        document = read_document(path) if path.exists() else {"version": 1, "include_builtin": True, "sources": []}
        rows = document.setdefault("sources", [])
        action = value.get("action")
        identifier = value.get("id")
        created, cleanup = None, None
        if action == "add":
            if len(rows) >= 64:
                raise ConfigError("最多配置 64 个自定义来源")
            kind, label = value.get("type"), value.get("label")
            try:
                bounded_text(label, 80, empty=False)
            except CollectorError:
                raise ConfigError("请输入 1–80 字符的来源名称") from None
            row = {"id": "custom-" + uuid.uuid4().hex[:12], "type": kind, "label": display_label(label),
                   "default": True, "refresh_seconds": value.get("refresh_seconds", 300)}
            if kind == "python":
                if "script_code" in value:
                    created = _prepare_script(row, value, path.parent, environment)
                else:
                    selected = script_catalog(root).get(value.get("script_id")) if isinstance(value.get("script_id"), str) else None
                    if selected is None:
                        raise ConfigError("请选择 .py 文件或填写采集代码，不能指定任意命令或解释器")
                    row.update({key: item for key, item in selected.items() if key not in ("id", "label")})
            elif kind in ("http", "rss"):
                row["url"] = value.get("url")
                if kind == "http":
                    row["method"] = value.get("method", "GET")
                    if row["method"] == "POST":
                        row["body"] = value.get("body", {})
                row["headers"] = value.get("headers", {})
            else:
                raise ConfigError("请选择 RSS / Atom、HTTP 或本地脚本")
            _source(row, path.parent)
            rows.append(row)
            identifier = row["id"]
        elif action in ("toggle", "delete") and isinstance(identifier, str):
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", identifier):
                raise ConfigError("无效的数据源 ID")
            existing = next((row for row in rows if isinstance(row, dict) and row.get("id") == identifier), None)
            if existing is None and identifier not in LABELS:
                raise ConfigError("数据源不存在，请刷新列表")
            if action == "delete":
                if identifier in LABELS:
                    raise ConfigError("内置来源可停用，不能删除")
                cleanup = _owned_script(existing, path.parent)
                rows[:] = [row for row in rows if not isinstance(row, dict) or row.get("id") != identifier]
            else:
                enabled = value.get("enabled")
                if type(enabled) is not bool:
                    raise ConfigError("enabled 必须是布尔值")
                if identifier in LABELS and enabled and (existing is None or set(existing) <= {"id", "enabled"}):
                    rows[:] = [row for row in rows if not isinstance(row, dict) or row.get("id") != identifier]
                    # Re-enabling an individual builtin when the global switch is off.
                    if not document.get("include_builtin", True):
                        builtin = {"id": identifier, "label": LABELS[identifier], "type": "python",
                                   "script": str(Path(__file__).with_name("builtin.py")), "args": [identifier]}
                        rows.append(builtin)
                elif existing is None:
                    rows.append({"id": identifier, "enabled": enabled})
                else:
                    existing["enabled"] = enabled
                    if enabled:
                        _source(existing, path.parent)
        else:
            raise ConfigError("无效的数据源操作")
        try:
            _write(path, document)
        except Exception:
            if created is not None:
                created.unlink(missing_ok=True)
            raise
        if cleanup is not None:
            try:
                cleanup.unlink(missing_ok=True)
            except OSError:
                pass  # The reference was removed atomically; a locked orphan never executes again.
        return {"ok": True, "id": identifier}
