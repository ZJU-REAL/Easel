"""Fault injection for the append-only chat replay log (no model or network)."""
import asyncio
import json

import pytest

import web.app as web


def encoded(event):
    return json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"


@pytest.fixture
def event_log(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path)
    path = web._job_event_file("recovery-turn")
    path.parent.mkdir()
    return path


@pytest.mark.parametrize("bad_record", [
    b'{"id":2,"event":',
    b'{"id":2,"data":"\xe4\xb8',  # interrupted UTF-8 character
    b"not-json",
    b"null",
    b"[]",
    b'{"id":null,"event":"token"}',
    b'{"id":"invalid","event":"token"}',
    b'{"id":2}',
    b'{"id":true,"event":"token"}',
    b'{"id":2.5,"event":"token"}',
    b'{"id":2,"event":null}',
])
def test_damaged_record_preserves_surrounding_events(event_log, bad_record):
    first = {"id": 1, "event": "token", "data": "已完成第一步"}
    done = {"id": 3, "event": "done", "data": {"sessionKey": "test"}}
    event_log.write_bytes(encoded(first) + bad_record + b"\n" + encoded(done))
    original = event_log.read_bytes()

    assert web._read_job_events("recovery-turn") == [first, done]
    assert web._read_job_events("recovery-turn", after=1) == [done]
    assert event_log.read_bytes() == original


def test_incomplete_tail_is_retried_after_append(event_log):
    first = {"id": 1, "event": "token", "data": "开始"}
    second = {"id": 2, "event": "token", "data": "中"}
    record = encoded(second)
    split = record.index("中".encode("utf-8")) + 1
    event_log.write_bytes(encoded(first) + record[:split])
    assert web._read_job_events("recovery-turn") == [first]

    with event_log.open("ab") as stream:
        stream.write(record[split:])
    assert web._read_job_events("recovery-turn", after=1) == [second]


def test_replay_reaches_terminal_event_after_corrupt_record(event_log):
    done = {"id": 2, "event": "done", "data": {"sessionKey": "test"}}
    event_log.write_bytes(b"broken\n" + encoded(done))

    async def replay():
        response = await web.api_chat_job_stream("recovery-turn")
        event = await asyncio.wait_for(
            anext(response.body_iterator), timeout=1,
        )
        with pytest.raises(StopAsyncIteration):
            await anext(response.body_iterator)
        return event

    assert asyncio.run(replay()) == {
        "id": "2", "event": "done", "data": json.dumps(done["data"]),
    }


def test_missing_log_returns_empty(event_log):
    assert web._read_job_events("recovery-turn") == []
