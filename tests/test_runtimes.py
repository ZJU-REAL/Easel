from __future__ import annotations

import json

import pytest

import easel.runtimes as runtimes
from easel.runtimes import common, openclaw, opencode


def test_registry_defaults_to_openclaw_and_lists_builtins(tmp_path, monkeypatch):
    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)
    monkeypatch.setattr(runtimes, "env_file_value", lambda _name: None)
    assert runtimes.get_runtime().descriptor.id == "openclaw"
    assert [item.id for item in runtimes.list_runtimes()] == ["openclaw", "opencode"]


def test_registry_selects_from_environment(monkeypatch):
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "opencode")
    assert runtimes.get_runtime().descriptor.id == "opencode"


def test_registry_rejects_unknown_runtime(monkeypatch):
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "unknown")
    with pytest.raises(ValueError, match="openclaw, opencode"):
        runtimes.get_runtime()


def test_optional_operations_have_uniform_unsupported_result():
    adapter = runtimes.get_runtime("opencode")
    result = adapter.answer_question(runtimes.QuestionAnswer("q", {}))
    assert result.ok is False
    assert result.code == 2
    assert "不支持" in result.reason


def test_status_descriptor_is_json_ready():
    value = runtimes.get_runtime("openclaw").descriptor.as_dict()
    assert value["id"] == "openclaw"
    assert value["label"] == "OpenClaw"
    assert isinstance(value["capabilities"], list)


@pytest.mark.parametrize("runtime_id,module_name,executable", [
    ("openclaw", "openclaw", "openclaw"),
    ("opencode", "opencode", "opencode"),
])
def test_setup_reuses_installed_runtime(runtime_id, module_name, executable, tmp_path, monkeypatch):
    module = __import__(f"easel.runtimes.{module_name}", fromlist=[module_name])
    monkeypatch.setattr(module.shutil, "which", lambda name: f"/bin/{executable}" if name == executable else None)
    if runtime_id == "openclaw":
        monkeypatch.setattr(module, "openclaw_base_cmd", lambda: [f"/bin/{executable}"])
    else:
        monkeypatch.setattr(module, "base_cmd", lambda: [f"/bin/{executable}"])
    result = runtimes.get_runtime(runtime_id).setup(runtimes.SetupContext(tmp_path, {}))
    assert result.ok


def test_openclaw_interactive_command_stays_inside_adapter(monkeypatch):
    seen = {}
    monkeypatch.setattr(openclaw, "openclaw_base_cmd", lambda: ["node", "/fake/openclaw.mjs"])

    class Completed:
        returncode = 0

    def run(command, **kwargs):
        seen["command"] = command
        return Completed()

    monkeypatch.setattr(openclaw.subprocess, "run", run)
    assert runtimes.get_runtime("openclaw").open_chat("画像提示") == 0
    command = seen["command"]
    assert command[:2] == ["node", "/fake/openclaw.mjs"]
    assert "tui" in command and "--timeout-ms" in command
    assert command[-2:] == ["--message", "画像提示"]


def test_opencode_event_parser():
    event = opencode.parse_event(json.dumps({
        "type": "text", "sessionID": "ses_123",
        "part": {"type": "text", "text": "你好"},
    }))
    assert event is not None
    assert event.type == "text"
    assert event.text == "你好"
    assert event.data == {"session_id": "ses_123"}


@pytest.mark.parametrize("lines,detail", [
    ([json.dumps({"type": "error", "error": {"name": "APIError", "data": {
        "message": "An active OpenCode Go subscription is required to use Go models.",
    }}})], "subscription"),
    ([], "没有返回正文"),
])
def test_opencode_zero_exit_does_not_hide_model_failure(lines, detail):
    from types import SimpleNamespace
    handle = opencode.OpenCodeRunHandle(SimpleNamespace(stdout=iter(lines), wait=lambda: 0), None)
    assert list(handle.events()) == []
    result = handle.wait()
    assert result.returncode != 0
    assert not result.clean_end
    assert detail in result.diagnostics["error"]


def test_opencode_server_url_uses_configured_port(monkeypatch):
    monkeypatch.delenv("EASEL_OPENCODE_URL", raising=False)
    monkeypatch.setenv("EASEL_OPENCODE_PORT", "4096")
    assert opencode.server_url() == "http://127.0.0.1:4096"


def test_opencode_windows_npm_shim_resolves_native_binary(tmp_path, monkeypatch):
    shim = tmp_path / "opencode.cmd"
    native = tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr(opencode.shutil, "which", lambda _name: str(shim))
    assert opencode.base_cmd() == [str(native)]


def test_opencode_request_uses_server_basic_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)
    monkeypatch.setattr(common, "ENV_FILE", tmp_path / ".env")
    common.ENV_FILE.write_text("OPENCODE_SERVER_PASSWORD=secret\n", encoding="utf-8")
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"{}"

    def open_request(request, timeout):
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(opencode.urllib.request, "urlopen", open_request)
    assert opencode.request("GET", "/global/health") == {}
    assert seen == {"authorization": "Basic b3BlbmNvZGU6c2VjcmV0", "timeout": 15}


def test_opencode_health_requires_healthy_response(monkeypatch):
    adapter = runtimes.get_runtime("opencode")
    monkeypatch.setattr(opencode, "request", lambda *_args: {"healthy": True})
    assert adapter.health().ok
    monkeypatch.setattr(opencode, "request", lambda *_args: {"healthy": False})
    assert not adapter.health().ok
