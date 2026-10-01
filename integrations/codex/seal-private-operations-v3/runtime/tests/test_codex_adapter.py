import asyncio
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from easel import codex_adapter as adapter
from web import app as web


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    script = tmp_path / "codex"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json,sys,time\n"
        "prompt=sys.stdin.read()\n"
        "if 'WAIT_TEST' in prompt: time.sleep(30)\n"
        "print(json.dumps({'type':'thread.started','thread_id':'thread-test'}),flush=True)\n"
        "if 'ERROR_TEST' in prompt:\n"
        " print(json.dumps({'type':'turn.failed','error':{'message':'provider unavailable'}}),flush=True)\n"
        " sys.exit(1)\n"
        "text='RESUMED' if 'resume' in sys.argv else 'PONG'\n"
        "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}),flush=True)\n"
    )
    script.chmod(0o700)
    monkeypatch.setenv("EASEL_CODEX_BIN", str(script))
    monkeypatch.setattr(adapter, "SESSION_FILE", tmp_path / "sessions.json")
    return tmp_path


def test_first_turn_resume_and_forget(fake_codex):
    events = []
    assert adapter.run_codex("hello", session_key="a", on_event=events.append)[:2] == (0, "PONG")
    assert adapter.run_codex("again", session_key="a")[:2] == (0, "RESUMED")
    assert adapter.run_codex("other", session_key="b")[:2] == (0, "PONG")
    assert len(events) == 2
    assert adapter.forget_session("a")
    assert adapter._load_sessions() == {"b": "thread-test"}


def test_concurrent_session_map_writes(fake_codex):
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda key: adapter._save_session(key, key), ["a", "b", "c", "d"]))
    assert len(adapter._load_sessions()) == 4


def test_failure_and_timeout(fake_codex):
    rc, text, err = adapter.run_codex("ERROR_TEST")
    assert rc == 1 and text == "" and "provider unavailable" in err
    assert adapter.run_codex("WAIT_TEST", timeout=0.1)[0] == 124


def test_cancel_running_and_before_launch(fake_codex):
    cancel = threading.Event()
    timer = threading.Timer(0.1, cancel.set)
    timer.start()
    try:
        assert adapter.run_codex("WAIT_TEST", cancel=cancel)[0] == 130
        assert adapter.run_codex("hello", cancel=cancel)[0] == 130
    finally:
        timer.join()


def test_corrupt_session_map_is_not_overwritten(fake_codex):
    adapter.SESSION_FILE.write_text("corrupt")
    assert adapter.run_codex("hello", session_key="a")[0] != 0
    assert adapter.SESSION_FILE.read_text() == "corrupt"


def test_skill_path_traversal_rejected():
    with pytest.raises(ValueError):
        adapter.build_skill_prompt("../../outside", "hello")


def test_web_job_persistence_replay_and_session_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path)
    calls = []

    def fake_run(message, **kwargs):
        calls.append(kwargs["session_key"])
        kwargs["on_event"]({"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}})
        return 0, "answer", ""

    monkeypatch.setattr(web, "run_codex", fake_run)

    async def scenario():
        request = web.ChatRequest(message="hello", sessionId="web-test", turnId="turn-test")
        await web.api_chat_stream(request)
        await asyncio.gather(*list(web._BG_TASKS))
        await web.api_chat_stream(request)
        return await web.api_chat_last("web-test", "turn-test")

    final = asyncio.run(scenario())
    assert calls == ["web:web-test"]
    assert final["status"] == "done" and final["text"] == "answer"
    events = web._read_job_events("turn-test")
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["sessionKey"] == "web-test"
    assert web._read_job_events("turn-test", after=events[-2]["id"]) == events[-1:]


def test_web_nonstream_failure_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(web, "run_codex", lambda *args, **kwargs: (1, "partial", "secret diagnostic"))
    with pytest.raises(RuntimeError, match="exit 1"):
        web.run_agent_sync("hello")
