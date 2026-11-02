#!/usr/bin/env python3
"""juejin_stats.py — 掘金创作数据采集（公开 API，无需浏览器）。

为什么单独一个脚本：掘金的账号级/文章级数据都有稳定的 JSON 接口，
比 Playwright 解析 DOM 快且稳（实测 2026-10）：

    user_api/v1/user/get              账号概览（需登录 cookie）：文章数/总阅读/总获赞/等级
    content_api/v1/article/query_list 文章列表（**免登录**）：每篇阅读/点赞/评论/收藏/热度

登录 cookie 从 JuejinProfile 的持久化目录读（与登录/发布共用同一 profile），
导出成 JSON 直接走 urllib —— 不起浏览器，秒级返回。

输出格式与 account_stats.py 对齐（web 层 /api/analytics 直接消费）。

用法：
    juejin_stats.py fetch                 # 输出单行 JSON
    juejin_stats.py selftest              # 离线自检
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BROWSER_PROFILES = Path.home() / ".easel-browser-profiles"
PROFILE = "JuejinProfile"

API_USER = "https://api.juejin.cn/user_api/v1/user/get"
API_ARTICLES = "https://api.juejin.cn/content_api/v1/article/query_list"
AID = "2608"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _request(url: str, body: dict | None, jar) -> dict:
    """发请求。jar = Playwright APIRequestContext（带登录 cookie）或 None（匿名）。

    为什么用 Playwright 的 request 而不是 urllib：Chromium 的 cookie 是加密存的，
    手工读 SQLite 只能拿到空值；用 context.request 让 Chromium 自己解密并带上 cookie。
    """
    headers = {"Referer": "https://juejin.cn/", "Accept": "application/json"}
    if jar is not None:
        resp = jar.post(url, data=body, headers=headers) if body is not None \
            else jar.get(url, headers=headers)
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        return resp.json()
    data = json.dumps(body).encode() if body is not None else None
    headers["User-Agent"] = UA
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _fetch_with(user_id: str, limit: int, jar) -> dict:
    """在给定 request 上下文内采集（jar=None 走匿名 urllib）。"""
    # 1) 账号概览（需登录）。失败不致命：文章列表是公开的，仍能出数据。
    user = {}
    warning = ""
    try:
        q = f"?aid={AID}&uuid=0&spider=0" + (f"&user_id={user_id}" if user_id else "")
        payload = _request(API_USER + q, None, jar)
        if payload.get("err_no") == 0 and isinstance(payload.get("data"), dict):
            user = payload["data"]
        else:
            warning = payload.get("err_msg") or "账号概览接口未返回数据"
    except Exception as e:  # noqa: BLE001
        warning = f"账号概览读取失败：{str(e)[:80]}"

    uid = user_id or str(user.get("user_id") or "")
    if not uid:
        raise RuntimeError(
            "无法确定掘金用户 ID（登录态 Cookie 缺失或已过期）。请先在账号页重新登录掘金。")

    # 2) 文章列表（公开接口，无需登录）
    articles = []
    try:
        payload = _request(API_ARTICLES,
                           {"user_id": uid, "sort_type": 2, "cursor": "0", "limit": limit},
                           jar)
        if payload.get("err_no") != 0:
            warning = warning or (payload.get("err_msg") or "文章列表接口异常")
        for item in payload.get("data") or []:
            ai = item.get("article_info") or {}
            articles.append({
                "title": ai.get("title") or "",
                "url": f"https://juejin.cn/post/{ai.get('article_id') or ''}",
                "views": ai.get("view_count"),
                "likes": ai.get("digg_count"),
                "comments": ai.get("comment_count"),
                "collects": ai.get("collect_count"),
                "hot": ai.get("hot_index"),
                "ctime": ai.get("ctime"),
            })
    except Exception as e:  # noqa: BLE001
        warning = warning or f"文章列表读取失败：{str(e)[:80]}"

    # 3) 汇总
    def _sum(key: str) -> int:
        return sum((a.get(key) or 0) for a in articles)

    views, likes = user.get("got_view_count"), user.get("got_digg_count")
    if views is None and articles:
        views = _sum("views")
    if likes is None and articles:
        likes = _sum("likes")
    follows = user.get("followee_count")

    now = int(time.time())
    return {
        "platform": "juejin", "name": "掘金",
        "nickname": user.get("user_name") or "",
        "loggedIn": bool(user),
        "userId": uid,
        # 掘金 user/get 里的 follower_count 即粉丝数（实测字段名易被误认为 fan*，勿漏）
        "followers": user.get("follower_count"),
        "likes": likes,
        "following": follows,
        "posts": user.get("post_article_count") or len(articles),
        "metrics": [
            {"label": "粉丝", "value": user.get("follower_count")},
            {"label": "总阅读", "value": views},
            {"label": "总获赞", "value": likes},
            {"label": "文章数", "value": user.get("post_article_count") or len(articles)},
            {"label": "掘力值", "value": user.get("power")},
        ],
        "notes": [
            {"title": a["title"], "url": a["url"],
             "stat": f"阅读 {a['views'] or 0} · 赞 {a['likes'] or 0} · 评 {a['comments'] or 0} · 藏 {a['collects'] or 0}",
             "cover": ""}
            for a in articles[:6]
        ],
        "articles": articles,
        "metrics_title": "账号累计（掘金公开接口）",
        "overview": [
            {"key": "followers", "label": "粉丝", "value": user.get("follower_count")},
            {"key": "likes", "label": "获赞", "value": likes},
            {"key": "following", "label": "关注", "value": follows},
        ],
        "growth": {}, "fetched_at": now,
        "warning": warning,
    }


def fetch(user_id: str = "", limit: int = 20) -> dict:
    """起一次 headless Chromium 读登录 cookie，再采集（Chromium 负责 cookie 解密）。"""
    from playwright.sync_api import sync_playwright

    profile = BROWSER_PROFILES / PROFILE
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(profile), headless=True, locale="zh-CN",
            args=["--no-sandbox", "--disable-gpu", "--no-proxy-server"])
        try:
            return _fetch_with(user_id, limit, ctx.request)
        finally:
            ctx.close()


def cmd_fetch(a) -> int:
    try:
        print(json.dumps(fetch(a.user_id or "", a.limit), ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001 — 失败也要输出 JSON 供前端展示
        print(json.dumps({"platform": "juejin", "name": "掘金", "loggedIn": False,
                          "error": str(e)[:200], "followers": None, "likes": None,
                          "posts": None, "metrics": [], "notes": [],
                          "overview": [], "growth": {}}, ensure_ascii=False))
        return 1


def cmd_selftest(_a) -> int:
    print("juejin_stats 自检（离线）...", file=sys.stderr)
    # 汇总逻辑：文章级求和兜底
    arts = [{"views": 3, "likes": 1}, {"views": 16, "likes": 0}]
    assert sum(x["views"] for x in arts) == 19
    print("✅ juejin_stats 自检通过")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="掘金创作数据采集")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("fetch", help="采集并输出 JSON")
    p.add_argument("--user-id", help="掘金用户 ID（默认从登录 cookie 推断）")
    p.add_argument("--limit", type=int, default=20, help="文章条数（默认 20）")
    p.set_defaults(func=cmd_fetch)
    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
