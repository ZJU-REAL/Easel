#!/usr/bin/env python3
"""x_stats.py — 推特 X 创作数据采集（浏览器 DOM，无需付费 API）。

为什么不走官方 API：X 自 2026 年起取消免费层（按量付费），且自助层移除了
followers_count；headless 下 GraphQL 响应也被保护（字段返回 null）。
实测可行路径是**读个人主页 DOM**（2026-10 验证拿到粉丝/关注/帖子数）。

数据来源：
    1. /settings/profile 读 handle（未登录跳 /logout 或登录页）
    2. /<handle> 主页读统计行：「N 正在关注」「N 关注者」「N 帖子」

输出格式与 account_stats.py 对齐，供 /api/analytics 消费。

用法：
    x_stats.py fetch [--handle HANDLE]
    x_stats.py selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BROWSER_PROFILES = Path.home() / ".easel-browser-profiles"
PROFILE = "TwitterXProfile"

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _launch_kwargs() -> dict:
    """复用 web_publisher 的代理/UA 策略（X 需外网代理 + headless UA 伪装）。"""
    try:
        import web_publisher as wp
        cfg = wp.PLATFORMS.get("twitter-x") or {}
        return wp._launch_kwargs(cfg, "twitter-x", headless=True)
    except Exception:
        return {"args": ["--no-sandbox", "--disable-gpu"]}


def _parse_count(text: str) -> int | None:
    """「1,234」「1.2万」「11」→ int。"""
    if not text:
        return None
    t = text.replace(",", "").replace("，", "").strip()
    m = re.search(r"([\d.]+)\s*(万|w|k|K|亿)?", t)
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("万", "w"):
        n *= 10_000
    elif unit in ("k",):
        n *= 1_000
    elif unit == "亿":
        n *= 100_000_000
    return int(round(n))


TWEETS_JS = r"""() => {
  const arts = [...document.querySelectorAll('article[data-testid="tweet"]')];
  const num = (s) => {
    if (!s) return null;
    const m = String(s).replace(/,/g, '').match(/([\d.]+)\s*(万|w|k|K|亿)?/);
    if (!m) return null;
    let n = parseFloat(m[1]);
    const u = (m[2] || '').toLowerCase();
    if (u === '万' || u === 'w') n *= 10000;
    else if (u === 'k') n *= 1000;
    else if (u === '亿') n *= 100000000;
    return Math.round(n);
  };
  const ariaNum = (a, tid) => {
    const el = a.querySelector('[data-testid="' + tid + '"]');
    if (!el) return null;
    const r = num(el.getAttribute('aria-label') || '');
    if (r !== null) return r;
    const sp = el.querySelector('span[data-testid="' + tid + '"]');
    return sp ? num(sp.innerText) : null;
  };
  return arts.map(a => {
    const txtEl = a.querySelector('[data-testid="tweetText"]');
    const text = txtEl ? txtEl.innerText : '';
    const linkEl = a.querySelector('a[href*="/status/"]');
    const link = linkEl ? linkEl.getAttribute('href') : '';
    const viewEl = a.querySelector('[aria-label*="查看"], [aria-label*="View"]');
    return {
      text: text.replace(/\n+/g, ' ').slice(0, 80),
      url: link ? ('https://x.com' + (link.startsWith('/') ? link : '/' + link)) : '',
      replies: ariaNum(a, 'reply'),
      retweets: ariaNum(a, 'retweet'),
      likes: ariaNum(a, 'like'),
      views: viewEl ? num(viewEl.getAttribute('aria-label')) : null
    };
  }).filter(t => t.text || t.url);
}"""

PROFILE_JS = r"""() => {
  const links = [...document.querySelectorAll(
    'a[href*="/following"], a[href*="/followers"], a[href*="/verified_followers"]')];
  const stats = links.map(a => ({href: a.getAttribute('href') || '',
                                 text: (a.innerText || '').replace(/\\n/g, ' ').trim()}));
  const title = document.title || '';
  const handleMatch = title.match(/\(@([A-Za-z0-9_]+)\)/);
  const body = (document.body.innerText || '');
  const postMatch = body.match(/([\d,]+)\s*(帖子|Posts)/i);
  const nameMatch = title.split('(')[0].trim();
  return {stats, title, handle: handleMatch ? handleMatch[1] : '',
          posts: postMatch ? postMatch[1] : '', name: nameMatch};
}"""


def fetch(handle: str = "") -> dict:
    from playwright.sync_api import sync_playwright

    profile = BROWSER_PROFILES / PROFILE
    result = {"platform": "twitter-x", "name": "推特 X", "nickname": "",
              "loggedIn": False, "followers": None, "likes": None,
              "following": None, "posts": None, "metrics": [], "notes": [],
              "overview": [], "growth": {}, "fetched_at": int(time.time()),
              "warning": ""}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=True, locale="zh-CN", **_launch_kwargs())
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            # 1) 拿 handle（设置页；未登录会跳登录/登出页）
            if not handle:
                page.goto("https://x.com/settings/profile", wait_until="domcontentloaded",
                          timeout=60000)
                page.wait_for_timeout(6000)
                if "login" in page.url.lower() or "logout" in page.url.lower():
                    result["warning"] = "X 登录态已失效，请在账号页重新登录"
                    return result
                info = page.evaluate(PROFILE_JS)
                handle = info.get("handle") or ""
                result["nickname"] = info.get("name") or ""
                # 设置页也能拿到帖子数等（部分在 DOM 里）
                if not handle:
                    m = re.search(r"@([A-Za-z0-9_]+)", page.inner_text("body") or "")
                    handle = m.group(1) if m else ""
            if not handle:
                result["warning"] = "未能确定 X 账号 handle（登录态异常）"
                return result

            # 2) 主页读统计
            page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            # 主页统计条（关注者/正在关注/帖子）渲染时机不稳，轮询等它齐（最多 20s）
            info = {}
            posts_initial = None
            for _ in range(10):
                info = page.evaluate(PROFILE_JS) or {}
                stats_text = " ".join((st.get("text") or "") for st in (info.get("stats") or []))
                has_followers = ("关注者" in stats_text or "Followers" in stats_text)
                # 保留第一个非空帖子数（后续轮次可能解析失败，不能覆盖）
                posts_initial = posts_initial or _parse_count(info.get("posts") or "")
                if has_followers and posts_initial is not None:
                    break
                page.wait_for_timeout(2000)
            following = followers = None
            for st in info.get("stats") or []:
                href, text = st.get("href") or "", st.get("text") or ""
                n = _parse_count(text)
                if "/following" in href:
                    following = n
                elif "/followers" in href or "/verified_followers" in href:
                    followers = n
            # 兜底：href 没匹配到但文本里有「N 关注者/Followers」
            if followers is None:
                m2 = re.search(r"([\d,.]+\s*[万wWkK]?)\s*(关注者|Followers)", " ".join(
                    (st.get("text") or "") for st in (info.get("stats") or [])), re.I)
                if m2:
                    followers = _parse_count(m2.group(1))
            # 帖子数在滚动/切换视图后可能从 DOM 消失 → 解析失败时保留原值
            posts = _parse_count(info.get("posts") or "") or posts_initial
            result.update({
                "loggedIn": True,
                "nickname": info.get("name") or result["nickname"] or handle,
                "followers": followers,
                "following": following,
                "posts": posts,
                "handle": handle,
            })
            result["metrics"] = [
                {"label": "关注者", "value": followers},
                {"label": "正在关注", "value": following},
                {"label": "帖子数", "value": posts},
            ]
            result["overview"] = [
                {"key": "followers", "label": "关注者", "value": followers},
                {"key": "following", "label": "正在关注", "value": following},
            ]
            # 3) 推文级互动（滚动加载更多，最多 3 屏）
            tweets = []
            try:
                for _ in range(3):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(2500)
                raw = page.evaluate(TWEETS_JS) or []
                seen = set()
                for t in raw:
                    key = t.get("url") or t.get("text")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    tweets.append(t)
            except Exception:
                pass

            # 4) 推文聚合（账号级获赞用推文 likes 求和兜底）
            likes_total = sum((t.get("likes") or 0) for t in tweets) if tweets else None
            views_total = sum((t.get("views") or 0) for t in tweets) if tweets else None
            if likes_total is not None and result["likes"] is None:
                result["likes"] = likes_total
            if tweets:
                result["metrics"].extend([
                    {"label": "近期推文数", "value": len(tweets)},
                    {"label": "推文总获赞", "value": likes_total},
                    {"label": "推文总查看", "value": views_total},
                ])
            result["tweets"] = tweets
            result["notes"] = [
                {"title": t["text"] or "(无文本)",
                 "url": t["url"],
                 "stat": f"赞 {t.get('likes') or 0} · 转 {t.get('retweets') or 0} · 评 {t.get('replies') or 0}"
                         + (f" · 看 {t.get('views')}" if t.get("views") else ""),
                 "cover": ""}
                for t in tweets[:6]
            ]
            result["metrics_title"] = "账号快照（X 网页；官方 API 免费层已取消）"
            return result
        except Exception as e:  # noqa: BLE001
            result["warning"] = f"X 数据读取失败：{str(e)[:120]}"
            return result
        finally:
            ctx.close()


def cmd_fetch(a) -> int:
    try:
        print(json.dumps(fetch(a.handle or ""), ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"platform": "twitter-x", "name": "推特 X", "loggedIn": False,
                          "error": str(e)[:200], "followers": None, "likes": None,
                          "posts": None, "metrics": [], "notes": [],
                          "overview": [], "growth": {}}, ensure_ascii=False))
        return 1


def cmd_selftest(_a) -> int:
    print("x_stats 自检（离线）...", file=sys.stderr)
    assert _parse_count("11 关注者") == 11
    assert _parse_count("1,234 正在关注") == 1234
    assert _parse_count("1.2万") == 12000
    assert _parse_count("3.4k") == 3400
    assert _parse_count("") is None
    assert _parse_count("37 帖子") == 37
    print("✅ x_stats 自检通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="推特 X 创作数据采集（DOM）")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("fetch", help="采集并输出 JSON")
    p.add_argument("--handle", help="X 用户名（不带 @，默认自动探测）")
    p.set_defaults(func=cmd_fetch)
    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
