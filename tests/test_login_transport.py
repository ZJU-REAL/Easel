import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import login_transport


def transport(monkeypatch, platform, status=200):
    response = SimpleNamespace(status_code=status, content=b"decoded asset", headers={
        "Content-Encoding": "gzip", "Content-Length": "1", "Transfer-Encoding": "chunked",
        "Set-Cookie": "should-not-replace-auth", "Connection": "keep-alive",
        "Content-Type": "image/png",
    })
    session = Mock()
    session.get.return_value = response
    monkeypatch.setattr(login_transport.requests, "Session", lambda: session)
    context = Mock()
    login_transport.install(context, platform)
    handler = context.route.call_args.args[1]
    return session, context, handler


@pytest.mark.parametrize(("platform", "url", "resource_type"), [
    ("weixin-channels", "https://res.wx.qq.com/script.js", "script"),
    ("weixin-channels", "https://open.weixin.qq.com/connect/qrconnect?appid=page-id", "document"),
    ("weixin-channels", "https://open.weixin.qq.com/connect/qrcode/real-token", "image"),
    ("xiaohongshu", "https://fe-static.xhscdn.com/script.js", "script"),
    ("xiaohongshu", "https://ci.xiaohongshu.com/style.css", "stylesheet"),
])
def test_login_transport_preserves_page_urls_and_strips_decoded_body_headers(
        monkeypatch, platform, url, resource_type):
    session, context, handler = transport(monkeypatch, platform)
    route = Mock()
    request = SimpleNamespace(url=url, method="GET", resource_type=resource_type,
                              all_headers=lambda: {"user-agent": "browser"})
    handler(route, request)
    assert session.trust_env is False
    session.get.assert_called_once_with(url, headers={"user-agent": "browser", "accept-encoding": "identity"},
                                       timeout=(3, 5), allow_redirects=False)
    route.fulfill.assert_called_once_with(status=200, body=b"decoded asset",
                                         headers={"Content-Type": "image/png"})
    route.continue_.assert_not_called()
    context.on.call_args.args[1]()
    session.close.assert_called_once()


@pytest.mark.parametrize(("platform", "url", "method", "resource_type"), [
    ("weixin-channels", "https://channels.weixin.qq.com/auth", "GET", "fetch"),
    ("weixin-channels", "https://open.weixin.qq.com/connect/oauth2", "GET", "document"),
    ("weixin-channels", "https://res.wx.qq.com.evil.test/script", "GET", "script"),
    ("weixin-channels", "http://res.wx.qq.com/script.js", "GET", "script"),
    ("weixin-channels", "https://res.wx.qq.com/auth", "POST", "fetch"),
    ("xiaohongshu", "https://www.xiaohongshu.com/api/user", "GET", "fetch"),
    ("xiaohongshu", "https://ci.xiaohongshu.com/auth", "GET", "fetch"),
])
def test_account_auth_and_other_hosts_stay_in_browser(monkeypatch, platform, url, method, resource_type):
    session, _, handler = transport(monkeypatch, platform)
    route = Mock()
    handler(route, SimpleNamespace(url=url, method=method, resource_type=resource_type))
    route.continue_.assert_called_once()
    session.get.assert_not_called()


@pytest.mark.parametrize("failure", [302, 403, 500, "timeout"])
def test_login_transport_falls_back_to_browser_on_failure(monkeypatch, failure):
    session, _, handler = transport(monkeypatch, "weixin-channels",
                                   status=failure if isinstance(failure, int) else 200)
    if failure == "timeout":
        session.get.side_effect = requests.Timeout()
    route = Mock()
    handler(route, SimpleNamespace(url="https://res.wx.qq.com/script.js", method="GET",
                                  resource_type="script", all_headers=lambda: {}))
    route.continue_.assert_called_once()
    route.fulfill.assert_not_called()


def test_transport_is_not_installed_for_other_platforms():
    context = Mock()
    login_transport.install(context, "zhihu")
    context.route.assert_not_called()
