"""Per-tool regression matrix for the Easel MCP data plane.

Every registered tool is exercised on four axes:

1. success path (deterministic, no network, no browser);
2. invalid / out-of-scope input (must be refused, never crash);
3. subprocess failure (exit code != 0 must never read as success);
4. subprocess timeout (outcome is *unknown*, never "failed" or "blocked").

Plus protocol invariants: tool registry/schema shape, unknown tool name,
exception containment inside the MCP call handler, and secret redaction.

Nothing here touches a real platform: `server._run` is stubbed, and all Easel
state paths are redirected into a throwaway directory by the ``env`` fixture.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import easel_mcp_server as server


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Redirect every Easel state path into a throwaway directory."""
    outputs = tmp_path / "outputs"
    profiles = tmp_path / "profiles"
    (outputs / "media").mkdir(parents=True)
    (outputs / "media" / "clip.mp4").write_bytes(b"\x00\x01\x02")
    (outputs / "media" / "cover.png").write_bytes(b"\x89PNG\r\n")
    (outputs / "note.md").write_text("# hello\n正文\n", encoding="utf-8")
    (outputs / "cookies.json").write_text("{}", encoding="utf-8")
    (outputs / ".hidden").mkdir()
    (outputs / ".hidden" / "secret.md").write_text("x", encoding="utf-8")
    (outputs / "_login").mkdir()
    (outputs / "_publish").mkdir()
    (profiles / "token-jinian").mkdir(parents=True)
    (profiles / "token-jinian" / "identity.md").write_text(
        "# 画像\nToken纪年主号：AI/科技人文。\n", encoding="utf-8")

    mcp = outputs / "_mcp"
    monkeypatch.setattr(server, "OUTPUTS", outputs)
    monkeypatch.setattr(server, "LOGIN_DIR", outputs / "_login")
    monkeypatch.setattr(server, "PUBLISH_DIR", outputs / "_publish")
    monkeypatch.setattr(server, "MCP_DIR", mcp)
    monkeypatch.setattr(server, "CONFIRM_FILE", mcp / "confirmations.json")
    monkeypatch.setattr(server, "SCHEDULE_FILE", outputs / "_schedule.json")
    monkeypatch.setattr(server, "IDEAS_FILE", outputs / "_ideas.json")
    monkeypatch.setattr(server, "PROFILES", profiles)
    return SimpleNamespace(root=tmp_path, outputs=outputs, profiles=profiles, mcp=mcp)


def call(tool: str, **kwargs):
    """Invoke a tool by name and decode its JSON envelope."""
    fn = getattr(server, tool)
    return json.loads(fn(**kwargs))


def stub(monkeypatch, *, rc=0, stdout="", stderr="", raises=None):
    """Replace ``server._run`` with a canned outcome."""
    calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        if raises is not None:
            raise raises
        return rc, stdout, stderr

    monkeypatch.setattr(server, "_run", _run)
    return calls


def json_line(**payload) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def flatten_keys(value):
    """Yield every mapping key in a nested structure."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from flatten_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from flatten_keys(item)


SECRET_KEY = re.compile(r"(?i)cookie|token|password|secret|sessdata|credential")


# --------------------------------------------------------------------------
# protocol helpers
# --------------------------------------------------------------------------

def _lowlevel_tool_handler():
    """Return the low-level SDK's ``call_tool`` handler (takes the request)."""
    import mcp.types as types

    built = server._build_server()
    handler = built.request_handlers.get(types.CallToolRequest)
    assert handler is not None, "MCP Server 未注册 tools/call handler"
    return handler


def _tool_call(name: str, arguments: dict):
    import asyncio
    import mcp.types as types

    request = types.CallToolRequest(
        method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments))
    return asyncio.run(_lowlevel_tool_handler()(request))


# --------------------------------------------------------------------------
# 1. protocol / registry invariants
# --------------------------------------------------------------------------

REGISTERED = [
    "easel_status", "easel_list_personas", "easel_read_persona", "easel_list_skills",
    "easel_read_skill", "easel_skill_policy", "easel_request_skill_confirmation",
    "easel_run_skill", "easel_list_outputs", "easel_read_output", "easel_list_accounts",
    "easel_login_status", "easel_check_account", "easel_fetch_analytics",
    "easel_get_publish_policy", "easel_plan_publish", "easel_request_manual_export",
    "easel_export_manual_package", "easel_request_publish_confirmation", "easel_publish",
    "easel_publish_status", "easel_request_write_confirmation", "easel_list_schedule",
    "easel_schedule_context", "easel_create_schedule", "easel_update_schedule",
    "easel_delete_schedule", "easel_list_ideas", "easel_create_idea", "easel_update_idea",
    "easel_delete_idea",
]


def test_registry_is_the_documented_31_tools():
    assert len(REGISTERED) == 31
    assert len(set(REGISTERED)) == 31
    assert all(callable(getattr(server, name)) for name in REGISTERED)


def test_every_registered_tool_has_a_docstring_and_schema():
    import inspect

    for name in REGISTERED:
        fn = getattr(server, name)
        assert (fn.__doc__ or "").strip(), f"{name} 缺少描述"
        schema = server._schema_for_callable(fn)
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        has_params = bool(inspect.signature(fn).parameters)
        assert bool(schema["properties"]) is has_params, f"{name} 参数与 schema 不一致"
        for prop, spec in schema["properties"].items():
            assert spec.get("type") in {"string", "integer", "number", "boolean", "array", "object"}, \
                f"{name}.{prop} 类型不受支持: {spec}"
            if spec["type"] == "array":
                assert spec["items"]["type"] in {"string", "integer", "number", "boolean", "object"}
        required = set(schema.get("required", []))
        declared = set(schema["properties"])
        assert required <= declared, f"{name} required 越界"
        for param in inspect.signature(fn).parameters.values():
            if param.default is inspect.Parameter.empty:
                assert param.name in required, f"{name}.{param.name} 必填但未标记"


def test_mcp_handler_lists_all_tools_over_the_wire():
    import asyncio
    import mcp.types as types

    built = server._build_server()
    lister = built.request_handlers[types.ListToolsRequest]
    result = asyncio.run(lister(types.ListToolsRequest(method="tools/list")))
    names = {t.name for t in result.root.tools}
    assert names == set(REGISTERED)
    assert all(t.description for t in result.root.tools)


def test_mcp_call_handler_reports_unknown_tool():
    result = _tool_call("easel_not_a_tool", {})
    payload = json.loads(result.root.content[0].text)
    assert payload["ok"] is False and "未知工具" in payload["error"]


def test_mcp_call_handler_contains_tool_exceptions(env, monkeypatch):
    def boom():
        raise RuntimeError("cookie=leaked-value")

    boom.__name__ = "easel_list_personas"      # 保持注册名，替换实现
    monkeypatch.setattr(server, "easel_list_personas", boom)
    result = _tool_call("easel_list_personas", {})
    payload = json.loads(result.root.content[0].text)
    assert payload["ok"] is False
    assert "leaked-value" not in payload["error"]
    assert "[REDACTED]" in payload["error"]


def test_direct_tool_call_also_contains_argument_errors():
    """不走传输层直接调用，也必须拿到 ok=false 信封而不是堆栈。"""
    assert json.loads(server.easel_list_skills(query=7))["ok"] is False
    assert json.loads(server.easel_schedule_context(days="abc"))["ok"] is False
    assert json.loads(server.easel_read_persona(name=5))["ok"] is False


# --------------------------------------------------------------------------
# 2. read-only tools
# --------------------------------------------------------------------------

def test_status_reports_gate_state(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", False)
    closed = call("easel_status")
    assert closed["ok"] is True and closed["publish_enabled"] is False
    assert closed["raw_shell"] is False and closed["raw_credentials"] is False
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    assert call("easel_status")["publish_enabled"] is True


def test_list_personas_reads_identity_first_line(env):
    rows = call("easel_list_personas")
    assert rows["ok"] is True and rows["count"] == 1
    assert rows["personas"][0]["name"] == "token-jinian"
    assert "Token纪年" in rows["personas"][0]["description"]


def test_list_personas_on_missing_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "PROFILES", tmp_path / "nope")
    rows = call("easel_list_personas")
    assert rows["ok"] is True and rows["count"] == 0


def test_read_persona_success_and_refusals(env):
    ok = call("easel_read_persona", name="token-jinian")
    assert ok["ok"] is True and "identity.md" in ok["files"]
    assert call("easel_read_persona", name="../etc")["ok"] is False
    assert call("easel_read_persona", name="missing")["ok"] is False
    assert "格式无效" in call("easel_read_persona", name="a b")["error"]


def test_login_status_marks_itself_unverified(env):
    """A marker-only 'logged_in' must never read as 'usable'. 2026-10-18:
    weixin-channels reported logged_in=true from a marker while the cookie
    was in fact dead, and the only deep check timed out."""
    rows = call("easel_login_status")["accounts"]
    assert rows, "expected at least one platform row"
    for row in rows:
        assert row["deep_verified"] is False
        assert row["verification"] == "marker_or_file_presence_only"
        assert row["usable_unknown"] is True
        assert "easel_check_account" in row["note"]
    one = call("easel_login_status", platform="xiaohongshu")["accounts"]
    assert len(one) == 1 and one[0]["deep_verified"] is False


def test_list_schedule_and_ideas_flag_absent_source(env):
    """Empty must be distinguishable from 'no data source' — a commander
    reading count=0 as 'nothing scheduled' is the exact failure this guards."""
    for name in ("easel_list_schedule", "easel_list_ideas"):
        r = call(name)
        assert "source_exists" in r, (name, r)
        assert isinstance(r["source_exists"], bool)
        if r["count"] == 0:
            assert r["source_exists"] is False, (name, r)


def test_run_pins_stdin_to_devnull(monkeypatch):
    """The MCP server's stdin is the protocol pipe; a child that inherits it
    blocks forever (measured: 30 s timeout, zero child output). Pin DEVNULL."""
    import easel_mcp_server as srv
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise srv._SubprocessTimeout("stop")

    monkeypatch.setattr(srv.subprocess, "run", fake_run)
    with pytest.raises(srv._SubprocessTimeout):
        srv._run(["python", "-c", "pass"], timeout=5)
    assert seen.get("stdin") is srv.subprocess.DEVNULL, seen


def test_last_json_parses_pretty_printed_multiline(monkeypatch):
    """calendar_ops emits json.dumps(indent=2); its first line is a bare '{',
    which the old line scanner could never satisfy."""
    import easel_mcp_server as srv
    payload = {"today": "2026-10-18", "window_days": 14, "per_platform": [],
               "upcoming_schedules": [], "suggestions": ["a", "b"]}
    pretty = json.dumps(payload, indent=2, ensure_ascii=False)
    assert srv._last_json(pretty) == payload

    # nested objects must not be mistaken for the top-level object
    nested = {"today": "x", "rows": [{"a": 1}, {"b": 2}], "n": 1}
    assert srv._last_json(json.dumps(nested, indent=2, ensure_ascii=False)) == nested

    # an inner object is indented, so it must never win over the top-level one
    inner_first = {"outer": {"deep": {"deeper": 1}}, "tail": 2}
    assert srv._last_json(json.dumps(inner_first, indent=2, ensure_ascii=False)) == inner_first

    # CRLF output (Windows pipes) must still parse
    assert srv._last_json(pretty.replace("\n", "\r\n")) == payload

    # leading log lines before a pretty blob are tolerated
    noisy = "loading...\nwarn: nothing\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    assert srv._last_json(noisy) == payload

    # compact single-line still works (fast path)
    assert srv._last_json("noise\n" + json.dumps(payload)) == payload

    # degenerate inputs
    assert srv._last_json("") is None
    assert srv._last_json("   \n  ") is None
    assert srv._last_json("not json at all") is None
    assert srv._last_json("[\"a\",\"b\"]") is None       # a list is not a dict
    assert srv._last_json("{\"broken\": ") is None


def test_last_json_prefers_last_object_when_several_emitted():
    import easel_mcp_server as srv
    two = (json.dumps({"i": 1}, indent=2) + "\n" + json.dumps({"i": 2}, indent=2) + "\n")
    assert srv._last_json(two) == {"i": 2}


def test_list_skills_returns_real_descriptions_not_frontmatter(env):
    rows = call("easel_list_skills")
    assert rows["count"] == 114
    placeholders = [r for r in rows["skills"]
                    if not r["description"].strip() or set(r["description"].strip()) <= set("- ")]
    assert placeholders == [], f"占位符描述：{[r['name'] for r in placeholders][:5]}"
    copywriting = next(r for r in rows["skills"] if r["name"] == "copywriting")
    assert "文案" in copywriting["description"]
    assert "\n" not in copywriting["description"]


def test_skill_description_parses_inline_and_block_forms(tmp_path):
    inline = tmp_path / "a" / "SKILL.md"
    inline.parent.mkdir(parents=True)
    inline.write_text("---\nname: a\ndescription: 一句话描述\nlayer: produce\n---\n\n# A\n", encoding="utf-8")
    assert server._skill_description(inline) == "一句话描述"

    folded = tmp_path / "b" / "SKILL.md"
    folded.parent.mkdir(parents=True)
    folded.write_text("---\nname: b\ndescription: >\n  第一行\n  第二行\nlayer: produce\n---\n\n# B\n", encoding="utf-8")
    assert server._skill_description(folded) == "第一行 第二行"

    body = tmp_path / "c" / "SKILL.md"
    body.parent.mkdir(parents=True)
    body.write_text("# C\n\n正文第一行\n", encoding="utf-8")
    assert server._skill_description(body) == "正文第一行"

    empty = tmp_path / "d" / "SKILL.md"
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    assert server._skill_description(empty) == ""

    assert server._skill_description(tmp_path / "missing" / "SKILL.md") == ""


def test_list_skills_reports_full_catalog(env):
    rows = call("easel_list_skills")
    assert rows["ok"] is True and rows["count"] == 114
    filtered = call("easel_list_skills", query="upload")
    assert filtered["count"] >= 1
    assert all("upload" in row["name"] for row in filtered["skills"])
    assert call("easel_list_skills", query="zzz-nope")["count"] == 0


def test_read_skill_success_and_refusals(env):
    ok = call("easel_read_skill", name="copywriting")
    assert ok["ok"] is True and ok["content"].strip()
    assert call("easel_read_skill", name="nope")["ok"] is False
    assert call("easel_read_skill", name="../../secret")["ok"] is False


def test_list_outputs_excludes_system_and_credential_files(env):
    (env.outputs / "media" / "extra.txt").write_text("x", encoding="utf-8")
    rows = call("easel_list_outputs")
    paths = {row["path"] for row in rows["files"]}
    assert "note.md" in paths and "media/clip.mp4" in paths
    assert "cookies.json" not in paths
    assert not any(p.startswith(("_", ".")) for p in paths)


def test_list_outputs_prefix_and_limit(env):
    for i in range(4):
        (env.outputs / f"batch{i}.md").write_text("x", encoding="utf-8")
    rows = call("easel_list_outputs", prefix="batch")
    assert rows["count"] == 4 and rows["truncated"] is False
    limited = call("easel_list_outputs", prefix="batch", limit=2)
    assert limited["count"] == 2 and limited["truncated"] is True


def test_list_outputs_clamps_absurd_limits(env):
    assert call("easel_list_outputs", limit=0)["ok"] is True
    assert call("easel_list_outputs", limit=10_000)["ok"] is True


def test_read_output_success_and_refusals(env):
    ok = call("easel_read_output", path="note.md")
    assert ok["ok"] is True and "hello" in ok["content"]
    assert call("easel_read_output", path="../outside.md")["ok"] is False
    assert call("easel_read_output", path="_login/bilibili.json")["ok"] is False
    assert call("easel_read_output", path="cookies.json")["ok"] is False
    assert call("easel_read_output", path="media/clip.mp4")["ok"] is False
    assert call("easel_read_output", path="missing.md")["ok"] is False
    assert call("easel_read_output", path="note.md", max_chars=4)["content"]


def test_list_accounts_leaks_no_credential_fields(env, monkeypatch):
    monkeypatch.setattr(server, "_account_fast_status",
                        lambda platform, cfg: {"state": "success", "logged_in": True, "source": "x"})
    rows = call("easel_list_accounts")
    assert rows["ok"] is True and rows["count"] == len(server.ACCOUNT_CONFIG)
    assert not [k for k in flatten_keys(rows) if SECRET_KEY.search(str(k))]


def test_login_status_all_single_and_unknown(env):
    (env.outputs / "_login" / "bilibili.json").write_text(
        json.dumps({"state": "success"}), encoding="utf-8")
    every = call("easel_login_status")
    assert every["ok"] is True and len(every["accounts"]) == len(server.ACCOUNT_CONFIG)
    bili = call("easel_login_status", platform="bilibili")
    assert bili["accounts"][0]["logged_in"] is True
    assert bili["accounts"][0]["verification"] == "marker_or_file_presence_only"
    assert call("easel_login_status", platform="nope")["ok"] is False


# --------------------------------------------------------------------------
# 3. subprocess-backed read tools
# --------------------------------------------------------------------------

def test_check_account_success_strips_credentials(env, monkeypatch):
    stub(monkeypatch, stdout=json_line(ok=True, state="success", name="Gary",
                                       cookies="abc", token="t0p", sessdata="s3cr3t"))
    row = call("easel_check_account", platform="bilibili")
    assert row["ok"] is True and row["state"] == "success"
    assert "cookies" not in row and "token" not in row and "sessdata" not in row


def test_check_account_non_json_output_is_unknown(env, monkeypatch):
    stub(monkeypatch, rc=1, stdout="not json at all", stderr="boom")
    row = call("easel_check_account", platform="xiaohongshu")
    assert row["ok"] is False and row["state"] == "unknown"


def test_check_account_timeout_is_unknown(env, monkeypatch):
    stub(monkeypatch, raises=server._SubprocessTimeout("超时"))
    row = call("easel_check_account", platform="douyin")
    assert row["ok"] is False and row["state"] == "unknown"


def test_check_account_exception_is_unknown(env, monkeypatch):
    stub(monkeypatch, raises=OSError("socket closed"))
    row = call("easel_check_account", platform="zhihu")
    assert row["ok"] is False and row["state"] == "unknown"


def test_check_account_unsupported_and_unknown_platform(env, monkeypatch):
    assert call("easel_check_account", platform="alipay")["state"] == "unsupported"
    assert call("easel_check_account", platform="nope")["ok"] is False


def test_fetch_analytics_success_and_error_payload(env, monkeypatch):
    stub(monkeypatch, stdout=json_line(ok=True, followers=10, views=99))
    row = call("easel_fetch_analytics", platform="xiaohongshu")
    assert row["ok"] is True and row["data"]["followers"] == 10
    stub(monkeypatch, rc=0, stdout=json_line(error="登录失效"))
    failed = call("easel_fetch_analytics", platform="xiaohongshu")
    assert failed["ok"] is False and "登录失效" in failed["error"]


def test_fetch_analytics_failure_timeout_and_unsupported(env, monkeypatch):
    stub(monkeypatch, rc=2, stdout="", stderr="traceback")
    row = call("easel_fetch_analytics", platform="douyin")
    assert row["ok"] is False and row["state"] == "unknown"
    stub(monkeypatch, raises=server._SubprocessTimeout("超时"))
    assert call("easel_fetch_analytics", platform="douyin")["state"] == "unknown"
    assert call("easel_fetch_analytics", platform="alipay")["ok"] is False
    assert call("easel_fetch_analytics", platform="")["ok"] is False


def test_schedule_context_success_and_failures(env, monkeypatch):
    stub(monkeypatch, stdout=json_line(days=14, items=[]))
    row = call("easel_schedule_context")
    assert row["ok"] is True and row["data"]["days"] == 14
    stub(monkeypatch, rc=1, stderr="bad data file")
    assert call("easel_schedule_context")["ok"] is False
    stub(monkeypatch, raises=server._SubprocessTimeout("超时"))
    timed_out = call("easel_schedule_context")
    assert timed_out["ok"] is False and timed_out["state"] == "unknown"


def test_schedule_context_clamps_days(env, monkeypatch):
    calls = stub(monkeypatch, stdout=json_line(days=90))
    call("easel_schedule_context", days=0)
    assert "--days" in calls[0] and calls[0][calls[0].index("--days") + 1] == "1"
    call("easel_schedule_context", days=9999)
    assert calls[1][calls[1].index("--days") + 1] == "90"


# --------------------------------------------------------------------------
# 4. planning / manual export / gated publish
# --------------------------------------------------------------------------

def test_publish_policy_default_and_invalid_mode(env, monkeypatch):
    monkeypatch.delenv("EASEL_PUBLISH_MODE", raising=False)
    row = call("easel_get_publish_policy")
    assert row["mode"] == "automated" and row["confirmation_required"] is True
    monkeypatch.setenv("EASEL_PUBLISH_MODE", "banana")
    assert call("easel_get_publish_policy")["mode"] == "manual"


def test_plan_publish_success_and_refusals(env):
    row = call("easel_plan_publish", platforms=["bilibili", "nope"], title="测试")
    assert row["ok"] is True and row["target_count"] == 2
    by_name = {d["platform"]: d for d in row["dispatch"]}
    assert by_name["bilibili"]["ok"] is True
    assert by_name["bilibili"]["publisher"] == "skill-bilibili-upload"
    assert by_name["nope"]["ok"] is False
    assert call("easel_plan_publish", platforms=[])["ok"] is False


def test_manual_export_requires_confirmation(env):
    req = call("easel_request_manual_export", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    assert req["ok"] is True and req["confirmation_id"]
    assert call("easel_export_manual_package", platform="bilibili", title="T", body="B",
                media=["media/clip.mp4"])["ok"] is False
    done = call("easel_export_manual_package", platform="bilibili", title="T", body="B",
                media=["media/clip.mp4"], confirmation_id=req["confirmation_id"])
    assert done["ok"] is True
    assert done["published"] is False and done["status"] == "ready_for_manual_submission"
    assert (env.outputs / done["path"]).is_file()
    # one-time
    again = call("easel_export_manual_package", platform="bilibili", title="T", body="B",
                 media=["media/clip.mp4"], confirmation_id=req["confirmation_id"])
    assert again["ok"] is False


def test_manual_export_refuses_bad_platform_and_media(env):
    assert call("easel_request_manual_export", platform="nope", title="T", body="B")["ok"] is False
    assert call("easel_request_manual_export", platform="bilibili", title="T", body="B",
                media=["../escape.mp4"])["ok"] is False
    assert call("easel_request_manual_export", platform="bilibili", title="T", body="B",
                media=["note.md"])["ok"] is False


def test_publish_confirmation_requires_supported_platform(env):
    assert call("easel_request_publish_confirmation", platform="alipay", title="T", body="B")["ok"] is False
    assert call("easel_request_publish_confirmation", platform="nope", title="T", body="B")["ok"] is False
    ok = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
              media=["media/clip.mp4"])
    assert ok["ok"] is True and ok["operation"] == "publish"


def test_publish_is_blocked_while_host_gate_is_closed(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", False)
    row = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"])
    assert row["ok"] is False and row["state"] == "blocked"
    assert "EASEL_MCP_ALLOW_PUBLISH" in row["error"]


def test_publish_requires_matching_confirmation(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(server, "_publish_command", lambda *a, **k: ["echo", "hi"])
    stub(monkeypatch, rc=0, stdout="done")
    missing = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"])
    assert missing["ok"] is False and missing["state"] == "blocked"

    req = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    wrong = call("easel_publish", platform="bilibili", title="T2", body="B", media=["media/clip.mp4"],
                 confirmation_id=req["confirmation_id"])
    assert wrong["ok"] is False and "确认凭证" in wrong["error"]


def test_publish_submitted_is_never_verified(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(server, "_publish_command", lambda *a, **k: ["echo", "hi"])
    stub(monkeypatch, rc=0, stdout="uploaded")
    req = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    row = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"],
               confirmation_id=req["confirmation_id"])
    assert row["ok"] is True and row["state"] == "submitted"
    assert row["verified"] is False
    assert row["verification"] == "unknown_requires_platform_readback"


def test_publish_nonzero_exit_is_failed_not_success(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(server, "_publish_command", lambda *a, **k: ["echo", "hi"])
    stub(monkeypatch, rc=3, stdout="", stderr="平台拒绝")
    req = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    row = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"],
               confirmation_id=req["confirmation_id"])
    assert row["ok"] is False and row["state"] == "failed" and row["verified"] is False


def test_publish_timeout_is_unknown_not_blocked(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(server, "_publish_command", lambda *a, **k: ["echo", "hi"])
    stub(monkeypatch, raises=server._SubprocessTimeout("超时"))
    req = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    row = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"],
               confirmation_id=req["confirmation_id"])
    assert row["ok"] is False and row["state"] == "unknown"


def test_publish_rejects_media_before_touching_platform(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(server, "_publish_command", lambda *a, **k: ["echo", "hi"])
    stub(monkeypatch, rc=0, stdout="must not run")
    req = call("easel_request_publish_confirmation", platform="bilibili", title="T", body="B",
               media=["media/clip.mp4"])
    row = call("easel_publish", platform="bilibili", title="T", body="B", media=["../escape.mp4"],
               confirmation_id=req["confirmation_id"])
    assert row["ok"] is False and row["state"] == "failed"
    assert "outputs" in row["error"] or "路径" in row["error"]
    # 素材非法时不能烧掉确认凭证：修好素材后同一凭证仍应可用
    retry = call("easel_publish", platform="bilibili", title="T", body="B", media=["media/clip.mp4"],
                 confirmation_id=req["confirmation_id"])
    assert retry["ok"] is True and retry["state"] == "submitted"


def test_publish_command_builder_rules(env):
    with pytest.raises(ValueError):
        server._publish_command("bilibili", "T", "B", "", [])           # 需要视频
    with pytest.raises(ValueError):
        server._publish_command("xiaohongshu", "T", "B", "", [])        # 需要素材
    with pytest.raises(ValueError):
        server._publish_command("wechat-oa", "T", "B", "", ["media/clip.mp4"])
    bili = server._publish_command("bilibili", "", "正文兜底标题", "#AI，#科技", ["media/clip.mp4"])
    assert "biliup" in bili[0] or bili[0].endswith("biliup.exe")
    assert "正文兜底标题" in bili
    assert "AI,科技" in bili
    xhs = server._publish_command("xiaohongshu", "T", "B", "", ["media/cover.png"])
    assert "publish" in xhs and "cover.png" in " ".join(xhs)
    channels = server._publish_command("weixin-channels", "T", "B", "", ["media/clip.mp4"])
    assert "weixin-channels" in channels


def test_publish_status_reads_files_and_rejects_unknown(env):
    (env.outputs / "_publish" / "bilibili.json").write_text(
        json.dumps({"state": "submitted", "message": "等待平台回读"}), encoding="utf-8")
    every = call("easel_publish_status")
    by_name = {r["platform"]: r for r in every["statuses"]}
    assert by_name["bilibili"]["state"] == "submitted"
    single = call("easel_publish_status", platform="bilibili")
    assert single["statuses"][0]["state"] == "submitted"
    # 点名一个不存在的平台必须显式报错，不能静默返回空列表
    assert call("easel_publish_status", platform="nope")["ok"] is False


def test_publish_status_defaults_to_unknown(env):
    row = call("easel_publish_status", platform="zhihu")
    assert row["statuses"][0]["state"] == "unknown"


# --------------------------------------------------------------------------
# 5. controlled writes
# --------------------------------------------------------------------------

def test_write_confirmation_rejects_unknown_operation(env):
    assert call("easel_request_write_confirmation", operation="drop_database")["ok"] is False


def test_schedule_crud_round_trip(env):
    assert call("easel_list_schedule")["count"] == 0
    req = call("easel_request_write_confirmation", operation="schedule_create",
               payload={"title": "S7", "date": "2026-10-20", "platform": "bilibili",
                        "time": "20:00", "status": "idea", "note": "n"})
    created = call("easel_create_schedule", title="S7", date="2026-10-20", platform="bilibili",
                   time_text="20:00", status="idea", note="n", confirmation_id=req["confirmation_id"])
    assert created["ok"] is True
    item_id = created["item"]["id"]
    assert call("easel_list_schedule")["count"] == 1

    upd = call("easel_request_write_confirmation", operation="schedule_update",
               payload={"id": item_id, "title": "S7 改", "date": "2026-10-21", "platform": "bilibili",
                        "time": "20:00", "status": "ready", "note": "n"})
    assert call("easel_update_schedule", schedule_id=item_id, title="S7 改", date="2026-10-21",
                platform="bilibili", time_text="20:00", status="ready", note="n",
                confirmation_id=upd["confirmation_id"])["ok"] is True
    assert call("easel_list_schedule")["items"][0]["title"] == "S7 改"

    dele = call("easel_request_write_confirmation", operation="schedule_delete", payload={"id": item_id})
    assert call("easel_delete_schedule", schedule_id=item_id,
                confirmation_id=dele["confirmation_id"])["ok"] is True
    assert call("easel_list_schedule")["count"] == 0


def test_schedule_writes_require_confirmation(env):
    assert call("easel_create_schedule", title="X", date="2026-10-20")["ok"] is False
    assert call("easel_update_schedule", schedule_id="x", title="X", date="2026-10-20")["ok"] is False
    assert call("easel_delete_schedule", schedule_id="x")["ok"] is False
    assert call("easel_list_schedule")["count"] == 0


def test_schedule_update_and_delete_missing_id(env):
    req = call("easel_request_write_confirmation", operation="schedule_update",
               payload={"id": "ghost", "title": "X", "date": "2026-10-20", "platform": "",
                        "time": "", "status": "idea", "note": ""})
    assert call("easel_update_schedule", schedule_id="ghost", title="X", date="2026-10-20",
                confirmation_id=req["confirmation_id"])["ok"] is False
    dele = call("easel_request_write_confirmation", operation="schedule_delete", payload={"id": "ghost"})
    assert call("easel_delete_schedule", schedule_id="ghost",
                confirmation_id=dele["confirmation_id"])["ok"] is False


def test_ideas_crud_round_trip(env):
    assert call("easel_list_ideas")["count"] == 0
    req = call("easel_request_write_confirmation", operation="idea_create",
               payload={"title": "选题A", "note": "n", "source": "radar", "status": "pending"})
    created = call("easel_create_idea", title="选题A", note="n", source="radar", status="pending",
                   confirmation_id=req["confirmation_id"])
    assert created["ok"] is True
    idea_id = created["item"]["id"]
    assert call("easel_list_ideas")["items"][0]["title"] == "选题A"

    upd = call("easel_request_write_confirmation", operation="idea_update",
               payload={"id": idea_id, "title": "选题A改", "note": "n", "source": "radar",
                        "status": "approved"})
    assert call("easel_update_idea", idea_id=idea_id, title="选题A改", note="n", source="radar",
                status="approved", confirmation_id=upd["confirmation_id"])["ok"] is True
    assert call("easel_list_ideas")["items"][0]["status"] == "approved"

    dele = call("easel_request_write_confirmation", operation="idea_delete", payload={"id": idea_id})
    assert call("easel_delete_idea", idea_id=idea_id,
                confirmation_id=dele["confirmation_id"])["ok"] is True
    assert call("easel_list_ideas")["count"] == 0


def test_idea_writes_require_confirmation(env):
    assert call("easel_create_idea", title="X")["ok"] is False
    assert call("easel_update_idea", idea_id="x", title="X")["ok"] is False
    assert call("easel_delete_idea", idea_id="x")["ok"] is False
    assert call("easel_list_ideas")["count"] == 0


def test_confirmation_cannot_be_reused_across_operations(env):
    req = call("easel_request_write_confirmation", operation="idea_create",
               payload={"title": "A", "note": "", "source": "", "status": "pending"})
    # payload matches idea_create, but the token kind is write:idea_create — reusing it
    # for a schedule create must fail on the digest/kind binding.
    assert call("easel_create_schedule", title="A", date="2026-10-20",
                confirmation_id=req["confirmation_id"])["ok"] is False


def test_expired_confirmation_is_rejected(env, monkeypatch):
    req = call("easel_request_write_confirmation", operation="idea_create",
               payload={"title": "A", "note": "", "source": "", "status": "pending"})
    rows = json.loads(env.mcp.joinpath("confirmations.json").read_text(encoding="utf-8"))
    rows[0]["expires_at"] = time.time() - 10
    env.mcp.joinpath("confirmations.json").write_text(json.dumps(rows), encoding="utf-8")
    assert call("easel_create_idea", title="A",
                confirmation_id=req["confirmation_id"])["ok"] is False


# --------------------------------------------------------------------------
# 6. skill runner
# --------------------------------------------------------------------------

def test_skill_policy_tiers(env):
    assert call("easel_skill_policy", name="copywriting")["requires_confirmation"] is False
    assert call("easel_skill_policy", name="skill-bilibili-upload")["requires_confirmation"] is True
    assert call("easel_skill_policy", name="nope")["ok"] is False


def test_run_skill_success_and_failure(env, monkeypatch):
    stub(monkeypatch, rc=0, stdout="文案生成完成")
    row = call("easel_run_skill", skill_name="copywriting", input_text="写一句")
    assert row["ok"] is True and row["state"] == "completed" and row["skill"] == "copywriting"
    stub(monkeypatch, rc=1, stdout="", stderr="技能内部错误")
    bad = call("easel_run_skill", skill_name="copywriting", input_text="写一句")
    assert bad["ok"] is False and bad["state"] == "failed" and bad["exit_code"] == 1


def test_run_skill_timeout_is_unknown(env, monkeypatch):
    stub(monkeypatch, raises=server._SubprocessTimeout("超时"))
    row = call("easel_run_skill", skill_name="copywriting", input_text="写一句")
    assert row["ok"] is False and row["state"] == "unknown"


def test_run_skill_refusals(env, monkeypatch):
    stub(monkeypatch, rc=0, stdout="should not run")
    assert call("easel_run_skill", skill_name="nope", input_text="x")["ok"] is False
    assert call("easel_run_skill", skill_name="copywriting", input_text="  ")["ok"] is False
    assert call("easel_run_skill", skill_name="copywriting", input_text="x" * 200_000)["ok"] is False
    assert call("easel_run_skill", skill_name="copywriting", input_text="C:/Users/Administrator/.env")["ok"] is False
    assert call("easel_run_skill", skill_name="copywriting", input_text="x",
                profile="bad profile")["ok"] is False


def test_run_skill_high_risk_needs_confirmation(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", True)
    stub(monkeypatch, rc=0, stdout="ok")
    blocked = call("easel_run_skill", skill_name="skill-cross-platform-publish", input_text="发布 S7")
    assert blocked["ok"] is False and blocked["state"] == "blocked"
    req = call("easel_request_skill_confirmation", skill_name="skill-cross-platform-publish",
               input_text="发布 S7", profile="token-jinian")
    assert req["ok"] is True
    ok = call("easel_run_skill", skill_name="skill-cross-platform-publish", input_text="发布 S7",
              profile="token-jinian", confirmation_id=req["confirmation_id"])
    assert ok["ok"] is True and ok["state"] == "completed"
    # one-time
    assert call("easel_run_skill", skill_name="skill-cross-platform-publish", input_text="发布 S7",
                profile="token-jinian",
                confirmation_id=req["confirmation_id"])["ok"] is False


def test_run_skill_gated_skill_blocked_without_host_gate(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", False)
    stub(monkeypatch, rc=0, stdout="must not run")
    row = call("easel_run_skill", skill_name="skill-bilibili-upload", input_text="上传")
    assert row["ok"] is False and row["state"] == "blocked"
    assert call("easel_request_skill_confirmation", skill_name="skill-bilibili-upload",
                input_text="上传")["ok"] is False


def test_run_skill_internal_workflow_not_gated(env, monkeypatch):
    monkeypatch.setattr(server, "PUBLISH_ENABLED", False)
    stub(monkeypatch, rc=0, stdout="排期已建")
    req = call("easel_request_skill_confirmation", skill_name="publish-scheduler",
               input_text="S7 排期")
    assert req["ok"] is True
    row = call("easel_run_skill", skill_name="publish-scheduler", input_text="S7 排期",
               confirmation_id=req["confirmation_id"])
    assert row["ok"] is True


def test_run_skill_accepts_shared_root_file(env, monkeypatch, tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "brief.md").write_text("选题简报", encoding="utf-8")
    monkeypatch.setattr(server, "_SHARED_ROOT", shared)
    monkeypatch.setattr(server, "_SKILL_INPUT_ROOTS",
                        tuple({p.resolve() for p in (server.PROJECT_ROOT, server.OUTPUTS,
                                                     server.PROFILES, shared)}))
    stub(monkeypatch, rc=0, stdout="ok")
    row = call("easel_run_skill", skill_name="copywriting", input_text=str(shared / "brief.md"))
    assert row["ok"] is True


def test_run_skill_redacts_secrets_in_output(env, monkeypatch):
    stub(monkeypatch, rc=0, stdout="ok sessdata=deadbeef token=abc123")
    row = call("easel_run_skill", skill_name="copywriting", input_text="写一句")
    assert "deadbeef" not in row["output"] and "abc123" not in row["output"]
    assert "[REDACTED]" in row["output"]


# --------------------------------------------------------------------------
# 7. robustness: hostile argument types must not crash the tool
# --------------------------------------------------------------------------

@pytest.mark.parametrize("tool,kwargs", [
    ("easel_list_outputs", {"limit": "abc"}),
    ("easel_read_output", {"path": "note.md", "max_chars": "abc"}),
    ("easel_schedule_context", {"days": "abc"}),
    ("easel_read_persona", {"name": 5}),
    ("easel_read_skill", {"name": None}),
    ("easel_skill_policy", {"name": ""}),
    ("easel_list_skills", {"query": 7}),
    ("easel_login_status", {"platform": 7}),
    ("easel_plan_publish", {"platforms": "bilibili"}),
])
def test_hostile_argument_types_return_error_envelope(tool, kwargs):
    """A malformed argument must degrade to ok=False, never raise into the session."""
    try:
        row = call(tool, **kwargs)
    except Exception as exc:
        pytest.fail(f"{tool} 抛出未捕获异常: {exc!r}")
    assert row["ok"] is False


def test_real_run_converts_timeout():
    """The subprocess helper must raise the typed timeout, not a bare RuntimeError."""
    with pytest.raises(server._SubprocessTimeout):
        server._run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)


def test_safe_error_redacts_and_truncates():
    text = "cookie: abcdefghijklmnopqrstuvwxyz0123456789 " + "x" * 900
    out = server._safe_error(RuntimeError(text))
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in out
    assert "[REDACTED]" in out
    assert len(out) <= 500


def test_redact_text_truncates_long_output():
    assert server._redact_text("y" * 50_000, limit=100) == "y" * 100
    assert server._redact_text(None) == ""
