"""热点雷达回归测试：各平台响应格式归一化 + 取不到数据要能被识别出来。

背景（2026-10-01）：热点雷达六个平台里三个是空的——B站其实是解析器的锅（备用源返回 50 条
纯字符串数组，而解析器只认对象数组，全被丢掉），知乎/头条则是压根没有备用源且主源被限流。
这个文件守住两件事：各家格式都解析得出来、以及"取不到"要和"真的没数据"分开。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))

import app as web  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_trend_cache(monkeypatch):
    monkeypatch.setattr(web, "_TREND_CACHE", {})


# ---- 各家响应格式 ----

def test_parse_hot_handles_plain_string_array():
    """xxapi 的 B站热榜：data 就是一串标题字符串，没有对象包着。"""
    items = web._parse_hot({"code": 200, "data": ["凉哈皮谈首登亚运解说台", "   ", "holymoly亚运金牌"]})
    assert [i["title"] for i in items] == ["凉哈皮谈首登亚运解说台", "holymoly亚运金牌"]
    assert all(i["hot"] == "" and i["url"] == "" for i in items)


def test_parse_hot_handles_capitalized_fields():
    """头条官方热榜：Title / HotValue / Url 全是大写开头，热度还会是数字。"""
    items = web._parse_hot({"data": [
        {"ClusterId": 1, "Title": "农民交公粮能否视同缴社保", "HotValue": 1234567,
         "Url": "https://www.toutiao.com/trending/1/"},
    ]})
    assert items == [{"title": "农民交公粮能否视同缴社保", "hot": "1234567",
                      "url": "https://www.toutiao.com/trending/1/"}]


def test_parse_hot_handles_nested_target_and_rewrites_zhihu_url():
    """知乎官方热榜：正文在 target 里，链接给的是 api.zhihu.com，要点开得换成网页地址。"""
    items = web._parse_hot({"data": [
        {"type": "hot_list_feed", "card_id": "Q_1",
         "target": {"id": 2088649572151194406, "title": "迪拜航空客机返航",
                    "url": "https://api.zhihu.com/questions/2088649572151194406",
                    "metrics_area": {"text": "387 万热度"}}},
    ]})
    assert items == [{"title": "迪拜航空客机返航", "hot": "387 万热度",
                      "url": "https://www.zhihu.com/question/2088649572151194406"}]


def test_parse_hot_keeps_original_shape_working():
    """60s 那套老格式（data 直接是对象数组）不能被新写法改坏。"""
    items = web._parse_hot({"data": [{"title": "迪拜航空确认航班发生事故", "hot": "118万",
                                      "url": "https://s.weibo.com/x"}]})
    assert items == [{"title": "迪拜航空确认航班发生事故", "hot": "118万", "url": "https://s.weibo.com/x"}]


def test_parse_hot_accepts_nested_data_wrapper():
    items = web._parse_hot({"data": {"list": [{"word": "热词", "num": 42}]}})
    assert items == [{"title": "热词", "hot": "42", "url": ""}]


@pytest.mark.parametrize("bad", [
    {}, {"data": None}, {"data": "不是列表"}, {"data": [1, 2, 3]}, {"data": [{"hot": "1"}]}, [],
])
def test_parse_hot_returns_empty_on_junk(bad):
    """垃圾/空响应要安静地返回空列表，不能抛异常（抛了整条平台就断）。"""
    assert web._parse_hot(bad) == []


def test_trend_web_url_passes_through_other_urls():
    assert web._trend_web_url("") == ""
    assert web._trend_web_url("https://s.weibo.com/x") == "https://s.weibo.com/x"
    assert web._trend_web_url("https://api.zhihu.com/questions/abc") == "https://api.zhihu.com/questions/abc"


# ---- 源表本身 ----

def test_every_platform_has_a_source():
    """每个能选中的平台都要有主源，别出现"按钮在但没人给它取数据"。"""
    assert set(web.TREND_SOURCES) == set(web.TREND_LABELS)
    for pf, (primary, backup) in web.TREND_SOURCES.items():
        assert primary and primary.startswith("http"), f"{pf} 缺主源"
        if backup:
            assert backup.startswith("http")


# ---- 接口：取不到 vs 真的没有 ----

def test_trends_marks_unavailable_platform(monkeypatch):
    """/api/trends 要给每个平台带 ok 标：空列表＝这个平台取不到，不是"今天没热搜"。"""
    web._TREND_CACHE.clear()
    monkeypatch.setattr(web, "_fetch_platform",
                        lambda pf: [{"title": f"{pf} 的头条", "hot": "", "url": ""}] if pf == "weibo" else [])
    data = asyncio.run(web.api_trends("weibo,bilibili", 15))
    by_pf = {g["platform"]: g for g in data["trends"]}
    assert by_pf["weibo"]["ok"] is True and len(by_pf["weibo"]["items"]) == 1
    assert by_pf["bilibili"]["ok"] is False and by_pf["bilibili"]["items"] == []


def test_trends_ignores_unknown_platform(monkeypatch):
    """乱传平台名不能把接口带崩，也不能凭空多出渠道。"""
    web._TREND_CACHE.clear()
    monkeypatch.setattr(web, "_fetch_platform", lambda pf: [])   # 测试不打真实网络
    data = asyncio.run(web.api_trends("weibo,不存在", 5))
    assert [g["platform"] for g in data["trends"]] == ["weibo"]
    assert [g["label"] for g in data["trends"]] == ["微博"]


@pytest.mark.parametrize("primary_result", [None, {"data": []}, {"data": "invalid"}])
def test_fetch_platform_falls_back_on_error_or_empty_response(monkeypatch, primary_result):
    primary, backup = web.TREND_SOURCES["weibo"]
    calls = []

    def fetch(url):
        calls.append(url)
        if url == primary:
            if primary_result is None:
                raise OSError("unavailable")
            return primary_result
        return {"data": [{"title": "备用热点"}]}

    monkeypatch.setattr(web, "_http_get_json", fetch)
    assert web._fetch_platform("weibo") == [{"title": "备用热点", "hot": "", "url": ""}]
    assert calls == [primary, backup]


def test_trends_reuses_cached_items_when_all_sources_fail(monkeypatch):
    items = [{"title": "缓存热点", "hot": "", "url": ""}]
    web._TREND_CACHE["weibo"] = (0, items)
    monkeypatch.setattr(web, "_fetch_platform", lambda platform: [])
    data = asyncio.run(web.api_trends("weibo", 15))
    assert data["trends"][0]["items"] == items
    assert data["trends"][0]["ok"] is True
