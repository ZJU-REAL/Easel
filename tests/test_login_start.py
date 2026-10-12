import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import web.app as web


@pytest.mark.parametrize("platform", ["xiaohongshu", "zhihu", "wechat-oa"])
def test_login_start_returns_without_waiting_for_qr(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {})
    monkeypatch.setattr(web, "_WHOAMI_CACHE", {})
    monkeypatch.setattr(web, "_LOGIN_START_LOCKS", {})
    process = SimpleNamespace(poll=lambda: None)
    launch = Mock(return_value=process)
    monkeypatch.setattr(web.subprocess, "Popen", launch)

    async def sleep(duration):
        pytest.fail("Login start must not wait for browser or QR generation")

    monkeypatch.setattr(web.asyncio, "sleep", sleep)
    start = web.api_mp_login_start if platform == "wechat-oa" else web.api_login_start
    result = asyncio.run(start(platform))
    assert result["mode"] == "qr"
    assert result["state"] == "starting"
    assert result["qr"] == ""
    assert "二维码" in result["message"]
    launch.assert_called_once()
    key = "wechat-oa-mp" if platform == "wechat-oa" else platform
    assert web.LOGIN_PROCESSES[key] is process
    assert launch.call_args.kwargs["stdout"].closed


@pytest.mark.parametrize("platform", ["xiaohongshu", "zhihu", "wechat-oa"])
def test_login_start_reports_immediate_runner_exit(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {})
    monkeypatch.setattr(web, "_WHOAMI_CACHE", {})
    monkeypatch.setattr(web, "_LOGIN_START_LOCKS", {})
    monkeypatch.setattr(web.subprocess, "Popen", Mock(return_value=SimpleNamespace(poll=lambda: 1)))
    start = web.api_mp_login_start if platform == "wechat-oa" else web.api_login_start
    result = asyncio.run(start(platform))
    assert result["state"] == "error"
    assert result["qr"] == ""


def test_zhihu_restart_exits_old_runner_before_removing_qr(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "_WHOAMI_CACHE", {})
    monkeypatch.setattr(web, "_LOGIN_START_LOCKS", {})
    qr = tmp_path / "zhihu.png"
    qr.write_bytes(b"old-qr")
    (tmp_path / "zhihu.json").write_text('{"state":"qr_ready"}')
    order = []
    old = Mock()
    old.poll.return_value = None
    old.terminate.side_effect = lambda: order.append("terminate")
    def wait(**kwargs):
        assert qr.exists()
        order.append("wait")

    old.wait.side_effect = wait
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {"zhihu": old})
    new = SimpleNamespace(poll=lambda: None)
    def launch(*args, **kwargs):
        assert not qr.exists()
        order.append("launch")
        return new

    monkeypatch.setattr(web.subprocess, "Popen", launch)
    result = asyncio.run(web.api_login_start("zhihu", restart=True))
    assert order == ["terminate", "wait", "launch"]
    assert result["state"] == "starting"
    assert result["qr"] == ""
    assert web.LOGIN_PROCESSES["zhihu"] is new


def test_zhihu_restart_keeps_old_qr_if_runner_cannot_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "_LOGIN_START_LOCKS", {})
    qr = tmp_path / "zhihu.png"
    qr.write_bytes(b"old-qr")
    old = Mock()
    old.poll.return_value = None
    old.wait.side_effect = web.subprocess.TimeoutExpired("login", 8)
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {"zhihu": old})
    launch = Mock()
    monkeypatch.setattr(web.subprocess, "Popen", launch)
    with pytest.raises(web.HTTPException) as failure:
        asyncio.run(web.api_login_start("zhihu", restart=True))
    assert failure.value.status_code == 409
    assert qr.read_bytes() == b"old-qr"
    launch.assert_not_called()


@pytest.mark.parametrize("platform", ["xiaohongshu", "weixin-channels", "douyin", "kuaishou", "bilibili"])
def test_login_restart_reaps_old_runner_before_replacing_qr(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "_WHOAMI_CACHE", {})
    monkeypatch.setattr(web, "_LOGIN_START_LOCKS", {})
    qr = tmp_path / f"{platform}.png"
    qr.write_bytes(b"old")
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = lambda **kwargs: qr.exists() or pytest.fail("removed before exit")
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {platform: process})
    def launch(*args, **kwargs):
        assert not qr.exists()
        process.wait.assert_called_once_with(timeout=8)
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(web.subprocess, "Popen", launch)
    assert asyncio.run(web.api_login_start(platform, restart=True))["state"] == "starting"


@pytest.mark.parametrize("state", ["starting", "qr_ready", "scanned"])
def test_mp_exited_runner_always_terminates_polling(tmp_path, monkeypatch, state):
    monkeypatch.setattr(web, "LOGIN_DIR", tmp_path)
    monkeypatch.setattr(web, "LOGIN_PROCESSES", {"wechat-oa-mp": SimpleNamespace(poll=lambda: 1)})
    (tmp_path / "wechat-oa-mp.json").write_text(f'{{"state":"{state}"}}')
    (tmp_path / "wechat-oa-mp.png").write_bytes(b"old")
    status = web._mp_login_status()
    assert status["state"] == "error"
    assert status["qr"] == ""
