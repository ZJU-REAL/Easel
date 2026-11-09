"""Session detection against real browser DOM, with no live credentials or requests."""
from types import SimpleNamespace
from pathlib import Path
import sys
import json
import signal
from contextlib import nullcontext

import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import social_login
import login_state


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            pytest.skip("DOM integration checks require playwright install chromium")
        instance = playwright.chromium.launch(headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    context.route("**/*", lambda route: route.fulfill(body="<html><body></body></html>", content_type="text/html"))
    page = context.new_page()
    yield page
    context.close()


AUTH_HTML = {
    "facebook": '<div aria-label="Your profile"><svg><image href="https://example.com/me.png"/></svg></div>',
    "instagram": '<a href="/direct/inbox/">Messages</a>',
    "tiktok": '<div data-e2e="profile-icon"><img src="https://example.com/me.png"></div>',
    "youtube": '<button id="avatar-btn"><img src="https://example.com/me.png" alt="Own channel"></button>',
}


def load(page, platform, html, *, cookies=True, url=None):
    cfg = social_login.PLATFORMS[platform]
    page.goto(url or cfg["home_url"])
    page.set_content(html)
    if cookies:
        page.context.add_cookies([{"name": name, "value": "test-session", "url": cfg["home_url"]}
                                  for name in cfg["cookies"][0]])
    return cfg


@pytest.mark.parametrize("platform", AUTH_HTML)
def test_only_authenticated_navigation_with_session_cookies_verifies_login(page, platform):
    cfg = load(page, platform, AUTH_HTML[platform])
    result = social_login.inspect_account(page, cfg)
    assert result["loggedIn"] is True
    assert not result.get("error")


@pytest.mark.parametrize("platform", AUTH_HTML)
def test_public_profile_ui_without_session_does_not_verify_login(page, platform):
    cfg = load(page, platform, AUTH_HTML[platform], cookies=False)
    result = social_login.inspect_account(page, cfg)
    assert result["loggedIn"] is False
    assert result.get("error")


def test_expired_cookies_on_login_form_are_verified_as_signed_out(page):
    cfg = load(page, "facebook", '<input name="email"><input name="pass">',
               url="https://www.facebook.com/login/")
    assert social_login.inspect_account(page, cfg) == {"loggedIn": False, "name": "", "avatar": ""}


@pytest.mark.parametrize("url", ["https://www.facebook.com/checkpoint/", "https://facebook.com.evil.test/"])
def test_challenge_and_lookalike_origin_do_not_verify_or_clear_account(page, url):
    cfg = load(page, "facebook", AUTH_HTML["facebook"], url=url)
    result = social_login.inspect_account(page, cfg)
    assert result["loggedIn"] is False
    assert result.get("error")


def test_hidden_authentication_control_cannot_verify_login(page):
    cfg = load(page, "facebook", '<div aria-label="Your profile" style="display:none">Profile</div>')
    assert social_login.inspect_account(page, cfg).get("error")


def test_cookie_presence_on_an_empty_page_is_unknown_not_signed_out(page):
    cfg = load(page, "instagram", "<div>Loading…</div>")
    assert social_login.inspect_account(page, cfg).get("error")


def test_social_login_has_no_duplicate_x_profile():
    assert "x" not in social_login.PLATFORMS
    assert "TwitterXProfile" not in {cfg["profile"] for cfg in social_login.PLATFORMS.values()}


def test_proxy_credentials_are_passed_separately_and_not_in_server(monkeypatch):
    for key in ("EASEL_SOCIAL_PROXY", "EASEL_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EASEL_SOCIAL_PROXY", "http://user:p%40ss@127.0.0.1:7890")
    options = social_login.browser_options(headless=False)
    assert options["proxy"] == {"server": "http://127.0.0.1:7890", "username": "user", "password": "p@ss"}
    assert "--no-proxy-server" not in options.get("args", [])
    assert options["headless"] is False


def test_without_proxy_config_browser_uses_system_network(monkeypatch):
    for key in ("EASEL_SOCIAL_PROXY", "EASEL_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    assert "proxy" not in social_login.browser_options(headless=True)


def test_missing_profile_does_not_launch_browser_or_create_session(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(social_login, "_launch_context", lambda *args, **kwargs: pytest.fail("no saved session"))
    assert social_login.cmd_whoami(SimpleNamespace(platform="facebook", profile_base=str(tmp_path))) == 0
    assert '"loggedIn": false' in capsys.readouterr().out
    assert not (tmp_path / "FacebookProfile").exists()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    page = SimpleNamespace(goto=lambda *args, **kwargs: None, is_closed=lambda: False,
                           wait_for_timeout=lambda _ms: None)
    context = SimpleNamespace(pages=[page])
    context.close = lambda: None
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(social_login, "_launch_context", lambda *args, **kwargs: context)
    args = SimpleNamespace(platform="facebook", status_file=str(tmp_path / "status.json"),
                           profile_base=str(tmp_path / "browser"), timeout=240)
    return args, context, page


def test_runner_saves_browser_before_success_and_restores_signal_handler(runner, monkeypatch):
    args, context, _page = runner
    closed = []

    def close():
        assert login_state.read_status(args.status_file)["state"] == "window_login"
        closed.append(True)

    context.close = close
    monkeypatch.setattr(social_login, "inspect_account", lambda *args: {"loggedIn": True})
    initial = signal.getsignal(signal.SIGTERM)
    assert social_login.cmd_login(args) == 0
    assert closed == [True]
    assert login_state.read_status(args.status_file)["state"] == "success"
    assert signal.getsignal(signal.SIGTERM) == initial


def test_runner_save_failure_does_not_claim_success_or_expose_proxy(runner, monkeypatch):
    args, context, _page = runner
    context.close = lambda: (_ for _ in ()).throw(RuntimeError("proxy http://user:secret@host"))
    monkeypatch.setattr(social_login, "inspect_account", lambda *args: {"loggedIn": True})
    assert social_login.cmd_login(args) == 1
    status = login_state.read_status(args.status_file)
    assert status["state"] == "error"
    assert "secret" not in json.dumps(status)


def test_runner_cancel_closes_browser_and_never_leaves_starting_state(runner):
    args, context, page = runner
    closed = []
    context.close = lambda: closed.append(True)

    def interrupt(*_args, **_kwargs):
        raise SystemExit(130)

    page.goto = interrupt
    initial = signal.getsignal(signal.SIGTERM)
    assert social_login.cmd_login(args) == 130
    assert closed == [True]
    assert login_state.read_status(args.status_file)["state"] == "error"
    assert signal.getsignal(signal.SIGTERM) == initial


def test_runner_timeout_closes_browser_without_marking_account_logged_in(runner):
    args, context, _page = runner
    args.timeout = 0
    closed = []
    context.close = lambda: closed.append(True)
    assert social_login.cmd_login(args) == 1
    assert closed == [True]
    assert login_state.read_status(args.status_file)["state"] == "expired"


def test_closed_browser_error_is_actionable_without_claiming_network_failure():
    message = social_login._browser_error(RuntimeError("Target page, context or browser has been closed"))
    assert "浏览器已关闭" in message


def test_access_restriction_remains_visible_while_user_can_retry_in_browser(runner, monkeypatch):
    args, _context, page = runner
    page.goto = lambda *args, **kwargs: SimpleNamespace(status=429)
    observed = []

    def inspect(*_args):
        observed.append(login_state.read_status(args.status_file))
        return {"loggedIn": True}

    monkeypatch.setattr(social_login, "inspect_account", inspect)
    assert social_login.cmd_login(args) == 0
    assert observed[0]["state"] == "window_login"
    assert "429" in observed[0]["message"]
