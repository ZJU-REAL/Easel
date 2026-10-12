"""二维码裁剪、编码、平台拦截及 Web 登录进程的离线回归。"""
import ast
import asyncio
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import segno
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/shared/scripts"
sys.path.insert(0, str(SCRIPTS))
import login_qr
import login_state
import web_publisher
import xhs_publish


def qr_bytes(scale=3, border=4, content="easel-offline-login-test"):
    output = io.BytesIO()
    segno.make(content, micro=False).save(
        output, kind="png", scale=scale, border=border)
    return output.getvalue()


@pytest.mark.parametrize("scale", [2, 3, 5])
def test_qr_without_image_quiet_zone_is_detected(tmp_path, scale):
    output = tmp_path / "qr.png"
    assert login_qr.save_qr(qr_bytes(scale=scale, border=0), output)


def test_unchanged_qr_does_not_rewrite_and_changed_qr_refreshes(tmp_path):
    output = tmp_path / "qr.png"
    assert login_qr.save_qr(qr_bytes(), output)
    original = output.read_bytes()
    os.utime(output, ns=(1_000_000_000, 1_000_000_000))
    assert login_qr.save_qr(qr_bytes(), output)
    assert output.stat().st_mtime_ns == 1_000_000_000
    assert login_qr.save_qr(qr_bytes(content="easel-refreshed-login-test"), output)
    assert output.read_bytes() != original
    assert output.stat().st_mtime_ns != 1_000_000_000


def test_failed_atomic_save_keeps_previous_qr_and_cleans_temp(tmp_path, monkeypatch):
    output = tmp_path / "qr.png"
    assert login_qr.save_qr(qr_bytes(), output)
    original = output.read_bytes()
    monkeypatch.setattr(os, "replace", Mock(side_effect=OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        login_qr.save_qr(qr_bytes(content="easel-refreshed-login-test"), output)
    assert output.read_bytes() == original
    assert list(tmp_path.iterdir()) == [output]


def test_transparent_qr_is_composited_on_white(tmp_path):
    source = Image.open(io.BytesIO(qr_bytes(border=0))).convert("RGBA")
    source.putdata([
        (0, 0, 0, 255) if source.getpixel((column, row))[0] == 0 else (0, 0, 0, 0)
        for row in range(source.height) for column in range(source.width)
    ])
    encoded = io.BytesIO()
    source.save(encoded, format="PNG")
    assert login_qr.save_qr(encoded.getvalue(), tmp_path / "qr.png")


@pytest.mark.parametrize("scale", [2, 3, 5, 8])
def test_small_qr_is_cropped_padded_and_still_detectable(tmp_path, scale):
    import cv2

    output = tmp_path / "qr.png"
    assert login_qr.save_qr(qr_bytes(scale), output)
    with Image.open(output) as image:
        assert min(image.size) >= 360
        assert image.getpixel((0, 0)) == (255, 255, 255)
    found, _ = cv2.QRCodeDetector().detect(cv2.imread(str(output)))
    assert found


def test_large_login_panel_is_not_saved_as_qr(tmp_path):
    panel = Image.new("RGB", (1000, 700), "white")
    panel.paste(Image.open(io.BytesIO(qr_bytes())), (700, 400))
    source = io.BytesIO()
    panel.save(source, format="PNG")
    output = tmp_path / "qr.png"
    assert login_qr.save_qr(source.getvalue(), output)
    with Image.open(output) as image:
        assert max(image.size) < 500


def test_non_qr_image_does_not_create_output(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (300, 300), "red").save(image, format="PNG")
    output = tmp_path / "qr.png"
    assert not login_qr.save_qr(image.getvalue(), output)
    assert not output.exists()


def test_xhs_minimum_qr_size_rejects_small_switch_icon(tmp_path):
    output = tmp_path / "qr.png"
    assert not login_qr.save_qr(qr_bytes(scale=2), output, minimum_size=96)
    assert not output.exists()
    assert login_qr.save_qr(qr_bytes(scale=5), output, minimum_size=96)


@pytest.mark.parametrize("body", [
    "工程师正在维护页面，请稍后再试",
    "系统正在维护，请稍后重试",
])
def test_xhs_maintenance_is_not_expiry_or_authenticated_route(body):
    page = xhs_page(xhs_publish.CREATOR_HOME_URL, body=body)
    assert "维护页面" in xhs_publish._login_error(page)
    assert not xhs_publish._is_logged_in(page)


@pytest.mark.parametrize(("body", "expected"), [
    ("扫码成功，请在手机上确认", "scanned"),
    ("二维码已失效 点击刷新", "expired"),
    ("二维码已过期", "expired"),
    ("APP扫一扫登录", ""),
    ("扫码成功 二维码已失效", "scanned"),
])
def test_xhs_qr_state_distinguishes_confirmation_and_expiry(body, expected):
    assert xhs_publish._qr_state(xhs_page(body=body)) == expected


def test_xhs_qr_expiry_refresh_does_not_toggle_login_mode(tmp_path, monkeypatch):
    page = xhs_page(body="二维码已失效 点击刷新")
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all = lambda selector: [button] if "点击刷新" in selector else []
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert xhs_publish._refresh_expired_qr(page, tmp_path / "qr.png")
    button.click.assert_called_once()
    capture.assert_called_once_with(page, tmp_path / "qr.png",
                                   xhs_publish.SELECTORS["qrcode"], minimum_size=96)


def test_xhs_scanned_qr_is_never_refreshed(tmp_path, monkeypatch):
    page = xhs_page(body="扫码成功 请在手机上确认 二维码已失效")
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert not xhs_publish._refresh_expired_qr(page, tmp_path / "qr.png")
    capture.assert_not_called()


def test_xhs_whoami_falls_back_when_home_navigation_times_out(monkeypatch):
    page = xhs_page()

    def goto(destination, **kwargs):
        if destination == xhs_publish.CREATOR_HOME_URL:
            raise TimeoutError("navigation failed")
        page.url = destination

    page.goto = Mock(side_effect=goto)
    monkeypatch.setattr(xhs_publish, "_verify_login", lambda page, **kwargs: True)
    assert xhs_publish._check_account_login(page)
    assert page.goto.call_args_list[-1].args == (xhs_publish.EXPLORE_URL,)


def test_xhs_whoami_waits_for_creator_redirect(monkeypatch):
    page = xhs_page(xhs_publish.CREATOR_HOME_URL)
    anchor = SimpleNamespace(is_visible=lambda: True)
    cycles = []

    def wait(duration):
        cycles.append(duration)
        page.url = xhs_publish.CREATOR_LOGIN_URL
        page.query_selector_all = lambda selector: [anchor] \
            if selector in xhs_publish.SELECTORS["logged_out"].split(", ") else []

    page.wait_for_timeout = wait
    assert not xhs_publish._verify_login(page)
    assert cycles == [500]


def test_xhs_whoami_returns_unknown_for_two_maintenance_pages(monkeypatch):
    page = xhs_page(body="工程师正在维护页面")
    monkeypatch.setattr(xhs_publish, "_verify_login", lambda page, **kwargs: False)
    with pytest.raises(RuntimeError, match="保留上次登录"):
        xhs_publish._check_account_login(page)


def test_xhs_whoami_returns_logged_out_only_for_visible_login_wall(monkeypatch):
    page = xhs_page(body="短信登录")
    anchor = SimpleNamespace(is_visible=lambda: True)
    page.query_selector_all = lambda selector: [anchor] \
        if selector in xhs_publish.SELECTORS["logged_out"].split(", ") else []
    monkeypatch.setattr(xhs_publish, "_verify_login", lambda page, **kwargs: False)
    assert not xhs_publish._check_account_login(page)


def test_xhs_whoami_keeps_state_when_home_has_login_wall_but_creator_is_unknown(monkeypatch):
    page = xhs_page(body="短信登录")
    anchor = SimpleNamespace(is_visible=lambda: True)
    page.goto = lambda destination, **kwargs: setattr(page, "url", destination)
    page.query_selector_all = lambda selector: [anchor] if (
        page.url == xhs_publish.EXPLORE_URL
        and selector in xhs_publish.SELECTORS["logged_out"].split(", ")) else []
    monkeypatch.setattr(xhs_publish, "_verify_login", lambda page, **kwargs: False)
    with pytest.raises(RuntimeError, match="保留上次登录状态"):
        xhs_publish._check_account_login(page)


@pytest.mark.parametrize(("status", "payload", "verified"), [
    (200, {"success": True, "data": {"userId": "account-id", "userName": "Test"}}, True),
    (200, {"success": True, "data": {"userId": ""}}, False),
    (200, {"success": True, "data": {"userId": None}}, False),
    (200, {"success": True, "data": {"userId": True}}, False),
    (200, {"success": False, "data": {"userId": "account-id"}}, False),
    (200, {"success": True, "data": "maintenance"}, False),
    (401, {"success": False, "msg": "登录已过期"}, False),
    (503, {"success": True, "data": {"userId": "account-id"}}, False),
])
def test_creator_account_accepts_only_verified_server_identity(status, payload, verified):
    response = SimpleNamespace(status=status, json=lambda: payload)
    request = SimpleNamespace(get=Mock(return_value=response))
    result = xhs_publish._creator_account(SimpleNamespace(request=request))
    assert (result is not None) is verified
    request.get.assert_called_once_with(
        xhs_publish.CREATOR_ACCOUNT_URL,
        headers={"Referer": xhs_publish.CREATOR_HOME_URL},
        timeout=5000,
    )


def test_creator_account_network_error_is_unknown():
    request = SimpleNamespace(get=Mock(side_effect=TimeoutError("private cookie")))
    assert xhs_publish._creator_account(SimpleNamespace(request=request)) is None


def qr_element(image=None, visible=True):
    return SimpleNamespace(
        is_visible=lambda: visible,
        bounding_box=lambda: {"width": 100, "height": 100},
        screenshot=lambda **kwargs: image or qr_bytes())


def test_zhihu_strict_capture_accepts_small_qr_before_container(tmp_path):
    selectors = []

    def query(selector):
        selectors.append(selector)
        return [qr_element()] if selector == ".Qrcode-img" else []

    page = SimpleNamespace(query_selector_all=query)
    output = tmp_path / "qr.png"
    web_publisher._crop_qr(page, output, web_publisher.PLATFORMS["zhihu"])
    assert output.exists()
    assert ".Qrcode-img" in selectors


def test_zhihu_never_falls_back_to_whole_page(tmp_path):
    screenshot = Mock()
    page = SimpleNamespace(query_selector_all=lambda selector: [],
                           wait_for_timeout=Mock(), screenshot=screenshot)
    output = tmp_path / "qr.png"
    with pytest.raises(RuntimeError, match="未找到可识别"):
        web_publisher._crop_qr(page, output, web_publisher.PLATFORMS["zhihu"])
    screenshot.assert_not_called()
    assert not output.exists()


def test_qr_capture_retries_unloaded_image_and_skips_hidden(tmp_path):
    attempts = []

    def screenshot(**kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("image not loaded")
        return qr_bytes()

    visible = qr_element()
    visible.screenshot = screenshot
    hidden = qr_element(visible=False)
    page = SimpleNamespace(
        query_selector_all=lambda selector: [hidden, visible] if selector == ".qrcode-img" else [],
        wait_for_timeout=Mock())
    login_qr.capture_qr(page, tmp_path / "qr.png", ".qrcode-img")
    assert len(attempts) == 2
    page.wait_for_timeout.assert_called_once_with(800)


def test_qr_refresh_missing_candidate_keeps_previous_image(tmp_path):
    output = tmp_path / "qr.png"
    assert login_qr.save_qr(qr_bytes(), output)
    original = output.read_bytes()
    page = SimpleNamespace(query_selector_all=lambda selector: [], wait_for_timeout=Mock())
    with pytest.raises(RuntimeError, match="未找到可识别"):
        login_qr.capture_qr(page, output, ".qrcode-img", attempts=1)
    assert output.read_bytes() == original
    page.wait_for_timeout.assert_not_called()


@pytest.mark.parametrize("url", ["https://www.zhihu.com/", "https://www.zhihu.com/error"])
def test_zhihu_anonymous_redirect_is_not_a_login(url):
    page = SimpleNamespace(url=url, query_selector=lambda selector: None)
    assert not web_publisher._is_logged_in(page, web_publisher.PLATFORMS["zhihu"])


@pytest.mark.parametrize("visible,wall,expected", [
    (True, False, True), (False, False, False), (True, True, False),
])
def test_zhihu_requires_visible_account_and_no_login_wall(visible, wall, expected):
    def query(selector):
        if selector == ".AppHeader-profile":
            return SimpleNamespace(is_visible=lambda: visible)
        if selector == ".SignContainer":
            return SimpleNamespace(is_visible=lambda: wall)
        return None

    page = SimpleNamespace(url="https://www.zhihu.com/", query_selector=query)
    assert web_publisher._is_logged_in(page, web_publisher.PLATFORMS["zhihu"]) is expected


def test_zhihu_switches_to_qr_only_when_missing(tmp_path):
    ready = False
    clicked = []

    def click(**kwargs):
        nonlocal ready
        ready = True
        clicked.append(True)

    cfg = web_publisher.PLATFORMS["zhihu"]
    button = SimpleNamespace(is_visible=lambda: True, click=click)

    def query(selector):
        if selector == cfg["login_qr_switch"]:
            return [button]
        if selector == ".Qrcode-img" and ready:
            return [qr_element()]
        return []

    page = SimpleNamespace(query_selector_all=query, wait_for_timeout=Mock(),
                           wait_for_selector=Mock())
    output = tmp_path / "qr.png"
    login_qr.prepare_qr(page, output, cfg["login_qr_selector"], cfg["login_qr_switch"])
    login_qr.prepare_qr(page, output, cfg["login_qr_selector"], cfg["login_qr_switch"])
    assert clicked == [True]


def test_qr_preparation_waits_for_async_page_before_switching(tmp_path):
    ready = False

    def wait(selector, **kwargs):
        nonlocal ready
        ready = True

    page = SimpleNamespace(
        wait_for_selector=wait,
        query_selector_all=lambda selector: [qr_element()] if ready and selector == ".qr" else [])
    login_qr.prepare_qr(page, tmp_path / "qr.png", ".qr", "button")


@pytest.mark.parametrize("script", ["xhs_publish.py", "web_publisher.py"])
def test_gbk_stdio_does_not_crash_runner(tmp_path, script):
    env = dict(os.environ, PYTHONIOENCODING="gbk:strict", PYTHONUTF8="0")
    result = subprocess.run([sys.executable, str(SCRIPTS / script), "selftest"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "✅" in result.stdout.decode("utf-8")


def test_configure_stdio_handles_captured_or_closed_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(sys, "stderr", closed)
    login_state.configure_stdio()


def test_window_login_is_valid_status(tmp_path):
    status = str(tmp_path / "status.json")
    login_state.write_status(status, "window_login", "请在窗口登录")
    assert login_state.read_status(status)["state"] == "window_login"


def xhs_page(url=xhs_publish.EXPLORE_URL, title="", body=""):
    page = SimpleNamespace(
        url=url, title=lambda: title, inner_text=lambda *args, **kwargs: body,
        query_selector_all=lambda selector: [], wait_for_timeout=Mock(),
        wait_for_selector=Mock())

    def goto(destination, **kwargs):
        page.url = destination

    page.goto = Mock(side_effect=goto)
    return page


@pytest.mark.parametrize("url,title,body,risk", [
    ("https://www.xiaohongshu.com/website-login/error?error_code=300012", "", "", True),
    ("https://www.xiaohongshu.com/website-login/error", "安全限制", "IP 存在风险", True),
    ("https://www.xiaohongshu.com/website-login/error?error_code=300013", "安全限制", "", False),
    ("https://www.xiaohongshu.com/website-login/error", "安全限制", "请完成验证", False),
    ("https://www.xiaohongshu.com/explore?next=error_code=300012", "", "", False),
])
def test_only_explicit_ip_risk_is_classified_as_ip(url, title, body, risk):
    page = xhs_page(url, title, body)
    assert xhs_publish._risk_blocked(page) is risk
    reason = xhs_publish._login_error(page)
    if "300013" in url:
        assert "300013" in reason
        assert "不一定是 IP" in reason


def test_error_message_does_not_leak_url_login_tokens():
    page = xhs_page("https://www.xiaohongshu.com/website-login/error?error_code=300013&token=private")
    assert "private" not in xhs_publish._login_error(page)


@pytest.mark.parametrize("url,visible,logged", [
    (xhs_publish.EXPLORE_URL, False, False),
    (xhs_publish.EXPLORE_URL, True, True),
    (xhs_publish.CREATOR_LOGIN_URL, False, False),
    ("https://creator.xiaohongshu.com/website-login/error", False, False),
    ("https://creator.xiaohongshu.com/publish/publish", False, False),
    ("https://creator.xiaohongshu.com/publish/publish?error_code=300012", False, False),
    ("https://creator.xiaohongshu.com/home-error", False, False),
    ("https://other.example/?next=creator.xiaohongshu.com/home", False, False),
])
def test_xhs_requires_visible_account_anchor(url, visible, logged):
    page = xhs_page(url)
    page.query_selector_all = lambda selector: [SimpleNamespace(is_visible=lambda: visible)] \
        if selector == xhs_publish.SELECTORS["login_ok"] else []
    assert xhs_publish._is_logged_in(page) is logged


@pytest.mark.parametrize("visible", [True, False])
def test_creator_authenticated_route_with_login_wall_is_not_logged_in(visible):
    page = xhs_page("https://creator.xiaohongshu.com/publish/publish")
    avatar = SimpleNamespace(is_visible=lambda: True, get_attribute=lambda key: "/avatar.jpg")
    name = SimpleNamespace(is_visible=lambda: True, inner_text=lambda: "Test account")
    account = SimpleNamespace(is_visible=lambda: True,
                              query_selector=lambda selector: avatar if selector.startswith("img") else name)
    page.query_selector_all = lambda selector: [SimpleNamespace(is_visible=lambda: visible)] \
        if selector == xhs_publish.SELECTORS["logged_out"] else [account] if selector == ".user-info" else []
    assert xhs_publish._is_logged_in(page) is not visible


@pytest.mark.parametrize(("name_text", "avatar_src", "visible", "expected"), [
    ("Test account", "/avatar.jpg", True, True),
    ("", "/avatar.jpg", True, False),
    ("Test account", "", True, False),
    ("Test account", "/avatar.jpg", False, False),
])
def test_creator_requires_populated_visible_account(name_text, avatar_src, visible, expected):
    page = xhs_page(xhs_publish.CREATOR_HOME_URL)
    avatar = SimpleNamespace(is_visible=lambda: visible, get_attribute=lambda key: avatar_src)
    name = SimpleNamespace(is_visible=lambda: visible, inner_text=lambda: name_text)
    account = SimpleNamespace(is_visible=lambda: visible,
                              query_selector=lambda selector: avatar if selector.startswith("img") else name)
    page.query_selector_all = lambda selector: [account] if selector == ".user-info" else []
    assert xhs_publish._is_logged_in(page) is expected

def test_xhs_existing_qr_is_not_toggled_back_to_sms(tmp_path, monkeypatch):
    page = xhs_page()
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all = lambda selector: [button] if "扫码登录" in selector else []
    monkeypatch.setattr(login_qr, "capture_qr", Mock())
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    button.click.assert_not_called()


def test_xhs_creator_obfuscated_image_is_captured_after_corner_switch(tmp_path):
    ready = False
    clicked = []
    icon = io.BytesIO()
    Image.new("RGB", (64, 64), "gray").save(icon, format="PNG")

    def click(**kwargs):
        nonlocal ready
        ready = True
        clicked.append(True)

    switch = qr_element(image=icon.getvalue())
    switch.click = click
    page = xhs_page(xhs_publish.CREATOR_LOGIN_URL, body="短信登录")

    def query(selector):
        if selector == ".sso-login-wrapper img":
            return [switch, qr_element(image=qr_bytes(scale=5))] if ready else [switch]
        if selector in (".sso-login-wrapper > div > div > img", xhs_publish.SELECTORS["qr_switch"]):
            return [switch]
        return []

    page.query_selector_all = query
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert clicked == [True]
    assert (tmp_path / "qr.png").exists()
    page.goto.assert_not_called()
    assert any(call.kwargs.get("state") == "hidden"
               for call in page.wait_for_selector.call_args_list)


def test_xhs_creator_existing_obfuscated_qr_does_not_click_icon(tmp_path):
    page = xhs_page(xhs_publish.CREATOR_LOGIN_URL, body="APP扫一扫登录")
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all = lambda selector: [qr_element(image=qr_bytes(scale=5))] \
        if selector == ".sso-login-wrapper img" \
        else ([button] if selector == xhs_publish.SELECTORS["qr_switch"] else [])
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    button.click.assert_not_called()


def test_xhs_opens_anonymous_home_login_dialog(tmp_path, monkeypatch):
    page = xhs_page(body="发现")
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all = lambda selector: [button] \
        if selector == ".side-bar-component.login-btn" else []
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    button.click.assert_called_once()
    capture.assert_called_once()
    page.goto.assert_not_called()


def test_xhs_visible_login_panel_never_clicks_submit(tmp_path, monkeypatch):
    page = xhs_page(xhs_publish.CREATOR_LOGIN_URL, body="短信登录")
    wall = SimpleNamespace(is_visible=lambda: True)
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all = lambda selector: [wall] \
        if selector in (xhs_publish.SELECTORS["logged_out"], ".login-container") \
        else ([button] if selector == ".side-bar-component.login-btn" else [])
    monkeypatch.setattr(login_qr, "capture_qr", Mock())
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    button.click.assert_not_called()


@pytest.mark.parametrize("body,expected", [
    ("", "空白"),
    ("短信登录 发送验证码", "短信登录"),
    ("APP扫一扫登录", "二维码未加载"),
])
def test_xhs_missing_qr_retains_both_entry_diagnostics(tmp_path, monkeypatch, body, expected):
    page = xhs_page(body=body)
    monkeypatch.setattr(login_qr, "capture_qr", Mock(side_effect=RuntimeError("missing qr")))
    with pytest.raises(RuntimeError, match=expected) as error:
        xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert "小红书首页" in str(error.value)
    assert "创作平台" in str(error.value)


def test_xhs_home_risk_not_hidden_by_blank_creator(tmp_path, monkeypatch):
    page = xhs_page("https://www.xiaohongshu.com/website-login/error?error_code=300012")
    monkeypatch.setattr(login_qr, "capture_qr", Mock(side_effect=RuntimeError("missing qr")))
    with pytest.raises(RuntimeError, match="300012") as error:
        xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert "空白" in str(error.value)


def test_xhs_creator_navigation_failure_has_actionable_message(tmp_path, monkeypatch):
    page = xhs_page()
    page.goto.side_effect = TimeoutError("sensitive_url?token=private")
    monkeypatch.setattr(login_qr, "capture_qr", Mock(side_effect=RuntimeError("missing qr")))
    with pytest.raises(RuntimeError, match="创作平台.*TimeoutError") as error:
        xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert "private" not in str(error.value)


def test_xhs_login_during_capture_is_not_reported_as_error(tmp_path, monkeypatch):
    page = xhs_page()
    monkeypatch.setattr(xhs_publish, "_is_logged_in", lambda page: page.url.endswith("/home"))

    def capture(*args, **kwargs):
        page.url = "https://creator.xiaohongshu.com/home"
        raise RuntimeError("login redirect removed qr")

    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert not xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    page.goto.assert_not_called()


def test_xhs_headless_risk_falls_back_to_creator_once(tmp_path, monkeypatch):
    page = xhs_page("https://www.xiaohongshu.com/website-login/error?error_code=300012")
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    page.goto.assert_called_once_with(xhs_publish.CREATOR_LOGIN_URL,
                                     wait_until="commit", timeout=30000)
    capture.assert_called_once()


def test_xhs_missing_qr_also_tries_official_creator(tmp_path, monkeypatch):
    page = xhs_page()
    capture = Mock(side_effect=[RuntimeError("not ready"), None])
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert capture.call_count == 2
    assert page.goto.call_count == 1


def test_xhs_both_entries_blocked_report_actual_risk(tmp_path, monkeypatch):
    page = xhs_page("https://www.xiaohongshu.com/website-login/error?error_code=300012")
    page.goto.side_effect = lambda *args, **kwargs: None
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    with pytest.raises(RuntimeError, match="300012"):
        xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    assert page.goto.call_count == 1
    capture.assert_not_called()


def test_creator_existing_login_does_not_request_qr(tmp_path, monkeypatch):
    page = xhs_page("https://creator.xiaohongshu.com/home")
    monkeypatch.setattr(xhs_publish, "_is_logged_in", lambda page: True)
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert not xhs_publish._capture_login_qr(page, tmp_path / "qr.png")
    capture.assert_not_called()


@pytest.mark.parametrize("capture_result,expected", [
    (RuntimeError("平台拦截（300013）"), "error"),
    (False, "success"),
    (True, "expired"),
])
@pytest.mark.parametrize("explore_timeout", [False, True])
def test_xhs_runner_persists_terminal_status_and_closes_browser(tmp_path, monkeypatch,
                                                              capture_result, expected,
                                                              explore_timeout):
    from playwright import sync_api

    page = xhs_page()
    if explore_timeout:
        page.goto.side_effect = TimeoutError("homepage timeout")
    context = SimpleNamespace(pages=[page], close=Mock())

    class Manager:
        def __enter__(self):
            return SimpleNamespace()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(xhs_publish, "_launch", lambda *args, **kwargs: context)
    capture = Mock(side_effect=capture_result) if isinstance(capture_result, Exception) \
        else Mock(return_value=capture_result)
    monkeypatch.setattr(xhs_publish, "_capture_login_qr", capture)
    args = SimpleNamespace(qr_out=str(tmp_path / "qr.png"), timeout=-1,
                           status_file=str(tmp_path / "status.json"),
                           profile_base=str(tmp_path / "profiles"), headed=False,
                           proxy=None, no_proxy=True)
    assert xhs_publish.cmd_login(args) == (0 if expected == "success" else 1)
    status = login_state.read_status(args.status_file)
    assert status["state"] == expected
    if expected == "error":
        assert "300013" in status["message"]
    context.close.assert_called_once()
    capture.assert_called_once_with(page, Path(args.qr_out), creator_only=explore_timeout)


@pytest.mark.parametrize(("maintenance", "verified", "expected"), [
    (False, True, "success"),
    (True, True, "success"),
    (True, False, "error"),
    (False, False, "error"),
])
def test_xhs_scanned_login_checks_account_before_page_failure(
        tmp_path, monkeypatch, maintenance, verified, expected):
    from playwright import sync_api

    page = xhs_page()
    context = SimpleNamespace(pages=[page], close=Mock())

    class Manager:
        def __enter__(self):
            return SimpleNamespace()

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(xhs_publish, "_launch", lambda *args, **kwargs: context)
    monkeypatch.setattr(xhs_publish, "_is_logged_in", lambda page: False)
    monkeypatch.setattr(xhs_publish, "_capture_login_qr", Mock(return_value=True))
    reason = "小红书当前入口显示维护页面" if maintenance else ""
    monkeypatch.setattr(xhs_publish, "_login_error", Mock(side_effect=["settling", reason]))
    monkeypatch.setattr(xhs_publish, "_qr_state", lambda page: "scanned")
    account = Mock(side_effect=[None, {"userId": "verified"} if verified else None])
    monkeypatch.setattr(xhs_publish, "_creator_account", account)
    monkeypatch.setattr(xhs_publish, "time", SimpleNamespace(
        time=Mock(side_effect=[0, 0, 1, 31]),
        monotonic=Mock(side_effect=range(0, 100, 6))))
    refresh = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", refresh)
    qr_out = tmp_path / "qr.png"
    qr_out.write_bytes(b"test-qr")
    args = SimpleNamespace(
        qr_out=str(qr_out), timeout=30, status_file=str(tmp_path / "status.json"),
        profile_base=str(tmp_path / "profiles"), headed=False, proxy=None, no_proxy=True)
    assert xhs_publish.cmd_login(args) == (0 if verified else 1)
    status = login_state.read_status(args.status_file)
    assert status["state"] == expected
    assert account.call_count == 2
    if not verified:
        assert ("维护页面" if maintenance else "已扫码") in status["message"]
    else:
        assert not qr_out.exists()
    refresh.assert_not_called()
    context.close.assert_called_once()


@pytest.mark.parametrize("platform", ["xiaohongshu", "zhihu"])
@pytest.mark.parametrize("refresh_missing", [False, True])
def test_login_runner_refreshes_qr_and_handles_success(tmp_path, monkeypatch, platform,
                                                      refresh_missing):
    from playwright import sync_api

    page = xhs_page()
    page.wait_for_selector = Mock()
    context = SimpleNamespace(pages=[page], close=Mock())

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(
                launch_persistent_context=lambda *args, **kwargs: context))

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    clock = iter([0, 6, 6, 7])
    monkeypatch.setattr(xhs_publish.time, "monotonic", lambda: next(clock))
    refresh = Mock(side_effect=RuntimeError("redirect removed qr") if refresh_missing else None)
    monkeypatch.setattr(login_qr, "capture_qr", refresh)
    args = SimpleNamespace(platform=platform, qr_out=str(tmp_path / "qr.png"), timeout=30,
                           status_file=str(tmp_path / "status.json"),
                           profile_base=str(tmp_path / "profiles"), headed=False,
                           proxy=None, no_proxy=True)
    if platform == "xiaohongshu":
        monkeypatch.setattr(xhs_publish, "_launch", lambda *args, **kwargs: context)
        monkeypatch.setattr(xhs_publish, "_is_logged_in", Mock(side_effect=[False, False, True]))
        monkeypatch.setattr(xhs_publish, "_capture_login_qr", Mock(return_value=True))
        errors = iter(["stop settling", ""])
        monkeypatch.setattr(xhs_publish, "_login_error", lambda page: next(errors))
        assert xhs_publish.cmd_login(args) == 0
        selectors = xhs_publish.SELECTORS["qrcode"]
    else:
        monkeypatch.setattr(web_publisher, "_is_logged_in", Mock(side_effect=[False, False, True]))
        monkeypatch.setattr(login_qr, "prepare_qr", Mock())
        assert web_publisher.cmd_login_qr(args) == 0
        selectors = web_publisher.PLATFORMS["zhihu"]["login_qr_selector"]
    expected = {"attempts": 1, **({"minimum_size": 96} if platform == "xiaohongshu" else {})}
    refresh.assert_called_once_with(page, Path(args.qr_out), selectors, **expected)
    assert login_state.read_status(args.status_file)["state"] == "success"
    context.close.assert_called_once()


@pytest.mark.parametrize("launch_failure", [False, True])
def test_zhihu_runner_handles_launch_failure_or_login_during_capture(tmp_path, monkeypatch,
                                                                 launch_failure):
    from playwright import sync_api

    page = xhs_page()
    page.wait_for_selector = Mock()
    context = SimpleNamespace(pages=[page], close=Mock())
    launch = Mock(side_effect=RuntimeError("browser failed")) if launch_failure \
        else Mock(return_value=context)

    class Manager:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(web_publisher, "_is_logged_in", Mock(side_effect=[False, True]))
    monkeypatch.setattr(login_qr, "prepare_qr", Mock(side_effect=RuntimeError("redirect removed qr")))
    args = SimpleNamespace(platform="zhihu", qr_out=str(tmp_path / "qr.png"), timeout=30,
                           status_file=str(tmp_path / "status.json"),
                           profile_base=str(tmp_path / "profiles"))
    assert web_publisher.cmd_login_qr(args) == (1 if launch_failure else 0)
    assert login_state.read_status(args.status_file)["state"] == ("error" if launch_failure else "success")
    assert context.close.call_count == (0 if launch_failure else 1)


def web_functions():
    tree = ast.parse((ROOT / "web/app.py").read_text(encoding="utf-8"))
    names = {"api_login_start", "_start_login", "_login_status"}
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    env = {"json": json, "subprocess": subprocess, "sys": sys, "asyncio": asyncio,
           "_LOGIN_START_LOCKS": {}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "web/app.py", "exec"), env)
    return env


@pytest.mark.parametrize("state", ["starting", "qr_ready", "scanned", "window_login", "verifying"])
def test_web_detects_exited_login_even_after_qr_ready(tmp_path, state):
    env = web_functions()
    login_state.write_status(str(tmp_path / "zhihu.json"), state)
    (tmp_path / "zhihu.png").write_bytes(b"stale")
    env.update(LOGIN_DIR=tmp_path, LOGIN_PROCESSES={"zhihu": SimpleNamespace(poll=lambda: 1)})
    status = env["_login_status"]("zhihu")
    assert status["state"] == "error"
    assert status["qr"] == ""


@pytest.mark.parametrize("state", ["success", "expired", "error"])
def test_web_preserves_terminal_status_and_hides_stale_qr(tmp_path, state):
    env = web_functions()
    login_state.write_status(str(tmp_path / "zhihu.json"), state)
    (tmp_path / "zhihu.png").write_bytes(b"stale")
    env.update(LOGIN_DIR=tmp_path, LOGIN_PROCESSES={"zhihu": SimpleNamespace(poll=lambda: 0)})
    status = env["_login_status"]("zhihu")
    assert status["state"] == state
    assert status["qr"] == ""


def test_web_qr_cache_key_changes_within_same_second(tmp_path):
    env = web_functions()
    login_state.write_status(str(tmp_path / "zhihu.json"), "qr_ready")
    output = tmp_path / "zhihu.png"
    output.write_bytes(b"qr")
    env.update(LOGIN_DIR=tmp_path, LOGIN_PROCESSES={})
    os.utime(output, ns=(1_100_000_000, 1_100_000_000))
    first = env["_login_status"]("zhihu")["qrTs"]
    os.utime(output, ns=(1_200_000_000, 1_200_000_000))
    assert env["_login_status"]("zhihu")["qrTs"] != first


def test_repeated_web_login_preserves_existing_process_and_qr():
    env = web_functions()
    status = {"state": "qr_ready", "qr": "_login/zhihu.png"}
    env.update(LOGIN_RUNNERS={"zhihu": {"backend": "web", "wp": "zhihu"}},
               LOGIN_PROCESSES={"zhihu": SimpleNamespace(poll=lambda: None)},
               _login_status=lambda platform: status)
    assert asyncio.run(env["api_login_start"]("zhihu")) == {"mode": "qr", **status}


def test_web_login_sets_child_utf8_without_changing_parent_env(tmp_path, monkeypatch):
    env = web_functions()
    original = {"PYTHONIOENCODING": "gbk", "https_proxy": "test-proxy"}
    popen = Mock(return_value=SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(subprocess, "Popen", popen)

    async def sleep(duration):
        return None

    env.update(LOGIN_RUNNERS={"zhihu": {"backend": "web", "wp": "zhihu"}},
               LOGIN_PROCESSES={}, LOGIN_DIR=tmp_path, SHARED_SCRIPTS=SCRIPTS,
               PROJECT_ROOT=ROOT, LOGIN_TIMEOUT=180, _WHOAMI_LOCK=threading.Lock(),
               _WHOAMI_CACHE={}, _proxy_env=lambda: original.copy(),
               _login_status=lambda platform: {"state": "qr_ready", "qr": ""},
               asyncio=SimpleNamespace(sleep=sleep, Lock=asyncio.Lock))
    asyncio.run(env["api_login_start"]("zhihu"))
    child_env = popen.call_args.kwargs["env"]
    assert child_env["PYTHONIOENCODING"] == "utf-8"
    assert child_env["PYTHONUTF8"] == "1"
    assert original["PYTHONIOENCODING"] == "gbk"
    assert child_env["https_proxy"] == "test-proxy"
    assert popen.call_args.kwargs["stdout"].closed
