#!/usr/bin/env python3
"""zhihu_comments_fetch.py — 用已登录的知乎 Profile 抓文章评论。

用法：
  python skills/shared/scripts/zhihu_comments_fetch.py <article_id>

依赖：playwright + chromium（与 web_publisher 共用 ZhihuProfile）。
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = Path.home() / ".easel-browser-profiles" / "ZhihuProfile"

def fetch_comments(article_url: str, limit: int = 100):
    """通过访问文章页并拦截评论 API 响应来获取评论。"""
    from playwright.sync_api import sync_playwright

    captured = []

    def on_response(resp):
        url = resp.url
        if "comments" in url and "api/v4" in url:
            try:
                body = resp.json()
                for c in body.get("data", []):
                    author = c.get("author", {})
                    captured.append({
                        "id": c.get("id"),
                        "author": author.get("name", ""),
                        "content": c.get("content", ""),
                        "vote_count": c.get("vote_count", 0),
                        "created_time": c.get("created_time", 0),
                        "reply_to": (c.get("reply_to_author") or {}).get("name", ""),
                    })
                print(f"[INFO] 拦截到评论接口，共 {len(body.get('data', []))} 条，URL: {url[:100]}", file=sys.stderr)
            except Exception as e:
                print(f"[WARN] 解析响应失败: {e}", file=sys.stderr)

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        page = browser.new_page()
        page.on("response", on_response)

        print(f"[INFO] 访问文章: {article_url}", file=sys.stderr)
        page.goto(article_url, timeout=40000, wait_until="networkidle")
        time.sleep(3)

        # 滚动页面触发懒加载评论
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(2)

        # 如果评论数不够，尝试点击「加载更多」
        try:
            more = page.locator("text=查看全部评论").or_(page.locator("text=加载更多"))
            if more.count() > 0:
                more.first.click(timeout=5000)
                time.sleep(2)
        except Exception:
            pass

        # 最后 dump 页面里能看到的评论文字作为备用
        if not captured:
            print("[WARN] 未拦截到评论 API，尝试从页面 DOM 提取", file=sys.stderr)
            texts = page.evaluate("""
            () => {
                const sel = [
                    '.CommentContent', '.comment-content', '[class*="CommentItem"] p',
                    '[data-za-detail-view-element_name="Comment"] p',
                ];
                for (const s of sel) {
                    const els = document.querySelectorAll(s);
                    if (els.length > 0) return Array.from(els).map(e => e.innerText.trim());
                }
                return [];
            }
            """)
            for t in texts:
                if t:
                    captured.append({"id": None, "author": "", "content": t, "vote_count": 0, "created_time": 0, "reply_to": ""})

        browser.close()
    return captured


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("article_url", help="知乎文章完整 URL，如 https://zhuanlan.zhihu.com/p/<id>")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    comments = fetch_comments(args.article_url, args.limit)
    print(json.dumps(comments, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
