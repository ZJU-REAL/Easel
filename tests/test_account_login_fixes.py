import io
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import segno
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shared/scripts"))
import login_qr
import login_state
import web_publisher
import xhs_publish
import douyin_publish
import weixin_mp_stats


def account_element(name="Me", avatar="https://example.test/avatar.png", visible=True):
    name_element = SimpleNamespace(is_visible=lambda: visible, inner_text=lambda: name)
    avatar_element = SimpleNamespace(is_visible=lambda: visible, get_attribute=lambda key: avatar)
    return SimpleNamespace(
        is_visible=lambda: visible,
        query_selector=lambda selector: avatar_element if "img" in selector else name_element,
    )


def account_page(url):
    page = SimpleNamespace(
        url=url, query_selector_all=Mock(return_value=[]),
        query_selector=Mock(return_value=None), wait_for_selector=Mock(),
        wait_for_timeout=Mock(), inner_text=Mock(return_value=""), close=Mock(),
    )
    def navigate(destination, **kwargs):
        page.url = destination

    page.goto = Mock(side_effect=navigate)
    return page


@pytest.mark.parametrize(("name", "avatar", "expected_name", "expected_avatar"), [
    (" Me ", " https://example.test/avatar.png ", "Me", "https://example.test/avatar.png"),
    ({"name": "Me"}, ["avatar"], "", ""),
    ("Me", "data:image/png;base64,not-an-avatar", "Me", ""),
    ("Me", "javascript:alert(1)", "Me", ""),
    ("Me", "https:missing-host", "Me", ""),
    ("N" * 60, "http://example.test/avatar.png", "N" * 40, "http://example.test/avatar.png"),
])
def test_xhs_account_identity_validates_fields(name, avatar, expected_name, expected_avatar):
    assert xhs_publish._account_identity({"userName": name, "userAvatar": avatar}) == {
        "name": expected_name, "avatar": expected_avatar,
    }


def test_xhs_creator_identity_uses_visible_account_not_feed_author():
    page = account_page(xhs_publish.CREATOR_HOME_URL)
    page.query_selector_all.return_value = [
        account_element(name="Hidden", visible=False), account_element(name="My account"),
    ]
    assert xhs_publish._page_account_identity(page)["name"] == "My account"
    page.query_selector_all.assert_called_once_with(".user-info")
    page.goto.assert_not_called()


@pytest.mark.parametrize("href", [
    "", "/explore/note123", "https://example.test/user/profile/123", "//example.test/profile",
])
def test_xhs_unknown_own_account_link_never_falls_back_to_feed(href):
    page = account_page(xhs_publish.EXPLORE_URL)
    page.query_selector_all.return_value = [SimpleNamespace(
        is_visible=lambda: True, evaluate=lambda source: {"href": href, "avatar": ""},
    )]
    assert xhs_publish._page_account_identity(page) == {"name": "", "avatar": ""}
    page.goto.assert_not_called()
    page.query_selector_all.assert_called_once_with(xhs_publish.SELECTORS["login_ok"])


@pytest.mark.parametrize("redirect", [None, "https://www.xiaohongshu.com/user/profile/other",
                                     "https://example.test/user/profile/abc123"])
def test_xhs_profile_identity_is_bound_to_own_navigation_link(redirect):
    page = account_page(xhs_publish.EXPLORE_URL)
    channel = SimpleNamespace(is_visible=lambda: True, evaluate=lambda source: {
        "href": "/user/profile/abc123", "avatar": "https://example.test/own.png",
    })
    page.query_selector_all.side_effect = [[channel], [account_element(name="My profile")]]
    if redirect:
        page.goto.side_effect = lambda *args, **kwargs: setattr(page, "url", redirect)
    result = xhs_publish._page_account_identity(page)
    assert result["name"] == ("" if redirect else "My profile")
    page.goto.assert_called_once_with(
        "https://www.xiaohongshu.com/user/profile/abc123", wait_until="commit", timeout=4000,
    )
    if redirect:
        page.wait_for_selector.assert_not_called()


def test_xhs_account_check_has_bounded_navigation_and_verification(monkeypatch):
    page = account_page(xhs_publish.EXPLORE_URL)
    clock = iter([0, 0, 4, 8, 12])
    monkeypatch.setattr(xhs_publish.time, "monotonic", lambda: next(clock))
    verify = Mock(side_effect=[False, True])
    monkeypatch.setattr(xhs_publish, "_verify_login", verify)
    monkeypatch.setattr(xhs_publish, "_login_error", lambda page: "")
    monkeypatch.setattr(xhs_publish, "_visible_login_element", lambda *args: None)
    assert xhs_publish._check_account_login(page)
    assert [call.args[0] for call in page.goto.call_args_list] == [
        xhs_publish.CREATOR_HOME_URL, xhs_publish.EXPLORE_URL,
    ]
    assert all(call.kwargs == {"wait_until": "commit", "timeout": 4000}
               for call in page.goto.call_args_list)
    assert [call.kwargs["timeout_s"] for call in verify.call_args_list] == [4, 2]


def test_xhs_account_check_stops_when_overall_budget_expires(monkeypatch):
    page = account_page(xhs_publish.EXPLORE_URL)
    clock = iter([0, 0, 15, 15])
    monkeypatch.setattr(xhs_publish.time, "monotonic", lambda: next(clock))
    verify = Mock()
    monkeypatch.setattr(xhs_publish, "_verify_login", verify)
    monkeypatch.setattr(xhs_publish, "_login_error", lambda page: "")
    monkeypatch.setattr(xhs_publish, "_visible_login_element", lambda *args: None)
    with pytest.raises(RuntimeError, match="保留上次登录状态"):
        xhs_publish._check_account_login(page)
    page.goto.assert_called_once()
    verify.assert_not_called()


@pytest.mark.parametrize(("status", "payload", "valid"), [
    (200, {"id": "abc", "name": "Me"}, True),
    (401, {"id": "abc", "name": "Me"}, False),
    (200, {"id": "", "name": "Me"}, False),
    (200, {"id": "abc", "name": " "}, False),
    (200, {"id": 123, "name": "Me"}, False),
    (200, {"id": "abc", "name": "Me", "error": {"code": 100}}, False),
    (200, [{"id": "abc", "name": "Me"}], False),
])
def test_zhihu_account_api_requires_authenticated_identity(status, payload, valid):
    browser = SimpleNamespace(request=SimpleNamespace(
        get=Mock(return_value=SimpleNamespace(status=status, json=lambda: payload)),
    ))
    result = web_publisher._authenticated_account(browser, web_publisher.PLATFORMS["zhihu"])
    assert (result is not None) is valid
    browser.request.get.assert_called_once_with("https://www.zhihu.com/api/v4/me", timeout=3000)


def test_account_api_failure_is_not_positive_login():
    browser = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=RuntimeError("network"))))
    assert web_publisher._authenticated_account(browser, web_publisher.PLATFORMS["zhihu"]) is None
    browser.request.get.reset_mock()
    assert web_publisher._authenticated_account(browser, web_publisher.PLATFORMS["weixin-channels"]) is None
    browser.request.get.assert_not_called()


@pytest.mark.parametrize(("payload", "valid"), [
    ({"errCode": 0, "data": {"finderUser": {"finderUsername": "own", "nickname": "Me",
                                           "headImgUrl": "https://self.test/own.png"}}}, True),
    ({"errCode": 401, "data": {"finderUser": {"finderUsername": "own", "nickname": "Me"}}}, False),
    ({"errCode": False, "data": {"finderUser": {"finderUsername": "own", "nickname": "Me"}}}, False),
    ({"errCode": 0, "data": {"finderUser": {"nickname": "Me", "adminNickname": "Admin"}}}, False),
    ({"errCode": 0, "data": {"finderUser": {"finderUsername": "own", "nickname": " "}}}, False),
    ({"errCode": 0, "data": []}, False),
    ([], False),
])
def test_channels_identity_requires_authenticated_channel_not_admin(payload, valid):
    account = web_publisher._channels_account(payload)
    assert (account is not None) is valid
    if valid:
        assert web_publisher._account_identity(account) == {
            "name": "Me", "avatar": "https://self.test/own.png",
        }


@pytest.mark.parametrize(("url", "status", "valid"), [
    ("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/auth/auth_data", 201, True),
    ("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/auth/auth_data", 401, False),
    ("https://example.test/cgi-bin/mmfinderassistant-bin/auth/auth_data", 200, False),
    ("https://channels.weixin.qq.com/cgi-bin/mmfinderassistant-bin/feed/list", 200, False),
])
def test_channels_observer_accepts_only_own_auth_endpoint(url, status, valid):
    browser = SimpleNamespace(on=Mock())
    cfg = web_publisher.PLATFORMS["weixin-channels"]
    web_publisher._observe_channels_account(browser, cfg)
    callback = browser.on.call_args.args[1]
    callback(SimpleNamespace(url=url, status=status, json=lambda: {
        "errCode": 0, "data": {"finderUser": {"finderUsername": "own", "nickname": "Me"}},
    }))
    assert (web_publisher._authenticated_account(browser, cfg) is not None) is valid


@pytest.mark.parametrize(("avatar", "expected"), [
    ("//self.test/own.png", "https://self.test/own.png"),
    ("/own.png", "https://self.test/own.png"),
    ("javascript:alert(1)", ""),
    ("data:image/png;base64,secret", ""),
    ("https:missing-host", ""),
    ("https://user:password@self.test/own.png", ""),
    ("https://[invalid/own.png", ""),
    ({"url": "https://self.test/own.png"}, ""),
])
def test_generic_account_avatar_validation(avatar, expected):
    identity = web_publisher._account_identity({"name": " Me ", "avatar_url": avatar}, "https://self.test")
    assert identity == {"name": "Me", "avatar": expected}


def test_channels_dom_identity_ignores_admin_and_hidden_account():
    page = account_page("https://channels.weixin.qq.com/platform")
    page.query_selector_all.side_effect = [
        [SimpleNamespace(is_visible=lambda: False, inner_text=lambda: "Hidden"),
         SimpleNamespace(is_visible=lambda: True, inner_text=lambda: "Own channel")],
        [SimpleNamespace(is_visible=lambda: False, get_attribute=lambda key: "https://self.test/hidden.png"),
         SimpleNamespace(is_visible=lambda: True, get_attribute=lambda key: "//self.test/channel.png")],
    ]
    assert web_publisher._visible_account_identity(page, web_publisher.PLATFORMS["weixin-channels"]) == {
        "name": "Own channel", "avatar": "https://self.test/channel.png",
    }
    assert [call.args[0] for call in page.query_selector_all.call_args_list] == [
        ".finder-info .finder-nickname", ".finder-info img.avatar[src]",
    ]


@pytest.mark.parametrize(("message", "state"), [
    ("扫描成功，请在微信中确认登录", "scanned"),
    ("二维码已失效，请刷新二维码", "expired"),
    ("请使用微信扫描二维码登录", ""),
])
def test_channels_scan_confirmation_is_read_from_wechat_frame(message, state):
    page = account_page("https://channels.weixin.qq.com/login.html")
    page.frames = [SimpleNamespace(url="https://open.weixin.qq.com/connect/qrconnect",
                                  inner_text=lambda *args, **kwargs: message)]
    assert web_publisher._login_qr_state(page, web_publisher.PLATFORMS["weixin-channels"]) == state


@pytest.mark.parametrize(("response", "valid"), [
    ({"httpStatus": 200, "body": {"status_code": 0, "user_info": {
        "uid": "own", "nickname": "Me", "avatar_larger": {"url_list": ["https://self.test/own.png"]},
    }}}, True),
    ({"httpStatus": 401, "body": {"status_code": 0, "user_info": {"uid": "own"}}}, False),
    ({"httpStatus": 200, "body": {"status_code": 1002, "user_info": {"uid": "own"}}}, False),
    ({"httpStatus": 200, "body": {"status_code": 0, "user_info": {"nickname": "Other"}}}, False),
    ({"httpStatus": 200, "fetchError": "network", "body": {"status_code": 0}}, False),
    ([], False),
])
def test_douyin_identity_uses_current_account_api_not_page_authors(response, valid):
    identity = douyin_publish._account_identity(response)
    assert (identity is not None) is valid
    if valid:
        assert identity == {"name": "Me", "avatar": "https://self.test/own.png"}


def test_douyin_identity_skips_invalid_avatar_urls():
    response = {"httpStatus": 200, "body": {"status_code": 0, "user_info": {
        "uid": "own", "nickname": "Me", "avatar_larger": {"url_list": [
            "https://[invalid/a.png", "https://user:password@self.test/a.png",
            "https:missing-host", "https://self.test/own.png",
        ]},
    }}}
    assert douyin_publish._account_identity(response)["avatar"] == "https://self.test/own.png"


@pytest.mark.parametrize("module", [douyin_publish, weixin_mp_stats])
def test_login_runner_restores_signal_handler_when_terminated(monkeypatch, module):
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(args):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(module, "_run_login", terminate)
    with pytest.raises(SystemExit):
        module.cmd_login(SimpleNamespace(status_file=None))
    assert signal.getsignal(signal.SIGTERM) is previous_handler


@pytest.mark.parametrize("url", [
    "https://example.test/?token=123", "http://mp.weixin.qq.com/?token=123", "about:blank?token=123",
])
def test_mp_token_is_only_trusted_on_authenticated_platform(url):
    assert not weixin_mp_stats._extract_token(url)
    assert weixin_mp_stats._extract_token("https://mp.weixin.qq.com/cgi-bin/home?token=123") == "123"


def test_mp_identity_only_uses_visible_current_account_card():
    page = account_page("https://mp.weixin.qq.com/cgi-bin/home")
    page.query_selector_all.return_value = [account_element(name="Hidden", visible=False),
                                            account_element(name="Own MP", avatar="//self.test/mp.png")]
    assert weixin_mp_stats._account_identity(page) == {"name": "Own MP", "avatar": "https://self.test/mp.png"}
    page.query_selector_all.assert_called_once_with(".weui-desktop-account")


def test_mp_periodic_qr_capture_is_bounded_and_never_screens_entire_page(tmp_path):
    page = account_page(weixin_mp_stats.MP_HOME)
    page.screenshot = Mock()
    assert not weixin_mp_stats._capture_qr(page, tmp_path / "qr.png", attempts=1, fallback=False)
    page.wait_for_timeout.assert_called_once_with(1000)
    page.screenshot.assert_not_called()


@pytest.mark.parametrize(("text", "expected"), [
    ("扫码成功，请在手机上确认", "scanned"),
    ("二维码已过期 点击刷新", "expired"),
    ("二维码无效", "expired"),
    ("扫码成功 二维码已过期", "scanned"),
    ("使用知乎 APP 扫码登录", ""),
])
def test_zhihu_scan_confirmation_takes_precedence_over_expiry(text, expected):
    page = account_page(web_publisher.PLATFORMS["zhihu"]["login_url"])
    page.inner_text.return_value = text
    assert web_publisher._login_qr_state(page, web_publisher.PLATFORMS["zhihu"]) == expected


def test_zhihu_scanned_qr_is_never_refreshed(tmp_path):
    page = account_page(web_publisher.PLATFORMS["zhihu"]["login_url"])
    page.inner_text.return_value = "扫码成功，请在手机上确认"
    assert not web_publisher._refresh_login_qr(page, tmp_path / "qr.png", web_publisher.PLATFORMS["zhihu"])
    page.query_selector_all.assert_not_called()


def test_zhihu_expired_qr_uses_refresh_control(tmp_path, monkeypatch):
    page = account_page(web_publisher.PLATFORMS["zhihu"]["login_url"])
    page.inner_text.side_effect = ["二维码已失效", "使用知乎 APP 扫码"]
    button = SimpleNamespace(is_visible=lambda: True, click=Mock())
    page.query_selector_all.return_value = [button]
    capture = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", capture)
    assert web_publisher._refresh_login_qr(page, tmp_path / "qr.png", web_publisher.PLATFORMS["zhihu"])
    button.click.assert_called_once_with(timeout=2000)
    capture.assert_called_once()


def test_zhihu_probe_uses_homepage_and_does_not_navigate_scan_page(monkeypatch):
    page = account_page("about:blank")
    browser = SimpleNamespace(new_page=Mock(return_value=page))
    settle = Mock()
    monkeypatch.setattr(web_publisher, "_settle_login", settle)
    monkeypatch.setattr(web_publisher, "_is_logged_in", lambda *args: True)
    assert web_publisher._probe_logged_in(browser, web_publisher.PLATFORMS["zhihu"])
    page.goto.assert_called_once_with("https://www.zhihu.com/", wait_until="commit", timeout=5000)
    settle.assert_called_once_with(page, web_publisher.PLATFORMS["zhihu"], max_ms=4000)
    page.close.assert_called_once()


@pytest.mark.parametrize("current_url", ["about:blank", "https://example.test/"])
def test_login_navigation_reports_real_connection_timeouts(current_url):
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = account_page(current_url)
    page.goto.side_effect = PlaywrightTimeout("timeout")
    with pytest.raises(RuntimeError, match="检查服务器"):
        web_publisher._navigate_login(page, "https://channels.weixin.qq.com/")


def test_login_navigation_can_inspect_same_origin_after_timeout():
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    page = account_page("https://channels.weixin.qq.com/login.html")
    page.goto.side_effect = PlaywrightTimeout("timeout")
    web_publisher._navigate_login(page, "https://channels.weixin.qq.com/")
    page.goto.assert_called_once_with("https://channels.weixin.qq.com/", wait_until="commit", timeout=10000)


def test_channels_unauthenticated_spa_route_is_not_login_success():
    page = account_page("https://channels.weixin.qq.com/platform/post/create")
    assert not web_publisher._is_logged_in(page, web_publisher.PLATFORMS["weixin-channels"])
    page.query_selector.return_value = SimpleNamespace(is_visible=lambda: True)
    page.query_selector.side_effect = lambda selector: SimpleNamespace(is_visible=lambda: True) \
        if selector == ".finder-nickname" else None
    assert web_publisher._is_logged_in(page, web_publisher.PLATFORMS["weixin-channels"])


def test_channels_iframe_qr_is_detected_and_cropped(tmp_path):
    encoded = io.BytesIO()
    segno.make("easel-offline-login-test", micro=False).save(
        encoded, kind="png", scale=5, border=4,
    )
    panel = Image.new("RGB", (600, 400), "white")
    panel.paste(Image.open(io.BytesIO(encoded.getvalue())), (150, 80))
    screenshot = io.BytesIO()
    panel.save(screenshot, format="PNG")
    iframe = SimpleNamespace(is_visible=lambda: True, screenshot=Mock(return_value=screenshot.getvalue()))
    page = account_page("https://channels.weixin.qq.com/login.html")
    page.query_selector.return_value = iframe
    page.frames = []
    output = tmp_path / "qr.png"
    web_publisher._capture_qr(page, output, web_publisher.PLATFORMS["weixin-channels"])
    with Image.open(output) as image:
        assert max(image.size) < 400
        assert min(image.size) >= 360


def test_channels_empty_iframe_never_saves_whole_login_page(tmp_path):
    screenshot = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(screenshot, format="PNG")
    iframe = SimpleNamespace(is_visible=lambda: True, screenshot=Mock(return_value=screenshot.getvalue()))
    page = account_page("https://channels.weixin.qq.com/login.html")
    page.query_selector.return_value = iframe
    page.frames = []
    page.screenshot = Mock()
    output = tmp_path / "qr.png"
    with pytest.raises(RuntimeError, match="未找到可识别"):
        web_publisher._capture_qr(page, output, web_publisher.PLATFORMS["weixin-channels"])
    assert not output.exists()
    assert iframe.screenshot.call_count == 3
    page.screenshot.assert_not_called()


def test_channels_qr_waits_for_iframe_image_pixels_before_screenshot(tmp_path, monkeypatch):
    order = []
    page = account_page("https://channels.weixin.qq.com/login.html")
    page.main_frame = object()
    frame = SimpleNamespace(
        url="https://open.weixin.qq.com/connect/qrconnect",
        wait_for_selector=Mock(side_effect=lambda *args, **kwargs: order.append("image_attached")),
        wait_for_function=Mock(side_effect=lambda *args, **kwargs: order.append("image_loaded")),
    )
    page.frames = [frame]
    image = SimpleNamespace(is_visible=lambda: True, screenshot=Mock(
        side_effect=lambda **kwargs: order.append("screenshot") or b"pixels",
    ))
    page.query_selector.return_value = image
    monkeypatch.setattr(login_qr, "save_qr", lambda *args, **kwargs: True)
    web_publisher._capture_qr(page, tmp_path / "qr.png", web_publisher.PLATFORMS["weixin-channels"])
    assert order == ["image_attached", "image_loaded", "screenshot"]
    assert frame.wait_for_function.call_args.kwargs["timeout"] == 15000
    assert page.wait_for_selector.call_args.kwargs["timeout"] == 30000


@pytest.mark.parametrize("terminate", [False, True])
def test_zhihu_runner_confirms_api_without_redirect_and_closes_browser(
        tmp_path, monkeypatch, terminate):
    from playwright import sync_api

    page = account_page(web_publisher.PLATFORMS["zhihu"]["login_url"])
    browser = SimpleNamespace(pages=[page], close=Mock())
    manager = Mock()
    manager.__enter__ = Mock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=Mock(return_value=browser),
    )))
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: manager)
    monkeypatch.setattr(web_publisher, "_navigate_login", Mock())
    monkeypatch.setattr(web_publisher, "_is_logged_in", lambda *args: False)
    account = Mock(side_effect=[None, None, None, {"id": "abc", "name": "Me"}])
    monkeypatch.setattr(web_publisher, "_authenticated_account", account)
    monkeypatch.setattr(web_publisher, "_probe_logged_in", lambda *args: False)
    monkeypatch.setattr(web_publisher, "_login_qr_state", lambda *args: "scanned")
    capture = Mock()
    monkeypatch.setattr(login_qr, "prepare_qr", capture)
    refresh = Mock()
    monkeypatch.setattr(login_qr, "capture_qr", refresh)
    args = SimpleNamespace(platform="zhihu", qr_out=str(tmp_path / "qr.png"), timeout=1,
                           status_file=str(tmp_path / "status.json"), profile_base=str(tmp_path))
    previous_handler = signal.getsignal(signal.SIGTERM)
    states = []
    write_status = login_state.write_status
    def record(*args, **kwargs):
        if args[1] == "success":
            browser.close.assert_called_once()
        states.append(args[1])
        return write_status(*args, **kwargs)

    monkeypatch.setattr(login_state, "write_status", record)
    if terminate:
        page.wait_for_timeout.side_effect = lambda duration: signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with pytest.raises(SystemExit):
            web_publisher.cmd_login_qr(args)
    else:
        assert web_publisher.cmd_login_qr(args) == 0
        assert login_state.read_status(args.status_file)["state"] == "success"
        assert "scanned" in states
        assert page.url.endswith("/signin")
    browser.close.assert_called_once()
    refresh.assert_not_called()
    assert signal.getsignal(signal.SIGTERM) is previous_handler


@pytest.mark.parametrize("confirmed_by", ["response", "popup", "probe"])
def test_channels_runner_confirms_shared_session_and_retains_probe(tmp_path, monkeypatch, confirmed_by):
    from playwright import sync_api

    page = account_page("https://channels.weixin.qq.com/login.html")
    popup = account_page("https://channels.weixin.qq.com/platform")
    probe = account_page("https://channels.weixin.qq.com/")
    browser = SimpleNamespace(pages=[page], close=Mock(), on=Mock(), new_page=Mock(return_value=probe))
    manager = Mock()
    manager.__enter__ = Mock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=Mock(return_value=browser),
    )))
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: manager)
    monkeypatch.setattr(web_publisher, "_block_heavy", Mock())
    monkeypatch.setattr(web_publisher, "_observe_channels_account", Mock())
    monkeypatch.setattr(web_publisher, "_navigate_login", Mock())
    monkeypatch.setattr(web_publisher, "_capture_qr", Mock())
    monkeypatch.setattr(web_publisher, "_login_qr_state", lambda *args: "scanned")
    monkeypatch.setattr(web_publisher, "_is_logged_in", lambda candidate, cfg: candidate is popup)
    monkeypatch.setattr(web_publisher, "_authenticated_account", lambda context, cfg:
                        getattr(context, "_easel_channel_account", None))
    waits = []

    def wait(duration):
        waits.append(duration)
        if len(waits) == 7:
            if confirmed_by == "popup":
                browser.pages.append(popup)
            else:
                browser._easel_channel_account = {"id": "own", "name": "Me"}

    page.wait_for_timeout.side_effect = wait
    write_status = login_state.write_status

    def record(*args, **kwargs):
        if args[1] == "success":
            browser.close.assert_called_once()
        return write_status(*args, **kwargs)

    monkeypatch.setattr(login_state, "write_status", record)
    args = SimpleNamespace(platform="weixin-channels", qr_out=str(tmp_path / "qr.png"), timeout=2,
                           status_file=str(tmp_path / "status.json"), profile_base=str(tmp_path))
    assert web_publisher.cmd_login_qr(args) == 0
    assert login_state.read_status(args.status_file)["state"] == "success"
    browser.close.assert_called_once()
    browser.new_page.assert_called_once()
    probe.close.assert_not_called()


@pytest.mark.parametrize("reused", [False, True])
def test_mp_runner_releases_profile_before_success(tmp_path, monkeypatch, reused):
    from playwright import sync_api

    page = account_page("https://mp.weixin.qq.com/")
    context = SimpleNamespace(pages=[page], close=Mock())
    manager = Mock()
    manager.__enter__ = Mock(return_value=SimpleNamespace())
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: manager)
    monkeypatch.setattr(weixin_mp_stats, "_launch", lambda *args: context)
    monkeypatch.setattr(weixin_mp_stats, "_capture_qr", Mock(return_value=True))
    tokens = iter(["own" if reused else "", "own"])
    monkeypatch.setattr(weixin_mp_stats, "_extract_token", lambda url: next(tokens))
    write_status = login_state.write_status

    def record(*args, **kwargs):
        if args[1] == "success":
            context.close.assert_called_once()
        return write_status(*args, **kwargs)

    monkeypatch.setattr(login_state, "write_status", record)
    args = SimpleNamespace(headed=False, profile_base=str(tmp_path), proxy=None, no_proxy=True,
                           timeout=2, qr_out=str(tmp_path / "qr.png"),
                           status_file=str(tmp_path / "status.json"))
    assert weixin_mp_stats.cmd_login(args) == 0
    context.close.assert_called_once()
    assert login_state.read_status(args.status_file)["state"] == "success"


def test_channels_incomplete_account_page_is_not_verified_logout(tmp_path, monkeypatch, capsys):
    import json
    from playwright import sync_api

    page = account_page("https://channels.weixin.qq.com/")
    browser = SimpleNamespace(pages=[page], close=Mock(), on=Mock())
    manager = Mock()
    manager.__enter__ = Mock(return_value=SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=Mock(return_value=browser),
    )))
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: manager)
    monkeypatch.setattr(web_publisher, "_block_heavy", Mock())
    monkeypatch.setattr(web_publisher, "_navigate_login", Mock())
    monkeypatch.setattr(web_publisher, "_settle_login", Mock())
    monkeypatch.setattr(web_publisher, "_settle_channels_account", Mock(side_effect=RuntimeError("not ready")))
    args = SimpleNamespace(platform="weixin-channels", profile_base=str(tmp_path))
    assert web_publisher.cmd_whoami(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert not result["loggedIn"]
    assert result["error"]
    browser.close.assert_called_once()


@pytest.mark.parametrize("response_delay", [28, 39])
def test_channels_identity_wait_allows_slow_current_account_response(monkeypatch, response_delay):
    page = account_page("https://channels.weixin.qq.com/")
    page.frames = []
    browser = SimpleNamespace()
    clock = [0.0]
    monkeypatch.setattr(web_publisher.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(web_publisher, "_authenticated_account", lambda *args:
                        {"id": "own", "name": "Me"} if clock[0] >= response_delay else None)
    page.wait_for_timeout.side_effect = lambda duration: clock.__setitem__(0, clock[0] + duration / 1000)
    assert web_publisher._settle_channels_account(page, browser)
    assert clock[0] == response_delay


@pytest.mark.parametrize("loaded", [False, True])
def test_channels_identity_wait_requires_loaded_qr_for_verified_logout(monkeypatch, loaded):
    page = account_page("https://channels.weixin.qq.com/")
    page.frames = [SimpleNamespace(url="https://open.weixin.qq.com/connect/qrconnect",
                                   evaluate=lambda script: loaded)]
    browser = SimpleNamespace()
    clock = [0.0]
    monkeypatch.setattr(web_publisher.time, "monotonic", lambda: clock[0])
    page.wait_for_timeout.side_effect = lambda duration: clock.__setitem__(0, clock[0] + duration / 1000)
    if loaded:
        assert not web_publisher._settle_channels_account(page, browser, max_ms=500)
    else:
        with pytest.raises(RuntimeError, match="尚未就绪"):
            web_publisher._settle_channels_account(page, browser, max_ms=500)
