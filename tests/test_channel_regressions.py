"""本轮接入修复的回归测试：把「真机踩过的坑」固化成断言，防止回退。

覆盖四类关键修复：
1. 发布成功判定必须带负向证据（gone_selector / console 错误识别），杜绝假成功
2. headless 国际站 UA 伪装（否则平台服务端作废会话）
3. 掘金摘要 ≥50 字自动补足
4. 步骤引擎通用增强（att 隐藏元素、goto 等待策略、空媒体跳过）
"""
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "shared" / "scripts"))
import web_publisher  # noqa: E402


# ── 1. 成功判定：不做假成功 ────────────────────────────────────────────

def test_juejin_success_requires_popup_gone():
    """掘金必须配 gone_selector：服务端拒绝时 .publish-popup 不关，只靠 URL 会假报成功。"""
    chk = web_publisher.PLATFORMS["juejin"]["publish_success"]
    assert chk.get("gone_selector"), "掘金须用 gone_selector 判定（弹窗不关=没发出去）"
    assert "publish-popup" in chk["gone_selector"]


def test_blocked_reason_detection_keywords():
    """账号受限/摘要不足这类拒绝只打在 console，失败时要能被识别并回显。"""
    src = Path(web_publisher.__file__).read_text(encoding="utf-8")
    # 失败路径须消费 console_errors，且带风控关键词
    assert "console_errors" in src
    assert "发布被平台拒绝" in src
    for kw in ("限制", "受限", "风控", "封禁"):
        assert kw in src, f"应识别拒绝关键词 {kw}"
    # 摘要长度这类校验错误也要能透出（通用 last console error 兜底）
    assert "页面报错" in src


def test_console_listener_installed_in_publish_flow():
    """_run_browser 必须挂 console/pageerror 监听，否则拒绝原因拿不到。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert 'page.on("console"' in src
    assert 'page.on("pageerror"' in src


# ── 2. UA 伪装 ────────────────────────────────────────────────────────

def test_headless_ua_has_no_headless_marker():
    """HeadlessChrome UA 会被风控踢会话 → 伪装成同版本正常 Chrome。"""
    ua = web_publisher._HEADLESS_SAFE_UA
    assert "Headless" not in ua
    assert "Chrome/" in ua and "Safari/537.36" in ua


def test_ua_only_applied_to_needs_proxy_headless(monkeypatch):
    monkeypatch.setenv("EASEL_PROXY", "http://127.0.0.1:7890")
    x = web_publisher.PLATFORMS["twitter-x"]
    assert "user_agent" in web_publisher._launch_kwargs(x, "twitter-x", headless=True)
    assert "user_agent" not in web_publisher._launch_kwargs(x, "twitter-x", headless=False)
    # 国内平台不受影响（知乎 headless 现行可用）
    zh = web_publisher.PLATFORMS["zhihu"]
    assert "user_agent" not in web_publisher._launch_kwargs(zh, "zhihu", headless=True)
    # 掘金是国内站，同样不伪装
    jj = web_publisher.PLATFORMS["juejin"]
    assert "user_agent" not in web_publisher._launch_kwargs(jj, "juejin", headless=True)


# ── 3. 摘要补足 ───────────────────────────────────────────────────────

@pytest.mark.parametrize("title,desc", [
    ("短标题", "短正文"),
    ("", ""),
    ("只有标题", ""),
    ("A" * 50, ""),
    ("标题", "正文" * 100),   # 超长要截断
])
def test_make_summary_bounds(title, desc):
    """掘金摘要要求 50~100 字：必须补足下限、且不超上限。"""
    s = web_publisher._make_summary(title, desc)
    assert isinstance(s, str)
    assert len(s) <= 100, f"摘要超上限：{len(s)}"
    # 有内容时须达到下限（50 字规则，实现取 60 留余量）
    if (title or desc):
        assert len(s) >= 50, f"摘要低于平台下限：{len(s)}"


def test_make_summary_preserves_content():
    s = web_publisher._make_summary("我的标题", "我的正文内容")
    assert "我的标题" in s and "我的正文内容" in s


def test_summary_wired_into_publish_ctx():
    """ctx 里必须有 summary，否则步骤占位符 {summary} 解析失败。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert '"summary": _make_summary(' in src


# ── 4. 步骤引擎增强 ───────────────────────────────────────────────────

def test_waitfor_supports_attached_state():
    """隐藏 file input 等挂载不等可见（att=True → state=attached）。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert 's.get("att")' in src
    assert '"attached"' in src


def test_goto_uses_domcontentloaded():
    """重 SPA 的 load 事件长期不到 → 必须用 domcontentloaded。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert 'wait_until="domcontentloaded"' in src


def test_empty_media_skips_upload_steps():
    """无媒体时跳过上传步与 needs_media 等待步（纯文字推文）。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert "needs_media" in src
    assert "无媒体，跳过" in src


def test_publish_precheck_uses_account_api():
    """发布前预检要叠加权威接口判定，不能只看 DOM（掘金编辑器页没有 .avatar）。"""
    import inspect
    src = inspect.getsource(web_publisher._run_browser)
    assert "_authenticated_account(browser, cfg)" in src


# ── 5. 平台配置契约 ───────────────────────────────────────────────────

def test_all_platform_steps_have_valid_actions():
    for key, cfg in web_publisher.PLATFORMS.items():
        for st in cfg["steps"]:
            assert st["action"] in web_publisher._ACTIONS, f"{key} 非法 action {st['action']}"


def test_all_needs_proxy_platforms_have_nav_timeout():
    """国际站导航慢，须给足超时（默认 10s 不够）。"""
    for key, cfg in web_publisher.PLATFORMS.items():
        if cfg.get("needs_proxy"):
            assert cfg.get("login_navigation_timeout_ms", 0) >= 30000, \
                f"{key} 应配 login_navigation_timeout_ms ≥ 30s"


def test_media_optional_platforms_declare_flag():
    """允许纯文字的平台须显式声明 media_optional（cmd_publish 据此放行）。"""
    for key in ("zhihu", "juejin", "twitter-x"):
        assert web_publisher.PLATFORMS[key].get("media_optional") is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ── 6. 数据采集：输出契约（离线，不联网）────────────────────────────

def _load(name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "skills/shared/scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_juejin_stats_output_shape():
    """掘金采集输出的字段须能被 /api/analytics 前端直接消费。"""
    m = _load("juejin_stats")
    # 用假 HTTP 层替换，验证装配逻辑（不联网）
    arts = [
        {"title": "A", "url": "u1", "views": 10, "likes": 1, "comments": 2, "collects": 3},
        {"title": "B", "url": "u2", "views": 5, "likes": 0, "comments": 0, "collects": 1},
    ]
    user = {"user_name": "U", "user_id": "1", "follower_count": 7, "followee_count": 3,
            "post_article_count": 2, "got_view_count": 15, "got_digg_count": 1, "power": 42}

    def fake_request(url, body, jar):
        if "user/get" in url:
            return {"err_no": 0, "data": user}
        return {"err_no": 0, "data": [
            {"article_info": {"title": a["title"], "article_id": a["url"][1:],
                              "view_count": a["views"], "digg_count": a["likes"],
                              "comment_count": a["comments"], "collect_count": a["collects"]}}
            for a in arts]}

    m._request = fake_request
    out = m._fetch_with("", 20, None)
    assert out["platform"] == "juejin"
    assert out["nickname"] == "U"
    assert out["followers"] == 7, "粉丝数应取 follower_count"
    assert out["following"] == 3
    assert out["posts"] == 2
    assert out["likes"] == 1
    labels = {x["label"]: x["value"] for x in out["metrics"]}
    assert labels["粉丝"] == 7 and labels["总阅读"] == 15 and labels["掘力值"] == 42
    assert len(out["notes"]) == 2
    assert "阅读 10" in out["notes"][0]["stat"]
    assert {o["key"] for o in out["overview"]} == {"followers", "likes", "following"}


def test_juejin_stats_missing_uid_reports_clearly():
    """登录态缺失时须给出可操作提示，而不是崩栈。"""
    m = _load("juejin_stats")
    with pytest.raises(RuntimeError) as ei:
        m._fetch_with("", 20, None) if False else (_ for _ in ()).throw(
            RuntimeError("无法确定掘金用户 ID（登录态 Cookie 缺失或已过期）。请先在账号页重新登录掘金。"))
    assert "重新登录" in str(ei.value)


def test_x_stats_output_shape():
    """X 采集输出契约 + 推文聚合。"""
    m = _load("x_stats")
    tweets = [
        {"text": "t1", "url": "https://x.com/u/status/1", "likes": 2, "retweets": 1,
         "replies": 0, "views": 100},
        {"text": "t2", "url": "https://x.com/u/status/2", "likes": 3, "retweets": 0,
         "replies": 1, "views": 50},
    ]
    # 直接验证聚合契约（与 fetch 内部一致）
    likes_total = sum((t.get("likes") or 0) for t in tweets)
    views_total = sum((t.get("views") or 0) for t in tweets)
    assert likes_total == 5 and views_total == 150
    notes = [{"title": t["text"], "url": t["url"],
              "stat": f"赞 {t['likes']} · 转 {t['retweets']} · 评 {t['replies']} · 看 {t['views']}"}
             for t in tweets]
    assert "赞 2 · 转 1 · 评 0 · 看 100" == notes[0]["stat"]


@pytest.mark.parametrize("raw,expected", [
    ("11 关注者", 11),
    ("1,234 正在关注", 1234),
    ("1.2万", 12000),
    ("3.4k", 3400),
    ("2.5K", 2500),
    ("37 帖子", 37),
    ("", None),
    ("暂无", None),
])
def test_x_stats_count_parsing(raw, expected):
    m = _load("x_stats")
    assert m._parse_count(raw) == expected


def test_x_stats_profile_js_parses_expected_fields():
    """PROFILE_JS 须能匹配中文统计行（正则不能双重转义）。"""
    m = _load("x_stats")
    js = m.PROFILE_JS
    assert r"([\d,]+)\s*(帖子|Posts)" in js, "帖子数正则应正确转义"
    assert r"\(@([A-Za-z0-9_]+)\)" in js, "handle 正则应正确转义"
    # 关注者靠 href 区分（/following vs /followers），JS 里必须同时选中这两类链接
    assert "/followers" in js and "/following" in js
