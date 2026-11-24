"""skill-upload-post-publisher 单测：全程离线（HTTP 层被替换，任何真实请求都会失败）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "upload_post_publish.py"


@pytest.fixture
def up(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("upload_post_publish_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)  # 不读到开发机真实 .env
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "test-key-not-real")
    monkeypatch.setenv("UPLOAD_POST_USER", "creator")
    monkeypatch.delenv("EASEL_PUBLISH_MODE", raising=False)  # 默认自动发布
    monkeypatch.setattr(mod, "project_root", lambda: tmp_path)  # 台账写进临时目录
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    mod.real_http_post = mod.http_post
    monkeypatch.setattr(mod, "http_get", _fail("unexpected GET"))
    monkeypatch.setattr(mod, "http_post", _fail("unexpected POST"))
    recorded: list[tuple] = []
    import calendar_ops
    monkeypatch.setattr(calendar_ops, "record_publish",
                        lambda *a, **k: recorded.append((a, k)) or True)
    mod.recorded = recorded
    return mod


def _fail(msg):
    def f(*_a, **_k):
        raise AssertionError(msg)
    return f


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00" * 64)
    return p


def run(mod, monkeypatch, *argv) -> int:
    monkeypatch.setattr(sys, "argv", ["upload_post_publish.py", *argv])
    try:
        return mod.main()
    except SystemExit as e:
        return e.code


def completed(*platforms, **extra):
    return {"status": "completed", "completed": len(platforms), "total": len(platforms),
            "results": [{"platform": p, "success": True,
                         "post_url": f"https://example.com/{p}/1", **extra} for p in platforms]}


def test_dry_run_never_posts_and_defaults_youtube_private(up, monkeypatch, video, capsys):
    monkeypatch.setattr(up, "http_get", lambda path, key, params=None: {
        "profile": {"social_accounts": {"tiktok": {"handle": "a"}, "youtube": None}}})
    rc = run(up, monkeypatch, "publish", "--platforms", "tiktok,shorts",
             "--media", str(video), "--title", "Hello")
    out = capsys.readouterr().out
    assert rc == 0
    assert '"privacyStatus": "private"' in out
    assert "未连接：youtube" in out  # dry-run 提示未连接平台


def test_exec_sends_idempotency_key_polls_and_records(up, monkeypatch, video):
    posts, gets = [], []

    def fake_post(path, key, data, files, headers):
        posts.append((path, data, headers, [f[0] for f in files]))
        return {"success": True, "request_id": data["request_id"]}

    def fake_get(path, key, params=None):
        gets.append(params)
        return completed("tiktok", "youtube")

    monkeypatch.setattr(up, "http_post", fake_post)
    monkeypatch.setattr(up, "http_get", fake_get)
    rc = run(up, monkeypatch, "publish", "--platforms", "tiktok,youtube", "--media", str(video),
             "--title", "Hello", "--tags", "AI,tips", "--tiktok-privacy", "SELF_ONLY", "--exec")
    assert rc == 0 and len(posts) == 1
    path, data, headers, fields = posts[0]
    assert path == "/api/upload" and fields == ["video"]
    assert headers["Idempotency-Key"] == data["request_id"]
    assert data["platform[]"] == ["tiktok", "youtube"]
    assert data["title"] == "Hello #AI #tips" and data["privacy_level"] == "SELF_ONLY"
    assert gets == [{"request_id": data["request_id"]}]
    assert [a[0] for a, _k in up.recorded] == ["TikTok", "YouTube"]


def test_network_error_never_resends(up, monkeypatch, video):
    posts = []

    def boom(*a, **k):
        posts.append(a)
        raise ConnectionError("reset by peer")

    monkeypatch.setattr(up, "http_post", boom)
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("x"))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == 0 and len(posts) == 1


def test_failed_or_only_skipped_is_not_success(up, monkeypatch):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"request_id": "r"})
    monkeypatch.setattr(up, "http_get", lambda *a, **k: {"status": "completed", "results": [
        {"platform": "x", "success": False, "error_message": "duplicate"},
        {"platform": "bluesky", "success": False, "skipped": True}]})
    assert run(up, monkeypatch, "publish", "--platforms", "x,bluesky",
               "--title", "text post", "--exec") == 1
    assert up.recorded == []


def test_text_and_images_route_to_their_endpoints(up, monkeypatch, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    seen = []
    monkeypatch.setattr(up, "http_post", lambda path, key, data, files, headers:
                        seen.append((path, [f[0] for f in files])) or {"request_id": "r"})
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("linkedin"))
    run(up, monkeypatch, "publish", "--platforms", "linkedin", "--title", "t", "--exec")
    run(up, monkeypatch, "publish", "--platforms", "linkedin", "--media", str(img),
        "--media", str(img), "--title", "t", "--exec")
    assert seen == [("/api/upload_text", []), ("/api/upload_photos", ["photos[]", "photos[]"])]


@pytest.mark.parametrize("argv", [
    ["--platforms", "youtube", "--title", "text only"],             # YouTube 不支持纯文本
    ["--platforms", "pinterest", "--title", "t"],                    # 缺画板（且无媒体）
    ["--platforms", "mastodon", "--title", "t"],                     # 未知平台
    ["--platforms", "x", "--title", "t", "--schedule", "2020-01-01T00:00:00Z"],  # 过去时间
])
def test_invalid_input_fails_before_any_network(up, monkeypatch, argv):
    assert run(up, monkeypatch, "publish", *argv, "--exec") not in (0, None)


def test_content_guard_blocks_secrets_before_upload(up, monkeypatch, video):
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "my key sk-ABCDefgh12345678ijkl", "--exec")
    assert rc == 7  # content_guard.EXIT_LEAK，且未触发任何 HTTP


def test_status_queries_job_id_first_for_job_shaped_ids(up, monkeypatch):
    calls = []
    monkeypatch.setattr(up, "http_get", lambda path, key, params=None:
                        calls.append(params) or completed("tiktok"))
    assert run(up, monkeypatch, "status", "--id", "a" * 32) == 0
    assert calls == [{"job_id": "a" * 32}]


def test_selftest(up, monkeypatch):
    assert run(up, monkeypatch, "selftest") == 0


# ── 不确定的提交结果：绝不当成确定失败，也绝不重发 ───────────────────────────
def _httpx_post(monkeypatch, up, response_or_exc):
    """只替换 httpx.post，走真实的 http_post / 响应解析。"""
    import httpx
    sent = []

    def fake(url, **kw):
        sent.append(kw["headers"]["Idempotency-Key"])
        if isinstance(response_or_exc, Exception):
            raise response_or_exc
        return response_or_exc
    monkeypatch.setattr(httpx, "post", fake)
    monkeypatch.setattr(up, "http_post", up.real_http_post)
    return sent


def test_503_on_submit_then_server_has_it_is_success_without_resend(up, monkeypatch, video):
    import httpx
    sent = _httpx_post(monkeypatch, up, httpx.Response(503, text="Service Unavailable"))
    gets = []
    monkeypatch.setattr(up, "http_get", lambda path, key, params=None:
                        gets.append(params) or completed("tiktok"))
    rc = run(up, monkeypatch, "publish", "--platforms", "tiktok", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == 0 and len(sent) == 1
    assert gets and all(g == {"request_id": sent[0]} for g in gets)
    assert [k.get("status", "published") for _a, k in up.recorded] == ["published"]


@pytest.mark.parametrize("failure", ["503", "timeout"])
def test_ambiguous_submit_and_not_found_is_unknown_not_failure(up, monkeypatch, video, capsys,
                                                               failure):
    import httpx
    err = (httpx.Response(503) if failure == "503"
           else httpx.ReadTimeout("timed out"))
    sent = _httpx_post(monkeypatch, up, err)
    monkeypatch.setattr(up, "http_get", lambda *a, **k: {"status": "not_found"})
    rc = run(up, monkeypatch, "publish", "--platforms", "tiktok,youtube", "--media", str(video),
             "--title", "Hi", "--exec")
    out = capsys.readouterr().out
    assert rc == up.EXIT_UNKNOWN and len(sent) == 1
    assert f"status --id {sent[0]}" in out and "不要重跑 --exec" in out
    assert up.recorded == []  # 结果未定：不写日历，只留台账
    ledger = up.read_ledger(sent[0])
    assert ledger["state"] == "unknown" and ledger["platforms"] == ["tiktok", "youtube"]


def test_empty_2xx_body_is_treated_as_accepted_after_checking(up, monkeypatch, video):
    import httpx
    sent = _httpx_post(monkeypatch, up, httpx.Response(200, content=b""))
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("x"))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == 0 and len(sent) == 1


@pytest.mark.parametrize("code", [400, 401, 403, 422])
def test_explicit_4xx_rejection_is_definitive_and_not_polled(up, monkeypatch, video, code):
    import httpx
    _httpx_post(monkeypatch, up, httpx.Response(code, json={"message": "rejected"}))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")  # http_get 仍是 _fail：若去轮询会直接报错
    assert rc == 3 and up.recorded == []


def test_status_poll_errors_end_as_unknown(up, monkeypatch, video):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"request_id": "r"})
    monkeypatch.setattr(up, "http_get", _fail("connection reset"))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == up.EXIT_UNKNOWN
    assert up.recorded == []


# ── 评审补充的边界用例（#74 review） ─────────────────────────────────────────
def _exec_with_status(up, monkeypatch, video, status, platforms="tiktok", **resp):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"success": True, **resp,
                                                          "request_id": a[2]["request_id"]})
    monkeypatch.setattr(up, "http_get", lambda *a, **k: status)
    return run(up, monkeypatch, "publish", "--platforms", platforms, "--media", str(video),
               "--title", "Hi", "--exec")


def test_tiktok_inbox_fallback_is_a_draft_not_published(up, monkeypatch, video, capsys):
    rc = _exec_with_status(up, monkeypatch, video, {"status": "completed", "results": [
        {"platform": "tiktok", "success": True, "fallback_to_inbox": True,
         "post_url": "Video sent to Inbox (No Public URL)"}]})
    out = capsys.readouterr().out
    assert rc == 0 and "草稿" in out and "✅" not in out
    assert [(a[0], k["status"]) for a, k in up.recorded] == [("TikTok", "draft")]


def test_success_without_post_id_or_link_is_unverified(up, monkeypatch, video, capsys):
    rc = _exec_with_status(up, monkeypatch, video, {"status": "completed", "results": [
        {"platform": "tiktok", "success": True}]})
    out = capsys.readouterr().out
    assert rc == up.EXIT_UNKNOWN and up.recorded == []
    assert "None" not in out and "没有作品链接或 ID" in out


def test_entry_with_only_platform_is_unknown_not_failed(up, monkeypatch, video, capsys):
    rc = _exec_with_status(up, monkeypatch, video, {"status": "completed",
                                                    "results": [{"platform": "tiktok"}]})
    out = capsys.readouterr().out
    assert rc == up.EXIT_UNKNOWN and "❌" not in out and up.recorded == []


def _schedule_args(video):
    return ["publish", "--platforms", "x", "--media", str(video), "--title", "Hi",
            "--schedule", "2099-01-01T09:00:00", "--timezone", "Asia/Shanghai", "--exec"]


def test_schedule_200_with_success_false_is_rejected_not_scheduled(up, monkeypatch, video, capsys):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"success": False, "message": "no slot"})
    rc = run(up, monkeypatch, *_schedule_args(video))
    assert rc == up.EXIT_REJECTED and "已排期" not in capsys.readouterr().out


def test_schedule_without_job_id_is_unknown_not_scheduled(up, monkeypatch, video, capsys):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"success": True})
    rc = run(up, monkeypatch, *_schedule_args(video))
    out = capsys.readouterr().out
    assert rc == up.EXIT_UNKNOWN and "✅ 已排期" not in out and "job_id" in out


def test_schedule_with_job_id_is_scheduled(up, monkeypatch, video, capsys):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"success": True, "job_id": "j" * 32})
    assert run(up, monkeypatch, *_schedule_args(video)) == 0
    assert "已排期" in capsys.readouterr().out


def test_immediate_200_with_success_false_is_rejected(up, monkeypatch, video):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"success": False, "message": "bad"})
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")  # http_get 仍是 _fail：不会去轮询
    assert rc == up.EXIT_REJECTED and up.recorded == []


@pytest.mark.parametrize("code", [413, 429])
def test_other_4xx_like_quota_are_definitive(up, monkeypatch, video, code):
    import httpx
    _httpx_post(monkeypatch, up, httpx.Response(code, json={"message": "monthly limit"}))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == up.EXIT_REJECTED


def test_409_same_key_in_progress_is_checked_not_rejected(up, monkeypatch, video):
    import httpx
    sent = _httpx_post(monkeypatch, up, httpx.Response(409, json={
        "error_code": "IDEMPOTENCY_KEY_IN_USE"}))
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("x"))
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")
    assert rc == 0 and len(sent) == 1


# ── Provider 与发布模式 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["twitter-x", "twitter"])
def test_browser_x_route_is_a_different_provider(up, monkeypatch, name, capsys):
    assert run(up, monkeypatch, "publish", "--platforms", name, "--title", "t") not in (0, None)
    assert "twitter-x" in capsys.readouterr().err


def test_manual_publish_mode_refuses_exec(up, monkeypatch, video, capsys):
    monkeypatch.setenv("EASEL_PUBLISH_MODE", "manual")
    rc = run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
             "--title", "Hi", "--exec")  # http_post 仍是 _fail
    assert rc == up.EXIT_MANUAL_MODE and "人工审核发布" in capsys.readouterr().err


def test_manual_publish_mode_still_allows_dry_run(up, monkeypatch, video, capsys):
    monkeypatch.setenv("EASEL_PUBLISH_MODE", "manual")
    monkeypatch.delenv("UPLOAD_POST_API_KEY")
    assert run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
               "--title", "Hi") == 0
    assert "人工专用" in capsys.readouterr().out


def test_profile_is_passed_to_calendar(up, monkeypatch, video):
    monkeypatch.setattr(up, "http_post", lambda *a, **k: {"request_id": "r"})
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("x"))
    run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video), "--title", "Hi",
        "--profile", "户外达人", "--exec")
    assert [k["profile"] for _a, k in up.recorded] == ["户外达人"]


# ── 台账：重启后核对与补记 ─────────────────────────────────────────────────────
def test_unknown_then_status_record_writes_calendar_once(up, monkeypatch, video):
    import httpx
    sent = _httpx_post(monkeypatch, up, httpx.ReadTimeout("timed out"))
    monkeypatch.setattr(up, "http_get", lambda *a, **k: {"status": "not_found"})
    assert run(up, monkeypatch, "publish", "--platforms", "x", "--media", str(video),
               "--title", "Hi", "--exec") == up.EXIT_UNKNOWN
    assert up.recorded == []
    monkeypatch.setattr(up, "http_get", lambda *a, **k: completed("x"))
    assert run(up, monkeypatch, "status", "--id", sent[0], "--record") == 0
    assert run(up, monkeypatch, "status", "--id", sent[0], "--record") == 0
    assert [(a[0], k["status"]) for a, k in up.recorded] == [("X", "published")]


def test_status_not_found_with_local_ledger_is_unknown(up, monkeypatch):
    up.write_ledger("rid-1", platforms=["x"], state="unknown")
    monkeypatch.setattr(up, "http_get", lambda *a, **k: {"status": "not_found"})
    assert run(up, monkeypatch, "status", "--id", "rid-1") == up.EXIT_UNKNOWN
