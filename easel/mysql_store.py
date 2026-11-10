"""MySQL storage for Easel's structured records.

EASEL_MYSQL_DSN is read from the project .env or the process environment.
The database and tables are created explicitly by ``python -m easel.mysql_store migrate``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from easel.direct_api import read_settings


def dsn() -> str:
    return read_settings().get("EASEL_MYSQL_DSN", "").strip()


def enabled() -> bool:
    return bool(dsn())


def connect():
    import pymysql

    url = urlsplit(dsn())
    if url.scheme != "mysql" or not url.hostname or not url.path.strip("/"):
        raise ValueError("EASEL_MYSQL_DSN 必须为 mysql://user:password@host:port/database")
    return pymysql.connect(host=url.hostname, port=url.port or 3306,
                           user=unquote(url.username or ""),
                           password=unquote(url.password or ""),
                           database=unquote(url.path.lstrip("/")), charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor, autocommit=False,
                           connect_timeout=5, read_timeout=10, write_timeout=10)


def _table(kind: str) -> str:
    if kind not in ("ideas", "schedule"):
        raise ValueError("Unknown record kind")
    return "easel_" + kind


def _decode(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def list_records(kind: str) -> list[dict]:
    table = _table(kind)
    order = "DESC" if kind == "ideas" else "ASC"
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {table} ORDER BY seq {order}")
            return [_decode(row["payload"]) for row in cur.fetchall()]


def get_record(kind: str, record_id: str) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {_table(kind)} WHERE id=%s", (record_id,))
            row = cur.fetchone()
            return _decode(row["payload"]) if row else None


def insert_record(kind: str, item: dict) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"INSERT INTO {_table(kind)} (id, payload) VALUES (%s, %s)",
                        (item["id"], json.dumps(item, ensure_ascii=False)))
        conn.commit()


def insert_missing(kind: str, items: list[dict]) -> None:
    """Import/append records without replacing concurrent writers' rows."""
    with connect() as conn:
        with conn.cursor() as cur:
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    cur.execute(f"INSERT IGNORE INTO {_table(kind)} (id, payload) VALUES (%s, %s)",
                                (item["id"], json.dumps(item, ensure_ascii=False)))
        conn.commit()


def update_record(kind: str, record_id: str, changes: dict) -> dict | None:
    table = _table(kind)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT payload FROM {table} WHERE id=%s FOR UPDATE", (record_id,))
            row = cur.fetchone()
            if not row:
                return None
            item = _decode(row["payload"])
            item.update(changes)
            cur.execute(f"UPDATE {table} SET payload=%s WHERE id=%s",
                        (json.dumps(item, ensure_ascii=False), record_id))
        conn.commit()
    return item


def delete_record(kind: str, record_id: str) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_table(kind)} WHERE id=%s", (record_id,))
            deleted = cur.rowcount > 0
        conn.commit()
    return deleted


def get_config() -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM easel_harness_config WHERE id=1")
            row = cur.fetchone()
            return _decode(row["payload"]) if row else {}


def save_config(config: dict) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO easel_harness_config (id, payload) VALUES (1, %s) "
                        "ON DUPLICATE KEY UPDATE payload=VALUES(payload)",
                        (json.dumps(config, ensure_ascii=False),))
        conn.commit()


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def get_binding(key: str) -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT runtime, native_id FROM easel_harness_sessions WHERE session_hash=%s",
                        (_digest(key),))
            return cur.fetchone() or {}


def save_binding(key: str, runtime: str, native_id: str) -> None:
    from easel.harnesses.base import HarnessError
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT runtime, native_id FROM easel_harness_sessions "
                        "WHERE session_hash=%s FOR UPDATE", (_digest(key),))
            current = cur.fetchone()
            if current and current["runtime"] != runtime:
                raise HarnessError("此会话属于其他 Agent 底座，请新建对话")
            if current and current["native_id"] and current["native_id"] != native_id:
                raise HarnessError("Agent 返回了不同的原生会话 ID，不会替换已有历史")
            cur.execute("INSERT INTO easel_harness_sessions (session_hash, runtime, native_id) "
                        "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE native_id=VALUES(native_id)",
                        (_digest(key), runtime, native_id))
        conn.commit()


def delete_binding(key: str) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM easel_harness_sessions WHERE session_hash=%s", (_digest(key),))
        conn.commit()


def migrate(root: Path) -> dict[str, int]:
    """Create tables and import legacy files once; existing MySQL rows win."""
    with connect() as conn:
        with conn.cursor() as cur:
            for kind in ("ideas", "schedule"):
                cur.execute(f"CREATE TABLE IF NOT EXISTS {_table(kind)} ("
                            "seq BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                            "id VARCHAR(128) NOT NULL UNIQUE, payload JSON NOT NULL) "
                            "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
            cur.execute("CREATE TABLE IF NOT EXISTS easel_harness_config ("
                        "id TINYINT NOT NULL PRIMARY KEY, payload JSON NOT NULL) "
                        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
            cur.execute("CREATE TABLE IF NOT EXISTS easel_harness_sessions ("
                        "session_hash CHAR(64) NOT NULL PRIMARY KEY, runtime VARCHAR(32) NOT NULL, "
                        "native_id VARCHAR(512) NOT NULL DEFAULT '') "
                        "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4")
        conn.commit()

    outputs = root / "outputs"
    counts = {}
    for kind in ("ideas", "schedule"):
        path = outputs / f"_{kind}.json"
        items = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        if not isinstance(items, list):
            raise ValueError(f"Invalid {path}")
        insert_missing(kind, list(reversed(items)) if kind == "ideas" else items)
        counts[kind] = len(items)
    config_path = outputs / "_harness" / "config.json"
    if config_path.is_file():
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT IGNORE INTO easel_harness_config (id, payload) VALUES (1, %s)",
                            (config_path.read_text(encoding="utf-8"),))
            conn.commit()
    counts["bindings"] = 0
    for path in (outputs / "_sessions" / "harness").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT IGNORE INTO easel_harness_sessions "
                            "(session_hash, runtime, native_id) VALUES (%s, %s, %s)",
                            (path.stem, data["runtime"], data.get("native_id", "")))
            conn.commit()
        counts["bindings"] += 1
    return counts


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] != "migrate":
        raise SystemExit("Usage: python -m easel.mysql_store migrate")
    if not enabled():
        raise SystemExit("Set EASEL_MYSQL_DSN first")
    print(json.dumps(migrate(Path(__file__).resolve().parents[1]), ensure_ascii=False))
