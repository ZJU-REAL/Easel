"""The wire contract shared by every collector (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 500
MAX_URL = 8192
MAX_SCRIPT_BYTES = 64 * 1024
MAX_MANAGEMENT_BYTES = 256 * 1024
MAX_WORKER_REQUEST_BYTES = 256 * 1024


def bounded_text(value: object, maximum: int, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise CollectorError("invalid_response")
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise CollectorError("invalid_response") from None
    if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise CollectorError("invalid_response")
    return value


def safe_json(raw: bytes, maximum: int = MAX_BYTES):
    """Reject deep documents, duplicate keys, non-finite numbers and oversized integers."""
    if len(raw) > maximum:
        raise CollectorError("output_too_large")
    depth, quoted, escaped = 0, False, False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 24:
                raise CollectorError("invalid_response")
        elif byte in (93, 125):
            depth -= 1
    def pairs(rows):
        obj = {}
        for key, value in rows:
            if key in obj:
                raise ValueError("duplicate key")
            obj[key] = value
        return obj
    def integer(text):
        if len(text) > 32:
            raise ValueError("integer too large")
        return int(text)
    def number(text):
        result = float(text)
        if not math.isfinite(result):
            raise ValueError("non-finite number")
        return result
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_int=integer,
                          parse_float=number, parse_constant=lambda _: number("nan"))
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise CollectorError("invalid_response") from None


class CollectorError(Exception):
    """Only this safe code, never raw collector output/credentials, reaches the UI."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def timestamp(value: object) -> float:
    if not isinstance(value, str) or len(value) > 64:
        raise CollectorError("invalid_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or not 1970 <= parsed.year <= 9999:
            raise ValueError("timezone required")
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        raise CollectorError("invalid_response") from None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def web_url(value: object, *, optional: bool = False) -> str:
    if optional and (value is None or value == ""):
        return ""
    try:
        bounded_text(value, MAX_URL, empty=False)
        if any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
            raise ValueError("invalid URL")
        url = urlsplit(value)
        if (url.scheme not in ("http", "https") or not url.hostname or url.port == 0
                or url.username is not None or url.password is not None):
            raise ValueError("invalid URL")
        return value
    except ValueError:
        raise CollectorError("invalid_response") from None


def decode_payload(raw: bytes) -> dict:
    return validate_payload(safe_json(raw))


def validate_payload(value: object) -> dict:
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise CollectorError("invalid_response")
    timestamp(value.get("fetched_at"))
    items = value.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise CollectorError("invalid_response")
    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise CollectorError("invalid_response")
        title = bounded_text(item.get("title"), 1000, empty=False)
        title = title.strip()
        url = web_url(item.get("url"), optional=True)
        identifier = item.get("id")
        if identifier is None:
            identifier = hashlib.sha256((url or title).encode("utf-8")).hexdigest()[:24]
        bounded_text(identifier, 512, empty=False)
        published = item.get("published_at")
        if published is not None:
            timestamp(published)
        heat = item.get("heat", {})
        if not isinstance(heat, dict):
            raise CollectorError("invalid_response")
        number = heat.get("value")
        if number is not None and (type(number) not in (int, float) or abs(number) > 9_007_199_254_740_991
                                   or not math.isfinite(number)):
            raise CollectorError("invalid_response")
        text, unit = heat.get("text", ""), heat.get("unit", "")
        bounded_text(text, 128)
        bounded_text(unit, 32)
        if identifier in seen:
            continue
        seen.add(identifier)
        normalized.append({"id": identifier, "title": title, "url": url,
                           "published_at": published,
                           "heat": {"value": number, "text": text, "unit": unit},
                           "hot": text or (str(number) if number is not None else "")})
    return {"version": 1, "fetched_at": value["fetched_at"], "items": normalized}
