"""Direct API must work without invoking any OpenClaw process or bridge."""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import subprocess
import sys
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import app as web
from easel import direct_api

BASE = "http://localhost:50288/v1"
SETTINGS = {"EASEL_DIRECT_API_BASE_URL": BASE, "EASEL_DIRECT_API_MODEL": "gpt-6.1-sol", "EASEL_DIRECT_API_KEY": "gateway-secret"}
ASYNC_CLIENT = httpx.AsyncClient


def sse(*events):
    return "".join("data: " + (e if isinstance(e, str) else json.dumps(e)) + "\n\n" for e in events)


def chunk(content=None, finish=None, **delta):
    if content is not None:
        delta["content"] = content
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


def upstream(monkeypatch, handler):
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(direct_api.httpx, "AsyncClient", client)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for key in (*SETTINGS, "EASEL_CHAT_TRANSPORT"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("EASEL_CHAT_TRANSPORT=api\n" + "\n".join(f"{k}={v}" for k, v in SETTINGS.items()))
    monkeypatch.setattr(web, "ENV_FILE", env)
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(web, "OPENCLAW_SESSIONS_DIR", tmp_path / "openclaw-sessions")
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(web, "_session_locks", {})
    monkeypatch.setattr(web, "_RUNNING_CHAT", {})
    monkeypatch.setattr(web, "_STOPPED_CHAT", set())
    monkeypatch.setattr(web, "_DIRECT_CHAT_TASKS", set())
    def forbidden(*args, **kwargs):
        raise AssertionError("API mode must not call OpenClaw")
    for name in ("openclaw_base_cmd", "_gateway_http_ready", "check_gateway",
                 "_heal_openclaw_session", "_sync_openclaw_chat", "_openclaw_provider_creds"):
        monkeypatch.setattr(web, name, forbidden)
    monkeypatch.setattr(web, "GatewayClient", forbidden)
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, headers={"Origin": local}) as client:
        yield client


def test_stream_history_and_recovery_without_openclaw(sandbox, monkeypatch):
    requests = []
    def respond(request):
        assert str(request.url) == BASE + "/chat/completions"
        assert request.headers["Authorization"] == "Bearer gateway-secret"
        assert not any(k.startswith("x-openclaw") for k in request.headers)
        body = json.loads(request.content)
        assert body["model"] == "gpt-6.1-sol"
        requests.append(body)
        return httpx.Response(200, text=sse(chunk(reasoning_content="想"), chunk("测试成功"),
                                           chunk(finish="stop"), "[DONE]"))
    upstream(monkeypatch, respond)
    for turn in ("first", "second"):
        response = sandbox.post("/api/chat/stream", json={"message": turn, "sessionId": "same", "turnId": turn})
        assert response.status_code == 200
        assert "event: token" in response.text and "测试成功" in response.text
        assert "event: thinking" in response.text and "event: done" in response.text
        assert "event: error" not in response.text and "没写完" not in response.text
    assert [m["role"] for m in requests[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert requests[1]["messages"][1]["content"] == "first"
    assert "技能库" not in requests[0]["messages"][-1]["content"]
    last = sandbox.get("/api/chat/last/same", params={"turn_id": "second"}).json()
    assert last["text"] == "测试成功" and last["clean_end"] is True
    replay = sandbox.get("/api/chat/jobs/second/stream").text
    assert "测试成功" in replay and "event: done" in replay
    assert sandbox.delete("/api/session/same").json()["deleted"]
    assert not direct_api.history_path(web.SESSIONS_DIR, "same").exists()


@pytest.mark.parametrize("status,events", [
    (401, []), (307, []), (200, [chunk("一半")]),
    (200, [{"error": {"message": "gateway-secret"}}]),
    (200, [chunk("太长", finish="length"), "[DONE]"]),
    (200, [chunk(tool_calls=[{"id": "tool"}]), "[DONE]"]),
    (200, ["[DONE]"]),
])
def test_failed_stream_is_not_committed(sandbox, monkeypatch, status, events):
    upstream(monkeypatch, lambda req: httpx.Response(status, text=sse(*events),
                                                    headers={"Location": "http://elsewhere/v1"}))
    response = sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": "failed", "turnId": "failure"})
    assert "event: error" in response.text
    assert "event: done" in response.text
    assert "gateway-secret" not in response.text
    assert not direct_api.history_path(web.SESSIONS_DIR, "failed").exists()
    last = sandbox.get("/api/chat/last/failed").json()
    assert last["status"] == "done" and last["clean_end"] is False


def test_nonstream_and_model_save_without_openclaw(sandbox, monkeypatch):
    captured = []
    def reply(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, text=sse(chunk("OK", finish="stop"), "[DONE]"))
    upstream(monkeypatch, reply)
    assert sandbox.get("/api/status").json()["transport"] == "api"
    assert sandbox.post("/api/chat/question/status", json={"questionIds": ["old-question"]}).json()["questions"]["old-question"]["status"] == "not_found"
    assert sandbox.post("/api/chat/question/answer", json={"questionId": "old-question", "answers": {}}).status_code == 409
    response = sandbox.post("/api/settings/models/save", json={"channel": "chat", "rows": [
        {"slot": "direct-api", "model": "another-model", "baseUrl": BASE, "key": "", "primary": True}]})
    assert response.status_code == 200, response.text
    assert response.json()["transport"] == "api"
    assert "gateway-secret" not in response.text
    assert sandbox.post("/api/chat", json={"message": "hello", "sessionId": "sync"}).json()["response"] == "OK"
    assert captured[0]["model"] == "another-model"
    assert sandbox.post("/api/skill", json={"skill": "check-compliance", "input": "hi"}).status_code == 409


def test_private_models_only_allowed_for_configured_gateway(sandbox, monkeypatch):
    monkeypatch.setattr(web, "_ssrf_safe", lambda url: False)
    captured = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"data":[{"id":"gpt-6.1-sol"}]}'
    class Opener:
        def open(self, request, **kwargs):
            captured.append(request.full_url)
            return Response()
    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *args: Opener())
    assert sandbox.post("/api/settings/models/available", json={"slot": "direct-api", "baseUrl": BASE}).json()["models"] == ["gpt-6.1-sol"]
    for address in ("http://localhost:50289/v1", "http://169.254.169.254/latest", "http://10.0.0.1/v1"):
        assert sandbox.post("/api/settings/models/available", json={"baseUrl": address, "key": "secret"}).status_code == 400
    assert captured == [BASE + "/models"]


def test_stop_cancels_upstream_and_releases_session(sandbox, monkeypatch):
    started = threading.Event()
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse(chunk("一半")).encode()
            started.set()
            await asyncio.sleep(30)
    upstream(monkeypatch, lambda req: httpx.Response(200, stream=SlowStream()))
    responses = []
    worker = threading.Thread(target=lambda: responses.append(sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": "stop"})))
    worker.start()
    assert started.wait(5)
    assert sandbox.post("/api/chat/stop", json={"sessionId": "stop"}).json()["stopped"] is True
    worker.join(5)
    assert not worker.is_alive()
    assert "event: done" in responses[0].text
    assert "event: error" not in responses[0].text
    assert sandbox.get("/api/chat/last/stop").json()["stop_reason"] == "user_stopped"
    assert not web._RUNNING_CHAT
    assert not direct_api.history_path(web.SESSIONS_DIR, "stop").exists()


def test_text_attachment_and_persona_are_inlined(sandbox, monkeypatch, tmp_path):
    session = "attachments"
    scope = web._attachment_scope(session)
    rel = f"_inbox/{scope}/upload/note.txt"
    path = web.OUTPUTS_DIR / rel
    path.parent.mkdir(parents=True)
    path.write_text("实际附件内容", encoding="utf-8")
    monkeypatch.setattr(web, "profile_exists", lambda name: name == "demo")
    monkeypatch.setattr(web, "load_profile_text", lambda name: "画像写作风格")
    bodies = []
    def reply(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, text=sse(chunk("OK", finish="stop"), "[DONE]"))
    upstream(monkeypatch, reply)
    response = sandbox.post("/api/chat", json={"message": "请分析", "sessionId": session, "persona": "demo",
        "attachments": [{"id": web._attachment_id(scope, rel), "name": "note.txt", "path": rel}]})
    assert response.status_code == 200, response.text
    assert "画像写作风格" in bodies[0]["messages"][0]["content"]
    assert "实际附件内容" in json.dumps(bodies[0], ensure_ascii=False)
    assert sandbox.post("/api/chat", json={"message": "test", "persona": "../private"}).status_code == 400


def test_settings_quoted_values_and_environment_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('EASEL_CHAT_TRANSPORT="api"\nEASEL_DIRECT_API_BASE_URL="http://localhost:50288/v1"\n')
    assert direct_api.api_mode(direct_api.read_settings(env))
    monkeypatch.setenv("EASEL_DIRECT_API_MODEL", "from-process")
    assert direct_api.read_settings(env)["EASEL_DIRECT_API_MODEL"] == "from-process"


def test_doctor_api_mode_skips_openclaw(tmp_path, monkeypatch):
    from easel.commands import doctor
    (tmp_path / ".env").write_text("EASEL_CHAT_TRANSPORT=api\n" + "\n".join(f"{k}={v}" for k, v in SETTINGS.items()))
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path)
    def forbidden(*args):
        raise AssertionError("doctor must skip OpenClaw in API mode")
    for name in ("_openclaw_version", "_node_version_ok", "_primary_model_routable", "_gateway_healthy", "_skills_synced"):
        monkeypatch.setattr(doctor, name, forbidden)
    doctor.cmd_doctor(None)


def test_switching_modes_requires_new_session(sandbox, monkeypatch):
    upstream(monkeypatch, lambda req: httpx.Response(200, text=sse(chunk("OK", finish="stop"), "[DONE]")))
    assert sandbox.post("/api/chat", json={"message": "test", "sessionId": "api-session"}).status_code == 200
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "wrong"}).status_code == 400
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "openclaw"}).status_code == 200
    assert sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": "api-session"}).status_code == 409
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "api"}).status_code == 200
    web.SESSIONS_DIR.mkdir(exist_ok=True)
    web._transport_pin_file("gateway-session").write_text("http")
    response = sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": "gateway-session"})
    assert "新建会话" in response.text and "event: error" in response.text


@pytest.mark.skipif(os.name == "nt", reason="setup.sh is the Linux/macOS installer")
def test_api_installer_skips_openclaw_and_gateway(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "setup.sh").write_text((root / "setup.sh").read_text())
    (tmp_path / ".env.example").write_text("EASEL_DIRECT_API_BASE_URL=http://localhost:50288/v1\nEASEL_DIRECT_API_MODEL=test\n")
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls"
    for command in ("python3", "node", "npm", "easel", "ffmpeg", "openclaw"):
        script = f"#!/bin/bash\nprintf '%s\\n' {shlex.quote(command)} >> {shlex.quote(str(log))}\n"
        if command == "node":
            script += "echo v24.21.0\n"
        elif command == "ffmpeg":
            script += "echo 'ffmpeg version 9.0.2'\n"
        elif command == "python3":
            script += (f'if [ "$1" = "-" ]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
                       f'if [ "$1" = "-c" ] && [[ "$2" == *sys.version_info* ]]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
                       'if [ "$1" = "--version" ]; then echo "Python 3.14.6"; fi\n')
        elif command == "openclaw":
            script += "exit 91\n"
        script += "exit 0\n"
        path = binary / command
        path.write_text(script)
        path.chmod(0o755)
    environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                   "EASEL_PIP_INDEX": "https://example.invalid", "EASEL_NPM_REGISTRY": "https://example.invalid"}
    process = subprocess.run(["bash", str(tmp_path / "setup.sh"), "--api"],
                             env=environment, capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    assert "openclaw" not in log.read_text().splitlines()
    assert "EASEL_CHAT_TRANSPORT=api" in (tmp_path / ".env").read_text()
    assert "API 直连模式" in process.stdout


def test_bootstrap_and_restart_skip_openclaw(sandbox, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("direct mode must not start or probe OpenClaw")
    monkeypatch.setattr(web.subprocess, "run", forbidden)
    response = sandbox.get("/api/settings/bootstrap")
    assert response.status_code == 200
    assert response.json()["modelConfigured"] is True
    assert sandbox.post("/api/gateway/restart").json()["ok"] is True
    web.ENV_FILE.write_text("EASEL_CHAT_TRANSPORT=api\n")
    assert sandbox.get("/api/settings/bootstrap").json()["modelConfigured"] is False


@pytest.mark.parametrize("prefix", ["", "web:"])
def test_existing_cli_history_cannot_be_discarded(sandbox, monkeypatch, prefix):
    def forbidden(*args, **kwargs):
        raise AssertionError("existing CLI sessions must never reach a direct upstream")
    monkeypatch.setattr(web, "stream_chat", forbidden)
    web.OPENCLAW_SESSIONS_DIR.mkdir()
    session = "old-cli"
    transcript = web.OPENCLAW_SESSIONS_DIR / f"{web._openclaw_session_id(prefix + session)}.jsonl"
    transcript.write_text("{}\n")
    response = sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": session})
    assert "event: error" in response.text and "新建会话" in response.text
    assert not direct_api.history_path(web.SESSIONS_DIR, session).exists()


@pytest.mark.parametrize("ending", ["\n", ""])
def test_terminal_event_without_blank_line_is_processed(sandbox, monkeypatch, ending):
    payload = sse(chunk("complete")) + "data: " + json.dumps(chunk(finish="stop")) + ending
    upstream(monkeypatch, lambda request: httpx.Response(200, text=payload))
    response = sandbox.post("/api/chat", json={"message": "test", "sessionId": "eof"})
    assert response.status_code == 200
    assert response.json()["response"] == "complete"
    assert direct_api.history_path(web.SESSIONS_DIR, "eof").is_file()


def test_done_without_finish_reason_is_not_success(sandbox, monkeypatch):
    upstream(monkeypatch, lambda request: httpx.Response(200, text=sse(chunk("partial"), "[DONE]")))
    response = sandbox.post("/api/chat/stream", json={"message": "test", "sessionId": "partial"})
    assert "event: error" in response.text
    assert not direct_api.history_path(web.SESSIONS_DIR, "partial").exists()


@pytest.mark.parametrize("key", ["your-api-key", "YOUR_API_KEY", "xxx", "...", "<key>"])
def test_placeholder_credentials_are_rejected(key):
    with pytest.raises(direct_api.DirectAPIError):
        direct_api.api_config({**SETTINGS, "EASEL_DIRECT_API_KEY": key})


def test_model_listing_before_model_selection(sandbox, monkeypatch):
    web.ENV_FILE.write_text("EASEL_CHAT_TRANSPORT=api\n" + "\n".join(
        f"{key}={value}" for key, value in SETTINGS.items() if key != "EASEL_DIRECT_API_MODEL"))
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"data":[{"id":"model-a"}]}'
    class Opener:
        def open(self, request, **kwargs):
            assert request.full_url == BASE + "/models"
            assert request.get_header("Authorization") == "Bearer gateway-secret"
            return Response()
    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *args: Opener())
    response = sandbox.post("/api/settings/models/available", json={"slot": "direct-api"})
    assert response.status_code == 200, response.text
    assert "model-a" in response.text


def test_queued_turn_does_not_overwrite_running_snapshot(sandbox, monkeypatch):
    async def scenario():
        started = asyncio.Event()
        finish = asyncio.Event()
        async def fake_stream(*args, **kwargs):
            started.set()
            await finish.wait()
            yield "token", "complete"
            yield "finish", "stop"
        monkeypatch.setattr(web, "stream_chat", fake_stream)
        first = web.ChatRequest(message="first", sessionId="queue", turnId="first")
        second = web.ChatRequest(message="second", sessionId="queue", turnId="second")
        active = asyncio.create_task(web._run_direct_chat(first, "queue", "first", "", lambda *args: None))
        await started.wait()
        queued = asyncio.create_task(web._run_direct_chat(second, "queue", "second", "", lambda *args: None))
        await asyncio.sleep(0)
        snapshot = json.loads(web._turn_file("web:queue").read_text(encoding="utf-8"))
        assert snapshot["status"] == "running" and snapshot["turn_id"] == "first"
        finish.set()
        await asyncio.gather(active, queued)
        assert not web._RUNNING_CHAT
        assert not web._session_lock("queue").locked()
    asyncio.run(scenario())


def test_model_listing_does_not_send_stored_key_to_draft_url(sandbox, monkeypatch):
    monkeypatch.setattr(web, "_ssrf_safe", lambda url: True)
    def forbidden(*args, **kwargs):
        raise AssertionError("must not send stored credentials to a new URL")
    monkeypatch.setattr(web.urllib.request, "build_opener", forbidden)
    response = sandbox.post("/api/settings/models/available", json={
        "slot": "direct-api", "baseUrl": "https://another.example/v1"})
    assert response.status_code == 400 and "Key" in response.text


def test_keyless_models_and_selftest_have_no_authorization(sandbox, monkeypatch):
    web.ENV_FILE.write_text("EASEL_CHAT_TRANSPORT=api\n" + "\n".join(
        f"{key}={value}" for key, value in SETTINGS.items() if key != "EASEL_DIRECT_API_KEY"))
    captured = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"data":[{"id":"model-a"}]}'
    class Opener:
        def open(self, request, **kwargs):
            assert request.get_header("Authorization") is None
            captured.append(request.full_url)
            return Response()
    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *args: Opener())
    assert sandbox.post("/api/settings/models/available", json={"slot": "direct-api"}).status_code == 200
    assert sandbox.post("/api/settings/models/selftest", json={"channel": "chat"}).status_code == 200
    assert captured == [BASE + "/models"] * 2


def test_environment_pinned_direct_config_is_not_silently_saved(sandbox, monkeypatch):
    monkeypatch.setenv("EASEL_DIRECT_API_MODEL", "from-process")
    response = sandbox.post("/api/settings/models/save", json={"channel": "chat", "rows": [
        {"slot": "direct-api", "baseUrl": BASE, "model": "another"}]})
    assert response.status_code == 409


def test_cross_process_timeout_does_not_overwrite_active_snapshot(sandbox, monkeypatch):
    web._save_turn("web:busy", "running", "active", {"turn_id": "owner"})
    monkeypatch.setattr(web._CrossProcLock, "acquire", lambda *args: False)
    monkeypatch.setattr(web, "TIMEOUT_CHAT", 0)
    response = sandbox.post("/api/chat", json={"message": "test", "sessionId": "busy"})
    assert response.status_code == 502
    snapshot = sandbox.get("/api/chat/last/busy").json()
    assert snapshot["status"] == "running" and snapshot["turn_id"] == "owner"
    assert not web._DIRECT_CHAT_TASKS


def test_cancelled_queue_releases_tracking_without_overwriting_active_turn(sandbox, monkeypatch):
    async def scenario():
        lock = web._session_lock("queue")
        await lock.acquire()
        web._save_turn("web:queue", "running", "active", {"turn_id": "owner"})
        request = web.ChatRequest(message="queued", sessionId="queue")
        queued = asyncio.create_task(web._run_direct_chat(request, "queue", "", "", lambda *args: None))
        await asyncio.sleep(0)
        assert web._DIRECT_CHAT_TASKS
        with pytest.raises(web.HTTPException) as error:
            await web.api_chat_transport_save(web.ChatTransportRequest(transport="openclaw"))
        assert error.value.status_code == 409
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert not web._DIRECT_CHAT_TASKS
        assert lock.locked()
        lock.release()
        snapshot = json.loads(web._turn_file("web:queue").read_text(encoding="utf-8"))
        assert snapshot["turn_id"] == "owner" and snapshot["status"] == "running"
    asyncio.run(scenario())


def test_doctor_recognizes_local_openclaw_backend(tmp_path, monkeypatch):
    from easel.commands import doctor
    for key in SETTINGS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(doctor, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("\n".join(
        f"{key}={value}" for key, value in SETTINGS.items() if key != "EASEL_DIRECT_API_KEY"))
    assert doctor._env_key_valid()
    (tmp_path / ".env").write_text("EASEL_DIRECT_API_BASE_URL=" + BASE)
    assert not doctor._env_key_valid()


def test_direct_save_rejects_placeholder_and_keeps_valid_config(sandbox):
    before = web.ENV_FILE.read_text(encoding="utf-8")
    response = sandbox.post("/api/settings/models/save", json={"channel": "chat", "rows": [
        {"slot": "direct-api", "baseUrl": BASE, "model": "another", "key": "your-api-key"}]})
    assert response.status_code == 400
    assert web.ENV_FILE.read_text(encoding="utf-8") == before


def test_snapshot_write_failure_still_releases_session(sandbox, monkeypatch):
    original = web._save_turn
    def save(session, status, *args, **kwargs):
        if status == "done":
            raise OSError("disk failure")
        return original(session, status, *args, **kwargs)
    monkeypatch.setattr(web, "_save_turn", save)
    upstream(monkeypatch, lambda request: httpx.Response(
        200, text=sse(chunk("complete", finish="stop"), "[DONE]")))
    with pytest.raises(OSError):
        sandbox.post("/api/chat", json={"message": "test", "sessionId": "disk"})
    assert not web._RUNNING_CHAT
    assert not web._DIRECT_CHAT_TASKS
    assert not web._session_lock("disk").locked()


@pytest.mark.skipif(os.name == "nt", reason="setup.sh is the Linux/macOS installer")
def test_local_openclaw_provider_configuration_and_check_mode(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = (root / "setup.sh").read_text()
    start = script.index("    LOCAL_API_PROVIDER_CONFIG=$(")
    end = script.index('    CLAUDE_MODEL="$DEFAULT_PRIMARY_MODEL"', start)
    snippet = script[start:end]
    preamble = """
oc_supports() { return 0; }
oc_set() { printf '%s\\n' "$3" > "$PROVIDER_CAPTURE"; }
"""
    capture = tmp_path / "provider.json"
    environment = {**os.environ, **SETTINGS, "PROJECT_ROOT": str(root),
                   "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                   "PROVIDER_CAPTURE": str(capture)}
    result = subprocess.run(["bash", "-c", "set -e\n" + preamble + snippet],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    provider = json.loads(capture.read_text())
    assert provider["baseUrl"] == BASE
    assert provider["apiKey"] == SETTINGS["EASEL_DIRECT_API_KEY"]
    assert provider["request"]["allowPrivateNetwork"] is True
    assert provider["agentRuntime"] == {"id": "openclaw"}
    assert provider["models"][0]["agentRuntime"] == {"id": "openclaw"}
    environment["EASEL_DIRECT_API_KEY"] = ""
    result = subprocess.run(["bash", "-c", "set -e\n" + preamble + snippet],
                            env=environment, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(capture.read_text())["authHeader"] is False
    start = script.index('if [ "$SETUP_MODE" = check ]; then\n    emit_action env_set EASEL_CHAT_TRANSPORT')
    end = script.index('if [ "$CHAT_MODE" = "api" ]; then', start)
    env_file = tmp_path / ".env"
    env_file.write_text("EASEL_CHAT_TRANSPORT=http\n")
    result = subprocess.run(["bash", "-c", "set -e\nemit_action() { :; }\n" + script[start:end]],
                            env={**environment, "SETUP_MODE": "check", "CHAT_MODE": "api",
                                 "PROJECT_ROOT": str(tmp_path)}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == "EASEL_CHAT_TRANSPORT=http\n"
