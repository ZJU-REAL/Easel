#!/usr/bin/env python3
"""calc.py — roi-calculator 的确定性 ROI 计算.

把"逐项计算 11 个营销指标 / 派生营收利润 / 多活动按 ROI 降序"从 LLM
心算固化为代码。LLM 只负责读基准（references/benchmarks.md）、解读结果、
写诊断与预算建议。

11 个指标：CTR / CPC / CPM / CPE / 转化率 / CPA / 营收 / ROAS /
           总成本 / 利润 / ROI

子命令:
  single   Mode A — 单活动分析（通过命令行 flag 传入各字段）
  multi    Mode B — 多活动对比（读 JSON 文件，按 ROI 降序排序）

有机模式：ad_spend 为 0 或缺失时自动切换，仅算 CTR + 互动率，跳过成本类指标。

输入字段（任意子集，缺失字段跳过其依赖指标）:
  ad_spend / impressions / clicks / engagements /
  conversions / avg_order_value / production_cost
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

FIELDS = ("ad_spend", "impressions", "clicks", "engagements",
          "conversions", "avg_order_value", "production_cost")


def _scale(value, factor):
    """把 safe_div 的结果按 factor 缩放；None 透传（缺数据不参与）。"""
    return None if value is None else value * factor


def _mul(a, b):
    """两数相乘；任一为 None 返回 None。"""
    return None if (a is None or b is None) else a * b


def _is_organic(c) -> bool:
    """ad_spend 为 0 / None 时视为有机内容模式。"""
    return not c.get("ad_spend")


def validate(c) -> list:
    """字段合理性校验，返回中文警告列表（不中断计算）。"""
    warns = []
    for k in FIELDS:
        v = c.get(k)
        if v is not None and v < 0:
            warns.append(f"⚠ {k} 为负值（{v}），指标可能失真")
    imp, clk, conv = c.get("impressions"), c.get("clicks"), c.get("conversions")
    if imp is not None and clk is not None and clk > imp:
        warns.append(f"⚠ 点击量({clk}) > 曝光量({imp})，数据异常")
    if clk is not None and conv is not None and conv > clk:
        warns.append(f"⚠ 转化数({conv}) > 点击量({clk})，数据异常")
    return warns


def compute(c: dict) -> dict:
    """计算单个活动的全部指标。缺分母的指标返回 None（标注"数据不足"）。"""
    spend = c.get("ad_spend")
    imp = c.get("impressions")
    clk = c.get("clicks")
    eng = c.get("engagements")
    conv = c.get("conversions")
    aov = c.get("avg_order_value")
    prod = c.get("production_cost") or 0

    organic = _is_organic(c)

    # 营收：转化数 × 客单价
    revenue = _mul(conv, aov)
    # 总成本：ad_spend + production_cost（有机模式下 ad_spend 视为 0）
    total_cost = (spend or 0) + prod
    total_cost = total_cost if total_cost > 0 else None
    profit = None if revenue is None else revenue - (total_cost or 0)

    metrics = {
        # 通用（付费/有机都算）
        "ctr_pct": _scale(ss.safe_div(clk, imp), 100),
        "engagement_rate_pct": ss.engagement_rate(eng, imp, as_percent=True),
        "conversion_rate_pct": _scale(ss.safe_div(conv, clk), 100),
    }

    if not organic:
        metrics.update({
            "cpc": ss.safe_div(spend, clk),
            "cpm": _scale(ss.safe_div(spend, imp), 1000),
            "cpe": ss.safe_div(spend, eng),
            "cpa": ss.safe_div(spend, conv),
            "revenue": revenue,
            "roas": ss.safe_div(revenue, spend),
            "total_cost": total_cost,
            "profit": profit,
            "roi_pct": _scale(ss.safe_div(profit, total_cost), 100),
        })
    else:
        # 有机模式：跳过全部成本类指标
        for k in ("cpc", "cpm", "cpe", "cpa", "revenue", "roas",
                  "total_cost", "profit", "roi_pct"):
            metrics[k] = None

    return {
        "name": c.get("name"),
        "mode": "organic" if organic else "paid",
        "inputs": {k: c.get(k) for k in FIELDS if c.get(k) is not None},
        "metrics": metrics,
        "warnings": validate(c),
    }


def cmd_single(args) -> None:
    c = {k: getattr(args, k) for k in FIELDS}
    c["name"] = args.name
    result = compute(c)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _load_campaigns(path: Path) -> list:
    if not path.exists():
        sys.exit(f"错误：未找到活动数据文件 {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"错误：无法解析 {path}：{e}")
    if isinstance(data, dict):
        data = data.get("campaigns", [])
    if not isinstance(data, list) or not data:
        sys.exit("错误：活动数据应为非空数组（或 {\"campaigns\": [...]}）")
    return data


def cmd_multi(args) -> None:
    campaigns = _load_campaigns(Path(args.file))
    results = []
    for i, c in enumerate(campaigns):
        c.setdefault("name", f"活动{i + 1}")
        results.append(compute(c))

    # 按 ROI 降序（None 排最后，保持稳定）
    def roi_key(r):
        v = r["metrics"].get("roi_pct")
        return (v is None, -(v if v is not None else 0))

    ranked = sorted(results, key=roi_key)
    for rank, r in enumerate(ranked, 1):
        r["roi_rank"] = rank

    roi_vals = ss.clean(r["metrics"].get("roi_pct") for r in ranked)
    summary = {
        "campaign_count": len(ranked),
        "avg_roi_pct": ss.mean(roi_vals),
        "best": ranked[0]["name"] if ranked else None,
        "worst": ranked[-1]["name"] if ranked and roi_vals else None,
        "warning": ss.sample_warning(len(ranked), 2, "对比活动"),
    }
    print(json.dumps({"summary": summary, "ranking": ranked},
                     ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(
        description="内容投放 ROI 确定性计算（11 指标 + 多活动排序）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("single", help="Mode A 单活动分析")
    s.add_argument("--name", help="活动名称")
    s.add_argument("--ad-spend", dest="ad_spend", type=float,
                   help="投放费用 CNY（0/缺失切有机模式）")
    s.add_argument("--impressions", type=float, help="曝光量")
    s.add_argument("--clicks", type=float, help="点击量")
    s.add_argument("--engagements", type=float, help="互动量（赞+评+转）")
    s.add_argument("--conversions", type=float, help="转化数")
    s.add_argument("--avg-order-value", dest="avg_order_value", type=float,
                   help="客单价 CNY")
    s.add_argument("--production-cost", dest="production_cost", type=float,
                   help="内容制作成本 CNY")
    s.add_argument("--json", action="store_true", help="以 JSON 输出（默认）")
    s.set_defaults(func=cmd_single)

    m = sub.add_parser("multi", help="Mode B 多活动对比（按 ROI 降序）")
    m.add_argument("--file", required=True,
                   help="活动数据 JSON（数组或 {campaigns:[...]}）")
    m.add_argument("--json", action="store_true", help="以 JSON 输出（默认）")
    m.set_defaults(func=cmd_multi)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
