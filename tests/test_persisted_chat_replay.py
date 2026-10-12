"""Recover committed terminal states even when the final SSE event is lost."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("persisted_replay_fixtures", Path(__file__).with_name("test_direct_api.py"))
_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_support)
sandbox, web = _support.sandbox, _support.web
from easel.run_store import RunStore


def finish(state):
    store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
    store.create("turn", "session", "direct_api")
    store.transition("turn", expected_version=1, state="running", owner_id="worker")
    store.transition("turn", expected_version=2, state=state, owner_id="worker")


@pytest.mark.parametrize("state", ["succeeded", "failed", "cancelled", "unknown", "interrupted"])
def test_drain_partial_log_then_finish_without_reexecuting(sandbox, monkeypatch, state):
    def forbidden(*args, **kwargs):
        raise AssertionError("replay cannot dispatch a model")
    monkeypatch.setattr(web, "stream_chat", forbidden)
    finish(state)
    log = web._job_event_file("turn")
    log.parent.mkdir()
    log.write_text(json.dumps({"id": 1, "event": "token", "data": "saved answer"}) + "\n", encoding="utf-8")
    before = log.read_bytes()
    response = sandbox.get("/api/chat/jobs/turn/stream")
    assert response.status_code == 200
    assert response.text.count("saved answer") == 1
    assert ("event: done" in response.text) == (state == "succeeded")
    assert ("event: error" in response.text) == (state != "succeeded")
    assert log.read_bytes() == before


def test_missing_log_recovers_only_matching_completed_snapshot(sandbox):
    finish("succeeded")
    web._save_turn("web:session", "done", "saved snapshot", {"turn_id": "turn"})
    response = sandbox.get("/api/chat/jobs/turn/stream")
    assert "saved snapshot" in response.text and "event: done" in response.text
    web._save_turn("web:session", "done", "another turn", {"turn_id": "other"})
    response = sandbox.get("/api/chat/jobs/turn/stream")
    assert "another turn" not in response.text and "event: error" in response.text


def test_queued_admission_without_log_waits_for_cancellation(sandbox):
    store = RunStore(web.SESSIONS_DIR / "runs.sqlite3")
    store.create("turn", "session", "direct_api")
    async def scenario():
        response = await web.api_chat_job_stream("turn")
        pending = asyncio.create_task(anext(response.body_iterator))
        try:
            await asyncio.sleep(0.05)
            assert not pending.done()
            store.transition("turn", expected_version=1, state="cancelled")
            event = await asyncio.wait_for(pending, 2)
            assert event["event"] == "error" and "取消" in event["data"]
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await response.body_iterator.aclose()
    asyncio.run(scenario())


def test_missing_unadmitted_turn_is_still_404(sandbox):
    assert sandbox.get("/api/chat/jobs/missing/stream").status_code == 404


def test_storage_failure_is_reported_without_infinite_tail(sandbox):
    log = web._job_event_file("turn")
    log.parent.mkdir(parents=True)
    log.write_text("", encoding="utf-8")
    (web.SESSIONS_DIR / "runs.sqlite3").write_bytes(b"corrupt database")
    response = sandbox.get("/api/chat/jobs/turn/stream")
    assert "event: error" in response.text and "event: done" not in response.text
