import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shared/scripts"))
import account_stats
import xhs_publish


def response(status=200, payload=None, state=None, url=xhs_publish.EXPLORE_URL):
    return SimpleNamespace(status=status, url=url, json=lambda: payload,
                           text=lambda: "<script>window.__INITIAL_STATE__="
                           + json.dumps(state or {}) + ";</script>")


def result():
    return {"nickname": "", "followers": None, "likes": None, "following": None,
            "posts": None, "metrics": [], "notes": [], "logged_in": True}


def test_creator_session_does_not_fetch_unneeded_web_page():
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response(
        payload={"success": True, "data": {"userId": "self", "userName": "Me"}}))))
    assert account_stats._xhs_session(context) == ({"userId": "self", "userName": "Me"}, True)
    assert context.request.get.call_count == 1


def test_expired_creator_can_use_authenticated_web_session():
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=[
        response(401, {"success": False}),
        response(state={"user": {"loggedIn": True, "userInfo": {"userId": "self"}}}),
    ])))
    account, creator = account_stats._xhs_session(context)
    assert account["userId"] == "self"
    assert creator is False


@pytest.mark.parametrize("web", [
    response(url="https://www.xiaohongshu.com/login"),
    TimeoutError("web unavailable"),
])
def test_confirmed_expired_creator_never_waits_for_login_page(web):
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=[
        response(401, {"success": False}), web,
    ])))
    assert account_stats._xhs_session(context) == (None, False)


@pytest.mark.parametrize("creator", [
    response(503), TimeoutError("network"), response(payload=[]),
    response(payload={"success": True, "data": {"userId": "../bad"}}),
])
def test_unknown_network_or_malformed_session_is_not_logged_out(creator):
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=[
        creator, response(state={"user": {"loggedIn": False}}),
    ])))
    with pytest.raises(RuntimeError, match="暂时无法确认"):
        account_stats._xhs_session(context)


def test_public_login_redirect_does_not_mean_creator_session_expired_on_network_failure():
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=[
        TimeoutError(), response(url="https://www.xiaohongshu.com/login"),
    ])))
    with pytest.raises(RuntimeError, match="暂时无法确认"):
        account_stats._xhs_session(context)


@pytest.mark.parametrize("wrapper", [None, "value", "_value"])
def test_own_profile_stats_read_zero_and_units_without_feed_author(wrapper):
    profile = {
        "userId": "self", "basicInfo": {"nickname": "My actual nickname"},
        "interactions": [{"type": "fans", "count": "1.2万"},
                         {"type": "follows", "count": 0},
                         {"type": "interaction", "count": "1,234"}],
    }
    state = {"user": {"userInfo": {"userId": "self"}, "loggedIn": True,
                      "userPageData": profile if wrapper is None else {wrapper: profile}},
             "feed": {"nickname": "Other author", "fans": 999999}}
    assert account_stats._xhs_profile_stats(state, "self") == {
        "nickname": "My actual nickname", "followers": 12000, "following": 0, "likes": 1234,
    }


@pytest.mark.parametrize("user", [
    None, [], {"loggedIn": True, "userInfo": {"userId": "other"},
               "userPageData": {"userId": "self", "interactions": [{"type": "fans", "count": 99}]}},
    {"userPageData": {"userId": "other", "basicInfo": {"nickname": "Other"}}},
])
def test_profile_identity_mismatch_or_missing_is_ignored(user):
    assert account_stats._xhs_profile_stats({"user": user}, "self") == {}


def test_malformed_profile_numbers_are_not_fabricated():
    profile = {"interactions": [
        {"type": "fans", "count": True}, {"type": "follows", "count": "12人推荐"},
        {"type": "interaction", "count": "-"}, {"type": [], "name": [], "count": 8}, None,
    ]}
    assert account_stats._xhs_profile_stats({"user": {"userPageData": profile}}, "self") == {}


@pytest.mark.parametrize("destination", [
    "https://www.xiaohongshu.com/user/profile/other",
    "https://other.test/user/profile/self",
    "https://www.xiaohongshu.com/login",
])
def test_own_profile_request_rejects_redirects(destination):
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response(
        url=destination, state={"user": {"userPageData": {
            "basicInfo": {"nickname": "Other"}, "interactions": [{"type": "fans", "count": 9}]}}}))))
    assert account_stats._xhs_own_stats(context, {"userId": "self"}) == {}


def test_logged_out_xhs_skips_navigation_and_notes(monkeypatch):
    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: (None, False))
    page = SimpleNamespace(goto=Mock())
    stats = account_stats._scrape_xhs(object(), page, result())
    assert stats == {**result(), "logged_in": False}
    page.goto.assert_not_called()


def test_web_overview_remains_available_without_creator_login(monkeypatch):
    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: ({"userId": "self"}, False))
    monkeypatch.setattr(account_stats, "_xhs_own_stats", lambda *args: {
        "nickname": "Me", "followers": 0, "likes": 5, "following": 2})
    page = SimpleNamespace(goto=Mock())
    stats = account_stats._scrape_xhs(object(), page, result())
    assert stats["followers"] == 0
    assert stats["nickname"] == "Me"
    assert stats["logged_in"] is True
    assert "重新登录" in stats["warning"]
    page.goto.assert_not_called()


def test_maintenance_falls_back_without_overwriting_own_numbers(monkeypatch):
    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: ({"userId": "self"}, True))
    monkeypatch.setattr(account_stats, "_xhs_own_stats", lambda *args: {"followers": 7})
    monkeypatch.setattr(account_stats, "_poll_stable", lambda *args: ["工程师正在维护"])
    monkeypatch.setattr(account_stats, "_scrape_notes", lambda *args: [])
    page = SimpleNamespace(goto=Mock(), url=xhs_publish.CREATOR_HOME_URL,
                           query_selector_all=lambda selector: [])
    stats = account_stats._scrape_xhs(object(), page, result())
    assert stats["followers"] == 7
    assert "暂不可用" in stats["warning"]
    assert stats["likes"] is None


def test_authenticated_but_empty_data_reports_error(monkeypatch):
    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: ({"userId": "self"}, True))
    monkeypatch.setattr(account_stats, "_xhs_own_stats", lambda *args: {})
    page = SimpleNamespace(goto=Mock(side_effect=TimeoutError()))
    with pytest.raises(RuntimeError, match="未取得创作数据"):
        account_stats._scrape_xhs(object(), page, result())


def test_creator_metrics_are_part_of_stability_signature():
    before = account_stats._xhs_stats_signature(["1", "粉丝数", "曝光数", "0"])
    after = account_stats._xhs_stats_signature(["1", "粉丝数", "曝光数", "12"])
    assert before != after


def test_creator_overview_uses_live_counts_not_delayed_growth():
    assert account_stats._xhs_creator_overview({
        "name": "My nickname", "fans_count": 270, "follow_count": 0, "faved_count": 1649,
        "grow_info": {"fans_count": 269},
    }) == {"nickname": "My nickname", "followers": 270, "following": 0, "likes": 1649}


@pytest.mark.parametrize("value", [None, True, -1, "42", [], {}, 1.5])
def test_creator_overview_does_not_fabricate_invalid_counts(value):
    assert account_stats._xhs_creator_overview({"fans_count": value}) == {}


def test_creator_metrics_preserve_real_zero_negative_growth_and_rate_visibility():
    assert account_stats._xhs_creator_metrics({"seven": {
        "impl_count": 0, "impl_count_rate": 0, "impl_count_rate_display": True,
        "view_count": 12, "view_count_rate": 100, "view_count_rate_display": False,
        "net_rise_fans_count": -2, "net_rise_fans_count_rate": -10.5,
        "net_rise_fans_count_rate_display": True,
        "like_count": None, "comment_count": True, "collect_count": -3,
        "share_count": 1, "share_count_rate": float("inf"), "share_count_rate_display": True,
    }}) == [
        {"label": "曝光数", "value": 0, "vs": "+0%"},
        {"label": "观看数", "value": 12, "vs": ""},
        {"label": "分享数", "value": 1, "vs": ""},
        {"label": "净涨粉", "value": -2, "vs": "-10.5%"},
    ]


@pytest.mark.parametrize("data", [None, [], {}, {"seven": []}, {"thirty": {"view_count": 100}}])
def test_creator_metrics_only_read_seven_day_data(data):
    assert account_stats._xhs_creator_metrics(data) == []


def test_creator_overview_request_includes_creator_referer():
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response(
        payload={"success": True, "data": {"fans_count": 2}}))))
    assert account_stats._xhs_creator_stats(context) == {"followers": 2}
    assert context.request.get.call_args.kwargs["headers"] == {
        "Referer": xhs_publish.CREATOR_HOME_URL}


@pytest.mark.parametrize("reply", [
    response(401, {"success": False, "data": {"fans_count": 999}}),
    response(payload={"success": False, "data": {"fans_count": 999}}),
    response(payload=[]), TimeoutError(),
])
def test_failed_creator_overview_is_not_used(reply):
    getter = Mock(side_effect=reply) if isinstance(reply, Exception) else Mock(return_value=reply)
    context = SimpleNamespace(request=SimpleNamespace(get=getter))
    assert account_stats._xhs_creator_stats(context) == {}


def test_creator_response_metrics_are_used_without_extra_profile_request(monkeypatch):
    import analytics_transport

    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: ({"userId": "self"}, True))
    monkeypatch.setattr(account_stats, "_xhs_creator_stats", lambda context: {"followers": 7})
    public_profile = Mock()
    monkeypatch.setattr(account_stats, "_xhs_own_stats", public_profile)
    monkeypatch.setattr(analytics_transport, "prepare", lambda *args: None)
    monkeypatch.setattr(account_stats, "_scrape_notes", lambda *args: [])
    listener = []
    page = SimpleNamespace(
        on=lambda event, callback: listener.append(callback), remove_listener=Mock(),
        goto=Mock(), url=xhs_publish.CREATOR_HOME_URL, query_selector_all=lambda selector: [])

    def poll(page, signature, max_ms):
        listener[0](response(payload={"success": True, "data": {"seven": {
            "view_count": 0, "view_count_rate_display": False}}},
            url="https://creator.xiaohongshu.com/api/galaxy/v2/creator/datacenter/account/base"))
        assert signature([]) == (("观看数", 0, ""),)
        return []

    monkeypatch.setattr(account_stats, "_poll_stable", poll)
    stats = account_stats._scrape_xhs(object(), page, result())
    assert stats["followers"] == 7
    assert stats["metrics"] == [{"label": "观看数", "value": 0, "vs": ""}]
    assert "warning" not in stats
    public_profile.assert_not_called()
    page.remove_listener.assert_called_once_with("response", listener[0])


def test_creator_dom_zero_placeholders_are_not_reported_as_real_metrics(monkeypatch):
    import analytics_transport

    monkeypatch.setattr(account_stats, "_xhs_session", lambda context: ({"userId": "self"}, True))
    monkeypatch.setattr(account_stats, "_xhs_creator_stats", lambda context: {"followers": 7})
    monkeypatch.setattr(analytics_transport, "prepare", lambda *args: None)
    monkeypatch.setattr(account_stats, "_scrape_notes", lambda *args: [])
    page = SimpleNamespace(on=Mock(), remove_listener=Mock(), goto=Mock(),
                           url=xhs_publish.CREATOR_HOME_URL, query_selector_all=lambda selector: [])

    def poll(page, signature, max_ms):
        lines = ["曝光数", "0", "环比-", "观看数", "0"]
        assert signature(lines) is None
        return lines

    monkeypatch.setattr(account_stats, "_poll_stable", poll)
    stats = account_stats._scrape_xhs(object(), page, result())
    assert stats["metrics"] == []
    assert "暂不可用" in stats["warning"]


@pytest.mark.parametrize("platform", ["douyin", "kuaishou", "zhihu", "weixin-channels"])
def test_other_platform_login_wall_returns_before_waiting_for_metrics(platform, tmp_path, monkeypatch):
    from playwright import sync_api

    context = SimpleNamespace(
        pages=[SimpleNamespace(url="https://platform.test/login", goto=Mock())], close=Mock())
    playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=lambda *args, **kwargs: context))
    class Manager:
        def __enter__(self):
            return playwright

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(account_stats, "_profile_dir", lambda *args: tmp_path)
    poll, notes = Mock(), Mock()
    monkeypatch.setattr(account_stats, "_poll_stable", poll)
    monkeypatch.setattr(account_stats, "_scrape_notes", notes)
    assert account_stats._scrape(platform, False, None, None)["logged_in"] is False
    poll.assert_not_called()
    notes.assert_not_called()
    context.close.assert_called_once()


def test_douyin_does_not_reject_session_before_spa_login_anchor_renders(tmp_path, monkeypatch):
    from playwright import sync_api

    page = SimpleNamespace(url=account_stats.PLATFORMS["douyin"]["url"], goto=Mock(),
                           query_selector_all=lambda selector: [])
    context = SimpleNamespace(pages=[page], close=Mock())
    playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch_persistent_context=lambda *args, **kwargs: context))
    class Manager:
        def __enter__(self):
            return playwright

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(account_stats, "_profile_dir", lambda *args: tmp_path)
    polled = []
    monkeypatch.setattr(account_stats, "_poll_stable", lambda *args: polled.append(True) or ["粉丝", "12"])
    monkeypatch.setattr(account_stats, "_platform_logged_in", lambda *args: bool(polled))
    monkeypatch.setattr(account_stats, "_scrape_notes", lambda *args: [])
    stats = account_stats._scrape("douyin", False, None, None)
    assert stats["logged_in"] is True
    assert stats["followers"] == 12


def test_polling_budget_includes_blocked_body_reads(monkeypatch):
    clock = [0.0]
    timeouts, waits = [], []
    monkeypatch.setattr(account_stats.time, "monotonic", lambda: clock[0])

    def read_body(selector, timeout):
        timeouts.append(timeout)
        clock[0] += timeout / 1000
        raise TimeoutError()

    def wait(duration):
        waits.append(duration)
        clock[0] += duration / 1000

    page = SimpleNamespace(inner_text=read_body, wait_for_timeout=wait)
    assert account_stats._poll_stable(page, lambda lines: None, 2000) == []
    assert clock[0] <= 2.001
    assert max(timeouts) <= 1000
    assert len(timeouts) <= 2


def test_stable_real_zero_returns_after_two_reads(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(account_stats.time, "monotonic", lambda: clock[0])
    reads = Mock(return_value="0\n粉丝数")
    page = SimpleNamespace(inner_text=reads,
                           wait_for_timeout=lambda duration: clock.__setitem__(0, clock[0] + duration / 1000))
    assert account_stats._poll_stable(page, lambda lines: (0,), 2000) == ["0", "粉丝数"]
    assert reads.call_count == 2


@pytest.mark.parametrize("visible", [False, True])
def test_hidden_login_button_does_not_invalidate_session(visible):
    page = SimpleNamespace(url="https://creator.test/home", query_selector_all=lambda selector: [
        SimpleNamespace(is_visible=lambda: visible)])
    assert account_stats._login_wall(page) is visible


def test_note_listener_is_removed_when_manager_navigation_fails():
    page = SimpleNamespace(on=Mock(), remove_listener=Mock(),
                           goto=Mock(side_effect=TimeoutError()))
    assert account_stats._scrape_notes("xiaohongshu", page, account_stats.PLATFORMS["xiaohongshu"]) == []
    page.remove_listener.assert_called_once_with("response", page.on.call_args.args[1])


def test_failed_xhs_fetch_closes_context_and_releases_lock(tmp_path, monkeypatch):
    from playwright import sync_api

    context = SimpleNamespace(pages=[object()], close=Mock())
    lock = SimpleNamespace(acquire=Mock(), release=Mock())
    launch = Mock(return_value=context)
    manager = SimpleNamespace()
    class Manager:
        def __enter__(self):
            return manager

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(sync_api, "sync_playwright", Manager)
    monkeypatch.setattr(account_stats, "_profile_dir", lambda *args: tmp_path)
    monkeypatch.setattr(xhs_publish, "_ProfileLock", lambda profile: lock)
    monkeypatch.setattr(xhs_publish, "_clear_stale_chrome_locks", lambda profile: None)
    monkeypatch.setattr(xhs_publish, "_launch", launch)
    monkeypatch.setattr(account_stats, "_scrape_xhs", Mock(side_effect=RuntimeError("no data")))
    with pytest.raises(RuntimeError, match="no data"):
        account_stats._scrape("xiaohongshu", False, None, None)
    assert launch.call_args.kwargs == {"login_assets": False}
    context.close.assert_called_once()
    lock.release.assert_called_once()


def test_logged_out_result_never_records_snapshot(monkeypatch, capsys):
    monkeypatch.setattr(account_stats, "_scrape", lambda *args: {
        **result(), "logged_in": False, "followers": 42})
    monkeypatch.setattr(account_stats, "load_history", lambda platform: [])
    record = Mock()
    monkeypatch.setattr(account_stats, "record_snapshot", record)
    args = SimpleNamespace(platform="xiaohongshu", headed=False, profile_base=None,
                           no_proxy=True, proxy=None)
    assert account_stats.cmd_fetch(args) == 0
    assert json.loads(capsys.readouterr().out)["loggedIn"] is False
    record.assert_not_called()
