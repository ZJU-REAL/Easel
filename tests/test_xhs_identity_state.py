import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "shared" / "scripts"))
import xhs_publish


def html_state(user):
    return '<script>window.__INITIAL_STATE__=' + json.dumps({
        "user": user, "feed": {"nickname": "unrelated author", "images": "https://feed.test/avatar"},
    }) + ";</script>"


def test_initial_state_reads_own_identity_only():
    account = xhs_publish._web_account_html(html_state({
        "loggedIn": True,
        "userInfo": {"userId": "self-id", "nickname": "My account", "images": "https://self.test/avatar"},
    }))
    assert xhs_publish._account_identity(account) == {
        "name": "My account", "avatar": "https://self.test/avatar",
    }


@pytest.mark.parametrize("user", [
    None, [], "bad", {}, {"loggedIn": False, "userInfo": {"userId": "id"}},
    {"loggedIn": True, "userInfo": {"userId": ""}},
    {"loggedIn": True, "userInfo": {"userId": ["id"]}},
    {"loggedIn": 1, "userInfo": {"userId": "id"}},
])
def test_anon_or_malformed_self_state_never_returns_feed_author(user):
    assert xhs_publish._web_account_html(html_state(user)) is None


def test_undefined_replacement_does_not_modify_quoted_nickname():
    html = html_state({"loggedIn": True, "userInfo": {
        "userId": "id", "nickname": "undefined person", "images": None,
    }}).replace('"images": null', '"images": undefined')
    assert xhs_publish._web_account_html(html)["userName"] == "undefined person"


@pytest.mark.parametrize("html", [
    "<script>window.__INITIAL_STATE__=alert('do not eval')</script>",
    "<script>window.__INITIAL_STATE__=[]</script>",
    "<script>window.__INITIAL_STATE__=null</script>",
    "<div>no state</div>", "x" * 2_000_001,
])
def test_invalid_initial_state_is_ignored_without_execution(html):
    assert xhs_publish._web_account_html(html) is None


def test_complete_web_identity_does_not_wait_for_creator(monkeypatch):
    account = {"userId": "self", "userName": "My account", "userAvatar": "https://self.test/avatar"}
    monkeypatch.setattr(xhs_publish, "_web_account", lambda context: account)

    def unnecessary_request(context):
        raise AssertionError("Complete identity should return immediately")

    monkeypatch.setattr(xhs_publish, "_creator_account", unnecessary_request)
    assert xhs_publish._authenticated_account(object()) == account


def test_incomplete_web_identity_is_enriched_from_same_account(monkeypatch):
    monkeypatch.setattr(xhs_publish, "_web_account", lambda context: {
        "userId": "self", "userName": "My account", "userAvatar": "",
    })
    monkeypatch.setattr(xhs_publish, "_creator_account", lambda context: {
        "userId": "self", "userName": "Creator name", "userAvatar": "https://self.test/avatar",
    })
    assert xhs_publish._account_identity(xhs_publish._authenticated_account(object())) == {
        "name": "My account", "avatar": "https://self.test/avatar",
    }


def test_identity_is_never_merged_across_accounts(monkeypatch):
    account = {"userId": "self", "userName": "", "userAvatar": ""}
    monkeypatch.setattr(xhs_publish, "_web_account", lambda context: account)
    monkeypatch.setattr(xhs_publish, "_creator_account", lambda context: {
        "userId": "other", "userName": "Other account", "userAvatar": "https://other.test/avatar",
    })
    assert xhs_publish._authenticated_account(object()) == account


def test_creator_identity_is_used_when_web_identity_is_unavailable(monkeypatch):
    account = {"userId": "self", "userName": "My account", "userAvatar": "https://self.test/avatar"}
    monkeypatch.setattr(xhs_publish, "_web_account", lambda context: None)
    monkeypatch.setattr(xhs_publish, "_creator_account", lambda context: account)
    assert xhs_publish._authenticated_account(object()) == account


@pytest.mark.parametrize("wrapper", ["plain", "value", "_value"])
def test_profile_basic_info_reads_current_self_and_prefers_large_avatar(wrapper):
    profile = {"basicInfo": {"nickname": "My actual nickname",
                             "imageb": "//self.test/large.png",
                             "images": "https://self.test/small.png"}}
    state = {"user": {"loggedIn": True, "userInfo": {"userId": "self-id"},
                      "userPageData": profile if wrapper == "plain" else {wrapper: profile}},
             "feed": {"nickname": "Unrelated author", "images": "https://other.test/avatar"}}
    assert xhs_publish._self_profile_identity(state, "self-id") == {
        "name": "My actual nickname", "avatar": "https://self.test/large.png",
    }


@pytest.mark.parametrize("own_id,profile_id,logged_in", [
    ("other", "self", True), ("self", "other", True), ("self", "self", False),
])
def test_profile_basic_info_rejects_other_users_and_anonymous_state(own_id, profile_id, logged_in):
    state = {"user": {"loggedIn": logged_in, "userInfo": {"userId": own_id},
                      "userPageData": {"userId": profile_id, "basicInfo": {
                          "nickname": "Not me", "images": "https://other.test/avatar"}}}}
    assert xhs_publish._self_profile_identity(state, "self") == {"name": "", "avatar": ""}


def test_vue_wrapped_authenticated_state_and_alternate_fields_are_supported():
    state = {"user": {"loggedIn": {"value": True}, "userInfo": {"_value": {
        "userId": "self", "nickname": "My nickname", "avatar": "//self.test/avatar"}}}}
    assert xhs_publish._account_identity(xhs_publish._state_account(state)) == {
        "name": "My nickname", "avatar": "https://self.test/avatar",
    }


@pytest.mark.parametrize("avatar", ["https://[broken", "https://user:secret@self.test/avatar",
                                   "https://self.test/\nimage", "javascript:alert(1)"])
def test_invalid_avatar_does_not_discard_valid_name_or_next_avatar(avatar):
    assert xhs_publish._account_identity({
        "nickname": "Me", "imageb": avatar, "images": "https://self.test/valid",
    }) == {"name": "Me", "avatar": "https://self.test/valid"}


def test_profile_request_uses_verified_id_and_validates_response_url():
    state = {"user": {"loggedIn": True, "userInfo": {"userId": "self"},
                      "userPageData": {"basicInfo": {"nickname": "Me", "imageb": "https://self.test/avatar"}}}}
    account = {"userId": "self", "userName": "", "userAvatar": ""}
    response = SimpleNamespace(status=200, url="https://www.xiaohongshu.com/user/profile/self",
                               text=lambda: '<script>window.__INITIAL_STATE__=' + json.dumps(state) + '</script>')
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response)))
    result = xhs_publish._self_profile_account(context, account)
    assert xhs_publish._account_identity(result) == {"name": "Me", "avatar": "https://self.test/avatar"}
    context.request.get.assert_called_once_with(
        response.url, headers={"Referer": xhs_publish.EXPLORE_URL}, timeout=4000)
    response.url = "https://www.xiaohongshu.com/user/profile/other"
    assert xhs_publish._self_profile_account(context, account) == account


def test_profile_canonical_fields_override_stale_login_state_fields():
    assert xhs_publish._account_identity({
        "userName": "Current name", "nickname": "Old name",
        "userAvatar": "https://self.test/current", "images": "https://self.test/old",
    }) == {"name": "Current name", "avatar": "https://self.test/current"}


def test_creator_account_request_includes_required_first_party_referer():
    account = {"userId": "self", "userName": "Me", "userAvatar": "https://self.test/avatar"}
    response = SimpleNamespace(status=200, json=lambda: {"success": True, "data": account})
    request = Mock(return_value=response)
    context = SimpleNamespace(request=SimpleNamespace(get=request))
    assert xhs_publish._creator_account(context) == account
    request.assert_called_once_with(
        xhs_publish.CREATOR_ACCOUNT_URL, headers={"Referer": xhs_publish.CREATOR_HOME_URL}, timeout=5000)


@pytest.mark.parametrize("complete", [False, True])
def test_whoami_enriches_incomplete_identity_without_losing_verified_login(monkeypatch, capsys, complete):
    account = {"userId": "self", "userName": "Me",
               "userAvatar": "https://self.test/avatar" if complete else ""}
    page = object()
    context = SimpleNamespace(pages=[page], close=Mock())
    playwright = Mock()
    playwright.__enter__ = Mock(return_value=object())
    playwright.__exit__ = Mock(return_value=False)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: playwright)
    monkeypatch.setattr(xhs_publish, "_ProfileLock", lambda profile: SimpleNamespace(acquire=Mock(), release=Mock()))
    monkeypatch.setattr(xhs_publish, "_launch", lambda *args, **kwargs: context)
    monkeypatch.setattr(xhs_publish, "_authenticated_account", lambda context: account)
    profile = Mock(return_value=account)
    dom = Mock(return_value={"name": "Do not replace name", "avatar": "https://self.test/avatar"})
    monkeypatch.setattr(xhs_publish, "_self_profile_account", profile)
    monkeypatch.setattr(xhs_publish, "_page_account_identity", dom)
    args = SimpleNamespace(profile_base=None, proxy=None, no_proxy=True)
    assert xhs_publish.cmd_whoami(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "loggedIn": True, "name": "Me", "avatar": "https://self.test/avatar",
    }
    assert profile.call_count == (0 if complete else 1)
    assert dom.call_count == (0 if complete else 1)
    context.close.assert_called_once()
