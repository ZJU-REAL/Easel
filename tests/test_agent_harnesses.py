import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import web.app as web
from easel.harnesses import store
from easel.harnesses.acp import ACPAdapter
from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.codex import CodexAdapter
from easel.harnesses.commands import acp_command, base_command
from easel.harnesses.rpc import RPC
from easel.harnesses import models as native_models


FIXTURE = Path(__file__).parent / "fixtures" / "harness_rpc.py"


def test_codex_model_catalog_paginates_without_creating_a_session(tmp_path, monkeypatch):
    request = request_for(tmp_path, "codex")
    monkeypatch.setattr(native_models, "base_command", lambda runtime: [
        sys.executable, str(FIXTURE), "codex"])
    result = asyncio.run(native_models.available_models("codex", request))
    assert result == [{"id": "first-model", "label": "First", "default": True},
                      {"id": "second-model", "label": "Second", "default": False}]
    methods = [message.get("method") for message in audit(tmp_path)]
    assert methods == ["initialize", "initialized", "model/list", "model/list"]


def test_codex_model_catalog_redacts_protocol_errors(tmp_path, monkeypatch):
    request = request_for(tmp_path, "codex", mode="models-error")
    monkeypatch.setattr(native_models, "base_command", lambda runtime: [
        sys.executable, str(FIXTURE), "codex"])
    with pytest.raises(HarnessError) as caught:
        asyncio.run(native_models.available_models("codex", request))
    assert "secret-test-key" not in str(caught.value)


def test_opencode_model_catalog_filters_logs_and_preserves_root(tmp_path, monkeypatch):
    code = (
        "import os; from pathlib import Path; "
        f"assert Path.cwd() == Path({str(tmp_path)!r}); "
        "assert os.environ['EASEL_ROOT'] == str(Path.cwd()); "
        "print('provider/first\\nlog message\\nprovider/second\\nprovider/first')"
    )
    monkeypatch.setattr(native_models, "base_command", lambda runtime: [sys.executable, "-c", code])
    result = asyncio.run(native_models.available_models("opencode", request_for(tmp_path, "acp")))
    assert [item["id"] for item in result] == ["provider/first", "provider/second"]


def test_opencode_model_catalog_does_not_expose_cli_output_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(native_models, "base_command", lambda runtime: [
        sys.executable, "-c", "print('secret-test-key'); raise SystemExit(1)"])
    with pytest.raises(HarnessError) as caught:
        asyncio.run(native_models.available_models("opencode", request_for(tmp_path, "acp")))
    assert "secret-test-key" not in str(caught.value)


def test_model_configuration_preview_does_not_switch_engine(sandbox, monkeypatch):
    captured = []

    def channels(runtime=None):
        captured.append(runtime)
        return {"runtime": runtime}

    monkeypatch.setattr(web, "_model_channels", channels)
    before = (web.OUTPUTS_DIR / "_harness" / "config.json").read_bytes()
    for runtime in ("api", "openclaw"):
        response = sandbox.get("/api/settings/models", params={"runtime": runtime})
        assert response.status_code == 200
        assert response.json()["runtime"] == runtime
    assert captured == ["api", "openclaw"]
    assert sandbox.get("/api/settings/models?runtime=codex").status_code == 400
    assert (web.OUTPUTS_DIR / "_harness" / "config.json").read_bytes() == before


@pytest.mark.parametrize("runtime", ["codex", "opencode"])
def test_native_model_endpoint_uses_project_root_without_writing_config(sandbox, monkeypatch, runtime):
    async def models(selected, request):
        assert selected == runtime
        assert request.cwd == web.PROJECT_ROOT
        assert request.env["EASEL_ROOT"] == str(web.PROJECT_ROOT)
        assert not request.native_id
        return [{"id": "another-model", "label": "Another", "default": False}]

    monkeypatch.setattr(native_models, "available_models", models)
    before = (web.OUTPUTS_DIR / "_harness" / "config.json").read_bytes()
    response = sandbox.post(f"/api/settings/harness/models/{runtime}")
    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "another-model"
    assert (web.OUTPUTS_DIR / "_harness" / "config.json").read_bytes() == before
    assert not list(web.SESSIONS_DIR.glob("harness/*"))


@pytest.mark.parametrize(("error", "status"), [
    (HarnessError("secret-test-key"), 409),
    (OSError("secret-test-key"), 409),
    (asyncio.TimeoutError("secret-test-key"), 504),
])
def test_native_model_endpoint_reports_safe_failure(sandbox, monkeypatch, error, status):
    async def models(runtime, request):
        raise error

    monkeypatch.setattr(native_models, "available_models", models)
    response = sandbox.post("/api/settings/harness/models/codex")
    assert response.status_code == status
    assert "secret-test-key" not in response.text
    assert sandbox.post("/api/settings/harness/models/api").status_code == 400


def request_for(tmp_path, runtime, mode="normal", native_id="", model="test-model"):
    env = {**os.environ, "FAKE_HARNESS_MODE": mode,
           "FAKE_HARNESS_AUDIT": str(tmp_path / "audit.jsonl"), "OPENAI_API_KEY": "secret-test-key"}
    return RunRequest("hello", tmp_path, env, native_id, model, "read-only", 10,
                      (sys.executable, str(FIXTURE), runtime))


def audit(tmp_path):
    return [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("runtime,adapter_type", [("codex", CodexAdapter), ("acp", ACPAdapter)])
def test_web_reuses_native_process_and_resumes_after_cleanup(tmp_path, runtime, adapter_type):
    from dataclasses import replace
    from easel.harnesses.rpc import close_sessions

    async def reject(questions):
        raise AssertionError("No permissions expected")

    async def scenario():
        request = replace(request_for(tmp_path, runtime, mode="stable-resume"), session_key="web-session")
        identifiers = []
        events = []
        adapter = adapter_type()
        try:
            for turn in range(2):
                await adapter.run(request, lambda *event: events.append(event), reject, identifiers.append)
                request = replace(request, native_id=identifiers[-1])
            methods = [message.get("method") for message in audit(tmp_path)]
            assert methods.count("initialize") == 1
            assert methods.count("thread/start" if runtime == "codex" else "session/new") == 1
            assert methods.count("turn/start" if runtime == "codex" else "session/prompt") == 2
            assert not any(method in methods for method in ("thread/resume", "session/load"))
            await close_sessions("web-session")
            await adapter.run(request, lambda *event: events.append(event), reject, identifiers.append)
            assert len(set(identifiers)) == 1
            methods = [message.get("method") for message in audit(tmp_path)]
            assert methods.count("initialize") == 2
            from easel import __version__
            assert all(message["params"]["clientInfo"]["version"] == __version__
                       for message in audit(tmp_path) if message.get("method") == "initialize")
            assert methods.count("thread/resume" if runtime == "codex" else "session/load") == 1
            assert events == [("thinking", "思考"), ("token", "你好")] * 3
        finally:
            await close_sessions()

    asyncio.run(scenario())


def test_binding_cannot_silently_replace_native_history(tmp_path):
    store.bind(tmp_path, "conversation", "codex", "original")
    with pytest.raises(HarnessError, match="不会替换已有历史"):
        store.bind(tmp_path, "conversation", "codex", "replacement")
    assert store.binding(tmp_path, "conversation")["native_id"] == "original"


def test_codex_rejects_replacement_thread_on_resume(tmp_path):
    async def reject(questions):
        raise AssertionError("No permissions expected")

    with pytest.raises(HarnessError, match="历史"):
        asyncio.run(CodexAdapter().run(request_for(tmp_path, "codex", native_id="original"),
                                      lambda *args: None, reject, lambda identifier: None))
    assert not any(message.get("method") == "turn/start" for message in audit(tmp_path))


def test_acp_rejects_replacement_session_on_resume(tmp_path):
    async def reject(questions):
        raise AssertionError("No permissions expected")

    with pytest.raises(HarnessError, match="历史"):
        asyncio.run(ACPAdapter().run(request_for(tmp_path, "acp", mode="wrong-resume", native_id="original"),
                                    lambda *args: None, reject, lambda identifier: None))
    assert not any(message.get("method") == "session/prompt" for message in audit(tmp_path))


def test_pooled_connections_isolate_sessions_and_configuration(tmp_path):
    from dataclasses import replace
    from easel.harnesses.rpc import close_sessions, connection

    async def respond(method, params):
        raise AssertionError("No client requests expected")

    async def scenario():
        request = replace(request_for(tmp_path, "codex"), session_key="first")
        try:
            async with connection(request, list(request.command), lambda *args: None, respond) as first:
                result = await first.call("environment", {})
                assert result == {"cwd": str(tmp_path), "root": str(tmp_path)}
                first_pid = first.process.pid
            async with connection(replace(request, session_key="second"), list(request.command),
                                  lambda *args: None, respond) as second:
                assert second.process.pid != first_pid
            async with connection(request, list(request.command), lambda *args: None, respond) as reused:
                assert reused.process.pid == first_pid
            changed = replace(request, model="changed-model")
            async with connection(changed, list(changed.command), lambda *args: None, respond) as reopened:
                assert reopened.process.pid != first_pid
                assert first.process.returncode is not None
        finally:
            await close_sessions()

    asyncio.run(scenario())


def test_pooled_connections_reject_concurrent_turn_and_clean_cancelled_process(tmp_path):
    from dataclasses import replace
    from easel.harnesses.rpc import _POOLS, close_sessions, connection

    async def respond(method, params):
        raise AssertionError("No client requests expected")

    async def scenario():
        request = replace(request_for(tmp_path, "codex"), session_key="busy")
        ready = asyncio.Event()
        processes = []

        async def hold():
            async with connection(request, list(request.command), lambda *args: None, respond) as rpc:
                processes.append(rpc.process)
                ready.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(hold())
        try:
            await asyncio.wait_for(ready.wait(), 5)
            with pytest.raises(HarnessError, match="正在执行"):
                async with connection(request, list(request.command), lambda *args: None, respond):
                    raise AssertionError("Busy session cannot be reused")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert processes[0].returncode is not None
            assert not _POOLS.get(asyncio.get_running_loop())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await close_sessions()

    asyncio.run(scenario())


def test_pooled_connections_expire_and_bound_idle_count(tmp_path, monkeypatch):
    from dataclasses import replace
    import easel.harnesses.rpc as protocol

    monkeypatch.setattr(protocol, "MAX_IDLE_PROCESSES", 2)

    async def respond(method, params):
        raise AssertionError("No client requests expected")

    async def scenario():
        processes = []
        try:
            for index in range(3):
                request = replace(request_for(tmp_path, "codex"), session_key=f"session-{index}")
                async with protocol.connection(request, list(request.command),
                                               lambda *args: None, respond) as rpc:
                    processes.append(rpc.process)
            assert processes[0].returncode is not None
            assert len(protocol._POOLS[asyncio.get_running_loop()]) == 2
            await protocol.close_sessions()
            monkeypatch.setattr(protocol, "IDLE_SECONDS", 0.05)
            async with protocol.connection(request, list(request.command),
                                           lambda *args: None, respond) as rpc:
                expiring = rpc.process
            for attempt in range(100):
                if expiring.returncode is not None:
                    break
                await asyncio.sleep(0.02)
            assert expiring.returncode is not None
            assert not protocol._POOLS.get(asyncio.get_running_loop())
        finally:
            await protocol.close_sessions()

    asyncio.run(scenario())


def test_web_native_working_directory_is_easel_root():
    import inspect

    source = inspect.getsource(web._run_harness_chat)
    assert "RunRequest(message, PROJECT_ROOT" in source
    assert "session_key=sk" in source


def test_settings_blocking_probes_are_offloaded():
    import inspect

    for endpoint in (web.api_harness_settings, web.api_settings_models, web.api_local_agents):
        assert "asyncio.to_thread" in inspect.getsource(endpoint)


@pytest.mark.parametrize("runtime,adapter", [("codex", CodexAdapter), ("acp", ACPAdapter)])
@pytest.mark.parametrize("native_id", ["", "old-native"])
def test_native_events_resume_model_and_binding(tmp_path, runtime, adapter, native_id):
    events = []
    identifiers = []

    async def reject(questions):
        raise AssertionError("No permissions expected")

    asyncio.run(adapter().run(request_for(tmp_path, runtime, mode="stable-resume", native_id=native_id),
                              lambda kind, text: events.append((kind, text)), reject, identifiers.append))
    assert events == [("thinking", "思考"), ("token", "你好")]
    assert identifiers == [native_id or ("native-thread" if runtime == "codex" else "native-session")]
    messages = audit(tmp_path)
    if runtime == "codex":
        start = next(message for message in messages if message.get("method") == ("thread/resume" if native_id else "thread/start"))
        assert start["params"]["approvalPolicy"] == "on-request"
        assert start["params"]["sandbox"] == "read-only"
        assert start["params"]["model"] == "test-model"
        turn = next(message for message in messages if message.get("method") == "turn/start")
        assert turn["params"]["sandboxPolicy"] == {"type": "readOnly"}
    else:
        assert all(message.get("jsonrpc") == "2.0" for message in messages)
        assert any(message.get("method") == ("session/load" if native_id else "session/new") for message in messages)
        model = next(message for message in messages if message.get("method") == "session/set_config_option")
        assert model["params"]["value"] == "test-model"


@pytest.mark.parametrize("runtime,adapter", [("codex", CodexAdapter), ("acp", ACPAdapter)])
@pytest.mark.parametrize("allow", [True, False])
def test_permissions_are_explicit_and_once_only(tmp_path, runtime, adapter, allow):
    async def answer(questions):
        options = questions[0]["options"]
        assert len(options) == 2
        assert "Always" not in str(options)
        return {"permission": [options[0 if allow else 1]["label"]]}

    asyncio.run(adapter().run(request_for(tmp_path, runtime, "permission"),
                              lambda *args: None, answer, lambda identifier: None))
    response = next(message for message in audit(tmp_path) if message.get("id") == "permission-request")
    if runtime == "codex":
        assert response["result"]["decision"] == ("accept" if allow else "decline")
    else:
        assert response["result"]["outcome"]["optionId"] == ("once" if allow else "deny")


@pytest.mark.parametrize("runtime,adapter", [("codex", CodexAdapter), ("acp", ACPAdapter)])
def test_noninteractive_permission_is_error_not_success(tmp_path, runtime, adapter):
    async def reject(questions):
        raise HarnessError("requires interactive approval")

    with pytest.raises(HarnessError, match="流式对话"):
        asyncio.run(adapter().run(request_for(tmp_path, runtime, "permission"),
                                  lambda *args: None, reject, lambda identifier: None))


@pytest.mark.parametrize("runtime,adapter", [("codex", CodexAdapter), ("acp", ACPAdapter)])
@pytest.mark.parametrize("mode", ["error", "exit"])
def test_native_failure_never_succeeds_or_leaks_keys(tmp_path, runtime, adapter, mode):
    async def reject(questions):
        raise AssertionError

    with pytest.raises(HarnessError) as failure:
        asyncio.run(adapter().run(request_for(tmp_path, runtime, mode),
                                  lambda *args: None, reject, lambda identifier: None))
    assert "secret-test-key" not in str(failure.value)


def test_codex_fatal_event_does_not_wait_until_timeout(tmp_path):
    async def reject(questions):
        raise AssertionError

    with pytest.raises(HarnessError, match="执行失败"):
        asyncio.run(asyncio.wait_for(CodexAdapter().run(
            request_for(tmp_path, "codex", "fatal"), lambda *args: None, reject, lambda identifier: None), 5))


def test_acp_cannot_silently_replace_unsupported_history(tmp_path):
    async def reject(questions):
        raise AssertionError

    with pytest.raises(HarnessError, match="不支持历史续接"):
        asyncio.run(ACPAdapter().run(request_for(tmp_path, "acp", "no-resume", "existing"),
                                    lambda *args: None, reject, lambda identifier: None))
    assert not any(message.get("method") == "session/new" for message in audit(tmp_path))


@pytest.mark.parametrize("runtime,adapter,cancel_method", [
    ("codex", CodexAdapter, "turn/interrupt"), ("acp", ACPAdapter, "session/cancel")])
def test_cancel_interrupts_native_turn(tmp_path, runtime, adapter, cancel_method):
    async def exercise():
        async def reject(questions):
            raise AssertionError
        task = asyncio.create_task(adapter().run(request_for(tmp_path, runtime, "hang"),
                                                lambda *args: None, reject, lambda identifier: None))
        for attempt in range(100):
            await asyncio.sleep(0.02)
            path = tmp_path / "audit.jsonl"
            if path.exists() and any(message.get("method") in ("turn/start", "session/prompt") for message in audit(tmp_path)):
                break
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert any(message.get("method") == cancel_method for message in audit(tmp_path))


def test_rpc_stderr_and_invalid_json(tmp_path):
    async def exercise():
        async def reject(*args):
            raise HarnessError("unsupported")
        request = request_for(tmp_path, "codex")
        async with RPC(request, list(request.command), lambda *args: None, reject) as rpc:
            await rpc.call("stderr", {})
            with pytest.raises(HarnessError, match="JSON"):
                await rpc.call("malformed", {})
    asyncio.run(exercise())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_rpc_cleanup_kills_descendants_that_ignore_term(tmp_path):
    async def exercise():
        async def reject(*args):
            raise HarnessError("unsupported")
        request = request_for(tmp_path, "codex")
        async with RPC(request, list(request.command), lambda *args: None, reject) as rpc:
            result = await rpc.call("tree", {})
        return result["pid"]
    child_pid = asyncio.run(exercise())
    for attempt in range(100):
        status = Path(f"/proc/{child_pid}/stat")
        if not status.exists() or status.read_text().split()[2] == "Z":
            break
        __import__("time").sleep(0.02)
    else:
        pytest.fail("Native descendant survived RPC cleanup")


@pytest.mark.parametrize("config", [
    {"runtime": 1}, {"runtime": "unknown"}, {"sandbox": "danger-full-access"},
    {"models": []}, {"models": {"codex": 1}}, {"models": {"codex": "bad\nmodel"}},
])
def test_corrupt_settings_fail_closed(tmp_path, config):
    store.write_json(tmp_path / "_harness" / "config.json", config)
    with pytest.raises(HarnessError):
        store.settings(tmp_path, {})


@pytest.mark.parametrize(("saved", "env", "expected"), [
    ({}, {}, "api"),
    ({}, {"EASEL_CHAT_TRANSPORT": "http"}, "openclaw"),
    ({}, {"EASEL_CHAT_TRANSPORT": "cli"}, "openclaw"),
    ({}, {"EASEL_CHAT_TRANSPORT": "api"}, "api"),
    ({"runtime": "openclaw"}, {}, "openclaw"),
    ({"runtime": "openclaw"}, {"EASEL_CHAT_TRANSPORT": "api"}, "api"),
    ({"runtime": "codex"}, {"EASEL_CHAT_TRANSPORT": "api"}, "codex"),
    ({"runtime": "api"}, {"EASEL_CHAT_TRANSPORT": "http"}, "api"),
    ({"runtime": "api"}, {"EASEL_AGENT_RUNTIME": "codex"}, "codex"),
])
def test_engine_defaults_and_saved_configuration(tmp_path, monkeypatch, saved, env, expected):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    store.write_json(tmp_path / "outputs" / "_harness" / "config.json", saved)
    assert store.settings(tmp_path / "outputs", env)["runtime"] == expected


def test_existing_openclaw_install_keeps_its_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    state_dir = tmp_path / ".openclaw-easel"
    state_dir.mkdir()
    (state_dir / "openclaw.json").write_text("{}", encoding="utf-8")
    assert store.settings(tmp_path / "outputs", {})["runtime"] == "openclaw"
    assert store.settings(tmp_path / "outputs", {
        "EASEL_OPENCLAW_STATE_DIR": str(tmp_path / "new-profile")})["runtime"] == "api"


def test_binding_is_hashed_durable_and_cannot_change_owner(tmp_path):
    store.bind(tmp_path, "../private/session", "codex", "native")
    assert store.binding_path(tmp_path, "../private/session").parent == tmp_path / "harness"
    assert store.binding(tmp_path, "../private/session") == {"runtime": "codex", "native_id": "native"}
    with pytest.raises(HarnessError):
        store.bind(tmp_path, "../private/session", "opencode", "replacement")


@pytest.mark.parametrize("name,script", [("codex", "@openai/codex/bin/codex.js"),
                                       ("opencode", "opencode-ai/bin/opencode")])
def test_windows_npm_launcher_is_shell_free(tmp_path, monkeypatch, name, script):
    launcher = tmp_path / f"{name}.cmd"
    entry = tmp_path / "node_modules" / script
    entry.parent.mkdir(parents=True)
    entry.touch()
    node = str(tmp_path / "node.exe")
    monkeypatch.setattr("easel.harnesses.commands.shutil.which",
                        lambda command: node if command == "node" else str(launcher))
    assert base_command(name) == [node, str(entry)]


def test_windows_opencode_native_executable_launcher(tmp_path, monkeypatch):
    launcher = tmp_path / "opencode.cmd"
    native = tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr("easel.harnesses.commands.shutil.which", lambda command: str(launcher))
    assert base_command("opencode") == [str(native)]


@pytest.mark.parametrize("name,script", [("codex", "@openai/codex/bin/codex.js"),
                                       ("opencode", "opencode-ai/bin/opencode")])
def test_windows_npm_launcher_prefers_adjacent_node(tmp_path, monkeypatch, name, script):
    launcher = tmp_path / f"{name}.cmd"
    entry = tmp_path / "node_modules" / script
    entry.parent.mkdir(parents=True)
    entry.touch()
    node = tmp_path / "node.exe"
    node.touch()
    monkeypatch.setattr("easel.harnesses.commands.shutil.which",
                        lambda command: str(tmp_path / "wrong-node.exe") if command == "node" else str(launcher))
    assert base_command(name) == [str(node), str(entry)]


@pytest.mark.skipif(os.name == "nt", reason="Unix npm shebang layout")
@pytest.mark.parametrize("name", ["codex", "opencode"])
def test_unix_npm_launcher_uses_adjacent_node_without_shell(tmp_path, monkeypatch, name):
    launcher = tmp_path / name
    launcher.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    node = tmp_path / "node"
    node.touch()
    node.chmod(0o755)
    monkeypatch.setattr("easel.harnesses.commands.shutil.which",
                        lambda command: str(tmp_path / "other-node") if command == "node" else str(launcher))
    assert base_command(name) == [str(node), str(launcher)]


@pytest.mark.skipif(os.name == "nt", reason="Unix native launcher layout")
def test_unix_native_opencode_is_not_invoked_with_node(tmp_path, monkeypatch):
    launcher = tmp_path / "opencode"
    launcher.write_bytes(b"\x7fELF executable")
    node = tmp_path / "node"
    node.touch()
    node.chmod(0o755)
    monkeypatch.setattr("easel.harnesses.commands.shutil.which", lambda command: str(launcher))
    assert base_command("opencode") == [str(launcher)]


@pytest.mark.parametrize("runtime", ["openclaw", "opencode", "codex", "acp"])
def test_harness_inspection_handles_inaccessible_installations(monkeypatch, runtime):
    def inaccessible(*args):
        raise PermissionError("cannot inspect installation")
    if runtime == "openclaw":
        from easel import openclaw_cmd
        resolver = Mock(side_effect=inaccessible)
        monkeypatch.setattr(openclaw_cmd, "openclaw_base_cmd", resolver)
    else:
        monkeypatch.setattr(web.harnesses, "acp_command" if runtime == "acp" else "base_command", inaccessible)
    descriptor = web.harnesses.describe(runtime)
    assert descriptor["id"] == runtime
    assert descriptor["installed"] is False


def test_acp_command_is_administrator_argv_not_shell(tmp_path, monkeypatch):
    store.write_json(tmp_path / "outputs" / "_harness" / "acp.json", {"command": ["node", "agent.js", "x;echo bad"]})
    monkeypatch.setattr("easel.harnesses.commands.shutil.which", lambda command: "/usr/bin/node")
    assert acp_command(tmp_path) == ("/usr/bin/node", "agent.js", "x;echo bad")
    store.write_json(tmp_path / "outputs" / "_harness" / "acp.json", {"command": ["node", "bad\narg"]})
    with pytest.raises(HarnessError):
        acp_command(tmp_path)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(web, "ENV_FILE", env)
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(web, "OPENCLAW_SESSIONS_DIR", tmp_path / "openclaw-sessions")
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path / "outputs")
    for name in ("_session_locks", "_RUNNING_CHAT", "_HARNESS_QUESTIONS"):
        monkeypatch.setattr(web, name, {})
    for name in ("_BG_TASKS", "_DIRECT_CHAT_TASKS", "_HARNESS_TASKS", "_STOPPED_CHAT"):
        monkeypatch.setattr(web, name, set())
    monkeypatch.setattr(web.harnesses, "describe", lambda runtime: {
        "id": runtime, "label": runtime, "protocol": "test", "install_hint": "install", "installed": True})
    store.write_json(web.OUTPUTS_DIR / "_harness" / "config.json",
                     {"runtime": "codex", "models": {"codex": "test-model"}, "sandbox": "read-only"})
    local = "http://127.0.0.1:7860"
    with TestClient(web.app, base_url=local, headers={"Origin": local}) as client:
        yield client


def test_web_config_guards_and_no_credential_mutation(sandbox, monkeypatch):
    before = web.ENV_FILE.read_bytes()
    response = sandbox.post("/api/settings/harness", json={"runtime": "opencode", "model": "provider/model"})
    assert response.status_code == 200 and response.json()["runtime"] == "opencode"
    assert web.ENV_FILE.read_bytes() == before
    assert sandbox.post("/api/settings/harness", json={"runtime": "codex", "sandbox": "danger-full-access"}).status_code == 400
    assert sandbox.post("/api/settings/harness", json={"runtime": "unknown"}).status_code == 400
    monkeypatch.setattr(web.harnesses, "describe", lambda runtime: {"installed": False})
    assert sandbox.post("/api/settings/harness", json={"runtime": "codex"}).status_code == 409
    monkeypatch.setattr(web, "_HARNESS_TASKS", {"active"})
    assert sandbox.post("/api/settings/harness", json={"runtime": "openclaw"}).status_code == 409
    web._HARNESS_TASKS.clear()


def test_dotenv_runtime_override_cannot_appear_to_save(sandbox):
    web.ENV_FILE.write_text("EASEL_AGENT_RUNTIME=codex\n", encoding="utf-8")
    assert sandbox.get("/api/settings/harness").json()["locked"]
    assert sandbox.post("/api/settings/harness", json={"runtime": "opencode"}).status_code == 409


def test_switching_chat_only_preserves_other_engine_settings_and_credentials(sandbox, monkeypatch):
    original = web.ENV_FILE.read_bytes()
    monkeypatch.setattr(web.harnesses, "describe", lambda runtime: {"installed": False})
    response = sandbox.post("/api/settings/harness", json={"runtime": "api"})
    assert response.status_code == 200
    assert response.json()["runtime"] == "api"
    assert response.json()["models"]["codex"] == "test-model"
    assert web.ENV_FILE.read_bytes() == original
    bootstrap = sandbox.get("/api/settings/bootstrap").json()
    assert bootstrap["modelConfigured"] is False
    assert sandbox.post("/api/gateway/restart").json()["ok"] is True
    assert sandbox.post("/api/settings/harness", json={"runtime": "openclaw"}).json()["runtime"] == "openclaw"
    monkeypatch.setattr(web.harnesses, "describe", lambda runtime: {"installed": True})
    response = sandbox.post("/api/settings/harness", json={"runtime": "codex", "model": "test-model"})
    assert response.json()["models"]["codex"] == "test-model"
    assert web.ENV_FILE.read_bytes() == original


def test_legacy_chat_only_switch_to_openclaw_updates_only_transport(sandbox, monkeypatch):
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    web.ENV_FILE.write_text("EASEL_CHAT_TRANSPORT=api\nEASEL_DIRECT_API_KEY=keep-secret\n", encoding="utf-8")
    response = sandbox.post("/api/settings/harness", json={"runtime": "openclaw"})
    assert response.status_code == 200
    assert response.json()["runtime"] == "openclaw"
    assert "EASEL_CHAT_TRANSPORT=http" in web.ENV_FILE.read_text()
    assert "EASEL_DIRECT_API_KEY=keep-secret" in web.ENV_FILE.read_text()
    assert response.json()["models"]["codex"] == "test-model"


def test_legacy_connection_endpoint_respects_task_lock_and_preserves_settings(sandbox, monkeypatch):
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    monkeypatch.setattr(web, "_HARNESS_TASKS", {"active"})
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "api"}).status_code == 409
    web._HARNESS_TASKS.clear()
    response = sandbox.post("/api/settings/chat/transport", json={"transport": "api"})
    assert response.status_code == 200
    config = web._harness_settings()
    assert config["runtime"] == "api"
    assert config["models"]["codex"] == "test-model"
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "openclaw"}).status_code == 200
    assert web._harness_settings()["runtime"] == "openclaw"


@pytest.mark.parametrize("prefix", ["", "web:"])
def test_old_openclaw_history_is_not_silently_replaced(sandbox, prefix):
    web.OPENCLAW_SESSIONS_DIR.mkdir()
    (web.OPENCLAW_SESSIONS_DIR / f"{web._openclaw_session_id(prefix + 'old')}.jsonl").write_text("{}")
    assert sandbox.post("/api/chat", json={"sessionId": "old", "message": "hello"}).status_code == 409
    assert not store.binding(web.SESSIONS_DIR, "old")


def test_old_gateway_settings_endpoints_do_not_run_for_native(sandbox):
    assert sandbox.post("/api/settings/models/selftest", json={"channel": "chat"}).status_code == 409
    assert sandbox.post("/api/chat/question/answer", json={"questionId": "old", "answers": {}}).status_code == 409
    assert sandbox.post("/api/settings/models/save", json={"channel": " chat ", "rows": []}).status_code == 409


def test_background_skill_runs_on_web_loop_without_openclaw(sandbox, monkeypatch):
    requests = []

    class Fake:
        async def run(self, request, emit, ask, bind):
            assert asyncio.get_running_loop() is web._HARNESS_LOOP
            requests.append(request)
            bind("skill-native")
            emit("token", "skill complete")

    monkeypatch.setattr(web.harnesses, "adapter", lambda runtime: Fake())
    assert web.run_agent_sync("read public skill", timeout=10) == "skill complete"
    assert requests[0].prompt == "read public skill"
    assert not web._RUNNING_CHAT and not web._HARNESS_TASKS


def test_new_harness_settings_reject_cross_site_write(sandbox):
    response = sandbox.post("/api/settings/harness", json={"runtime": "opencode"},
                            headers={"Origin": "https://hostile.example"})
    assert response.status_code == 403


def test_web_stream_replay_resume_and_delete(sandbox, monkeypatch):
    requests = []

    class Fake:
        async def run(self, request, emit, ask, bind):
            requests.append(request)
            bind("durable-native")
            emit("thinking", "思考")
            emit("token", "成功")

    monkeypatch.setattr(web.harnesses, "adapter", lambda runtime: Fake())
    for turn_id in ("first", "second"):
        response = sandbox.post("/api/chat/stream", json={"message": "hello", "sessionId": "same", "turnId": turn_id})
        assert response.status_code == 200
        assert "event: token" in response.text and "成功" in response.text
        assert "event: thinking" in response.text and "event: done" in response.text
    assert requests[0].native_id == "" and requests[1].native_id == "durable-native"
    assert all(request.model == "test-model" for request in requests)
    last = sandbox.get("/api/chat/last/same").json()
    assert last["text"] == "成功" and last["clean_end"] is True
    assert "成功" in sandbox.get("/api/chat/jobs/second/stream").text
    assert sandbox.post("/api/settings/harness", json={"runtime": "opencode"}).status_code == 200
    assert sandbox.post("/api/chat", json={"sessionId": "same", "message": "hello"}).status_code == 409
    assert sandbox.delete("/api/session/same").json()["deleted"]
    assert not store.binding(web.SESSIONS_DIR, "same")


def test_native_stream_disconnect_keeps_background_turn_and_result(sandbox, monkeypatch):
    async def exercise():
        started = asyncio.Event()
        finish = asyncio.Event()

        class Fake:
            async def run(self, request, emit, ask, bind):
                bind("disconnect-native")
                started.set()
                await finish.wait()
                emit("token", "断线后完成")

        monkeypatch.setattr(web.harnesses, "adapter", lambda runtime: Fake())
        response = await web.api_chat_stream(web.ChatRequest(
            message="hello", sessionId="disconnect", turnId="disconnect-turn"))
        await response.body_iterator.__anext__()
        await asyncio.wait_for(started.wait(), 2)
        await response.body_iterator.aclose()
        assert web._RUNNING_CHAT and web._HARNESS_TASKS
        tasks = list(web._BG_TASKS)
        assert tasks and all(not task.done() for task in tasks)
        finish.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 2)
        await asyncio.sleep(0)
        result = await web.api_chat_last("disconnect")
        assert result["text"] == "断线后完成" and result["clean_end"] is True
        assert not web._RUNNING_CHAT and not web._HARNESS_TASKS and not web._BG_TASKS
        events = web._read_job_events("disconnect-turn", 0)
        assert any(event["event"] == "token" and event["data"] == "断线后完成" for event in events)
        assert events[-1]["event"] == "done"

    asyncio.run(exercise())


def test_acp_command_config_cannot_be_overwritten_or_deleted_by_content_routes(sandbox):
    config = web.OUTPUTS_DIR / "_harness" / "acp.json"
    store.write_json(config, {"command": ["opencode", "acp"]})
    before = config.read_bytes()
    assert sandbox.delete("/api/output/_harness/acp.json").status_code == 403
    response = sandbox.post("/api/upload", data={"sessionId": "config-test"}, files={
        "files": ("../../_harness/acp.json", b'{"command":["other-agent"]}', "application/json")})
    assert response.status_code == 200
    uploaded = response.json()["files"][0]["path"]
    assert uploaded.startswith("_inbox/")
    assert config.read_bytes() == before


def test_web_stop_timeout_and_lock_cleanup(sandbox, monkeypatch):
    async def exercise():
        started = asyncio.Event()

        class Fake:
            async def run(self, request, emit, ask, bind):
                bind("durable-native")
                started.set()
                await asyncio.Future()

        monkeypatch.setattr(web.harnesses, "adapter", lambda runtime: Fake())
        events = []
        emit = lambda kind, text: events.append((kind, text))
        req = web.ChatRequest(message="hello", sessionId="stoppable")
        task = asyncio.create_task(web._run_harness_chat(req, "stoppable", "hello", "codex",
                                                       web._harness_settings(), emit))
        await asyncio.wait_for(started.wait(), 3)
        result = await web.api_chat_stop(web.StopRequest(sessionId="stoppable"))
        await task
        assert result["stopped"] and not web._RUNNING_CHAT and not web._HARNESS_TASKS
        assert not web._session_lock("stoppable").locked()
        last = json.loads(web._turn_file("web:stoppable").read_text(encoding="utf-8"))
        assert last["stop_reason"] == "stopped" and not last["clean_end"]
        await web._run_harness_chat(req, "stoppable", "hello", "codex", web._harness_settings(), emit, timeout=0.1)
        last = json.loads(web._turn_file("web:stoppable").read_text(encoding="utf-8"))
        assert last["stop_reason"] == "timeout" and not web._session_lock("stoppable").locked()
        assert "执行超时" in last["text"]

    asyncio.run(exercise())


def test_repeated_stop_does_not_interrupt_process_cleanup(monkeypatch):
    async def exercise():
        ready = asyncio.Event()
        cleanup_started = asyncio.Event()
        finish_cleanup = asyncio.Event()
        completed = []

        async def run():
            ready.set()
            try:
                await asyncio.Future()
            finally:
                cleanup_started.set()
                await finish_cleanup.wait()
                completed.append(True)

        proc = web._HarnessProc()
        proc._task = asyncio.create_task(run())
        cancel = Mock(wraps=proc._task.cancel)
        monkeypatch.setattr(proc._task, "cancel", cancel)
        await ready.wait()
        proc.terminate()
        await cleanup_started.wait()
        proc.kill()
        await asyncio.sleep(0)
        assert cancel.call_count == 1
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await proc._task
        assert completed == [True]

    asyncio.run(exercise())


def test_failed_ownership_check_does_not_overwrite_previous_result(sandbox):
    store.bind(web.SESSIONS_DIR, "old", "opencode", "native-old")
    web._save_turn("web:old", "done", "previous result", {"clean_end": True})
    events = []
    asyncio.run(web._run_harness_chat(web.ChatRequest(message="hello"), "old", "hello", "codex",
                                     web._harness_settings(), lambda kind, text: events.append((kind, text))))
    assert any(kind == "error" for kind, text in events)
    assert json.loads(web._turn_file("web:old").read_text())["text"] == "previous result"


def test_web_question_answer_and_cancellation_cleanup(sandbox):
    async def exercise():
        events = []
        task = asyncio.create_task(web._harness_ask("question-session", [
            {"questionId": "permission", "question": "Allow?", "options": [{"label": "允许本次"}, {"label": "拒绝"}]}
        ], lambda kind, text: events.append((kind, text))))
        await asyncio.sleep(0)
        identifier = next(iter(web._HARNESS_QUESTIONS))
        result = await web.api_question_answer(web.QuestionAnswerRequest(
            questionId=identifier, answers={"permission": ["拒绝"]}))
        assert result["ok"] and await task == {"permission": ["拒绝"]}
        assert not web._HARNESS_QUESTIONS
        task = asyncio.create_task(web._harness_ask("question-session", [
            {"questionId": "permission", "question": "Allow?", "options": []}
        ], lambda *args: None))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not web._HARNESS_QUESTIONS

    asyncio.run(exercise())
