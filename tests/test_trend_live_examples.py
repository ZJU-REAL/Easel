"""Mapping regressions for the reusable real API examples; live checks are separate."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from easel.trends.protocol import validate_payload


@pytest.fixture
def collector():
    spec = importlib.util.spec_from_file_location("live_trend_example", ROOT / "examples/trends/live_collector.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_hackernews_mapping_and_discussion_link_fallback(collector, monkeypatch):
    monkeypatch.setattr(collector, "fetch_json", lambda url: {"hits": [
        {"objectID": "123", "title": "A public story", "url": None,
         "created_at": "2026-10-29T00:00:00Z", "points": 42}]})
    result = validate_payload(collector.collect("hackernews", 20))
    assert result["items"][0]["url"] == "https://news.ycombinator.com/item?id=123"
    assert result["items"][0]["heat"]["value"] == 42


def test_live_github_mapping_title_downloads_and_draft_filter(collector, monkeypatch):
    release = {"id": 123, "name": "GitHub CLI 1.2.3", "tag_name": "v1.2.3",
               "html_url": "https://github.com/cli/cli/releases/tag/v1.2.3",
               "published_at": "2026-10-29T00:00:00Z",
               "assets": [{"download_count": 4}, {"download_count": 5}]}
    monkeypatch.setattr(collector, "fetch_json", lambda url: [release, {**release, "draft": True}])
    result = validate_payload(collector.collect("github", 10))
    assert len(result["items"]) == 1
    assert result["items"][0]["title"] == "GitHub CLI 1.2.3"
    assert result["items"][0]["heat"]["value"] == 9


@pytest.mark.parametrize("provider,response", [("hackernews", []), ("github", {})])
def test_live_examples_fail_on_unexpected_upstream_shape(collector, monkeypatch, provider, response):
    monkeypatch.setattr(collector, "fetch_json", lambda url: response)
    with pytest.raises(ValueError):
        collector.collect(provider)
