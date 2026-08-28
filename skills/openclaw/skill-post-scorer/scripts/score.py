#!/usr/bin/env python3
"""score.py — skill-post-scorer 的确定性历史数据分析.

把"互动分 = 点赞 + 评论×3 / 筛 Top 10%"从 LLM 心算固化为代码。
LLM 拿到 Top 10% 帖子及其分布后，负责提炼共性特征、给草稿五维评分。

子命令:
  top   读历史帖子 JSON，算每条互动分，输出 Top N%（默认 10%）门槛、
        Top 帖子列表与分布统计（均值/中位数/最高/最低）

输入 JSON（--input）：历史帖子数组，每条含点赞与评论字段，形如
  [{"title":"...", "likes":808, "comments":355}, ...]
兼容字段别名：likes/reactions/点赞、comments/评论。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

# 互动分权重：点赞×1 + 评论×3（评论代表深度互动，算法权重更高）
COMMENT_WEIGHT = 3.0


def load_posts(path: Path) -> list:
    if not path.exists():
        sys.exit(f"错误：未找到输入文件 {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"错误：无法解析 {path}：{e}")
    if isinstance(data, dict):
        data = data.get("posts") or data.get("items") or []
    if not isinstance(data, list) or not data:
        sys.exit("错误：输入应为非空历史帖子数组")
    return data


def _pick(post, *names):
    for n in names:
        if post.get(n) is not None:
            return post.get(n)
    return None


def engagement(post) -> float:
    """互动分 = 点赞 + 评论×3。缺失字段当 0。"""
    likes = _pick(post, "likes", "reactions", "点赞") or 0
    comments = _pick(post, "comments", "评论") or 0
    # 复用 social_stats.engagement_score，用权重实现 点赞×1 + 评论×3
    return ss.engagement_score(likes=likes, comments=comments,
                               weights={"comments": COMMENT_WEIGHT})


def cmd_top(args):
    posts = load_posts(Path(args.input))
    scored = []
    for p in posts:
        row = dict(p)
        row["engagement_score"] = engagement(p)
        scored.append(row)

    ranked = sorted(scored, key=lambda r: r["engagement_score"], reverse=True)
    n = len(ranked)
    top_n = max(1, round(n * args.top_pct / 100.0))
    top = ranked[:top_n]
    threshold = top[-1]["engagement_score"]

    scores = [r["engagement_score"] for r in ranked]
    result = {
        "summary": {
            "post_count": n,
            "top_pct": args.top_pct,
            "top_count": top_n,
            "top_threshold_score": threshold,
            "engagement_formula": "点赞 + 评论×3",
            "avg_score": ss.mean(scores),
            "median_score": ss.median(scores),
            "max_score": max(scores),
            "min_score": min(scores),
            "warning": ss.sample_warning(n, 10, "历史帖子"),
        },
        "top_posts": [
            {"title": r.get("title"),
             "likes": _pick(r, "likes", "reactions", "点赞"),
             "comments": _pick(r, "comments", "评论"),
             "engagement_score": r["engagement_score"]}
            for r in top
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(
        description="帖子历史数据确定性分析（互动分 + Top N%）")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("top", help="算互动分并筛 Top N%%")
    t.add_argument("--input", required=True, help="历史帖子 JSON（数组）")
    t.add_argument("--top-pct", dest="top_pct", type=float, default=10.0,
                   help="Top 百分位，默认 10%%")
    t.add_argument("--json", action="store_true", help="以 JSON 输出（默认）")
    t.set_defaults(func=cmd_top)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
