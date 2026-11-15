"""Offline regression for asynchronously loaded and refreshed account login QR codes."""
import base64
from contextlib import nullcontext
import html
import io
import random
from itertools import count
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
import segno
from PIL import Image
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/shared/scripts'))
sys.path.insert(0, str(ROOT / 'skills/builtin/skill-toutiao-publisher/scripts'))
import login_state
import toutiao_publish as tp
import weixin_mp_stats as mp


def qr_data():
    stream = io.BytesIO()
    segno.make_qr('offline-login-review').save(stream, kind='png', scale=5, border=4)
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


@pytest.fixture(scope='module')
def browser():
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip('requires Playwright Chromium')
        browser = pw.chromium.launch(headless=True)
        try:
            # A browser can serve DOM operations while its compositor cannot
            # capture frames (for example on a headless host without a working
            # rendering clock). Detect that prerequisite before pixel checks.
            probe = browser.new_page()
            try:
                probe.set_content('<main style="width:32px;height:32px;background:black"></main>')
                probe.screenshot(timeout=2000, animations='disabled')
            except PlaywrightTimeoutError as error:
                pytest.skip(f'Chromium frame capture unavailable ({type(error).__name__}); requires a working renderer')
            finally:
                probe.close()
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    context.route('**/*', lambda route: route.abort())
    page = context.new_page()
    yield page
    context.close()


def fast_deadline(monkeypatch, module):
    clock = count(step=10)
    monkeypatch.setattr(module.time, 'time', lambda: next(clock))


def test_toutiao_phone_login_and_qr_can_coexist(page, tmp_path):
    page.set_content(f'<input type="tel"><div class="qrcode-wrapper"><img src="{qr_data()}"></div>')
    assert tp._capture_qr(page, tmp_path / 'qr.png')


def test_toutiao_capture_waits_for_async_qr_in_phone_login_page(page, tmp_path):
    page.set_content('<input type="tel"><div class="qrcode-wrapper"></div>')
    page.evaluate('src => setTimeout(() => { const image=new Image(); image.src=src; '
                  'document.querySelector(".qrcode-wrapper").appendChild(image); }, 50)', qr_data())
    assert tp._capture_qr(page, tmp_path / 'qr.png')


def test_toutiao_qr_in_login_iframe_can_be_captured(page, tmp_path, monkeypatch):
    frame_html = f'<input type="tel"><div class="qrcode-wrapper"><img src="{qr_data()}"></div>'
    page.set_content(f'<iframe style="width:400px;height:400px" srcdoc="{html.escape(frame_html, quote=True)}"></iframe>')
    assert tp._qr_visible(page)
    fast_deadline(monkeypatch, tp)
    assert tp._capture_qr(page, tmp_path / 'qr.png')


def test_toutiao_non_qr_image_does_not_overwrite_previous_code(page, tmp_path, monkeypatch):
    image = Image.new('RGB', (160,160))
    image.frombytes(random.Random(7).randbytes(160*160*3))
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    assert len(stream.getvalue()) > 500
    src = 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()
    page.set_content(f'<div class="qrcode-wrapper"><img src="{src}"></div>')
    output = tmp_path / 'qr.png'
    output.write_bytes(b'previous-verified-qr')
    fast_deadline(monkeypatch, tp)
    assert not tp._capture_qr(page, output)
    assert output.read_bytes() == b'previous-verified-qr'


@pytest.mark.parametrize('permanent_binding', [False, True])
def test_toutiao_poll_allows_transient_qr_rotation_but_rejects_binding(tmp_path, monkeypatch, permanent_binding):
    clock = [0.0]
    states = []
    page = SimpleNamespace(url=tp.LOGIN_URL, goto=lambda *a, **k: None,
                           wait_for_timeout=lambda ms: clock.__setitem__(0, clock[0]+ms/1000))
    context = SimpleNamespace(pages=[page], close=lambda: None)
    pw = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a, **k: context))
    monkeypatch.setattr(tp, '_require_playwright', lambda: lambda: nullcontext(pw))
    monkeypatch.setattr(tp.time, 'time', lambda: clock[0])
    monkeypatch.setattr(tp, '_needs_phone_binding', lambda p: True)
    monkeypatch.setattr(tp, '_qr_visible', lambda p: clock[0]<4 or (not permanent_binding and clock[0]>=6))
    monkeypatch.setattr(tp, '_backend_authenticated', lambda p: False)
    monkeypatch.setattr(tp, '_capture_qr', lambda p, output: output.write_bytes(b'qr') or True)
    write = login_state.write_status
    monkeypatch.setattr(login_state, 'write_status', lambda path, state, *a, **k:
                        states.append((state, clock[0])) or write(path, state, *a, **k))
    status = tmp_path / 'status.json'
    assert tp._qr_login(tmp_path / 'profile', tmp_path / 'qr.png', status, 30, headed=False) == 1
    assert states[1][0] == 'qr_ready'
    if permanent_binding:
        assert states[-1][0] == 'error'
        assert states[-1][1] >= 16
    else:
        assert states[-1][0] == 'expired'
        assert not any(state in {'error','success'} for state, _ in states)


def test_mp_delayed_scan_switch_is_used_once(monkeypatch):
    clock = [0.0]
    switched = []
    qr = SimpleNamespace(is_visible=lambda: bool(switched), bounding_box=lambda: {'width':120,'height':120})
    link = SimpleNamespace(inner_text=lambda: '扫码登录', is_visible=lambda: True,
                           click=lambda **k: switched.append(clock[0]))
    page = SimpleNamespace(query_selector=lambda sel: qr,
                           query_selector_all=lambda sel: [qr] if 'qrcode' in sel else ([link] if clock[0]>=1 else []),
                           evaluate=lambda *a: bool(switched),
                           wait_for_timeout=lambda ms: clock.__setitem__(0, clock[0]+ms/1000))
    monkeypatch.setattr(mp.time, 'monotonic', lambda: clock[0])
    assert mp._ensure_qr_mode(page, timeout=3)
    assert len(switched) == 1


def test_mp_blank_qr_image_is_not_ready(page):
    page.set_content('<img class="login__type__container__scan__qrcode" style="width:120px;height:120px">')
    assert not mp._qr_visible(page)


def test_mp_capture_skips_hidden_qr_and_keeps_legacy_selector(page, tmp_path):
    page.set_content(f'<img class="login__type__container__scan__qrcode" style="display:none">'
                     f'<div class="login__type__container__scan"><img src="{qr_data()}"></div>')
    assert mp._capture_qr(page, tmp_path / 'qr.png', attempts=1)


def test_mp_expired_mask_clicks_only_explicit_refresh_link(page):
    page.set_content('<div class="login__type__container__scan_mask">二维码已过期 '
                     '<a onclick="window.help=true">帮助</a>'
                     '<a onclick="window.refreshed=true">点击刷新</a></div>')
    assert mp._refresh_expired_qr(page)
    assert page.evaluate('window.refreshed === true && window.help !== true')


def test_mp_scanned_mask_is_not_cancelled_by_old_expiry_message(page):
    page.set_content('<div class="login__type__container__scan_mask">扫码成功，旧码已过期 '
                     '<a onclick="window.cancelled=true">重新扫码</a></div>')
    assert not mp._refresh_expired_qr(page)
    assert page.evaluate('window.cancelled !== true')
