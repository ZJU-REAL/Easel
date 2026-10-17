from __future__ import annotations

import json

import easel_mcp_server as server


def test_publish_is_fail_closed_without_explicit_host_gate():
    result = json.loads(server.easel_publish("bilibili", "t", "b", [], "", "x"))
    assert result["ok"] is False
    assert result["state"] == "blocked"
    assert "闸" in result["error"]


def test_output_path_traversal_and_system_paths_are_rejected():
    result = json.loads(server.easel_read_output("../cookies.json"))
    assert result["ok"] is False
    result = json.loads(server.easel_read_output("_mcp/confirmations.json"))
    assert result["ok"] is False


def test_publish_plan_reports_platform_constraints():
    result = json.loads(server.easel_plan_publish(
        ["xiaohongshu"], "标题" * 30, "正文", [str(i) for i in range(12)], "article"
    ))
    assert result["ok"] is True
    warnings = result["dispatch"][0]["warnings"]
    assert any("标题" in item for item in warnings)
    assert any("标签" in item for item in warnings)
    assert any("类型" in item for item in warnings)


def test_confirmation_is_one_time_and_payload_bound(tmp_path, monkeypatch):
    confirm_file = tmp_path / "confirmations.json"
    monkeypatch.setattr(server, "CONFIRM_FILE", confirm_file)
    payload = {"platform": "bilibili", "title": "T", "body": "B", "media": [], "tags": ""}
    issued = server._issue_confirmation("publish", payload, ttl=60)
    server._consume_confirmation(issued["confirmation_id"], "publish", payload)
    try:
        server._consume_confirmation(issued["confirmation_id"], "publish", payload)
    except PermissionError:
        pass
    else:
        raise AssertionError("confirmation must be one-time")




def test_publish_class_skill_is_blocked_by_host_publish_gate():
    result = json.loads(server.easel_run_skill("skill-cross-platform-publish", "发布 S7"))
    assert result["ok"] is False
    assert result["state"] == "blocked"
    assert "EASEL_MCP_ALLOW_PUBLISH" in result["error"]


def test_publish_class_skill_cannot_be_confirmed_while_gate_is_closed():
    result = json.loads(server.easel_request_skill_confirmation(
        "skill-bilibili-upload", "上传 A", "token-jinian"))
    assert result["ok"] is False
    assert result["state"] == "blocked"
    assert "EASEL_MCP_ALLOW_PUBLISH" in result["error"]


def test_internal_publish_workflow_skills_are_not_host_gated():
    # Scheduler/log/checklist skills are internal write ops: they stay runnable
    # while the real publish gate is closed, but still require a confirmation.
    scheduler = json.loads(server.easel_skill_policy("publish-scheduler"))
    assert scheduler["requires_confirmation"] is True
    assert server._skill_requires_publish_gate("skill-publish-scheduler") is False
    upload = json.loads(server.easel_skill_policy("skill-bilibili-upload"))
    assert upload["requires_confirmation"] is True
    assert server._skill_requires_publish_gate("skill-bilibili-upload") is True


def test_all_builtin_skills_are_listed_and_high_risk_policy_is_explicit():
    result = json.loads(server.easel_list_skills())
    assert result["ok"] is True
    assert result["count"] == 114
    names = {row["name"] for row in result["skills"]}
    assert "skill-cross-platform-publish" in names
    policy = json.loads(server.easel_skill_policy("skill-cross-platform-publish"))
    assert policy["requires_confirmation"] is True
    safe_policy = json.loads(server.easel_skill_policy("copywriting"))
    assert safe_policy["requires_confirmation"] is False


def test_skill_runner_rejects_unknown_and_out_of_scope_inputs():
    unknown = json.loads(server.easel_run_skill("does-not-exist", "x"))
    assert unknown["ok"] is False
    assert "不存在" in unknown["error"]
    out_of_scope = json.loads(server.easel_run_skill("copywriting", "C:/Users/Administrator/.env"))
    assert out_of_scope["ok"] is False
    assert "输入文件" in out_of_scope["error"]


def test_high_risk_skill_requires_payload_bound_confirmation(tmp_path, monkeypatch):
    confirm_file = tmp_path / "confirmations.json"
    monkeypatch.setattr(server, "CONFIRM_FILE", confirm_file)
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    blocked = json.loads(server.easel_run_skill("skill-cross-platform-publish", "发布 S7"))
    assert blocked["ok"] is False
    assert blocked["state"] == "blocked"
    request = json.loads(server.easel_request_skill_confirmation(
        "skill-cross-platform-publish", "发布 S7", "token-jinian"))
    assert request["ok"] is True
    monkeypatch.setattr(server, "_run", lambda *args, **kwargs: (0, "完成 token=secret", ""))
    result = json.loads(server.easel_run_skill(
        "skill-cross-platform-publish", "发布 S7", "token-jinian", request["confirmation_id"]))
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert "[REDACTED]" in result["output"]


def test_skill_confirmation_is_bound_to_skill_input_and_profile(tmp_path, monkeypatch):
    confirm_file = tmp_path / "confirmations.json"
    monkeypatch.setattr(server, "CONFIRM_FILE", confirm_file)
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    request = json.loads(server.easel_request_skill_confirmation(
        "skill-bilibili-upload", "上传 A", "token-jinian"))
    monkeypatch.setattr(server, "_run", lambda *args, **kwargs: (0, "ok", ""))
    changed = json.loads(server.easel_run_skill(
        "skill-bilibili-upload", "上传 B", "token-jinian", request["confirmation_id"]))
    assert changed["ok"] is False
    assert "确认凭证" in changed["error"]


def test_low_level_schema_preserves_optional_arrays():
    schema = server._schema_for_callable(server.easel_plan_publish)
    assert schema["properties"]["platforms"] == {"type": "array", "items": {"type": "string"}}
    assert schema["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
