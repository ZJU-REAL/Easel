#!/usr/bin/env python3
"""aggregate.py — skill-content-postmortem 模式 B 的确定性聚合统计.

把"阈值划分 top20% / 爆款组 vs 普通组分组对比 / 多维交叉"从 LLM 心算
固化为代码。LLM 只负责读结果、提炼爆款公式、写避坑清单和行动建议。

模式 A（单条定性拆解）不用本脚本。

输入 JSON（--input）：内容记录数组，每条形如
  {"title": "...", "platform": "小红书",
   "likes": 1200, "collects": 800, "comments": 90, "shares": 30, "views": 50000,
   "hook_type": "反常识", "topic": "职场", "structure": "总分总",
   "length_bucket": "中", "time_bucket": "晚间", "tags": ["干货","职场"], ...}

数值字段用于算互动分与排名；其余字符串/列表字段作为"维度"做分组对比。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

# 参与互动综合分的数值字段
METRIC_KEYS = ("views", "likes", "comments", "shares", "collects")
# 不当作"维度"的字段（数值指标 + 标题）
NON_DIM = set(METRIC_KEYS) | {"title", "url", "link", "date",
                              "published_at", "id", "_score", "_is_top"}


def load_items(path: Path) -> list:
    if not path.exists():
        sys.exit(f"错误：未找到输入文件 {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"错误：无法解析 {path}：{e}")
    if isinstance(data, dict):
        data = data.get("items") or data.get("contents") or []
    if not isinstance(data, list):
        sys.exit("错误：输入应为内容记录数组")
    return data


def item_score(item: dict, metric: str) -> float:
    """排名用分值：指定 metric 取该字段；否则用互动综合分（含 collects×2）。"""
    if metric and metric != "engagement_score":
        return item.get(metric)
    base = ss.engagement_score(
        views=item.get("views"), likes=item.get("likes"),
        comments=item.get("comments"), shares=item.get("shares"))
    return base + (item.get("collects") or 0) * 2.0


def detect_dims(items: list) -> list:
    """自动识别维度字段：出现过的、非数值指标的 str/list 字段。"""
    dims = []
    seen = set()
    for it in items:
        for k, v in it.items():
            if k in NON_DIM or k in seen:
                continue
            if isinstance(v, (str, list)):
                dims.append(k)
                seen.add(k)
    return dims


def _values(item, dim):
    """取某维度的值列表（list 字段展开，标量包成单元素，None 跳过）。"""
    v = item.get(dim)
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


def analyze_dim(items, dim, top_ids):
    """对单个维度：按取值分组，统计总数/爆款数/爆款率/平均分/lift。"""
    global_avg = ss.mean([it["_score"] for it in items])
    buckets = {}
    for it in items:
        for val in _values(it, dim):
            buckets.setdefault(val, []).append(it)

    rows = []
    for val, its in buckets.items():
        top_n = sum(1 for it in its if id(it) in top_ids)
        avg = ss.mean([it["_score"] for it in its])
        rows.append({
            "value": val,
            "count": len(its),
            "top_count": top_n,
            "top_rate_pct": ss.engagement_rate(top_n, len(its), as_percent=True),
            "avg_score": avg,
            "lift_vs_global": ss.pct_change(avg, global_avg),
            "warning": ss.sample_warning(len(its), 3, f"'{val}'样本"),
        })
    rows.sort(key=lambda r: r["avg_score"] or -1, reverse=True)
    return rows


def cross_analyze(items, dim_a, dim_b, top_ids):
    """两维交叉：(a×b) 组合的爆款命中，按爆款率降序。"""
    combos = {}
    for it in items:
        for va in _values(it, dim_a):
            for vb in _values(it, dim_b):
                combos.setdefault(f"{va} × {vb}", []).append(it)
    rows = []
    for key, its in combos.items():
        top_n = sum(1 for it in its if id(it) in top_ids)
        rows.append({
            "combo": key, "count": len(its), "top_count": top_n,
            "top_rate_pct": ss.engagement_rate(top_n, len(its), as_percent=True),
            "avg_score": ss.mean([it["_score"] for it in its]),
        })
    rows.sort(key=lambda r: (r["top_rate_pct"] or -1, r["count"]), reverse=True)
    return rows


def run(args):
    items = load_items(Path(args.input))
    if not items:
        sys.exit("错误：输入内容为空，无法提炼规律")
    if len(items) < 5:
        # 模式 B 要求 ≥5 条，仍继续但强提示
        pass

    metric = args.metric
    for it in items:
        it["_score"] = item_score(it, metric)

    scored = [it for it in items if it["_score"] is not None]
    if not scored:
        sys.exit(f"错误：无有效分值（metric='{metric or 'engagement_score'}'），无法排名")

    ranked = sorted(scored, key=lambda it: it["_score"], reverse=True)

    # 阈值：优先绝对阈值，否则 top N%
    if args.threshold is not None:
        threshold = args.threshold
        top_items = [it for it in ranked if it["_score"] >= threshold]
    else:
        top_n = max(1, round(len(ranked) * args.top_pct / 100.0))
        top_items = ranked[:top_n]
        threshold = top_items[-1]["_score"] if top_items else None
    top_ids = {id(it) for it in top_items}

    dims = ([d.strip() for d in args.dims.split(",") if d.strip()]
            if args.dims else detect_dims(items))

    by_dim = {d: analyze_dim(scored, d, top_ids) for d in dims}

    cross = None
    if args.cross:
        parts = [p.strip() for p in args.cross.split(",")]
        if len(parts) == 2:
            cross = {"dims": parts,
                     "combos": cross_analyze(scored, parts[0], parts[1], top_ids)}

    # tags 共现（若存在 tags 列表字段）
    tag_lists = [it.get("tags", []) for it in scored if isinstance(it.get("tags"), list)]
    co = ss.cooccurrence(tag_lists, min_count=2) if tag_lists else {}
    cooccurrence = [{"tags": list(k), "count": v}
                    for k, v in sorted(co.items(), key=lambda x: x[1], reverse=True)]

    result = {
        "summary": {
            "total": len(items),
            "scored": len(scored),
            "metric": metric or "engagement_score",
            "top_pct": None if args.threshold is not None else args.top_pct,
            "threshold_score": threshold,
            "top_count": len(top_items),
            "top_rate_pct": ss.engagement_rate(len(top_items), len(scored),
                                               as_percent=True),
            "avg_score_all": ss.mean([it["_score"] for it in scored]),
            "avg_score_top": ss.mean([it["_score"] for it in top_items]),
            "median_score": ss.median([it["_score"] for it in scored]),
            "dimensions": dims,
            "warning": ss.sample_warning(len(scored), 5, "内容记录（模式B）"),
        },
        "top_posts": [{"title": it.get("title"), "score": it["_score"]}
                      for it in top_items],
        "by_dimension": by_dim,
        "cross": cross,
        "tag_cooccurrence": cooccurrence,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(
        description="内容复盘模式 B 聚合统计（阈值划分/分组对比/多维交叉）")
    p.add_argument("--input", required=True, help="内容记录 JSON（数组）")
    p.add_argument("--metric", help="排名字段，默认互动综合分 engagement_score")
    p.add_argument("--top-pct", dest="top_pct", type=float, default=20.0,
                   help="爆款阈值百分位，默认 top 20%%")
    p.add_argument("--threshold", type=float,
                   help="绝对阈值（覆盖 --top-pct），如收藏>500")
    p.add_argument("--dims", help="逗号分隔的维度字段名，默认自动识别")
    p.add_argument("--cross", help="两维交叉，如 'hook_type,topic'")
    p.add_argument("--json", action="store_true", help="以 JSON 输出（默认）")
    p.set_defaults(func=run)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
