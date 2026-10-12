"""Durability and contention tests use only temporary local SQLite files."""
from dataclasses import FrozenInstanceError
import multiprocessing
from pathlib import Path
import sqlite3

import pytest

from easel.run_store import InvalidTransition, RunConflict, RunStore, UnsupportedSchema
from easel import run_store


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "sessions" / "runs.sqlite3")


def test_restart_preserves_each_turn_and_exact_session_identity(store):
    first = store.create("turn/一", "session/a", "openclaw")
    store.create("turn_一", "session_a", "direct_api")
    store.create("next", "session/a", "openclaw")
    running = store.transition(first.turn_id, expected_version=1, state="running", owner_id="owner")
    done = store.transition(first.turn_id, expected_version=2, state="succeeded",
                            owner_id="owner", result_refs=["project/成品.md"])
    reopened = RunStore(store.path)
    assert reopened.get(first.turn_id) == done
    assert done.version == 3 and done.started_at == running.started_at
    assert done.finished_at and done.created_at == first.created_at
    assert done.result_refs == ("project/成品.md",)
    assert {r.turn_id for r in reopened.for_session("session/a")} == {"turn/一", "next"}
    assert len(reopened.for_session("session_a")) == 1
    assert reopened.get("absent") is None
    with pytest.raises(FrozenInstanceError):
        done.state = "running"


def test_duplicate_turn_cannot_overwrite_identity_or_progress(store):
    queued = store.create("turn", "session", "openclaw")
    with pytest.raises(RunConflict):
        store.create("turn", "other", "direct_api")
    assert store.get("turn") == queued


def test_stale_revision_and_wrong_executor_cannot_finish(store):
    store.create("turn", "session", "openclaw")
    running = store.transition("turn", expected_version=1, state="running", owner_id="owner")
    for version, owner in [(1, "owner"), (2, "other"), (2, None)]:
        with pytest.raises(RunConflict):
            store.transition("turn", expected_version=version, state="succeeded", owner_id=owner)
        assert store.get("turn") == running


@pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled", "interrupted", "unknown"])
def test_terminal_records_never_automatically_restart(store, state):
    store.create("turn", "session", "openclaw")
    store.transition("turn", expected_version=1, state="running", owner_id="owner")
    final = store.transition("turn", expected_version=2, state=state, owner_id="owner")
    assert (final.finished_at is None) == (state == "unknown")
    with pytest.raises(InvalidTransition):
        store.transition("turn", expected_version=3, state="running", owner_id="new-owner")
    assert RunStore(store.path).get("turn") == final


def test_reopening_does_not_declare_an_existing_executor_dead(store):
    store.create("turn", "session", "openclaw")
    running = store.transition("turn", expected_version=1, state="running", owner_id="other-process")
    assert RunStore(store.path).get("turn") == running


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_queued_task_can_finish_without_claiming_an_executor(store, state):
    store.create("turn", "session", "direct_api")
    result = store.transition("turn", expected_version=1, state=state)
    assert result.owner_id is None and result.started_at is None
    assert result.finished_at is not None


@pytest.mark.parametrize("state,owner,refs", [
    ("succeeded", None, ()), ("running", None, ()), ("cancelled", "owner", ()),
    ("running", "owner", ("project/result.md",)), ("invented", None, ()),
])
def test_invalid_transitions_are_atomic(store, state, owner, refs):
    before = store.create("turn", "session", "openclaw")
    with pytest.raises(InvalidTransition):
        store.transition("turn", expected_version=1, state=state, owner_id=owner, result_refs=refs)
    assert store.get("turn") == before


@pytest.mark.parametrize("ref", ["/tmp/result", "../result", "a/../b", "C:/result", "a\\b", "a//b", "", "a\x00b"])
def test_result_references_cannot_escape_outputs(store, ref):
    store.create("turn", "session", "openclaw")
    before = store.transition("turn", expected_version=1, state="running", owner_id="owner")
    with pytest.raises(ValueError):
        store.transition("turn", expected_version=2, state="succeeded", owner_id="owner", result_refs=[ref])
    assert store.get("turn") == before


def test_result_references_are_not_treated_as_files_to_open(store):
    store.create("turn", "session", "openclaw")
    store.transition("turn", expected_version=1, state="running", owner_id="owner")
    result = store.transition("turn", expected_version=2, state="succeeded", owner_id="owner",
                              result_refs=["not-created/result.md"])
    assert result.result_refs == ("not-created/result.md",)
    assert not (store.path.parent / "not-created").exists()


def test_same_session_serializes_running_records_but_other_sessions_are_independent(store):
    for turn, session in [("one", "same"), ("two", "same"), ("other", "other")]:
        store.create(turn, session, "openclaw")
    store.transition("one", expected_version=1, state="running", owner_id="owner-1")
    with pytest.raises(RunConflict):
        store.transition("two", expected_version=1, state="running", owner_id="owner-2")
    assert store.get("two").state == "queued"
    store.transition("other", expected_version=1, state="running", owner_id="owner-3")
    store.transition("one", expected_version=2, state="succeeded", owner_id="owner-1")
    assert store.transition("two", expected_version=1, state="running", owner_id="owner-2").version == 2


def test_future_and_unversioned_databases_are_not_replaced(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE future (value TEXT)")
        db.execute("INSERT INTO future VALUES ('keep')")
        db.execute("PRAGMA user_version=2")
    with pytest.raises(UnsupportedSchema):
        RunStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM future").fetchone()[0] == "keep"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        db.execute("PRAGMA user_version=0")
    with pytest.raises(UnsupportedSchema):
        RunStore(path)


def test_corruption_is_reported_not_silently_reinitialized(tmp_path):
    path = tmp_path / "broken.sqlite3"
    content = b"not a sqlite database" * 100
    path.write_bytes(content)
    with pytest.raises(sqlite3.DatabaseError):
        RunStore(path)
    assert path.read_bytes() == content


def test_unversioned_database_with_only_a_view_is_not_adopted(tmp_path):
    path = tmp_path / "foreign.sqlite3"
    db = sqlite3.connect(path)
    try:
        db.execute("CREATE VIEW foreign_view AS SELECT 1 AS value")
        db.commit()
        with pytest.raises(UnsupportedSchema):
            RunStore(path)
        assert db.execute("SELECT value FROM foreign_view").fetchone()[0] == 1
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        db.close()


def test_existing_instance_refuses_newer_schema(store):
    store.create("turn", "session", "openclaw")
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(UnsupportedSchema):
        store.get("turn")
    with pytest.raises(UnsupportedSchema):
        store.transition("turn", expected_version=1, state="running", owner_id="owner")
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT state, version FROM runs").fetchone() == ("queued", 1)


def test_commit_failure_rolls_back_and_is_reported(store, monkeypatch):
    before = store.create("turn", "session", "openclaw")
    original_connect = sqlite3.connect

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected disk write failure")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", lambda *a, **kw: original_connect(*a, factory=FailingCommit, **kw))
        with pytest.raises(sqlite3.OperationalError, match="disk write failure"):
            store.transition("turn", expected_version=1, state="running", owner_id="owner")
    assert RunStore(store.path).get("turn") == before


def test_database_contention_times_out_without_partial_update(store, monkeypatch):
    before = store.create("turn", "session", "openclaw")
    monkeypatch.setattr(run_store, "TIMEOUT_RUN_STORE", 0)
    writer = sqlite3.connect(store.path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store.transition("turn", expected_version=1, state="running", owner_id="owner")
    finally:
        writer.close()
    assert store.get("turn") == before


def _contending_writer(path, turn, owner, gate, pipe):
    try:
        store = RunStore(path)
        pipe.send("ready")
        if not gate.wait(10):
            raise TimeoutError("start gate")
        try:
            result = store.transition(turn, expected_version=1, state="running", owner_id=owner)
            pipe.send(("ok", result.owner_id))
        except RunConflict:
            pipe.send(("conflict", owner))
    finally:
        pipe.close()


@pytest.mark.parametrize("same_turn", [True, False])
def test_competing_processes_cannot_both_claim_a_turn_or_session(store, same_turn):
    store.create("one", "session", "openclaw")
    if not same_turn:
        store.create("two", "session", "openclaw")
    ctx = multiprocessing.get_context("spawn")
    gate = ctx.Event()
    processes, pipes = [], []
    try:
        for index, turn in enumerate(["one", "one" if same_turn else "two"]):
            receiver, sender = ctx.Pipe(duplex=False)
            process = ctx.Process(target=_contending_writer,
                                  args=(store.path, turn, f"owner-{index}", gate, sender))
            process.start()
            sender.close()
            processes.append(process)
            pipes.append(receiver)
        for pipe in pipes:
            assert pipe.poll(10) and pipe.recv() == "ready"
        gate.set()
        results = []
        for pipe in pipes:
            assert pipe.poll(10)
            results.append(pipe.recv()[0])
        assert sorted(results) == ["conflict", "ok"]
        assert sum(r.state == "running" for r in store.for_session("session")) == 1
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
    finally:
        gate.set()
        for process in processes:
            if process.is_alive():
                process.kill()
            process.join(10)
            process.close()
        for pipe in pipes:
            pipe.close()


def _crash_at_commit(path, phase, pipe):
    store = RunStore(path)
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def commit(self):
            if phase == "after":
                super().commit()
            pipe.send("commit-boundary")
            pipe.recv()  # Parent kills the process without Python cleanup.

    sqlite3.connect = lambda *args, **kwargs: original_connect(*args, factory=Connection, **kwargs)
    # Simulate a completed external action before recording its result. The
    # marker survives either crash; the ledger alone cannot prove its outcome.
    Path(path).with_suffix(".effect").write_text("external action completed", encoding="utf-8")
    store.transition("turn", expected_version=2, state="succeeded", owner_id="owner",
                     result_refs=["project/result.md"])


@pytest.mark.parametrize("phase,expected_state", [("before", "running"), ("after", "succeeded")])
def test_process_death_at_commit_preserves_a_complete_revision(store, phase, expected_state):
    store.create("turn", "session", "openclaw")
    running = store.transition("turn", expected_version=1, state="running", owner_id="owner")
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=_crash_at_commit, args=(store.path, phase, child))
    process.start()
    child.close()
    try:
        assert parent.poll(10) and parent.recv() == "commit-boundary"
        process.kill()
        process.join(10)
        assert not process.is_alive()
        reopened = RunStore(store.path)
        record = reopened.get("turn")
        assert record.state == expected_state
        assert store.path.with_suffix(".effect").read_text(encoding="utf-8") == "external action completed"
        if phase == "before":
            assert record == running
        else:
            assert record.version == 3 and record.result_refs == ("project/result.md",)
            assert record.finished_at is not None
        with sqlite3.connect(store.path) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        if process.is_alive():
            process.kill()
        process.join(10)
        process.close()
        parent.close()
