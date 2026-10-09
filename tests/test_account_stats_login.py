"""Platform login checks must distinguish visible login walls from hidden DOM."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import account_stats


class Frame:
    def __init__(self, elements=(), failures=0):
        self.elements = elements
        self.failures = failures

    def query_selector_all(self, selector):
        if self.failures:
            self.failures -= 1
            raise RuntimeError("execution context was destroyed")
        return [SimpleNamespace(is_visible=lambda visible=visible: visible)
                for visible in self.elements]


class Page(Frame):
    def __init__(self, anchors=(), frames=()):
        super().__init__(anchors)
        self.frames = list(frames)
        self.waits = []

    def wait_for_timeout(self, duration):
        self.waits.append(duration)


@pytest.mark.parametrize("anchors,qr_frames,expected", [
    ([True], [[]], True),
    ([False, True], [[False]], True),
    ([True], [[True]], False),
    ([True], [[], [True]], False),
    ([True], [[], [False]], True),
    ([], [[]], False),
    ([False], [[]], False),
])
def test_douyin_requires_visible_anchor_and_no_visible_qr(anchors, qr_frames, expected):
    page = Page(anchors, [Frame(elements) for elements in qr_frames])
    assert account_stats._platform_logged_in(page, account_stats.PLATFORMS["douyin"]) is expected


def test_navigation_error_is_retried():
    page = Page([True], [Frame(failures=1)])
    assert account_stats._platform_logged_in(page, account_stats.PLATFORMS["douyin"])
    assert page.waits == [500]


def test_repeated_detection_error_is_not_reported_as_logged_in():
    page = Page([True], [Frame(failures=3)])
    assert not account_stats._platform_logged_in(page, account_stats.PLATFORMS["douyin"])
    assert page.waits == [500, 500]


def test_other_platforms_keep_existing_login_detection():
    assert account_stats._platform_logged_in(None, account_stats.PLATFORMS["kuaishou"])


def test_expired_douyin_does_not_return_stale_metrics(tmp_path, monkeypatch):
    from playwright import sync_api

    page = Page([], [Frame([True])])
    page.url = account_stats.PLATFORMS["douyin"]["url"]
    page.goto = lambda *args, **kwargs: None
    page.query_selector = lambda selector: None
    closed = []
    context = SimpleNamespace(pages=[page], close=lambda: closed.append(True))
    playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=lambda *args, **kwargs: context))
    class Manager:
        def __enter__(self):
            return playwright

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(account_stats, "_profile_dir", lambda *args: tmp_path / "profile")
    monkeypatch.setattr(account_stats, "_poll_stable", lambda *args: ["粉丝", "123"])
    monkeypatch.setattr(account_stats, "_scrape_notes",
                        lambda *args: pytest.fail("must not scrape notes behind login wall"))
    result = account_stats._scrape("douyin", False, None, None)
    assert result["logged_in"] is False
    assert result["followers"] is None
    assert result["metrics"] == result["notes"] == []
    assert closed == [True]
