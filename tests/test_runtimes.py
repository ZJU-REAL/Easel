from __future__ import annotations

import json
import sys

import pytest

import easel.runtimes as runtimes
from easel.runtimes import common, openclaw, opencode
from easel.runtimes.base import RunRequest


class FakeProc:
    """最小进程面：stdout 可迭代 + poll/wait/terminate/kill，供 handle 单测复用。"""

    def __init__(self, returncode=0, stdout_lines=()):
        self.returncode = returncode
        self.stdout = iter(stdout_lines)
        self.terminated = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminate()


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


@pytest.mark.parametrize("version,expected", [
    (None, (True, "24.16")),          # 未装：按 openclaw@latest 从严
    ((2026, 9, 5), (True, "24.16")),  # 2026.9.x 引擎 >=24.16
    ((2026, 6, 11), (False, "22.19")),  # 2026.6.x 实测 engines >=22.19，不是 20.10
])
def test_openclaw_node_requirement(monkeypatch, version, expected):
    monkeypatch.setattr(openclaw, "openclaw_version", lambda: version)
    assert openclaw.node_requirement() == expected


def test_opencode_node_requirement_floor():
    assert opencode.OpenCodeAdapter().node_requirement() == (False, "20.10")


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


# ---- OpenClaw 回合句柄：共享 raw 流 / HTTP / 桥接 / 取消 ----


def test_openclaw_handle_consumes_only_own_run_events(tmp_path, monkeypatch):
    raw = tmp_path / "raw.jsonl"
    raw.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in [
        {"event": "assistant_text_stream", "evtType": "text_delta", "runId": "run-a", "delta": "自己的回答"},
        {"event": "assistant_thinking_stream", "evtType": "thinking_delta", "runId": "run-b", "delta": "别的会话的思考"},
        {"event": "assistant_text_stream", "evtType": "text_delta", "runId": "run-b", "delta": "混入的正文"},
        {"event": "assistant_message_end", "runId": "run-a"},
    ]) + "\n", encoding="utf-8")
    monkeypatch.setattr(openclaw, "SHARED_RAW_STREAM", raw)

    handle = openclaw.OpenClawRunHandle(FakeProc(), "sk", False, transport="cli", raw_start_offset=0)
    events = list(handle.events())
    result = handle.wait()

    assert [e.text for e in events if e.type == "text"] == ["自己的回答"]
    assert all(not (e.type == "text" and e.text == "混入的正文") for e in events)
    assert result.text == "自己的回答"
    assert result.clean_end is True                      # 最后事件是 assistant_message_end
    assert result.diagnostics["ignored_foreign_events"] == 2
    assert result.diagnostics["last_ev"] == "assistant_message_end"
    handle.close()


def test_openclaw_handle_http_turn_parses_sse(monkeypatch):
    class FakeResponse:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"先想"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"你好"}}]}'
            yield 'data: {"choices":[{"delta":{"tool_calls":[{"id":"t1"}]}}]}'
            yield "data: [DONE]"

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def stream(self, *_args, **_kwargs):
            return FakeResponse()

    class FakeHttpx:
        Timeout = staticmethod(lambda *_args, **_kwargs: None)
        Client = FakeClient

    monkeypatch.setitem(sys.modules, "httpx", FakeHttpx)

    handle = openclaw.OpenClawRunHandle(
        openclaw._GatewayHttpProc(), "sk", False, transport="http",
        http_payload=({"model": "openclaw/default"}, {}, 30),
    )
    events = list(handle.events())
    result = handle.wait()

    assert [e.text for e in events if e.type == "text"] == ["你好"]
    assert [e.text for e in events if e.type == "thinking"] == ["先想"]
    assert [e.text for e in events if e.type == "activity"] == ["🔧 正在执行操作…"]
    assert result.returncode == 0
    assert result.clean_end is True                      # 收到 [DONE]
    assert result.diagnostics["last_ev"] == "assistant_message_end"


def test_openclaw_http_transport_falls_back_to_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(openclaw, "CHAT_TRANSPORT", "http")
    monkeypatch.setattr(openclaw, "gateway_http_ready", lambda: False)
    monkeypatch.setattr(openclaw, "openclaw_base_cmd", lambda: ["/bin/openclaw"])
    monkeypatch.setattr(openclaw, "_heal_session", lambda _sk: None)
    monkeypatch.setattr(openclaw, "askuser_cards_enabled", lambda: False)
    monkeypatch.setattr(openclaw, "SHARED_RAW_STREAM", tmp_path / "missing.jsonl")
    seen = {}

    def popen(cmd, **_kwargs):
        seen["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(openclaw.subprocess, "Popen", popen)
    adapter = openclaw.OpenClawAdapter()
    handle = adapter.start(RunRequest("hi", "sk", 5, tmp_path, {}, None, "low", True))

    assert handle.transport == "cli"
    assert "--profile" in seen["cmd"] and "agent" in seen["cmd"]
    handle.close()


def test_openclaw_question_bridge_circuit_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(openclaw, "SHARED_RAW_STREAM", tmp_path / "missing.jsonl")
    monkeypatch.setattr(openclaw, "_QBRIDGE_DISABLED", False)
    monkeypatch.setattr(openclaw, "_QBRIDGE_WARNED", set())
    monkeypatch.setattr(openclaw, "askuser_cards_enabled", lambda: False)

    handle = openclaw.OpenClawRunHandle(FakeProc(), "sk", True, transport="cli", raw_start_offset=0)
    handle._poll_questions()

    assert openclaw._QBRIDGE_DISABLED is True
    handle.close()


def test_openclaw_cli_wait_falls_back_to_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(openclaw, "SHARED_RAW_STREAM", tmp_path / "missing.jsonl")
    proc = FakeProc(stdout_lines=["[provider-x] 噪声\n", "最终回答\n"])

    handle = openclaw.OpenClawRunHandle(proc, "sk", False, transport="cli", raw_start_offset=0)
    events = list(handle.events())
    result = handle.wait()

    assert events == []                      # 没有 raw 流事件（无常驻 gateway 写入）
    assert result.text == "最终回答"          # 退回清洗后的 stdout
    assert result.clean_end is False
    handle.close()


def test_openclaw_cli_cancel_terminates_process(tmp_path, monkeypatch):
    monkeypatch.setattr(openclaw, "SHARED_RAW_STREAM", tmp_path / "missing.jsonl")
    proc = FakeProc(returncode=None)

    handle = openclaw.OpenClawRunHandle(proc, "sk", False, transport="cli", raw_start_offset=0)
    handle.cancel()

    assert proc.terminated is True
    assert handle.poll() == -15
    handle.close()
