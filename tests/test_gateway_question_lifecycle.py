"""Closed gateway questions must not disable cards or expose stale answers."""

import asyncio
import json
import threading

import httpx
import pytest

import easel.gateway_questions as gateway
import web.app as web


class RpcSocket:
    def __init__(self, error=None, payload=None):
        self.error = error
        self.payload = payload
        self.request = None

    def send(self, message):
        self.request = json.loads(message)

    def recv(self):
        return json.dumps({
            "id": self.request["id"], "ok": self.error is None,
            "error": self.error, "payload": self.payload,
        })

    def close(self):
        pass


def rpc_client(error=None, payload=None):
    client = gateway.GatewayClient()
    client.ws = RpcSocket(error=error, payload=payload)
    return client


@pytest.mark.parametrize("reason", [
    "QUESTION_NOT_FOUND", "QUESTION_ALREADY_TERMINAL", "QUESTION_REQUESTER_INACTIVE",
    "QUESTION_EXPIRED", "QUESTION_CANCELLED", "QUESTION_CLOSED",
])
def test_terminal_rpc_error_is_not_unsupported(reason):
    client = rpc_client(error={
        "code": "INVALID_REQUEST", "message": "private answer must not be logged",
        "details": {"reason": reason},
    })
    with pytest.raises(gateway.GatewayQuestionError) as caught:
        client.resolve("stale-question", {"choice": ["private answer"]})
    assert not isinstance(caught.value, gateway.GatewayUnsupportedError)
    assert caught.value.reason == reason
    assert "private answer" not in str(caught.value)


@pytest.mark.parametrize("error", [
    {"code": "INVALID_REQUEST", "message": "invalid question.resolve params"},
    {"code": "INVALID_REQUEST", "message": "unknown method: other.method"},
    {"code": "INVALID_REQUEST", "message": "invalid choice",
     "details": {"reason": "QUESTION_INVALID_ANSWER"}},
    {"code": "INVALID_REQUEST", "message": "invalid request",
     "details": {"reason": "QUESTION_ID_IN_USE"}},
    {"code": "INVALID_REQUEST", "message": "invalid request",
     "details": {"reason": "QUESTION_FUTURE_REASON"}},
])
def test_invalid_request_does_not_imply_missing_method(error):
    with pytest.raises(gateway.GatewayQuestionError) as caught:
        rpc_client(error=error).resolve("question", {})
    assert not isinstance(caught.value, gateway.GatewayUnsupportedError)


@pytest.mark.parametrize("error", [
    {"code": "INVALID_REQUEST", "message": "unknown method: question.list"},
    {"code": "METHOD_NOT_FOUND", "message": "missing method"},
    {"code": "INVALID_REQUEST", "message": "missing method",
     "details": {"reason": "METHOD_NOT_FOUND"}},
])
def test_unknown_method_remains_unsupported(error):
    with pytest.raises(gateway.GatewayUnsupportedError):
        rpc_client(error=error).list_questions()


@pytest.fixture
def gateway_api(monkeypatch):
    monkeypatch.setattr(web, "_direct_api_enabled", lambda: False)
    monkeypatch.setattr(web, "_harness_settings", lambda: {"runtime": "openclaw"})
    monkeypatch.setattr(web, "_QBRIDGE_DISABLED", False)
    monkeypatch.setattr(web, "_QBRIDGE_WARNED", set())
    monkeypatch.setattr(web, "question_bridge_supported", lambda: True)


@pytest.mark.parametrize("reason", [
    "QUESTION_NOT_FOUND", "QUESTION_ALREADY_TERMINAL", "QUESTION_REQUESTER_INACTIVE",
])
def test_answer_api_explicitly_marks_closed_questions(gateway_api, monkeypatch, reason):
    client = rpc_client(error={
        "code": "INVALID_REQUEST", "message": "private answer",
        "details": {"reason": reason},
    })
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    result = asyncio.run(web.api_question_answer(web.QuestionAnswerRequest(
        questionId="stale", answers={"choice": ["private answer"]})))
    assert result["ok"] is False
    assert result["expired"] is True
    assert result["status"] == "expired"
    assert result["reason"] == reason
    assert "private answer" not in json.dumps(result)
    assert "not supported" not in result["error"]
    assert not web._QBRIDGE_DISABLED
    assert client.ws is None


def test_unknown_harness_question_explicitly_expires(gateway_api):
    result = asyncio.run(web.api_question_answer(web.QuestionAnswerRequest(
        questionId="harness_missing", answers={})))
    assert result["ok"] is False
    assert result["expired"] is True
    assert result["status"] == "expired"


@pytest.mark.parametrize("reason,status", [
    ("QUESTION_NOT_FOUND", "not_found"),
    ("QUESTION_ALREADY_TERMINAL", "closed"),
    ("QUESTION_REQUESTER_INACTIVE", "cancelled"),
    ("QUESTION_INVALID_ANSWER", "unknown"),
])
def test_status_distinguishes_closed_questions_from_rpc_failure(
        gateway_api, monkeypatch, reason, status):
    client = rpc_client(error={"code": "INVALID_REQUEST", "details": {"reason": reason}})
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    result = asyncio.run(web.api_question_status(web.QuestionStatusRequest(questionIds=["old"])))
    assert result["ok"] is True
    assert result["questions"]["old"]["status"] == status
    assert not web._QBRIDGE_DISABLED


def test_status_keeps_unsupported_path(gateway_api, monkeypatch):
    client = rpc_client(error={"code": "INVALID_REQUEST", "message": "unknown method: question.get"})
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    result = asyncio.run(web.api_question_status(web.QuestionStatusRequest(questionIds=["old"])))
    assert result["ok"] is False
    assert result["questions"] == {}


def test_status_only_returns_gateway_metadata(gateway_api, monkeypatch):
    client = rpc_client(payload={"question": {
        "id": "toolu_hook", "status": "pending", "createdAtMs": 1_700_000_000_000,
        "expiresAtMs": 1_700_007_200_000, "answers": {"secret": "private answer"},
        "questions": [{"question": "private prompt"}],
    }})
    monkeypatch.setattr(client, "connect", lambda: None)
    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    result = asyncio.run(web.api_question_status(web.QuestionStatusRequest(questionIds=["toolu_hook"])))
    assert result == {"ok": True, "questions": {"toolu_hook": {
        "status": "pending", "createdAtMs": 1_700_000_000_000,
        "expiresAtMs": 1_700_007_200_000,
    }}}


@pytest.mark.parametrize("stored_as_string", [True, False])
def test_question_closed_replay_uses_single_json_layer(tmp_path, monkeypatch, stored_as_string):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path)
    closed = {"id": "question", "status": "cancelled"}
    events = [
        {"id": 1, "event": "question_closed",
         "data": json.dumps(closed) if stored_as_string else closed},
        {"id": 2, "event": "done", "data": {"sessionKey": "session"}},
    ]
    path = web._job_event_file("closed-turn")
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    async def collect():
        response = await web.api_chat_job_stream("closed-turn")
        return [event async for event in response.body_iterator]

    replay = asyncio.run(collect())
    assert json.loads(replay[0]["data"]) == closed


class PollStop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, timeout):
        return self.stopped


def test_pending_departure_closes_card_without_disabling_bridge(gateway_api, monkeypatch):
    questions = [{"questionId": "choice", "question": "pick", "options": ["yes"]}]
    snapshots = [
        [{"id": "toolu_hook", "questions": questions, "expiresAtMs": 7_200_000,
          "createdAtMs": 0}],
        [{"id": "new", "questions": questions}],
        [{"id": "new", "questions": questions}],
        [],
    ]

    class Client:
        calls = 0
        closed = False

        def connect(self):
            pass

        def list_questions(self, **kwargs):
            assert kwargs == {"session_key": "agent:main:session", "status": "pending"}
            snapshot = snapshots[self.calls]
            self.calls += 1
            return snapshot

        def get_question(self, identifier):
            if identifier == "toolu_hook":
                return {"status": "cancelled", "answers": {"secret": "must not appear"}}
            raise gateway.GatewayQuestionClosedError("QUESTION_NOT_FOUND")

        def close(self):
            self.closed = True

    client = Client()

    class Process:
        def poll(self):
            return 0 if client.calls == len(snapshots) else None

    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    received = []
    web._poll_gateway_questions("session", Process(),
                                lambda kind, payload: received.append((kind, json.loads(payload))), PollStop())
    assert received == [
        ("question", {"id": "toolu_hook", "questions": questions,
                      "createdAtMs": 0, "expiresAtMs": 7_200_000}),
        ("question_closed", {"id": "toolu_hook", "status": "cancelled"}),
        ("question", {"id": "new", "questions": questions, "expiresAtMs": None}),
        ("question_closed", {"id": "new", "status": "not_found"}),
    ]
    assert not web._QBRIDGE_DISABLED
    assert client.closed
    assert "must not appear" not in json.dumps(received)


def test_poll_transient_failure_does_not_close_card(gateway_api, monkeypatch):
    stop = PollStop()

    class Client:
        calls = 0

        def connect(self):
            pass

        def list_questions(self, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise gateway.GatewayQuestionError("temporary network failure")
            if self.calls == 3:
                stop.stopped = True
            return [{"id": "pending", "questions": []}]

        def close(self):
            pass

    class Process:
        def poll(self):
            return None

    monkeypatch.setattr(web, "GatewayClient", Client)
    received = []
    web._poll_gateway_questions("session", Process(),
                                lambda kind, payload: received.append((kind, json.loads(payload))), stop)
    assert [kind for kind, payload in received] == ["question"]
    assert not web._QBRIDGE_DISABLED


def test_poll_true_unsupported_still_disables_bridge(gateway_api, monkeypatch):
    class Client:
        def connect(self):
            pass

        def list_questions(self, **kwargs):
            raise gateway.GatewayUnsupportedError("unknown method: question.list")

        def close(self):
            pass

    class Process:
        def poll(self):
            return None

    monkeypatch.setattr(web, "GatewayClient", Client)
    web._poll_gateway_questions("session", Process(), lambda *args: None, PollStop())
    assert web._QBRIDGE_DISABLED


def test_departure_status_failure_never_claims_expiry(gateway_api, monkeypatch):
    class Client:
        lists = 0
        gets = 0

        def connect(self):
            pass

        def list_questions(self, **kwargs):
            self.lists += 1
            return [{"id": "question", "questions": []}] if self.lists == 1 else []

        def get_question(self, identifier):
            self.gets += 1
            if self.gets == 1:
                raise gateway.GatewayQuestionError("network unavailable: private detail")
            return {"status": "cancelled"}

        def close(self):
            pass

    client = Client()

    class Process:
        def poll(self):
            return 0 if client.gets == 2 else None

    monkeypatch.setattr(web, "GatewayClient", lambda: client)
    received = []
    web._poll_gateway_questions("session", Process(),
                                lambda kind, payload: received.append((kind, json.loads(payload))), PollStop())
    assert received == [
        ("question", {"id": "question", "questions": [], "expiresAtMs": None}),
        ("question_closed", {"id": "question", "status": "cancelled"}),
    ]
    assert client.gets == 2
    assert not web._QBRIDGE_DISABLED


@pytest.mark.parametrize("closed_status", ["answered", "cancelled", "expired", "pending"])
def test_live_and_replayed_close_events_precede_done(
        gateway_api, tmp_path, monkeypatch, closed_status):
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(web, "DEBUG_DIR", tmp_path / "debug")
    monkeypatch.setattr(web, "SHARED_RAW_STREAM", tmp_path / "absent-raw.jsonl")
    monkeypatch.setattr(web, "_session_locks", {})
    monkeypatch.setattr(web, "_RUNNING_CHAT", {})
    monkeypatch.setattr(web, "_STOPPED_CHAT", set())
    monkeypatch.setattr(web, "_BG_TASKS", set())
    monkeypatch.setattr(web, "_chat_backend", lambda session_id: "openclaw")
    monkeypatch.setattr(web, "_chat_message", lambda req: req.message)
    monkeypatch.setattr(web, "_heal_openclaw_session", lambda sk: None)
    monkeypatch.setattr(web, "openclaw_base_cmd", lambda: ["unused-openclaw"])
    monkeypatch.setattr(web, "_agent_thinking_level", lambda: "off")
    monkeypatch.setattr(web, "_proxy_env", dict)
    monkeypatch.setattr(web, "_resolve_transport", lambda sk: "http")
    monkeypatch.setattr(web, "chat_completions_url", lambda: "http://gateway.test/chat/completions")
    first_poll = threading.Event()
    question = {"id": "toolu_hook", "questions": [{"questionId": "choice", "question": "pick"}],
                "createdAtMs": 1_700_000_000_000, "expiresAtMs": 1_700_007_200_000}

    class Client:
        calls = 0
        closed = False

        def connect(self):
            pass

        def list_questions(self, **kwargs):
            self.calls += 1
            first_poll.set()
            return [question] if self.calls == 1 or closed_status == "pending" else []

        def get_question(self, identifier):
            return {"status": closed_status, "answers": {"secret": "private answer"}}

        def close(self):
            self.closed = True

    gateway_client = Client()
    monkeypatch.setattr(web, "GatewayClient", lambda: gateway_client)
    async_client = httpx.AsyncClient

    async def gateway_response(request):
        assert await asyncio.to_thread(first_poll.wait, 2)
        payload = {"choices": [{"delta": {"content": "complete"}, "finish_reason": "stop"}]}
        return httpx.Response(200, text="data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: async_client(
        transport=httpx.MockTransport(gateway_response), **kwargs))

    async def scenario():
        response = await web.api_chat_stream(web.ChatRequest(
            message="test", sessionId="lifecycle", turnId="lifecycle-turn"))

        async def collect():
            return [event async for event in response.body_iterator]

        received = await asyncio.wait_for(collect(), timeout=4)
        assert received[-1]["event"] == "done"
        assert [json.loads(event["data"]) for event in received
                if event["event"] == "token"] == ["complete"]
        assert [json.loads(event["data"]) for event in received
                if event["event"] == "question"] == [question]
        expected_closed = [] if closed_status == "pending" else [{"id": "toolu_hook", "status": closed_status}]
        assert [json.loads(event["data"]) for event in received
                if event["event"] == "question_closed"] == expected_closed
        replay_response = await web.api_chat_job_stream("lifecycle-turn")
        replay = [event async for event in replay_response.body_iterator]
        assert [(event["event"], json.loads(event["data"])) for event in replay] == [
            (event["event"], json.loads(event["data"])) for event in received]
        assert (await web.api_chat_last("lifecycle", turn_id="lifecycle-turn"))["text"] == "complete"
        assert not web._RUNNING_CHAT
        assert not web._session_lock("lifecycle").locked()
        assert "private answer" not in web._job_event_file("lifecycle-turn").read_text(encoding="utf-8")
        assert gateway_client.closed
        assert not web._QBRIDGE_DISABLED

    asyncio.run(scenario())
