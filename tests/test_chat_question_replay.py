"""Stored question events must have the same SSE payload as live questions."""
import json

import pytest
from fastapi.testclient import TestClient

import web.app as web


@pytest.mark.parametrize("stored_as_string", [True, False])
@pytest.mark.parametrize("after", [0, 1])
def test_question_replay_preserves_payload(tmp_path, monkeypatch, stored_as_string, after):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path)
    question = {"id": "question-1", "questions": [
        {"question": "选择平台？", "options": ["小红书", "抖音"]},
    ]}
    events = [
        {"id": 1, "event": "token", "data": "开始"},
        {"id": 2, "event": "question",
         "data": json.dumps(question, ensure_ascii=False) if stored_as_string else question},
        {"id": 3, "event": "done", "data": {"sessionKey": "web:test"}},
    ]
    path = web._job_event_file("test-turn")
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events),
                    encoding="utf-8")
    local = "http://127.0.0.1:7860"
    client = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234))
    response = client.get(f"/api/chat/jobs/test-turn/stream?after={after}")
    assert response.status_code == 200
    blocks = response.text.replace("\r\n", "\n").strip().split("\n\n")
    parsed = {}
    for block in blocks:
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        parsed[fields["event"]] = json.loads(fields["data"])
    assert parsed["question"] == question
    assert parsed["done"] == {"sessionKey": "web:test"}
    assert ("token" in parsed) == (after == 0)


def test_missing_question_job_returns_not_found(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path)
    client = TestClient(web.app, base_url="http://127.0.0.1:7860",
                        client=("127.0.0.1", 51234))
    assert client.get("/api/chat/jobs/missing/stream").status_code == 404
