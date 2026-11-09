"""Login evidence against real Chromium DOM with all network traffic intercepted."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/builtin/skill-toutiao-publisher/scripts'))
import toutiao_publish as tp

AUTH_HTML = '<header><div class="user-info"><span class="user-name">我的头条号</span></div><a href="/profile_v4/graphic/publish">发布作品</a></header>'


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip('requires Playwright Chromium')
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def load(page, html, session=True):
    page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html))
    if session:
        page.context.add_cookies([{'name': 'sessionid', 'value': 'offline-test', 'url': tp.HOME_URL}])
    page.goto(tp.HOME_URL)


@pytest.mark.parametrize('html', [
    '', '<main>正在加载…</main>', '<main>服务暂不可用</main>',
    '<input type="tel" placeholder="手机号"><input placeholder="验证码">',
    '<div>手机绑定</div><input type="tel" aria-label="手机号">',
    '<div>绑定手机号</div><input placeholder="输入手机号">',
    AUTH_HTML + '<input type="password" placeholder="密码">',
])
def test_http_200_without_completed_login_never_proves_authentication(page, html):
    load(page, html)
    assert not tp._backend_authenticated(page)


def test_public_creator_navigation_without_session_cannot_verify_login(page):
    load(page, AUTH_HTML, session=False)
    assert not tp._backend_authenticated(page)


def test_creator_controls_and_scoped_session_verify_login(page):
    load(page, AUTH_HTML)
    assert tp._backend_authenticated(page)


def test_identity_is_not_borrowed_from_another_content_author(page):
    load(page, '<article><span class="user-name">其他作者</span></article>' + AUTH_HTML)
    assert tp._read_display_name(page) == '我的头条号'


def test_probe_on_empty_200_preserves_previous_account_as_unknown(page, tmp_path, monkeypatch):
    load(page, '')
    context = SimpleNamespace(pages=[page], close=lambda: None)
    pw = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a, **k: context))
    monkeypatch.setattr(tp, '_require_playwright', lambda: lambda: nullcontext(pw))
    monkeypatch.setattr(tp, 'PROFILE_DIR', tmp_path / 'profile')
    result = tp._probe_identity()
    assert not result['loggedIn'] and result.get('error')


def test_no_detected_qr_never_screenshots_an_entire_form(page, tmp_path, monkeypatch):
    load(page, '<input placeholder="请输入邮箱"><input type="password">')
    # Skip the scan deadline without relying on a real 15-second wait.
    clock = iter([0, 100])
    monkeypatch.setattr(tp.time, 'time', lambda: next(clock, 100))
    qr = tmp_path / 'qr.png'
    assert not tp._capture_qr(page, qr)
    assert not qr.exists()
