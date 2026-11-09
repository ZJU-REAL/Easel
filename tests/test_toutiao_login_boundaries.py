"""Offline login boundaries: redirects, backend failures and saved sessions."""
from contextlib import nullcontext
from itertools import count
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/builtin/skill-toutiao-publisher/scripts"))
import toutiao_publish as tp
import login_state


@pytest.mark.parametrize("url", ["about:blank", "https://example.com/", "http://mp.toutiao.com/",
                                     "https://mp.toutiao.com.evil.test/profile_v4/index"])
def test_untrusted_navigation_is_not_authenticated(monkeypatch, url):
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda page: False)
    assert not tp._is_logged_in(SimpleNamespace(url=url))


@pytest.mark.parametrize("status,final_path,expected", [(200, "/profile_v4/index", True),
    (500, "/profile_v4/index", False), (403, "/profile_v4/index", False),
    (200, "/intermediate", False), (200, "/auth/page/login", False)])
def test_backend_confirmation_requires_successful_creator_page(monkeypatch, status, final_path, expected):
    page = SimpleNamespace(url="https://mp.toutiao.com/intermediate", wait_for_timeout=lambda ms: None)

    def goto(url, **kwargs):
        page.url = "https://mp.toutiao.com" + final_path
        return SimpleNamespace(status=status)

    page.goto = goto
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda p: False)
    assert tp._backend_authenticated(page) is expected


@pytest.fixture
def browser_stub(tmp_path, monkeypatch):
    page = SimpleNamespace(url=tp.HOME_URL, goto=lambda *a, **k: SimpleNamespace(status=200),
                           wait_for_timeout=lambda ms: None)
    context = SimpleNamespace(pages=[page], close=lambda: None)
    pw = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a, **k: context))
    monkeypatch.setattr(tp, "_require_playwright", lambda: lambda: nullcontext(pw))
    monkeypatch.setattr(tp, "PROFILE_DIR", tmp_path / "profile")
    return page, context, tmp_path / "qr.png", tmp_path / "status.json"


def test_headless_binding_after_scan_requires_a_visible_retry(browser_stub, monkeypatch):
    page, context, qr, status = browser_stub
    binding = []
    closed = []
    page.wait_for_timeout = lambda ms: binding.append(True) if ms == 2000 else None
    context.close = lambda: closed.append(True)
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda p: bool(binding))
    monkeypatch.setattr(tp, "_backend_authenticated", lambda p: False)
    monkeypatch.setattr(tp, "_capture_qr", lambda p, out: out.write_bytes(b"qr") or True)
    clock = count()
    monkeypatch.setattr(tp.time, "time", lambda: next(clock))
    assert tp._qr_login(tp.PROFILE_DIR, qr, status, 30, headed=False) == 1
    result = login_state.read_status(str(status))
    assert result["state"] == "error" and "有头浏览器" in result["message"]
    assert not qr.exists()
    assert closed == [True]


@pytest.mark.parametrize("save_fails", [False, True])
def test_success_is_written_only_after_session_save(browser_stub, monkeypatch, save_fails):
    page, context, qr, status = browser_stub
    states = []

    def close():
        states.append(login_state.read_status(str(status))["state"])
        if save_fails and len(states) == 1:
            raise RuntimeError("session save failed")

    context.close = close
    monkeypatch.setattr(tp, "_backend_authenticated", lambda p: True)
    assert tp._qr_login(tp.PROFILE_DIR, qr, status, 30, headed=True) == (1 if save_fails else 0)
    assert states[0] == "starting"
    assert login_state.read_status(str(status))["state"] == ("error" if save_fails else "success")


def test_failed_identity_probe_preserves_unknown_state(browser_stub):
    page, context, qr, status = browser_stub
    page.goto = lambda *a, **k: SimpleNamespace(status=500)
    result = tp._probe_identity()
    assert not result["loggedIn"] and result.get("error")


def test_phone_binding_during_qr_capture_is_never_screenshotted(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda p: True)
    page = SimpleNamespace(locator=lambda s: pytest.fail("binding form is not a QR"),
                           screenshot=lambda **k: pytest.fail("do not screenshot phone inputs"))
    assert not tp._capture_qr(page, tmp_path / "qr.png")


def test_binding_appearing_during_capture_transfers_to_visible_window(browser_stub, monkeypatch):
    page, context, qr, status = browser_stub
    binding = []
    monkeypatch.setattr(tp, "_needs_phone_binding", lambda p: bool(binding))
    monkeypatch.setattr(tp, "_capture_qr", lambda p, out: binding.append(True) or False)
    monkeypatch.setattr(tp, "_backend_authenticated", lambda p: False)
    clock = count(step=100)
    monkeypatch.setattr(tp.time, "time", lambda: next(clock))
    states = []
    write_status = login_state.write_status
    monkeypatch.setattr(login_state, "write_status", lambda path, state, *a, **k:
                        states.append(state) or write_status(path, state, *a, **k))
    assert tp._qr_login(tp.PROFILE_DIR, qr, status, 30, headed=True) == 1
    assert states == ["starting", "window_login", "expired"]
