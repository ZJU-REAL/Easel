"""Shared caching, single-flight collection and public status for every transport."""
from __future__ import annotations

import threading
import time
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from easel.timeouts import TIMEOUT_TREND_BUSY_WAIT, TIMEOUT_TREND_BUSY_RETRY, TIMEOUT_TREND_FAILURE_RETRY

from .protocol import MAX_BYTES, CollectorError, timestamp, validate_payload
from .runner import collect
from .sources import Source, display_label

ERROR_MESSAGES = {
    "timeout": "采集超时，请检查数据源服务或脚本",
    "start_failed": "无法启动采集脚本，请检查脚本和 Python 解释器路径",
    "process_failed": "采集脚本执行失败，请在本地运行脚本检查日志",
    "invalid_response": "采集结果不符合热点数据协议 v1",
    "invalid_feed": "无法解析 RSS/Atom 订阅，请检查订阅地址和格式",
    "output_too_large": "采集输出超过 2 MiB 限制",
    "http_failed": "HTTP 数据源请求失败，请检查地址、鉴权和网络",
    "missing_environment": "数据源引用的环境变量未设置",
    "expired_data": "数据源返回的数据已超过最大保留时间",
    "collector_failed": "数据源采集失败，请检查采集配置",
    "resource_limit": "采集器超过资源限制或异常退出，其余来源不受影响",
    "isolation_failed": "无法建立采集隔离，已停止执行，请检查本地运行环境",
    "busy": "采集器正在工作，请稍后刷新",
    "invalid_script": "Python 脚本语法校验失败，请检查代码",
}


@dataclass
class _Entry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    payload: dict | None = None
    attempted_at: float = 0
    error: str | None = None
    size: int = 0


def failure_group(source: Source, code: str = "collector_failed") -> dict:
    return {"platform": source.id, "label": display_label(source.label), "items": [], "ok": False,
            "status": "error", "stale": False, "fetched_at": None, "last_attempt_at": 0,
            "error": {"code": code, "message": ERROR_MESSAGES.get(code, ERROR_MESSAGES["collector_failed"])}}


class TrendService:
    def __init__(self):
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(4)

    def get(self, source: Source, environment: dict[str, str], limit: int = 12) -> dict:
        try:
            return self._get(source, environment, max(1, min(int(limit), 30)))
        except Exception:
            return failure_group(source)

    def _get(self, source: Source, environment: dict[str, str], limit: int) -> dict:
        key = source.cache_key(environment)
        with self._lock:
            entry = self._entries.setdefault(key, _Entry())
            self._entries.move_to_end(key)
            # Bound memory when a local config or environment is edited repeatedly.
            if len(self._entries) > 96:
                self._entries.popitem(last=False)
        if not entry.lock.acquire(timeout=TIMEOUT_TREND_BUSY_WAIT):
            return self._render(source, entry, limit, "busy")
        try:
            now = time.time()
            # Failures are retried after at most 30s, rather than on every page request.
            retry = TIMEOUT_TREND_BUSY_RETRY if entry.error == "busy" else min(source.refresh, TIMEOUT_TREND_FAILURE_RETRY) if entry.error else source.refresh
            if not entry.attempted_at or now - entry.attempted_at >= retry:
                try:
                    if not self._slots.acquire(timeout=TIMEOUT_TREND_BUSY_WAIT):
                        raise CollectorError("busy")
                    try:
                        payload = validate_payload(collect(source, environment))
                    finally:
                        self._slots.release()
                    now = time.time()
                    fetched = timestamp(payload["fetched_at"])
                    if fetched > now + 300:
                        raise CollectorError("invalid_response")
                    if now - fetched > source.max_stale:
                        raise CollectorError("expired_data")
                    size = len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"))
                    if size > MAX_BYTES:
                        raise CollectorError("output_too_large")
                    entry.payload, entry.error, entry.size = payload, None, size
                    with self._lock:
                        total = sum(item.size for item in self._entries.values())
                        for old_key, old in list(self._entries.items()):
                            if total <= 16 * 1024 * 1024:
                                break
                            if old is not entry and not old.lock.locked():
                                total -= old.size
                                self._entries.pop(old_key, None)
                except CollectorError as error:
                    entry.error = error.code
                except Exception:
                    # Never return exception strings containing headers, tokens or stderr.
                    entry.error = "collector_failed"
                entry.attempted_at = time.time()
            return self._render(source, entry, limit)
        finally:
            entry.lock.release()

    def _render(self, source: Source, entry: _Entry, limit: int, override: str | None = None) -> dict:
        now = time.time()
        payload = entry.payload
        fetched = timestamp(payload["fetched_at"]) if payload else None
        usable = payload is not None and now - fetched <= source.max_stale
        stale = usable and (override is not None or entry.error is not None or now - fetched >= source.refresh)
        error = override or entry.error or ("expired_data" if payload and not usable else None)
        return {"platform": source.id, "label": display_label(source.label), "items": payload["items"][:limit] if usable else [],
                "ok": usable, "status": "stale" if stale else "fresh" if usable else "error",
                "stale": bool(stale), "fetched_at": payload["fetched_at"] if payload else None,
                "last_attempt_at": int(entry.attempted_at),
                "error": {"code": error, "message": ERROR_MESSAGES.get(error, ERROR_MESSAGES["collector_failed"])}
                if error else None}
