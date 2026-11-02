"""Read-only native policy diagnostics must not claim enforcement."""
import json

import pytest

from easel.commands import doctor


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Exercise the shared profile resolver, not a second hard-coded config path.
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    return tmp_path / "openclaw.json"


@pytest.mark.parametrize("value,state", [
    (True, "显式开启"), (False, "显式关闭"),
    ("false", "格式异常"), (0, "格式异常"), (1, "格式异常"),
    (None, "格式异常"), ({}, "格式异常"),
])
def test_switch_requires_boolean_and_preserves_config(config, value, state):
    source = json.dumps({"tools": {"loopDetection": {"enabled": value}},
                         "models": {"apiKey": "PRIVATE-KEY"}}).encode()
    config.write_bytes(source)
    before = config.stat().st_mtime_ns
    lines = doctor._tool_loop_policy()
    assert lines == [f"tools.loopDetection.enabled：{state}"]
    assert config.read_bytes() == source
    assert config.stat().st_mtime_ns == before
    assert "PRIVATE-KEY" not in "\n".join(lines)


@pytest.mark.parametrize("data", [{}, {"tools": {}}, {"tools": {"loopDetection": {}}}])
def test_unset_is_not_reported_as_disabled(config, data):
    config.write_text(json.dumps(data), encoding="utf-8-sig")
    assert doctor._tool_loop_policy() == ["tools.loopDetection.enabled：未设置"]


@pytest.mark.parametrize("data", [{"tools": None}, {"tools": []},
                                      {"tools": {"loopDetection": False}}])
def test_malformed_scope_is_unknown_not_unset(config, data):
    config.write_text(json.dumps(data), encoding="utf-8")
    assert "格式异常" in doctor._tool_loop_policy()[0]


@pytest.mark.parametrize("source", [b"{invalid PRIVATE-KEY", b"\xff", b"[]"])
def test_unreadable_or_invalid_config_does_not_leak_payload(config, source):
    config.write_bytes(source)
    lines = doctor._tool_loop_policy()
    assert len(lines) == 1 and "未知" in lines[0]
    assert "PRIVATE-KEY" not in lines[0]


def test_missing_config_is_not_created(config):
    assert "未知" in doctor._tool_loop_policy()[0]
    assert not config.exists()


def test_agent_overrides_are_counted_separately_from_global(config):
    entries = [{"tools": {"loopDetection": {"enabled": value}}}
               for value in (True, False, "false")] + [{}]
    config.write_text(json.dumps({"tools": {"loopDetection": {"enabled": True}},
                                  "agents": {"list": entries, "entries": {"PRIVATE-ID": entries[1]}}}),
                      encoding="utf-8")
    lines = doctor._tool_loop_policy()
    assert "显式开启" in lines[0]
    assert lines[1] == "agents.list 的 Agent 开关：显式开启 1，显式关闭 1，未设置 1，格式异常 1"
    assert lines[2] == "agents.entries 的 Agent 开关：显式开启 0，显式关闭 1，未设置 0，格式异常 0"
    assert "同时存在" in lines[3]
    assert "PRIVATE-ID" not in "\n".join(lines)


@pytest.mark.parametrize("agents", [None, [], {"list": {}}, {"entries": []}])
def test_malformed_agent_layout_is_reported(config, agents):
    config.write_text(json.dumps({"agents": agents}), encoding="utf-8")
    assert "无法检查 Agent 覆盖" in doctor._tool_loop_policy()[1]


@pytest.mark.parametrize("runtime", ["api", "codex", "openclaw"])
def test_doctor_only_reports_for_openclaw_without_changing_exit_code(config, monkeypatch, capsys, runtime):
    from easel import harnesses
    from easel import local_agents

    monkeypatch.setattr(harnesses, "settings", lambda *args: {"runtime": runtime})
    monkeypatch.setattr(harnesses, "describe", lambda *args: {"installed": True, "install_hint": ""})
    monkeypatch.setattr(doctor, "PROJECT_ROOT", config.parent)
    monkeypatch.setattr(doctor, "_check", lambda *args: True)
    monkeypatch.setattr(doctor, "api_config", lambda *args: ("local", "test", ""))
    monkeypatch.setattr(doctor, "_openclaw_version", lambda: (2026, 6, 11))
    for name in ("_node_version_ok", "_module_available", "_venv_available",
                 "_chromium_available", "_env_key_valid", "_gateway_healthy"):
        monkeypatch.setattr(doctor, name, lambda *args: True)
    for name in ("_primary_model_routable", "_skills_synced"):
        monkeypatch.setattr(doctor, name, lambda *args: (True, ""))
    monkeypatch.setattr(doctor, "_skills_fresh", lambda *args: (True, ""))
    monkeypatch.setattr("easel.skills_sync.agent_workspace", lambda: config.parent / "workspace")
    monkeypatch.setattr(local_agents, "summarize_local_agents", lambda: {"installedCount": 0})
    calls = []
    monkeypatch.setattr(doctor, "_tool_loop_policy", lambda: calls.append(True) or ["状态未知"])
    assert doctor.cmd_doctor(None) == 0
    output = capsys.readouterr().out
    assert bool(calls) == (runtime == "openclaw")
    assert ("不证明网关已加载" in output) == (runtime == "openclaw")
