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
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
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
