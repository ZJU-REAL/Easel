#!/usr/bin/env python3
"""social_stats — Easel 归因层公共计算模块.

纯函数集合，供各归因层 SKILL 的脚本 import，把 LLM 心算/手改 JSON 的
不可靠环节固化为确定性代码。只用标准库，保证可移植。

约定：
- 所有除法用 safe_div，除 0 返回 None（而不是抛异常或返回 0）。
- None 代表"数据缺失"，聚合时被排除，并在覆盖率里体现。
- 函数不做 I/O、不打印、无副作用，方便测试与复用。
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional, Sequence, Any


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def safe_div(numerator: Optional[float], denominator: Optional[float],
             default: Optional[float] = None) -> Optional[float]:
    """安全除法：分母为 0 / None，或分子为 None 时返回 default（默认 None）。"""
    if numerator is None or denominator is None:
        return default
    if denominator == 0:
        return default
    return numerator / denominator


def clean(values: Iterable[Optional[float]]) -> list:
    """去掉 None，返回可参与计算的数值列表。"""
    return [v for v in values if v is not None]


def mean(values: Iterable[Optional[float]]) -> Optional[float]:
    """算术平均，忽略 None。空列表返回 None。"""
    xs = clean(values)
    return safe_div(sum(xs), len(xs))


def median(values: Iterable[Optional[float]]) -> Optional[float]:
    """中位数，忽略 None。空列表返回 None。"""
    xs = sorted(clean(values))
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return float(xs[mid])
    return (xs[mid - 1] + xs[mid]) / 2.0


def coverage(values: Sequence[Optional[float]]) -> Optional[float]:
    """非 None 比例（0~1），衡量某指标的数据覆盖率。空序列返回 None。"""
    if not values:
        return None
    return safe_div(len(clean(values)), len(values))


# --------------------------------------------------------------------------- #
# 互动指标
# --------------------------------------------------------------------------- #
def engagement_rate(interactions: Optional[float], denominator: Optional[float],
                    as_percent: bool = False) -> Optional[float]:
    """互动率 = 互动总量 / 基数（reach / impressions / views）.

    as_percent=True 时返回百分数（乘 100）。基数为 0/None 返回 None。
    """
    r = safe_div(interactions, denominator)
    if r is None:
        return None
    return r * 100 if as_percent else r


def engagement_score(views: Optional[float] = 0, likes: Optional[float] = 0,
                     comments: Optional[float] = 0, shares: Optional[float] = 0,
                     weights: Optional[dict] = None) -> float:
    """互动综合分。默认权重 views×0.1 + likes×1 + comments×2 + shares×3。

    None 视为 0（缺失即不贡献分数）。可通过 weights 覆盖默认权重。
    """
    w = {"views": 0.1, "likes": 1.0, "comments": 2.0, "shares": 3.0}
    if weights:
        w.update(weights)
    vals = {"views": views, "likes": likes, "comments": comments, "shares": shares}
    return sum(w[k] * (vals[k] or 0) for k in w)


# --------------------------------------------------------------------------- #
# 变化率：环比 / 同比 / 日增长
# --------------------------------------------------------------------------- #
def pct_change(current: Optional[float], previous: Optional[float],
               as_percent: bool = True) -> Optional[float]:
    """环比/同比变化率 = (current - previous) / previous.

    previous 为 0/None 或 current 为 None 时返回 None。
    as_percent=True（默认）返回百分数。
    """
    if current is None or previous is None or previous == 0:
        return None
    r = (current - previous) / previous
    return r * 100 if as_percent else r


def delta(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """绝对变化量 = current - previous。任一为 None 返回 None。"""
    if current is None or previous is None:
        return None
    return current - previous


def daily_growth(series: Sequence[Optional[float]]) -> list:
    """相邻两点的绝对增量列表。返回长度为 len(series)-1。

    任一端点为 None 的间隔返回 None。
    """
    out = []
    for i in range(1, len(series)):
        out.append(delta(series[i], series[i - 1]))
    return out


def daily_growth_rate(series: Sequence[Optional[float]], as_percent: bool = True) -> list:
    """相邻两点的增长率列表 = (v_i - v_{i-1}) / v_{i-1}。长度 len(series)-1。"""
    out = []
    for i in range(1, len(series)):
        out.append(pct_change(series[i], series[i - 1], as_percent=as_percent))
    return out


# --------------------------------------------------------------------------- #
# 移动平均 / 外推
# --------------------------------------------------------------------------- #
def moving_average(series: Sequence[Optional[float]], window: int) -> list:
    """简单移动平均。窗口内忽略 None；窗口全 None 时该点为 None。

    返回与输入等长的列表，前 window-1 个点用可用数据的部分窗口计算。
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    out = []
    for i in range(len(series)):
        start = max(0, i - window + 1)
        out.append(mean(series[start:i + 1]))
    return out


def milestone_eta(current: float, rate_per_day: Optional[float],
                  milestone: float, max_days: Optional[int] = None) -> Optional[int]:
    """按日增速外推到达里程碑所需天数（向上取整）。

    rate_per_day <= 0 / None 返回 None（无法到达）。
    已达标返回 0。超过 max_days 返回 None（预测不外推太远，避免误导）。
    """
    if current >= milestone:
        return 0
    if rate_per_day is None or rate_per_day <= 0:
        return None
    import math
    days = math.ceil((milestone - current) / rate_per_day)
    if max_days is not None and days > max_days:
        return None
    return days


def next_milestone(current: float,
                   ladder: Sequence[float] = (1000, 5000, 10000, 50000, 100000,
                                              500000, 1000000)) -> Optional[float]:
    """返回 ladder 中第一个大于 current 的里程碑。都达到了返回 None。"""
    for m in ladder:
        if m > current:
            return m
    return None


# --------------------------------------------------------------------------- #
# 加权评分
# --------------------------------------------------------------------------- #
def weighted_score(components: dict, weights: dict,
                   skip_none: bool = True) -> Optional[float]:
    """加权评分。components/weights 用相同的键。

    skip_none=True 时，值为 None 的维度被剔除并对剩余权重重新归一化
    （体现"缺数据不废评分"）。全为 None 返回 None。
    """
    keys = [k for k in weights if k in components]
    if skip_none:
        keys = [k for k in keys if components[k] is not None]
    total_w = sum(weights[k] for k in keys)
    if total_w == 0:
        return None
    return sum(components[k] * weights[k] for k in keys) / total_w


def scale_to_range(value: Optional[float], lo: float, hi: float,
                   out_lo: float = 0.0, out_hi: float = 10.0,
                   clamp: bool = True) -> Optional[float]:
    """线性映射 value 从 [lo,hi] 到 [out_lo,out_hi]，用于把原始指标转成子评分。"""
    if value is None or hi == lo:
        return None
    r = (value - lo) / (hi - lo)
    if clamp:
        r = max(0.0, min(1.0, r))
    return out_lo + r * (out_hi - out_lo)


# --------------------------------------------------------------------------- #
# 分组聚合
# --------------------------------------------------------------------------- #
def group_aggregate(records: Iterable[dict], key_fn: Callable[[dict], Any],
                    value_fn: Callable[[dict], Optional[float]] = None,
                    agg: str = "count") -> dict:
    """按 key_fn 分组，对 value_fn 提取的值做聚合。

    agg: count / sum / mean / median / min / max。
    count 时忽略 value_fn。key_fn 返回 None 的记录被跳过。
    返回 {key: 聚合值}。
    """
    buckets: dict = {}
    for rec in records:
        k = key_fn(rec)
        if k is None:
            continue
        buckets.setdefault(k, []).append(rec)

    out = {}
    for k, recs in buckets.items():
        if agg == "count":
            out[k] = len(recs)
            continue
        vals = clean(value_fn(r) for r in recs)
        if agg == "sum":
            out[k] = sum(vals) if vals else None
        elif agg == "mean":
            out[k] = mean(vals)
        elif agg == "median":
            out[k] = median(vals)
        elif agg == "min":
            out[k] = min(vals) if vals else None
        elif agg == "max":
            out[k] = max(vals) if vals else None
        else:
            raise ValueError(f"unknown agg: {agg}")
    return out


def cooccurrence(item_lists: Iterable[Sequence[Any]], min_count: int = 1) -> dict:
    """共现矩阵：统计成对元素在同一列表中同时出现的次数。

    返回 {(a, b): count}，a < b（字符串序），只保留 >= min_count 的对。
    """
    from itertools import combinations
    counts: dict = {}
    for items in item_lists:
        uniq = sorted(set(items), key=str)
        for a, b in combinations(uniq, 2):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return {k: v for k, v in counts.items() if v >= min_count}


# --------------------------------------------------------------------------- #
# 样本量警告
# --------------------------------------------------------------------------- #
def sample_warning(n: int, min_n: int = 5, label: str = "样本") -> Optional[str]:
    """样本量不足时返回中文警告字符串，充足返回 None。"""
    if n < min_n:
        return f"⚠ {label}不足（{n} < {min_n}），结果可能不具统计意义"
    return None


# --------------------------------------------------------------------------- #
# 自测
# --------------------------------------------------------------------------- #
def _selftest():
    assert safe_div(10, 2) == 5
    assert safe_div(1, 0) is None
    assert safe_div(1, 0, default=0) == 0
    assert safe_div(None, 2) is None
    assert mean([1, 2, 3, None]) == 2
    assert mean([]) is None
    assert median([1, 2, 3]) == 2
    assert median([1, 2, 3, 4]) == 2.5
    assert coverage([1, None, 3, None]) == 0.5

    assert engagement_rate(50, 1000, as_percent=True) == 5.0
    assert engagement_rate(1, 0) is None
    assert engagement_score(views=100, likes=10, comments=5, shares=2) == \
        100 * 0.1 + 10 + 5 * 2 + 2 * 3

    assert pct_change(120, 100) == 20.0
    assert pct_change(80, 100) == -20.0
    assert pct_change(1, 0) is None
    assert delta(10, 4) == 6

    assert daily_growth([100, 110, 130]) == [10, 20]
    assert daily_growth_rate([100, 110]) == [10.0]

    ma = moving_average([1, 2, 3, 4, 5], 3)
    assert ma[-1] == 4.0 and ma[0] == 1.0

    assert milestone_eta(900, 20, 1000) == 5
    assert milestone_eta(900, 20, 1000, max_days=3) is None
    assert milestone_eta(1000, 20, 1000) == 0
    assert milestone_eta(900, 0, 1000) is None
    assert next_milestone(1200) == 5000
    assert next_milestone(2_000_000) is None

    ws = weighted_score({"a": 8, "b": 6, "c": None}, {"a": 0.5, "b": 0.3, "c": 0.2})
    # c 被剔除，权重归一化到 a=0.5/0.8, b=0.3/0.8
    assert abs(ws - (8 * 0.5 + 6 * 0.3) / 0.8) < 1e-9
    assert scale_to_range(5, 0, 10) == 5.0
    assert scale_to_range(20, 0, 10) == 10.0  # clamp

    recs = [
        {"p": "xhs", "likes": 10},
        {"p": "xhs", "likes": 30},
        {"p": "dy", "likes": None},
    ]
    assert group_aggregate(recs, lambda r: r["p"]) == {"xhs": 2, "dy": 1}
    assert group_aggregate(recs, lambda r: r["p"],
                           lambda r: r["likes"], "mean") == {"xhs": 20.0, "dy": None}

    co = cooccurrence([["a", "b", "c"], ["a", "b"]], min_count=2)
    assert co == {("a", "b"): 2}

    assert sample_warning(3, 5) is not None
    assert sample_warning(5, 5) is None

    print("social_stats: all selftests passed")


if __name__ == "__main__":
    _selftest()
