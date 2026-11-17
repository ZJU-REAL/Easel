import asyncio
import pytest
from easel.harnesses.base import RunRequest, HarnessError
from easel.harnesses import codex_login, codex_diagnostics

async def noop(*a, **kw): pass

def test_logout_blocks_concurrent_login(tmp_path, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class RPC:
            def __init__(self, *args): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def call(self, method, *args, **kw):
                if method == "account/logout":
                    entered.set()
                    await release.wait()
                    return {}
                if method == "account/login/start":
                    return {"loginId": "test", "authUrl": "https://chatgpt.com/test"}
                return {}
            async def wait_notification(self, future): return await future
        monkeypatch.setattr(codex_login, "RPC", RPC)
        monkeypatch.setattr(codex_login, "initialize", noop)
        monkeypatch.setattr(codex_login, "close_sessions", noop)
        login = codex_login.CodexLogin()
        request = RunRequest("", tmp_path, {}, command=("unused",))
        task = asyncio.create_task(login.logout(request))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            with pytest.raises(HarnessError):
                await asyncio.wait_for(login.start(request), 1)
        finally:
            release.set()
            await task
            await login.close()
    asyncio.run(scenario())

@pytest.mark.parametrize("account", [{"type": "invalid"}, [], "private-token"])
def test_account_schema_errors_are_unknown_not_authenticated(tmp_path, monkeypatch, account):
    class RPC:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def call(self, method, *args, **kw):
            return {"account": account, "requiresOpenaiAuth": True} if method == "account/read" else {}
    monkeypatch.setattr(codex_diagnostics, "RPC", RPC)
    monkeypatch.setattr(codex_diagnostics, "initialize", noop)
    result = asyncio.run(codex_diagnostics.account_status(RunRequest("", tmp_path, {}, command=("unused",))))
    assert result["state"] == "unknown"
    assert "private-token" not in str(result)

def test_probe_invalid_thread_shape_returns_safe_failure(tmp_path, monkeypatch):
    class RPC:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def call(self, method, *args, **kw): return {"thread": {}}
    monkeypatch.setattr(codex_diagnostics, "RPC", RPC)
    monkeypatch.setattr(codex_diagnostics, "initialize", noop)
    result = asyncio.run(codex_diagnostics.probe(RunRequest("", tmp_path, {}, command=("unused",))))
    assert result["ok"] is False and result["error"]["code"] == "unknown"


from tests.test_agent_harnesses import sandbox

def test_logout_state_blocks_probe_settings_and_other_auth(sandbox, monkeypatch, tmp_path):
    import web.app as web
    monkeypatch.setattr(web._CODEX_LOGIN, "logging_out", True)
    monkeypatch.setattr(web, "_codex_diagnostic_request", lambda *a: RunRequest("", tmp_path, {}, command=("unused",)))
    assert sandbox.post("/api/settings/harness/codex/probe", json={}).status_code == 409
    assert sandbox.post("/api/settings/harness/codex/login", json={}).status_code == 409
    assert sandbox.post("/api/settings/harness/codex/logout").status_code == 409
    assert sandbox.post("/api/settings/harness", json={"runtime": "api"}).status_code == 409
    assert sandbox.post("/api/settings/chat/transport", json={"transport": "api"}).status_code == 409
    assert sandbox.get("/api/settings/harness/codex/status").json()["state"] == "unknown"


from dataclasses import replace
from tests.test_agent_harnesses import request_for
from easel.harnesses.codex import CodexAdapter

@pytest.mark.parametrize("command,secret", [
    ("API_KEY='synthetic spaced credential' command", "synthetic spaced credential"),
    ("curl -H 'Authorization: Basic synthetic-credential' https://example.test", "synthetic-credential"),
    ("curl https://user:synthetic-credential@example.test", "synthetic-credential"),
    ("command --password synthetic-credential", "synthetic-credential"),
])
def test_progress_redacts_literal_credentials_not_present_in_environment(tmp_path, command, secret):
    request = request_for(tmp_path, "codex", "progress")
    request = replace(request, env={**request.env, "FAKE_PROGRESS_COMMAND": command})
    events = []
    async def ask(*args): return {"permission": ["允许本次"]}
    asyncio.run(CodexAdapter().run(request, lambda *args: events.append(args), ask, lambda value: None))
    activities = str([value for kind, value in events if kind == "activity"])
    assert secret not in activities
    assert "退出码 0" in activities
