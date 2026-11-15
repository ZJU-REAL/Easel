"""Identity failures retain their semantics and suppress automatic browser retries."""
import ast
import asyncio
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest
from web import app as web


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'LOGIN_DIR', tmp_path / 'login')
    monkeypatch.setattr(web, 'BROWSER_PROFILES', tmp_path / 'browser-profiles')
    monkeypatch.setattr(web, '_WHOAMI_CACHE', {})
    monkeypatch.setattr(web, '_WHOAMI_TASKS', {})
    monkeypatch.setattr(web, '_WHOAMI_FAILURES', {}, raising=False)
    monkeypatch.setattr(web, 'LOGIN_PROCESSES', {})
    return tmp_path


def failed_check():
    return SimpleNamespace(returncode=0, stdout='{"loggedIn":false,"error":"not ready"}')


def check_error(platform='xiaohongshu', *, force=False, status=502):
    with pytest.raises(web.HTTPException) as error:
        asyncio.run(web.api_account_whoami(platform, force=force))
    assert error.value.status_code == status
    return error.value.detail


def test_failed_check_is_reused_as_error_without_launching_a_browser(state, monkeypatch):
    calls=[]
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: calls.append(True) or failed_check())
    detail=check_error()
    assert check_error() == detail
    assert len(calls)==1
    assert not web._WHOAMI_CACHE


def test_failed_force_check_preserves_previously_verified_identity(state, monkeypatch):
    web._write_login_marker('xiaohongshu', 'success')
    identity={'loggedIn':True,'name':'Own account','avatar':'https://offline.test/avatar.png'}
    web._WHOAMI_CACHE['xiaohongshu']=(web.time.time(), identity.copy())
    marker=(web.LOGIN_DIR/'xiaohongshu.json').read_bytes()
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: failed_check())
    check_error(force=True)
    assert web._WHOAMI_CACHE['xiaohongshu'][1] == identity
    assert (web.LOGIN_DIR/'xiaohongshu.json').read_bytes()==marker
    check_error()


def test_browser_timeout_also_has_a_short_cooldown(state, monkeypatch):
    calls=[]
    def timeout(*a, **k):
        calls.append(True)
        raise subprocess.TimeoutExpired(a[0], 35)
    monkeypatch.setattr(web.subprocess, 'run', timeout)
    check_error(status=504)
    check_error(status=504)
    assert len(calls)==1


def test_cooldown_expires_and_explicit_retry_bypasses_it(state, monkeypatch):
    clock=[1000.0]; calls=[]
    monkeypatch.setattr(web.time, 'time', lambda: clock[0])
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: calls.append(True) or failed_check())
    check_error(); check_error()
    assert len(calls)==1
    check_error(force=True)
    assert len(calls)==2
    clock[0]+=121
    check_error()
    assert len(calls)==3


def test_login_change_invalidates_cooldown_even_if_both_markers_are_success(state, monkeypatch):
    web._write_login_marker('xiaohongshu', 'success', 'First')
    calls=[]
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: calls.append(True) or failed_check())
    check_error()
    web._write_login_marker('xiaohongshu', 'success', 'Second')
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: calls.append(True) or
                        SimpleNamespace(returncode=0, stdout='{"loggedIn":true,"name":"Second","avatar":""}'))
    assert asyncio.run(web.api_account_whoami('xiaohongshu'))['name']=='Second'
    assert len(calls)==2


def test_logout_clears_cooldown_for_an_account_without_a_marker(state, monkeypatch):
    calls=[]
    monkeypatch.setattr(web.subprocess, 'run', lambda *a, **k: calls.append(True) or failed_check())
    check_error()
    assert asyncio.run(web.api_logout('xiaohongshu'))['ok']
    check_error()
    assert len(calls)==2


def extra_hosts(value):
    source=ast.parse((Path(__file__).resolve().parents[1]/'web/app.py').read_text(encoding='utf-8'))
    nodes=[n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_normalize_extra_hosts']
    nodes += [n for n in source.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=='_EXTRA_HOSTS' for t in n.targets)]
    env={'os':SimpleNamespace(environ={'EASEL_EXTRA_HOSTS':value}),'re':re}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'host-config','exec'),env)
    return env['_EXTRA_HOSTS']


@pytest.mark.parametrize('value,expected',[
    ('example.com:8443,*.example.net:443', ['example.com','*.example.net']),
    ('::1,2001:db8::1', ['::1','2001:db8::1']),
    (' example.com ,localhost ', ['example.com','localhost']),
])
def test_extra_hosts_strips_only_an_unambiguous_numeric_port(value,expected):
    assert extra_hosts(value)==expected
