"""Durable per-turn metadata; this module never starts or replays an agent.

Callers still need the runtime's session lock before starting execution. SQLite
ownership/version checks protect metadata, not remote tools or side effects.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import sqlite3

from easel.timeouts import TIMEOUT_RUN_STORE


SCHEMA_VERSION = 2
BACKENDS = frozenset({"openclaw", "direct_api", "codex", "opencode", "acp"})
_FINAL = frozenset({"succeeded", "failed", "cancelled", "interrupted", "unknown"})
_TRANSITIONS = {"queued": {"running", "failed", "cancelled"}, "running": _FINAL}


class RunConflict(RuntimeError):
    """Duplicate identity, stale revision, wrong owner or occupied session."""


class InvalidTransition(ValueError):
    """The requested state change is not supported."""


class UnsupportedSchema(RuntimeError):
    """The database requires another schema version; do not overwrite it."""


@dataclass(frozen=True)
class RunRecord:
    turn_id: str
    session_id: str
    backend: str
    state: str
    version: int
    owner_id: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    result_refs: tuple[str, ...]


def _identifier(value: str) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > 512
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Identifiers must contain 1-512 characters without control characters")


def _references(values) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("result_refs must be a sequence of relative output paths")
    refs = tuple(values)
    for ref in refs:
        if (not isinstance(ref, str) or not ref or len(ref) > 2048
                or "\\" in ref or ":" in ref or any(ord(c) < 32 for c in ref)
                or PurePosixPath(ref).is_absolute()
                or any(part in ("", ".", "..") for part in ref.split("/"))):
            raise ValueError("Result references must be relative paths below outputs")
    return refs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _record(row: sqlite3.Row) -> RunRecord:
    values = dict(row)
    values["result_refs"] = tuple(json.loads(values["result_refs"]))
    return RunRecord(**values)


class RunStore:
    """Small local SQLite ledger with atomic, revision-checked state changes.

    Use a dedicated file on a local filesystem. Connections are short lived,
    so instances do not share connections across threads or child processes.
    Errors (including disk-full, corruption and lock timeout) propagate: callers
    must not claim a checkpoint was saved when its commit failed.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(initialize=True, write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version in (0, 1):
                if version == 0 and db.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone():
                    raise UnsupportedSchema("Unversioned database is not an empty run store")
                if version == 1:
                    # Rebuild the CHECK constraint transactionally. Old readers
                    # reject v2 rather than writing through a changed schema.
                    db.execute("ALTER TABLE runs RENAME TO runs_v1")
                    db.execute("DROP INDEX runs_session")
                    db.execute("DROP INDEX runs_active_session")
                db.execute("""
                    CREATE TABLE runs (
                        turn_id TEXT PRIMARY KEY NOT NULL,
                        session_id TEXT NOT NULL,
                        backend TEXT NOT NULL CHECK (backend IN
                            ('openclaw', 'direct_api', 'codex', 'opencode', 'acp')),
                        state TEXT NOT NULL CHECK (state IN
                            ('queued','running','succeeded','failed','cancelled','interrupted','unknown')),
                        version INTEGER NOT NULL CHECK (version > 0),
                        owner_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        result_refs TEXT NOT NULL,
                        CHECK (state != 'running' OR owner_id IS NOT NULL)
                    )
                """)
                db.execute("CREATE INDEX runs_session ON runs(session_id, created_at, turn_id)")
                db.execute("CREATE UNIQUE INDEX runs_active_session ON runs(session_id) "
                           "WHERE state='running'")
                if version == 1:
                    db.execute("INSERT INTO runs SELECT * FROM runs_v1")
                    db.execute("DROP TABLE runs_v1")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION:
                raise UnsupportedSchema("Unsupported run-store schema version")
            db.commit()

    @contextmanager
    def _connection(self, *, initialize: bool = False, write: bool = False):
        db = sqlite3.connect(self.path, timeout=TIMEOUT_RUN_STORE, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            # Rollback journal + FULL sync: a transaction is either wholly
            # committed or rolled back when a process disappears mid-write.
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            # Version and data must be read in the same transaction: a schema
            # upgrade by another process cannot slip between check and update.
            if not initialize and db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise UnsupportedSchema("Unsupported run-store schema version")
            yield db
        finally:
            # Closing an uncommitted connection rolls back, including on a
            # BaseException. No long-lived connection survives process forks.
            db.close()

    def create(self, turn_id: str, session_id: str, backend: str) -> RunRecord:
        _identifier(turn_id)
        _identifier(session_id)
        if backend not in BACKENDS:
            raise ValueError("Unsupported agent backend")
        stamp = _now()
        with self._connection(write=True) as db:
            try:
                db.execute("INSERT INTO runs VALUES (?, ?, ?, 'queued', 1, NULL, ?, ?, NULL, NULL, '[]')",
                           (turn_id, session_id, backend, stamp, stamp))
            except sqlite3.IntegrityError as exc:
                raise RunConflict("Turn identity already exists") from exc
            row = db.execute("SELECT * FROM runs WHERE turn_id=?", (turn_id,)).fetchone()
            db.commit()
        return _record(row)

    def get(self, turn_id: str) -> RunRecord | None:
        with self._connection() as db:
            row = db.execute("SELECT * FROM runs WHERE turn_id=?", (turn_id,)).fetchone()
        return _record(row) if row is not None else None

    def for_session(self, session_id: str) -> list[RunRecord]:
        with self._connection() as db:
            rows = db.execute("SELECT * FROM runs WHERE session_id=? ORDER BY created_at, turn_id",
                              (session_id,)).fetchall()
        return [_record(row) for row in rows]

    def transition(self, turn_id: str, *, expected_version: int, state: str,
                   owner_id: str | None = None, result_refs=()) -> RunRecord:
        """Compare-and-swap a state under a SQLite write transaction.

        Starting requires an owner ID; finishing a running turn requires that
        same ID. Terminal states, including unknown, cannot restart execution.
        interrupted requires evidence that execution stopped; loss of contact
        alone is unknown. Reopening the store never infers either state.
        """
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("expected_version must be a positive integer")
        if owner_id is not None:
            _identifier(owner_id)
        refs = _references(result_refs)
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM runs WHERE turn_id=?", (turn_id,)).fetchone()
            if row is None:
                raise KeyError(turn_id)
            current = _record(row)
            if current.version != expected_version:
                raise RunConflict("Stale run revision")
            if state not in _TRANSITIONS.get(current.state, ()):
                raise InvalidTransition("Unsupported run state transition")
            if current.state == "running" and owner_id != current.owner_id:
                raise RunConflict("Run is owned by another executor")
            if state == "running" and owner_id is None:
                raise InvalidTransition("Starting a run requires an owner")
            if current.state == "queued" and state != "running" and owner_id is not None:
                raise InvalidTransition("Queued termination has no executor owner")
            if refs and state not in _FINAL:
                raise InvalidTransition("Result references require a terminal state")
            stamp = _now()
            started = stamp if state == "running" else current.started_at
            finished = stamp if state in _FINAL - {"unknown"} else None
            try:
                db.execute("""UPDATE runs SET state=?, version=version+1, owner_id=?,
                              updated_at=?, started_at=?, finished_at=?, result_refs=?
                              WHERE turn_id=? AND version=?""",
                           (state, owner_id, stamp, started, finished,
                            json.dumps(refs, ensure_ascii=False), turn_id, expected_version))
            except sqlite3.IntegrityError as exc:
                raise RunConflict("Session already has a running turn") from exc
            updated = db.execute("SELECT * FROM runs WHERE turn_id=?", (turn_id,)).fetchone()
            db.commit()
        return _record(updated)
