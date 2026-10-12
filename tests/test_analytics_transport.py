import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/shared/scripts"))
import analytics_transport


def context_for(html):
    return SimpleNamespace(
        request=SimpleNamespace(get=Mock(return_value=SimpleNamespace(status=200, text=lambda: html))),
        route=Mock())


def session_factory(monkeypatch, response=None, error=None):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get = Mock(side_effect=error) if error else Mock(return_value=response or SimpleNamespace(
        status_code=200, content=b"window.creator = true;"))
    monkeypatch.setattr(analytics_transport.requests, "Session", lambda: session)
    return session


def test_only_public_creator_scripts_are_downloaded_and_cached(tmp_path, monkeypatch):
    destination = "https://fe-static.xhscdn.com/formula-static/resource/index.1234.js"
    context = context_for(
        f'<script src="{destination}"></script><script src="{destination}"></script>'
        '<script src="https://creator.xiaohongshu.com/api/galaxy/user/info"></script>'
        '<script src="https://untrusted.test/tracker.js"></script>')
    session = session_factory(monkeypatch)
    analytics_transport.prepare(context, "https://creator.xiaohongshu.com/new/home", tmp_path)
    session.get.assert_called_once()
    assert session.get.call_args.args == (destination,)
    assert "headers" not in session.get.call_args.kwargs
    assert session.trust_env is False
    assert len(list(tmp_path.glob("*.js"))) == 1
    assert not list(tmp_path.glob("*.tmp"))
    pattern, handler = context.route.call_args.args
    assert pattern == "https://fe-static.xhscdn.com/**"
    route = SimpleNamespace(fulfill=Mock(), continue_=Mock())
    handler(route, SimpleNamespace(url=destination))
    route.fulfill.assert_called_once_with(body=b"window.creator = true;",
                                          content_type="application/javascript")
    handler(route, SimpleNamespace(url=destination + "?unknown"))
    route.continue_.assert_called_once()
    analytics_transport.prepare(context, "https://creator.xiaohongshu.com/new/home", tmp_path)
    assert session.get.call_count == 1


@pytest.mark.parametrize("response,error", [
    (SimpleNamespace(status_code=503, content=b"maintenance"), None),
    (SimpleNamespace(status_code=200, content=b""), None),
    (None, requests.Timeout()),
])
def test_failed_prefetch_leaves_browser_transport_unchanged(tmp_path, monkeypatch, response, error):
    context = context_for('<script src="https://fe-static.xhscdn.com/resource/index.js"></script>')
    session_factory(monkeypatch, response, error)
    analytics_transport.prepare(context, "https://creator.xiaohongshu.com/new/home", tmp_path)
    context.route.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_home_network_failure_does_not_break_fallback(tmp_path):
    context = SimpleNamespace(request=SimpleNamespace(get=Mock(side_effect=TimeoutError())), route=Mock())
    analytics_transport.prepare(context, "https://creator.xiaohongshu.com/new/home", tmp_path)
    context.route.assert_not_called()


def test_route_assets_follow_current_home_and_note_manifest_versions():
    root = "https://fe-static.xhscdn.com/formula-static/ugc/public/"
    assets = {
        root + "resource/js/bundler-runtime.01234567.js": (
            b'x.u=function(e){return"resource/js/async/"+e+"."+({3074:"12345678",'
            b'3567:"aabbccdd",2298:"87654321",8888:"eeeeeeee"})[e]+".js"},'
            b'x.miniCssF=function(e){return"resource/css/async/"+e+"."+({3567:"33445566"})[e]+".css"},'),
        root + "resource/js/index.76543210.js": (
            b'{name:"home",path:"home",component:function(){return Promise.all([n.e("3074"),'
            b'n.e("3567")]).then(n.bind(n,12))},meta:{}},'
            b'{name:"noteManager",path:"note-manager",component:function(){return n.e("2298")},meta:{}},'
            b'{name:"unrelated",path:"other",component:function(){return n.e("8888")},meta:{}}'),
    }
    assert analytics_transport._route_assets(assets) == [
        root + "resource/js/async/3074.12345678.js",
        root + "resource/js/async/3567.aabbccdd.js",
        root + "resource/js/async/2298.87654321.js",
        root + "resource/css/async/3567.33445566.css",
    ]


def test_prefetch_deadline_does_not_break_browser_fallback(tmp_path, monkeypatch):
    context = context_for('<script src="https://fe-static.xhscdn.com/resource/index.js"></script>')
    session_factory(monkeypatch)
    monkeypatch.setattr(analytics_transport, "as_completed",
                        Mock(side_effect=analytics_transport.FuturesTimeoutError()))
    analytics_transport.prepare(context, "https://creator.xiaohongshu.com/new/home", tmp_path)
    context.route.assert_not_called()
