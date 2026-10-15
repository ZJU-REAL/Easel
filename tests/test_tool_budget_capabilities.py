import asyncio
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from easel import harnesses
from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.capabilities import require_tool_budget, tool_budget_capability


@pytest.mark.parametrize("runtime", ["codex", "acp", "opencode", "openclaw"])
def test_strict_requirement_does_not_trust_installed_or_claimed_capability(runtime):
    with pytest.raises(HarnessError, match="本次任务未启动"):
        require_tool_budget(runtime, {"EASEL_REQUIRE_TOOL_BUDGET": "1",
                                     "EASEL_TOOL_BUDGET_VERIFIED": "1"})
    require_tool_budget(runtime, {})
    assert not tool_budget_capability(runtime)["enforcement_verified"]


def test_chat_only_cannot_execute_tools_and_unknown_backend_is_rejected():
    require_tool_budget("api", {"EASEL_REQUIRE_TOOL_BUDGET": "1"})
    assert tool_budget_capability("api")["admission"] == "no_tools"
    with pytest.raises(HarnessError):
        require_tool_budget("future", {"EASEL_REQUIRE_TOOL_BUDGET": "1"})


@pytest.mark.parametrize("value", ["true", "", "yes", "2", None, True, 1])
def test_invalid_policy_is_not_silently_disabled(value):
    with pytest.raises(HarnessError):
        require_tool_budget("api", {"EASEL_REQUIRE_TOOL_BUDGET": value})


@pytest.mark.parametrize("runtime", ["codex", "acp", "opencode"])
def test_adapter_rejects_before_subprocess_resolution_or_callbacks(runtime, tmp_path, monkeypatch):
    import easel.harnesses.acp as acp
    import easel.harnesses.codex as codex

    forbidden = Mock(side_effect=AssertionError("Dispatched before capability check"))
    for module in (acp, codex):
        monkeypatch.setattr(module, "connection", forbidden)
        monkeypatch.setattr(module, "base_command", forbidden)
    request = RunRequest("do work", tmp_path, {"EASEL_REQUIRE_TOOL_BUDGET": "1"})
    with pytest.raises(HarnessError, match="本次任务未启动"):
        asyncio.run(harnesses.adapter(runtime).run(request, forbidden, forbidden, forbidden))
    forbidden.assert_not_called()


@pytest.mark.parametrize("runtime", ["codex", "acp", "opencode", "openclaw"])
def test_web_stream_and_sync_fail_before_binding_or_dispatch(runtime, tmp_path, monkeypatch):
    import web.app as web

    forbidden = Mock(side_effect=AssertionError("Unexpected side effect"))
    monkeypatch.setattr(web, "_direct_api_enabled", lambda: False)
    monkeypatch.setattr(web, "_harness_settings", lambda: {"runtime": runtime})
    monkeypatch.setattr(web, "read_settings", lambda *a: {"EASEL_REQUIRE_TOOL_BUDGET": "1"})
    monkeypatch.setattr(web.harness_store, "binding", forbidden)
    monkeypatch.setattr(web, "_chat_message", forbidden)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(web.api_chat_stream(web.ChatRequest(message="hello", sessionId="existing")))
    assert caught.value.status_code == 409
    with pytest.raises(HTTPException):
        web.run_agent_sync("hello", session_id="existing")
    forbidden.assert_not_called()


def test_cli_ping_and_skill_reject_before_work(monkeypatch):
    from easel.commands import ping, skill

    monkeypatch.setattr(harnesses, "settings", lambda *a: {"runtime": "openclaw"})
    for module, command in ((ping, ping.cmd_ping), (skill, skill.cmd_skill)):
        monkeypatch.setattr(module, "read_settings", lambda: {"EASEL_REQUIRE_TOOL_BUDGET": "1"})
        with pytest.raises(HarnessError, match="本次任务未启动"):
            command(None)


def test_descriptor_distinguishes_installation_and_enforcement(monkeypatch):
    monkeypatch.setattr(harnesses, "base_command", lambda *a: ["installed"])
    descriptor = harnesses.describe("codex")
    assert descriptor["installed"]
    assert descriptor["tool_budget"] == {"admission": "observation_only", "enforcement_verified": False,
                                         "reason": "adapter_has_no_universal_pre_execution_gate"}
