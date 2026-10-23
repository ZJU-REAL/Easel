"""Withdrawing an admission must win atomically against model dispatch."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("queued_chat_fixtures", Path(__file__).with_name("test_direct_api.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
sandbox, web = _support.sandbox, _support.web
from easel.chat_runs import DirectChatRun
from easel.run_store import RunStore, RunConflict


def test_cancelled_waiter_never_dispatches_or_overwrites_owner_snapshot(sandbox, monkeypatch):
    async def scenario():
        calls = []
        async def model(*args, **kwargs):
            calls.append(1)
            yield "finish", "stop"
        monkeypatch.setattr(web, "stream_chat", model)
        run = DirectChatRun(web.SESSIONS_DIR / "runs.sqlite3")
        await run.create("turn", "session")
        lock = web._session_lock("session")
        await lock.acquire()
        web._save_turn("web:session", "done", "owner answer", {"turn_id": "owner"})
        queued = asyncio.Event()
        task = asyncio.create_task(web._run_direct_chat(
            web.ChatRequest(message="hi", turnId="turn"), "session", "hi", "",
            lambda *args, **kwargs: queued.set(), run=run))
        try:
            await asyncio.wait_for(queued.wait(), 2)
            result = await web.api_chat_job_cancel_queued(
                "turn", web.ReconcileChatRunRequest(expected_version=1))
            assert result["state"] == "cancelled" and result["version"] == 2
            assert lock.locked()  # cancellation must not take/release another run's lock
            lock.release()
            await asyncio.wait_for(task, 2)
            assert not calls
            assert RunStore(run.path).get("turn").state == "cancelled"
            assert (await web.api_chat_last("session"))["text"] == "owner answer"
        finally:
            if lock.locked():
                lock.release()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("backend", ["direct_api", "openclaw", "codex", "opencode", "acp"])
def test_restart_leftover_can_be_withdrawn_without_replaying(sandbox, backend):
    path = web.SESSIONS_DIR / "runs.sqlite3"
    RunStore(path).create("turn", "session", backend)
    result = sandbox.post("/api/chat/jobs/turn/cancel-queued", json={"expected_version": 1})
    assert result.status_code == 200 and result.json()["state"] == "cancelled"
    assert not web._job_event_file("turn").exists()
    assert sandbox.post("/api/chat/jobs/turn/cancel-queued", json={"expected_version": 1}).status_code == 409
    assert sandbox.post("/api/chat/stream", json={"message": "retry", "turnId": "turn"}).status_code == 409


@pytest.mark.parametrize("backend", ["openclaw", "codex", "opencode", "acp"])
def test_cancelled_native_waiter_never_dispatches(sandbox, monkeypatch, backend):
    def forbidden(*args, **kwargs):
        raise AssertionError("cancelled admission must never start an agent")

    monkeypatch.setattr(web, "_chat_backend", lambda key: backend)
    monkeypatch.setattr(web, "_chat_message", lambda req: req.message)
    monkeypatch.setattr(web.harnesses, "adapter", forbidden)
    monkeypatch.setattr(web.subprocess, "Popen", forbidden)
    monkeypatch.setattr(web, "openclaw_base_cmd", lambda: ["unused"])
    monkeypatch.setattr(web, "_agent_thinking_level", lambda: "off")
    monkeypatch.setattr(web, "question_bridge_supported", lambda: False)
    monkeypatch.setattr(web, "_proxy_env", dict)

    async def scenario():
        lock = web._session_lock("session")
        await lock.acquire()
        web._save_turn("web:session", "done", "previous result", {"turn_id": "previous"})
        try:
            response = await web.api_chat_stream(web.ChatRequest(
                message="hello", sessionId="session", turnId="withdrawn"))
            await response.body_iterator.__anext__()
            cancelled = await web.api_chat_job_cancel_queued(
                "withdrawn", web.ReconcileChatRunRequest(expected_version=1))
            assert cancelled["state"] == "cancelled"
        finally:
            lock.release()
        await asyncio.wait_for(collect(response), 3)
        assert RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("withdrawn").state == "cancelled"
        assert (await web.api_chat_last("session"))["text"] == "previous result"
        assert not web._RUNNING_CHAT and not web._session_lock("session").locked()

    async def collect(response):
        return [event async for event in response.body_iterator]

    asyncio.run(scenario())


def test_executor_and_canceller_have_exactly_one_winner(sandbox):
    path = web.SESSIONS_DIR / "runs.sqlite3"
    store = RunStore(path)
    store.create("turn", "session", "direct_api")
    def start():
        try:
            store.transition("turn", expected_version=1, state="running", owner_id="runner")
            return True
        except RunConflict:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        executor = pool.submit(start)
        canceller = pool.submit(sandbox.post, "/api/chat/jobs/turn/cancel-queued", json={"expected_version": 1})
        started, response = executor.result(), canceller.result()
    assert (started, response.status_code) in [(True, 409), (False, 200)]
    record = store.get("turn")
    assert record.version == 2 and record.state == ("running" if started else "cancelled")


@pytest.mark.parametrize("backend,state,version", [
    ("direct_api", "running", 2), ("direct_api", "queued", 3),
])
def test_unmatched_admissions_are_unchanged(sandbox, backend, state, version):
    store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
    before = store.create("turn", "session", backend)
    if state == "running":
        before = store.transition("turn", expected_version=1, state="running", owner_id="runner")
    assert sandbox.post("/api/chat/jobs/turn/cancel-queued", json={"expected_version": version}).status_code == 409
    assert store.get("turn") == before
