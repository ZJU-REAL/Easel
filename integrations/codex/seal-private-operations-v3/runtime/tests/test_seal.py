import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from easel.skill_labels import SKILL_LABELS
from seal_core.tasks import TaskStore
from web import app as web
import xhs_publish as xhs


def test_chinese_catalog_complete_and_consistent():
    skills = web.get_skills()
    # V3 将完整的 113 项能力内置在一个 Codex Skill 中。
    assert len(skills) == 113
    assert set(SKILL_LABELS) == {s['name'] for s in skills}
    assert len({v[0] for v in SKILL_LABELS.values()}) == 113
    for s in skills:
        assert any('\u4e00' <= c <= '\u9fff' for c in s['displayName'])
        assert 8 <= len(s['displayDescription']) <= 60
        detail = asyncio.run(web.api_skill_detail(s['name']))
        assert detail['displayName'] == s['displayName']
        assert detail['displayDescription'] == s['displayDescription']
        assert detail['body']


@pytest.fixture
def login_env(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'LOGIN_DIR', tmp_path)
    monkeypatch.setattr(web, 'LOGIN_PROCESSES', {})
    monkeypatch.setattr(web, '_ACCOUNT_LOCKS', {})
    monkeypatch.setattr(web, '_WHOAMI_CACHE', {})
    return tmp_path


def test_xhs_direct_default_and_explicit_override(monkeypatch):
    monkeypatch.delenv('EASEL_XHS_PROXY_MODE', raising=False)
    monkeypatch.setenv('https_proxy', 'http://proxy.example:80')
    assert web._xhs_proxy_args() == ['--no-proxy']
    assert xhs._proxy(None, False) is None
    monkeypatch.setenv('EASEL_XHS_PROXY_MODE', 'proxy')
    assert web._xhs_proxy_args() == []
    assert xhs._proxy(None, False) == 'http://proxy.example:80'
    assert xhs._proxy('http://explicit:80', False) == 'http://explicit:80'
    assert xhs._proxy('http://explicit:80', True) is None


def test_xhs_login_state_syncs_to_v3_redbook_file(tmp_path, monkeypatch):
    target = tmp_path / "redbook" / "cookies.json"
    monkeypatch.setenv("REDBOOK_COOKIE_FILE", str(target))
    context = Mock()
    context.cookies.return_value = [
        {"name": "a1", "value": "test-a1", "domain": ".xiaohongshu.com"},
        {"name": "web_session", "value": "test-session", "domain": ".xiaohongshu.com"},
        {"name": "unrelated", "value": "skip", "domain": ".example.com"},
    ]

    assert xhs._sync_redbook_cookies(context)
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["platform"] == "xhs"
    assert payload["cookies"] == {"a1": "test-a1", "web_session": "test-session"}
    assert payload["createdAt"].endswith("Z")


def test_xhs_login_does_not_write_incomplete_redbook_state(tmp_path, monkeypatch):
    target = tmp_path / "redbook" / "cookies.json"
    monkeypatch.setenv("REDBOOK_COOKIE_FILE", str(target))
    context = Mock()
    context.cookies.return_value = [
        {"name": "a1", "value": "test-a1", "domain": ".xiaohongshu.com"},
    ]

    assert not xhs._sync_redbook_cookies(context)
    assert not target.exists()


def test_delete_task_detaches_linked_data_to_global(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs"
    schedule_file = output_root / "_schedule.json"
    ideas_file = output_root / "_ideas.json"
    sessions_dir = tmp_path / "sessions"
    task_store = TaskStore(output_root / "_ops_tasks")
    task = task_store.create("待删除任务", "xiaohongshu", scenario="W3", conversation_id="ops_delete_test")
    task_id = task["task_id"]
    output_root.mkdir(parents=True, exist_ok=True)
    ideas_file.write_text(json.dumps([{"id": "idea", "task_id": task_id}]), encoding="utf-8")
    schedule_file.write_text(json.dumps([{"id": "event", "task_id": task_id}]), encoding="utf-8")
    project = output_root / "保留项目"
    project.mkdir()
    (project / ".easel.json").write_text(json.dumps({"title": "保留项目", "task_id": task_id}), encoding="utf-8")

    monkeypatch.setattr(web, "OUTPUTS_DIR", output_root)
    monkeypatch.setattr(web, "SCHEDULE_FILE", schedule_file)
    monkeypatch.setattr(web, "IDEAS_FILE", ideas_file)
    monkeypatch.setattr(web, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(web, "OPS_TASKS", task_store)
    monkeypatch.setattr(web, "forget_session", lambda _key: True)

    result = asyncio.run(web.ops_task_delete(task_id))

    assert result["detached"] == {"ideas": 1, "schedule": 1, "projects": 1}
    assert json.loads(ideas_file.read_text())[0]["task_id"] is None
    assert json.loads(schedule_file.read_text())[0]["task_id"] is None
    assert json.loads((project / ".easel.json").read_text())["task_id"] is None
    with pytest.raises(Exception):
        task_store.get(task_id)


def test_login_navigation_retry_is_bounded():
    page = Mock()
    page.locator.return_value.count.side_effect = [Exception('Execution context was destroyed'), 1]
    assert xhs._has_login(page)
    assert page.wait_for_timeout.call_count == 1
    page.locator.return_value.count.side_effect = Exception('Execution context was destroyed')
    with pytest.raises(Exception, match='Execution context'):
        xhs._has_login(page, attempts=2)
    page.locator.return_value.count.side_effect = Exception('Target closed')
    with pytest.raises(Exception, match='Target closed'):
        xhs._has_login(page)


def test_failed_runner_never_exposes_stale_qr(login_env):
    (login_env / 'xiaohongshu.json').write_text(json.dumps({'state': 'qr_ready'}))
    (login_env / 'xiaohongshu.png').write_bytes(b'old-qr')
    web.LOGIN_PROCESSES['xiaohongshu'] = SimpleNamespace(poll=lambda: 1)
    s = web._login_status('xiaohongshu')
    assert s['state'] == 'error'
    assert s['qr'] == ''


def test_repeated_login_reuses_runner(login_env, monkeypatch):
    proc = SimpleNamespace(poll=lambda: None)
    popen = Mock(return_value=proc)
    monkeypatch.setattr(web.subprocess, 'Popen', popen)

    async def scenario():
        first, second = await asyncio.gather(web.api_login_start('xiaohongshu'), web.api_login_start('xiaohongshu'))
        assert first['state'] == second['state'] == 'starting'
        with pytest.raises(HTTPException) as err:
            await web.api_account_whoami('xiaohongshu')
        assert err.value.status_code == 409

    asyncio.run(scenario())
    assert popen.call_count == 1
    assert '--no-proxy' in popen.call_args.args[0]
    assert '--headed' in popen.call_args.args[0]
    assert popen.call_args.kwargs['start_new_session']


def test_whoami_and_login_serialize_profile_access(login_env, monkeypatch):
    order = []

    async def verify(platform):
        order.append('verify-start')
        await asyncio.sleep(.01)
        order.append('verify-end')
        return {'loggedIn': False}

    async def start(platform):
        order.append('login')
        return {'state': 'starting'}

    monkeypatch.setattr(web, '_account_whoami', verify)
    monkeypatch.setattr(web, '_login_start', start)

    async def scenario():
        await asyncio.gather(web.api_account_whoami('xiaohongshu'), web.api_login_start('xiaohongshu'))

    asyncio.run(scenario())
    assert order == ['verify-start', 'verify-end', 'login']


def test_whoami_error_not_cached_or_marked_logged_out(login_env, monkeypatch):
    web._write_login_marker('xiaohongshu', 'success')
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='{"loggedIn": false, "error": "network"}'))
    with pytest.raises(HTTPException) as err:
        asyncio.run(web.api_account_whoami('xiaohongshu'))
    assert err.value.status_code == 503
    assert web._login_status('xiaohongshu')['state'] == 'success'
    assert not web._WHOAMI_CACHE


def test_status_waits_for_profile_save(login_env):
    web._write_login_marker('xiaohongshu', 'success')
    web.LOGIN_PROCESSES['xiaohongshu'] = SimpleNamespace(poll=lambda: None)
    assert asyncio.run(web.api_login_status('xiaohongshu'))['state'] == 'verifying'


def test_cancel_targets_only_owned_runner(login_env, monkeypatch):
    proc = Mock(pid=12345)
    proc.poll.return_value = None
    web.LOGIN_PROCESSES['xiaohongshu'] = proc
    killpg = Mock()
    monkeypatch.setattr(web.os, 'killpg', killpg)
    asyncio.run(web.api_login_cancel('xiaohongshu'))
    killpg.assert_called_once_with(12345, web.signal.SIGTERM)
    assert web._login_status('xiaohongshu')['state'] == 'cancelled'


def test_browser_direct_explicitly_disables_system_proxy(tmp_path):
    playwright = Mock()
    xhs._launch(playwright, headed=True, base=str(tmp_path), proxy=None)
    args = playwright.chromium.launch_persistent_context.call_args.kwargs
    assert '--no-proxy-server' in args['args']
    assert args['headless'] is False
    xhs._launch(playwright, headed=False, base=str(tmp_path), proxy='http://proxy:80')
    args = playwright.chromium.launch_persistent_context.call_args.kwargs
    assert '--no-proxy-server' not in args['args']
    assert args['proxy']['server'] == 'http://proxy:80'
