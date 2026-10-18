"""Reconciliation must neither steal an active run nor replay a model request."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
from fastapi import HTTPException

# Other skill suites also use the package name tests. Resolve the shared
# fixture by file location, independent of pytest's package collection order.
_spec = importlib.util.spec_from_file_location("reconcile_chat_fixtures", Path(__file__).with_name("test_direct_api.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
sandbox, web = _support.sandbox, _support.web
from easel.run_store import RunStore


@pytest.fixture(autouse=True)
def no_model_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("reconciliation must never invoke the model")
    monkeypatch.setattr(web, "stream_chat", forbidden)


def running(backend="direct_api", session="session"):
    store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
    store.create("turn", session, backend)
    return store.transition("turn", expected_version=1, state="running", owner_id="owner")


def reconcile(client, version=2):
    return client.post("/api/chat/jobs/turn/reconcile", json={"expected_version": version})


@pytest.mark.parametrize("backend", ["direct_api", "openclaw", "codex", "opencode", "acp"])
def test_orphan_becomes_unknown_without_erasing_results_or_allowing_replay(sandbox, backend):
    record = running(backend)
    web._save_turn("web:session", "done", "saved answer", {"turn_id": "turn"})
    log = web._job_event_file("turn")
    log.parent.mkdir(parents=True)
    log.write_bytes(b'partial events\n')
    response = reconcile(sandbox)
    assert response.status_code == 200
    state = response.json()
    assert state["state"] == "unknown" and state["version"] == 3
    assert state["owner_id"] == record.owner_id and state["finished_at"] is None
    assert state["can_resume"] is False and state["reconciliation"] == "marked_unknown"
    assert state["live_status"] == "session_lock_acquired"
    assert log.read_bytes() == b'partial events\n'
    assert sandbox.get("/api/chat/last/session").json()["text"] == "saved answer"
    assert sandbox.post("/api/chat/stream", json={"message": "retry", "turnId": "turn"}).status_code == 409
    assert reconcile(sandbox).status_code == 409
    assert reconcile(sandbox, 3).json()["reconciliation"] == "unchanged"
    assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn").version == 3


@pytest.mark.parametrize("state", ["queued", "legacy", "missing"])
def test_unverifiable_records_are_never_changed(sandbox, state):
    path = web.SESSIONS_DIR / "runs.sqlite3"
    before = None
    if state == "queued":
        before = RunStore(path).create("turn", "session", "direct_api")
    elif state == "legacy":
        log = web._job_event_file("turn")
        log.parent.mkdir(parents=True)
        log.write_bytes(b'old events\n')
    response = reconcile(sandbox, before.version if before else 2)
    assert response.status_code == (404 if state == "missing" else 409)
    if before:
        assert RunStore(path).get("turn") == before
    else:
        assert not path.exists()


@pytest.mark.parametrize("version", [None, 0, -1, True, "2", 2.5])
def test_revision_must_be_an_explicit_positive_integer(sandbox, version):
    record = running()
    assert reconcile(sandbox, version).status_code == 422
    assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn") == record


def test_active_in_process_owner_is_not_reconciled(sandbox):
    record = running()
    async def scenario():
        lock = web._session_lock("session")
        await lock.acquire()
        try:
            with pytest.raises(HTTPException) as caught:
                await web.api_chat_job_reconcile("turn", web.ReconcileChatRunRequest(expected_version=2))
            assert caught.value.status_code == 409
            assert lock.locked()
            assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn") == record
        finally:
            lock.release()
    asyncio.run(scenario())


def test_real_process_lock_prevents_reconciliation_until_process_exits(sandbox, tmp_path):
    # The child creates its own running record while holding the same OS lock
    # as the API runner. Killing it leaves both a durable record and a marker
    # for an upstream action whose result the ledger cannot establish.
    child = r'''
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "web"))
import app as web
from easel.run_store import RunStore
web.SESSIONS_DIR = Path(sys.argv[1])
lock = web._CrossProcLock("session")
assert lock.acquire(0)
store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
store.create("turn", "session", "direct_api")
store.transition("turn", expected_version=1, state="running", owner_id="child")
Path(sys.argv[2]).write_text("upstream action sent", encoding="utf-8")
while True:
    time.sleep(1)
'''
    marker = tmp_path / "upstream-action"
    process = subprocess.Popen([sys.executable, "-c", child, str(web.SESSIONS_DIR), str(marker)],
                               cwd=Path(__file__).resolve().parents[1],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "child did not acquire its lock and persist the run"
        assert reconcile(sandbox).status_code == 409
        assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn").state == "running"
        process.terminate()
        process.wait(timeout=5)
        response = reconcile(sandbox)
        assert response.status_code == 200 and response.json()["state"] == "unknown"
        assert marker.read_text(encoding="utf-8") == "upstream action sent"
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_concurrent_reconcilers_commit_only_one_revision(sandbox):
    running()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: reconcile(sandbox), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    record = RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn")
    assert record.state == "unknown" and record.version == 3


def test_revision_change_between_read_and_lock_does_not_overwrite_completion(sandbox, monkeypatch):
    record = running()
    original = web._CrossProcLock.acquire
    def acquire(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if result:
            RunStore(web.SESSIONS_DIR / "runs.sqlite3").transition(
                "turn", expected_version=record.version, state="succeeded", owner_id=record.owner_id)
        return result
    monkeypatch.setattr(web._CrossProcLock, "acquire", acquire)
    assert reconcile(sandbox).status_code == 409
    assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn").state == "succeeded"
    assert not web._session_lock("session").locked()


def test_unavailable_lock_is_not_treated_as_evidence_of_death(sandbox, monkeypatch):
    record = running()
    monkeypatch.setattr(web._CrossProcLock, "acquire", lambda *args: False)
    assert reconcile(sandbox).status_code == 409
    assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn") == record
    assert not web._session_lock("session").locked()


def test_failed_commit_leaves_run_unchanged_and_releases_both_locks(sandbox, monkeypatch):
    record = running()
    original = RunStore.transition
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private database error details")
    monkeypatch.setattr(RunStore, "transition", fail)
    response = reconcile(sandbox)
    assert response.status_code == 503 and "private" not in response.text
    assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn") == record
    assert not web._session_lock("session").locked()
    lock = web._CrossProcLock("session")
    try:
        assert lock.acquire(0)
    finally:
        lock.release()
    monkeypatch.setattr(RunStore, "transition", original)
    assert reconcile(sandbox).status_code == 200


@pytest.mark.parametrize("failure", ["corrupt", "directory", "schema"])
def test_unreadable_store_is_not_reported_as_missing_or_replaced(sandbox, failure):
    path = web.SESSIONS_DIR / "runs.sqlite3"
    path.parent.mkdir(parents=True)
    if failure == "directory":
        path.mkdir()
    elif failure == "corrupt":
        path.write_bytes(b"corrupt database" * 100)
    else:
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA user_version=99")
    before = path.read_bytes() if path.is_file() else None
    assert reconcile(sandbox).status_code == 503
    assert sandbox.get("/api/chat/jobs/turn").status_code == 503
    if before is None:
        assert path.is_dir()
    else:
        assert path.read_bytes() == before


def test_cancel_during_commit_keeps_locks_until_worker_finishes(sandbox, monkeypatch):
    running()
    original = RunStore.transition
    release = threading.Event()
    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        def transition(self, *args, **kwargs):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(5)
            return original(self, *args, **kwargs)
        monkeypatch.setattr(RunStore, "transition", transition)
        task = asyncio.create_task(web.api_chat_job_reconcile(
            "turn", web.ReconcileChatRunRequest(expected_version=2)))
        contender = web._CrossProcLock("session")
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            assert web._session_lock("session").locked()
            assert not contender.acquire(0)
            contender.release()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn").state == "unknown"
            assert not web._session_lock("session").locked()
            assert contender.acquire(0)
        finally:
            release.set()
            contender.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
