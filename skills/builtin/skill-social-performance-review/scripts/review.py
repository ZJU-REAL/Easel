#!/usr/bin/env python3
"""review.py — skill-social-performance-review 的确定性月度复盘计算.

把"逐帖评分 / 互动率 / Top-Bottom 排名 / 环比 / 加权内部评分"从 LLM
心算固化为代码。LLM 负责写洞察、原因诊断和下月建议。

子命令:
  score   读入标准化的月度帖子 JSON，输出逐帖互动率、Top/Bottom、
          支柱/格式聚合、环比、加权内部评分（1-10）

输入 JSON（--input）结构见 SKILL.md「确定性计算」节。缺字段自动降级，
不中断计算，并在 warnings 里说明。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

# 内部评分维度权重（与 SKILL.md / analysis-framework.md 一致）
SCORE_WEIGHTS = {
    "engagement_vs_benchmark": 0.25,
    "follower_growth": 0.20,
    "top_post": 0.20,
    "schedule_execution": 0.15,
    "reach_trend": 0.20,
}


def load_input(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"错误：未找到输入文件 {path}。请提供标准化的月度帖子 JSON。")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"错误：无法读取 {path}：{e}")


def _denominator(post):
    """互动率基数：优先 reach，其次 impressions，再 views。返回 (值, 名称)。"""
    for key in ("reach", "impressions", "views"):
        v = post.get(key)
        if v:
            return v, key
    return None, None


def _interactions(post):
    """互动总量 = likes + comments + saves + shares（缺失当 0，全缺返回 None）。"""
    parts = [post.get(k) for k in ("likes", "comments", "saves", "shares")]
    if all(p is None for p in parts):
        return None
    return sum(p or 0 for p in parts)


def score_posts(data):
    posts = data.get("posts", [])
    warnings = []
    if not posts:
        sys.exit("错误：输入中 posts 为空，无法复盘。")

    # 逐帖：互动率、互动综合分
    per_post = []
    for p in posts:
        inter = _interactions(p)
        denom, denom_name = _denominator(p)
        er = ss.engagement_rate(inter, denom, as_percent=True)
        row = {
            "title": p.get("title"), "date": p.get("date"),
            "type": p.get("type"), "pillar": p.get("pillar"),
            "reach": p.get("reach"), "impressions": p.get("impressions"),
            "views": p.get("views"),
            "likes": p.get("likes"), "comments": p.get("comments"),
            "saves": p.get("saves"), "shares": p.get("shares"),
            "interactions": inter,
            "engagement_rate_pct": er, "er_denominator": denom_name,
            "engagement_score": ss.engagement_score(
                views=p.get("views"), likes=p.get("likes"),
                comments=p.get("comments"), shares=p.get("shares")),
        }
        per_post.append(row)

    # 排名：小红书优先看收藏，否则看互动率
    platform = (data.get("platform") or "").lower()
    if platform in ("xiaohongshu", "小红书", "xhs"):
        rank_key, rank_name = (lambda r: r.get("saves") or -1), "saves"
    else:
        rank_key, rank_name = (lambda r: r.get("engagement_rate_pct") or -1), \
            "engagement_rate_pct"
    ranked = sorted(per_post, key=rank_key, reverse=True)
    top3 = ranked[:3]
    bottom3 = ranked[-3:][::-1] if len(ranked) > 3 else []

    # 账号快照聚合
    avg_er = ss.mean([r["engagement_rate_pct"] for r in per_post])
    total_reach = sum(ss.clean(r["reach"] for r in per_post)) or None
    snapshot = {
        "post_count": len(per_post),
        "avg_engagement_rate_pct": avg_er,
        "median_engagement_rate_pct": ss.median(
            [r["engagement_rate_pct"] for r in per_post]),
        "total_reach": total_reach,
        "total_interactions": sum(ss.clean(r["interactions"] for r in per_post)) or None,
        "followers": data.get("followers"),
    }

    # 支柱 / 格式聚合
    def agg_group(key):
        groups = {}
        for r in per_post:
            groups.setdefault(r.get(key) or "未分类", []).append(r)
        return {g: {"count": len(rs),
                    "avg_engagement_rate_pct": ss.mean(
                        [x["engagement_rate_pct"] for x in rs]),
                    "avg_reach": ss.mean([x["reach"] for x in rs]),
                    "avg_saves": ss.mean([x["saves"] for x in rs])}
                for g, rs in groups.items()}

    by_pillar = agg_group("pillar")
    by_format = agg_group("type")

    # 环比（vs previous）
    prev = data.get("previous") or {}
    mom = {
        "engagement_rate_pct_change": ss.pct_change(
            avg_er, prev.get("avg_engagement_rate_pct")),
        "reach_change_pct": ss.pct_change(total_reach, prev.get("reach")),
        "followers_change": data.get("followers_change"),
    }

    internal_score = _internal_score(data, per_post, top3, avg_er, mom, warnings)

    if len(per_post) < 5:
        warnings.append(ss.sample_warning(len(per_post), 5, "本月帖子"))
    warnings = [w for w in warnings if w]

    return {
        "month": data.get("month"), "platform": data.get("platform"),
        "rank_by": rank_name,
        "account_snapshot": snapshot,
        "per_post": per_post,
        "top3": top3, "bottom3": bottom3,
        "by_pillar": by_pillar, "by_format": by_format,
        "month_over_month": mom,
        "internal_score": internal_score,
        "warnings": warnings,
    }


def _internal_score(data, per_post, top3, avg_er, mom, warnings):
    """加权内部评分 1-10。缺失维度剔除并重新归一化。"""
    comps = {}

    # 互动率 vs 基准：avg_er / benchmark_avg 映射到 0-10（达标=6）
    bench = (data.get("benchmark") or {}).get("engagement_rate_avg")
    if avg_er is not None and bench:
        ratio = avg_er / (bench * 100 if bench < 1 else bench)
        comps["engagement_vs_benchmark"] = ss.scale_to_range(ratio, 0.5, 1.5, 0, 10)
    else:
        warnings.append("内部评分：缺基准或互动率，跳过'互动率vs基准'维度")

    # 粉丝增长趋势：followers_change 相对基数映射
    fc = data.get("followers_change")
    followers = data.get("followers")
    if fc is not None and followers:
        growth_pct = ss.pct_change(followers, followers - fc)  # 近似月增长率%
        comps["follower_growth"] = ss.scale_to_range(growth_pct, -2, 5, 0, 10)
    elif fc is not None:
        comps["follower_growth"] = 6.0 if fc > 0 else (3.0 if fc == 0 else 1.0)

    # 最佳帖子表现：Top1 互动率相对全月均值
    if top3 and avg_er:
        t1 = top3[0].get("engagement_rate_pct")
        if t1 is not None:
            comps["top_post"] = ss.scale_to_range(
                ss.safe_div(t1, avg_er), 1.0, 3.0, 5, 10)

    # 排期执行率：实际 / 计划
    plan = (data.get("plan") or {}).get("planned_posts")
    if plan:
        rate = ss.safe_div(len(per_post), plan)
        comps["schedule_execution"] = ss.scale_to_range(rate, 0.5, 1.0, 0, 10)

    # 触达趋势：环比方向
    rc = mom.get("reach_change_pct")
    if rc is not None:
        comps["reach_trend"] = ss.scale_to_range(rc, -20, 20, 0, 10)

    score = ss.weighted_score(comps, SCORE_WEIGHTS)
    return {
        "score_1to10": round(score, 1) if score is not None else None,
        "components": comps,
        "dimensions_used": list(comps.keys()),
        "note": "缺数据的维度已剔除并重新归一化权重",
    }


def cmd_score(args):
    data = load_input(Path(args.input))
    print(json.dumps(score_posts(data), ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description="月度社媒复盘的确定性计算")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="逐帖评分+互动率+环比+加权内部评分")
    s.add_argument("--input", required=True, help="标准化月度帖子 JSON 路径")
    s.set_defaults(func=cmd_score)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
