"""Built-in adapters retain upstream compatibility after moving out of web/app.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easel.trends import builtin
from easel.trends.protocol import validate_payload
from easel.trends.sources import load_sources


@pytest.mark.parametrize("response,hot,url", [
    ({"data": ["标题", "   "]}, "", ""),
    ({"data": [{"Title": "标题", "HotValue": 1234567, "Url": "https://example.com/1"}]},
     "1234567", "https://example.com/1"),
    ({"data": [{"target": {"title": "标题", "url": "https://api.zhihu.com/questions/123",
                            "metrics_area": {"text": "387 万热度"}}}]},
     "387 万热度", "https://www.zhihu.com/question/123"),
    ({"data": [{"title": "标题", "hot": "118万", "url": "https://example.com/1"}]},
     "118万", "https://example.com/1"),
    ({"data": {"list": [{"word": "标题", "num": 42}]}}, "42", ""),
    ({"data": {"data": [{"name": "标题"}]}}, "", ""),
])
def test_builtin_normalizes_upstream_shapes(response, hot, url):
    assert builtin.parse_upstream(response) == [{"title": "标题", "url": url, "heat": {"text": hot}}]


@pytest.mark.parametrize("bad", [{}, {"data": None}, {"data": "invalid"}, {"data": [1, 2]},
                                  {"data": [{"hot": "1"}]}, []])
def test_builtin_rejects_junk(bad):
    assert builtin.parse_upstream(bad) == []


@pytest.mark.parametrize("mode", ["exception", "empty", "malformed"])
def test_builtin_falls_back_and_returns_wire_contract(monkeypatch, mode):
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            if mode == "exception":
                raise OSError("upstream unavailable")
            if mode == "malformed":
                return {"data": [{"title": "bad link", "url": "javascript:alert(1)"}]}
            return {"data": []}
        return {"data": [{"title": "备用热点"}]}

    monkeypatch.setattr(builtin, "fetch_json", fetch)
    result = validate_payload(builtin.collect_platform("weibo"))
    assert result["items"][0]["title"] == "备用热点"
    assert calls == list(builtin.SOURCES["weibo"])


def test_builtin_outage_is_not_successful_empty_result(monkeypatch):
    monkeypatch.setattr(builtin, "fetch_json", lambda url: {"data": []})
    with pytest.raises(RuntimeError):
        builtin.collect_platform("weibo")


def test_all_builtin_platforms_use_public_python_transport(tmp_path):
    sources = load_sources(tmp_path, {})
    assert {s.id for s in sources} == set(builtin.SOURCES)
    assert all(s.type == "python" and Path(s.options["script"]).is_file() for s in sources)
    assert {s.id for s in sources if s.default} == {"weibo", "douyin", "zhihu"}
