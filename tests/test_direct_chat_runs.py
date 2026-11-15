"""API-only chat persistence; all model responses are local test doubles."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import sqlite3
import threading

import httpx
import pytest

# Skill-local suites also define a package named tests. Load this sibling by
# its exact path so root-level pytest collection cannot select the wrong one.
_spec = importlib.util.spec_from_file_location("direct_chat_fixtures", Path(__file__).with_name("test_direct_api.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
sandbox, web = _support.sandbox, _support.web
upstream, sse, chunk = _support.upstream, _support.sse, _support.chunk
from easel.chat_runs import DirectChatRun
from easel.run_store import RunStore


def test_lifecycle_and_status_survive_reopening_store(sandbox, monkeypatch):
    def respond(request):
        record = RunStore(web.SESSIONS_DIR / "runs.sqlite3").get("turn")
        assert record.state == "running" and record.version == 2
        assert web._session_lock("session").locked()
        return httpx.Response(200, text=sse(chunk("answer"), chunk(finish="stop"), "[DONE]"))
    upstream(monkeypatch, respond)
    response = sandbox.post("/api/chat/stream", json={"message": "hello", "sessionId": "session", "turnId": "turn"})
    assert response.status_code == 200 and "event: error" not in response.text
    state = sandbox.get("/api/chat/jobs/turn").json()
    assert state["state"] == "succeeded" and state["version"] == 3
    assert state["session_id"] == "session" and state["backend"] == "direct_api"
    assert state["can_resume"] is False and state["live_status"] == "not_checked"
    assert sandbox.get("/api/chat/last/session", params={"turn_id": "turn"}).json()["text"] == "answer"
    assert "answer" in sandbox.get("/api/chat/jobs/turn/stream").text


def test_duplicate_submission_does_not_repeat_model_or_erase_replay(sandbox, monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=sse(chunk("answer"), chunk(finish="stop"), "[DONE]"))
    upstream(monkeypatch, respond)
    body = {"message": "hello", "sessionId": "session", "turnId": "turn"}
    assert sandbox.post("/api/chat/stream", json=body).status_code == 200
    original = web._job_event_file("turn").read_bytes()
    assert sandbox.post("/api/chat/stream", json=body).status_code == 409
    assert len(calls) == 1
    assert web._job_event_file("turn").read_bytes() == original


@pytest.mark.parametrize("first", ["/api/chat", "/api/chat/stream"])
def test_nonstream_and_stream_share_task_identity(sandbox, monkeypatch, first):
    calls = []
    upstream(monkeypatch, lambda request: (calls.append(request) or httpx.Response(
        200, text=sse(chunk("answer"), chunk(finish="stop"), "[DONE]"))))
    body = {"message": "hello", "sessionId": "same", "turnId": "shared-turn"}
    response = sandbox.post(first, json=body)
    assert response.status_code == 200
    if first == "/api/chat":
        assert response.json() == {"response": "answer", "sessionKey": "same", "turnId": "shared-turn"}
    second = "/api/chat/stream" if first == "/api/chat" else "/api/chat"
    assert sandbox.post(second, json=body).status_code == 409
    assert len(calls) == 1
    assert sandbox.get("/api/chat/jobs/shared-turn").json()["state"] == "succeeded"


def test_nonstream_replays_old_turn_after_session_snapshot_changes(sandbox, monkeypatch):
    answers = iter(["first answer", "second answer"])
    upstream(monkeypatch, lambda request: httpx.Response(
        200, text=sse(chunk(next(answers)), chunk(finish="stop"), "[DONE]")))
    for turn in ("first", "second"):
        assert sandbox.post("/api/chat", json={
            "message": "hello", "sessionId": "same", "turnId": turn}).status_code == 200
    assert sandbox.get("/api/chat/last/same").json()["text"] == "second answer"
    replay = sandbox.get("/api/chat/jobs/first/stream")
    assert "first answer" in replay.text and "second answer" not in replay.text
    assert "event: done" in replay.text


def test_simultaneous_duplicate_requests_start_only_one_model(sandbox, monkeypatch):
    calls = []
    upstream(monkeypatch, lambda request: (calls.append(request) or httpx.Response(
        200, text=sse(chunk("answer"), chunk(finish="stop"), "[DONE]"))))
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: sandbox.post("/api/chat/stream", json={
            "message": "hello", "sessionId": "session", "turnId": "turn"}), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["corrupt", "unwritable"])
def test_failed_admission_never_starts_model(sandbox, monkeypatch, failure):
    def forbidden(*args, **kwargs):
        raise AssertionError("model must not run without a persisted admission")
    monkeypatch.setattr(web, "stream_chat", forbidden)
    path = web.SESSIONS_DIR / "runs.sqlite3"
    web.SESSIONS_DIR.mkdir(parents=True)
    if failure == "corrupt":
        path.write_bytes(b"broken database" * 100)
    else:
        path.mkdir()
    response = sandbox.post("/api/chat/stream", json={"message": "hello", "turnId": "turn"})
    assert response.status_code == 503
    assert not web._job_event_file("turn").exists()


def test_invalid_turn_id_cannot_alias_another_event_log(sandbox):
    for turn_id in ("a/b", "a b", "x" * 161, "Turn", "con", "nul", "lpt1", "turn."):
        assert sandbox.post("/api/chat/stream", json={"message": "hello", "turnId": turn_id}).status_code == 422


def test_legacy_turn_id_cannot_be_reused_or_truncated(sandbox):
    path = web._job_event_file("old")
    path.parent.mkdir(parents=True)
    path.write_bytes(b'legacy events\n')
    response = sandbox.post("/api/chat/stream", json={"message": "hello", "turnId": "old"})
    assert response.status_code == 409
    assert path.read_bytes() == b'legacy events\n'


def test_model_failure_is_persisted_without_success(sandbox, monkeypatch):
    upstream(monkeypatch, lambda request: httpx.Response(500, text="not available"))
    response = sandbox.post("/api/chat/stream", json={"message": "hello", "turnId": "failure"})
    assert "event: error" in response.text
    assert sandbox.get("/api/chat/jobs/failure").json()["state"] == "failed"


def test_failed_terminal_commit_is_visible_and_preserves_legacy_result(sandbox, monkeypatch):
    original = RunStore.transition
    def transition(self, turn_id, **kwargs):
        if kwargs["state"] == "succeeded":
            raise sqlite3.OperationalError("injected write failure")
        return original(self, turn_id, **kwargs)
    monkeypatch.setattr(RunStore, "transition", transition)
    upstream(monkeypatch, lambda request: httpx.Response(
        200, text=sse(chunk("answer"), chunk(finish="stop"), "[DONE]")))
    response = sandbox.post("/api/chat/stream", json={"message": "hello", "sessionId": "session", "turnId": "turn"})
    assert "event: error" in response.text and "injected write failure" not in response.text
    assert sandbox.get("/api/chat/jobs/turn").json()["state"] == "running"
    assert sandbox.get("/api/chat/last/session").json()["text"] == "answer"
    assert not web._session_lock("session").locked()


def test_status_reads_do_not_infer_death_or_migrate_old_logs(sandbox):
    path = web.SESSIONS_DIR / "runs.sqlite3"
    assert sandbox.get("/api/chat/jobs/missing").status_code == 404
    assert not path.exists()
    log = web._job_event_file("old")
    log.parent.mkdir(parents=True)
    log.write_text('{"id":1,"event":"done","data":{}}\n', encoding="utf-8")
    assert sandbox.get("/api/chat/jobs/old").json()["tracking"] == "legacy"
    assert not path.exists()
    store = RunStore(path)
    store.create("other-process", "session", "direct_api")
    record = store.transition("other-process", expected_version=1, state="running", owner_id="other")
    status = sandbox.get("/api/chat/jobs/other-process").json()
    assert status["state"] == "running" and status["live_status"] == "not_checked"
    assert store.get("other-process") == record


@pytest.mark.parametrize("stage", ["queued", "running", "disconnected"])
def test_live_lifecycle_cancellation_and_disconnect(sandbox, monkeypatch, stage):
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: errors.append(context))
        async def model(*args, **kwargs):
            started.set()
            await finish.wait()
            yield "token", "answer"
            yield "finish", "stop"
        monkeypatch.setattr(web, "stream_chat", model)
        lock = web._session_lock("session")
        if stage == "queued":
            await lock.acquire()
            web._save_turn("web:session", "running", "owner", {"turn_id": "owner"})
        before = set(web._BG_TASKS)
        response = await web.api_chat_stream(web.ChatRequest(message="hello", sessionId="session", turnId="turn"))
        task, = web._BG_TASKS - before
        try:
            if stage == "queued":
                while True:
                    event = await asyncio.wait_for(anext(response.body_iterator), 2)
                    if "排队" in event.get("data", ""):
                        break
            else:
                await asyncio.wait_for(started.wait(), 2)
            store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
            assert store.get("turn").state == ("queued" if stage == "queued" else "running")
            if stage == "disconnected":
                await asyncio.wait_for(anext(response.body_iterator), 2)
                await response.body_iterator.aclose()
                assert not task.done()
                finish.set()
                await asyncio.wait_for(task, 2)
                assert store.get("turn").state == "succeeded"
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
                assert store.get("turn").state == "cancelled"
                if stage == "queued":
                    assert (await web.api_chat_last("session"))["turn_id"] == "owner"
                    assert lock.locked()
                else:
                    assert not lock.locked()
            assert not errors
        finally:
            finish.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if lock.locked():
                lock.release()
            await response.body_iterator.aclose()
    asyncio.run(scenario())


def test_cancel_during_terminal_write_still_saves_legacy_snapshot(sandbox, monkeypatch):
    release = threading.Event()
    original = RunStore.transition
    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        def transition(self, turn_id, **kwargs):
            if kwargs["state"] == "succeeded":
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
            return original(self, turn_id, **kwargs)
        async def model(*args, **kwargs):
            yield "token", "answer"
            yield "finish", "stop"
        monkeypatch.setattr(RunStore, "transition", transition)
        monkeypatch.setattr(web, "stream_chat", model)
        run = DirectChatRun(web.SESSIONS_DIR / "runs.sqlite3")
        await run.create("turn", "session")
        task = asyncio.create_task(web._run_direct_chat(web.ChatRequest(message="hello", turnId="turn"),
                                   "session", "hello", "", lambda *args: None, run=run))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            assert web._session_lock("session").locked()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert RunStore(run.path).get("turn").state == "succeeded"
            assert (await web.api_chat_last("session"))["text"] == "answer"
            assert not web._session_lock("session").locked()
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["create", "running"])
def test_cancellation_waits_for_database_write_before_cleanup(tmp_path, monkeypatch, stage):
    release = threading.Event()
    original = RunStore.create if stage == "create" else RunStore.transition

    async def scenario():
        entered = asyncio.Event()
        loop = asyncio.get_running_loop()
        run = DirectChatRun(tmp_path / "runs.sqlite3")
        def blocked(self, *args, **kwargs):
            if stage == "create" or kwargs["state"] == "running":
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
            return original(self, *args, **kwargs)
        if stage == "running":
            await run.create("turn", "session")
        monkeypatch.setattr(RunStore, "create" if stage == "create" else "transition", blocked)
        async def caller():
            if stage == "create":
                await run.create("turn", "session")
            else:
                try:
                    await run.transition("running")
                finally:
                    await run.transition("cancelled")
        task = asyncio.create_task(caller())
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            record = RunStore(run.path).get("turn")
            assert record.state == "cancelled"
            assert record.version == (2 if stage == "create" else 3)
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
