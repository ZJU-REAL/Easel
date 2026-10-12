import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
import app as web


@pytest.fixture(autouse=True)
def isolated_inflight(monkeypatch):
    monkeypatch.setattr(web, "_analytics_inflight", {})


def test_concurrent_refreshes_share_one_fetch(monkeypatch):
    async def scenario():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def fetch(platform):
            calls.append(platform)
            started.set()
            await finish.wait()
            return {"platform": platform}

        monkeypatch.setattr(web, "_fetch_analytics", fetch)
        first = asyncio.create_task(web.api_analytics("xiaohongshu"))
        await started.wait()
        second = asyncio.create_task(web.api_analytics("xiaohongshu"))
        await asyncio.sleep(0)
        finish.set()
        assert await first == await second == {"platform": "xiaohongshu"}
        assert calls == ["xiaohongshu"]
        await asyncio.sleep(0)
        assert web._analytics_inflight == {}
        assert await web.api_analytics("xiaohongshu") == {"platform": "xiaohongshu"}
        assert calls == ["xiaohongshu", "xiaohongshu"]

    asyncio.run(scenario())


def test_cancelled_client_does_not_cancel_shared_fetch(monkeypatch):
    async def scenario():
        finish = asyncio.Event()
        async def fetch(platform):
            await finish.wait()
            return {"platform": platform}

        monkeypatch.setattr(web, "_fetch_analytics", fetch)
        client = asyncio.create_task(web.api_analytics("xiaohongshu"))
        await asyncio.sleep(0)
        client.cancel()
        with pytest.raises(asyncio.CancelledError):
            await client
        assert not web._analytics_inflight["xiaohongshu"].cancelled()
        other = asyncio.create_task(web.api_analytics("xiaohongshu"))
        finish.set()
        assert await other == {"platform": "xiaohongshu"}

    asyncio.run(scenario())


def test_failed_refresh_can_be_retried(monkeypatch):
    async def scenario():
        async def fetch(platform):
            raise HTTPException(502, "Unavailable")

        monkeypatch.setattr(web, "_fetch_analytics", fetch)
        for attempt in range(2):
            with pytest.raises(HTTPException):
                await web.api_analytics("xiaohongshu")
            await asyncio.sleep(0)
            assert web._analytics_inflight == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("code,payload,status", [
    (0, {"loggedIn": True, "followers": None, "likes": None, "metrics": [], "notes": []}, 502),
    (1, {"loggedIn": True, "followers": 7}, 502),
    (0, {"error": "Platform maintenance"}, 502),
    (0, {"loggedIn": True, "followers": 0}, None),
    (0, {"loggedIn": False}, None),
])
def test_failed_or_empty_payload_is_not_success(monkeypatch, code, payload, status):
    monkeypatch.setattr(web, "_run_analytics_command", lambda *args: subprocess.CompletedProcess(
        [], code, json.dumps(payload), ""))
    if status:
        with pytest.raises(HTTPException) as error:
            asyncio.run(web._fetch_analytics("xiaohongshu"))
        assert error.value.status_code == status
    else:
        assert asyncio.run(web._fetch_analytics("xiaohongshu")) == payload


def test_fetch_propagates_actionable_script_error(monkeypatch):
    monkeypatch.setattr(web, "_run_analytics_command", lambda *args: subprocess.CompletedProcess(
        [], 1, "", "ERROR: 小红书登录目录正被占用"))
    with pytest.raises(HTTPException, match="登录目录正被占用"):
        asyncio.run(web._fetch_analytics("xiaohongshu"))


def test_fetch_reports_bounded_timeout(monkeypatch):
    runner = Mock(side_effect=subprocess.TimeoutExpired("fetch", 90))
    monkeypatch.setattr(web, "_run_analytics_command", runner)
    with pytest.raises(HTTPException) as error:
        asyncio.run(web._fetch_analytics("xiaohongshu"))
    assert error.value.status_code == 504
    assert runner.call_args.args[2] == 90
    assert runner.call_args.args[1]["PYTHONIOENCODING"] == "utf-8"
    assert runner.call_args.args[1]["PYTHONUTF8"] == "1"


def test_subprocess_timeout_stops_browser_tree(monkeypatch):
    process = Mock(pid=123456)
    process.communicate.side_effect = [subprocess.TimeoutExpired("fetch", 1), ("", "")]
    popen = Mock(return_value=process)
    monkeypatch.setattr(web.subprocess, "Popen", popen)
    if os.name == "nt":
        killer = Mock()
        monkeypatch.setattr(web.subprocess, "run", killer)
    else:
        killer = Mock()
        monkeypatch.setattr(web.os, "killpg", killer)
    with pytest.raises(subprocess.TimeoutExpired):
        web._run_analytics_command(["python", "fetch"], {}, 1)
    assert popen.call_args.kwargs["encoding"] == "utf-8"
    assert popen.call_args.kwargs["start_new_session"] is (os.name != "nt")
    if os.name == "nt":
        assert killer.call_args.args[0] == ["taskkill", "/PID", "123456", "/T", "/F"]
    else:
        killer.assert_called_once_with(123456, signal.SIGKILL)
    process.kill.assert_called_once()
    assert process.communicate.call_count == 2
