#!/usr/bin/env python3
"""track.py — skill-data-tracker 的确定性数据追踪.

把"读快照 / 算增长率 / 移动平均 / 里程碑外推 / 生命周期分类"从 LLM
心算固化为代码。LLM 只负责解读结果、写增长建议。

子命令:
  snapshot   记录当日账号指标快照（一天一快照，同日覆盖），并给出与上次的 delta
  trend      读历史快照，算日增长/日增长率/7日移动平均/里程碑外推
  lifecycle  跨快照追踪单条帖子，分类速爆型/稳增型/长尾型
  export-followers  从权威快照导出 publish-analytics 使用的 follower-log.json

快照路径: <项目根>/outputs/_analytics/snapshots/{profile}/{platform}/{date}.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SNAP_ROOT = PROJECT_ROOT / "outputs" / "_analytics" / "snapshots"
LEGACY_SNAP_ROOT = PROJECT_ROOT / "outputs" / "analytics" / "snapshots"


def _safe_segment(value: str, fallback: str) -> str:
    segment = re.sub(r"[\\/\x00]", "_", (value or fallback).strip())
    if segment in {"", ".", ".."}:
        return fallback
    return segment


def snap_dir(profile: str, platform: str | None = None, *, for_write: bool = False) -> Path:
    """Use the unified analytics root, with read-only fallback for legacy data."""
    name = _safe_segment(profile, "default")
    current = SNAP_ROOT / name
    legacy = LEGACY_SNAP_ROOT / name
    if platform:
        current = current / _safe_segment(platform, "unknown")
    if not for_write and not current.exists() and legacy.exists():
        return legacy
    return current


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_snapshots(profile: str) -> list:
    """Merge legacy and current snapshots; current files win on the same date."""
    name = _safe_segment(profile, "default")
    by_key = {}
    # Read legacy first so a migrated/current snapshot overrides the same date.
    for directory in (LEGACY_SNAP_ROOT / name, SNAP_ROOT / name):
        if not directory.exists():
            continue
        for fp in sorted(directory.rglob("*.json")):
            try:
                with open(fp, encoding="utf-8") as f:
                    snap = json.load(f)
                key = (snap.get("date") or fp.stem, snap.get("platform") or "unknown")
                by_key[key] = snap
            except (json.JSONDecodeError, OSError):
                print(f"警告：跳过无法解析的快照 {fp}", file=sys.stderr)
    return [by_key[key] for key in sorted(by_key)]


# --------------------------------------------------------------------------- #
# snapshot
# --------------------------------------------------------------------------- #
def cmd_snapshot(args) -> None:
    profile = args.profile or "default"
    d = args.date or date.today().isoformat()
    prev = load_snapshots(profile)
    metrics = {}
    for k, v in (("followers", args.followers),
                 ("total_likes", args.total_likes),
                 ("total_posts", args.total_posts)):
        if v is not None:
            metrics[k] = v

    posts = []
    if args.posts:
        try:
            posts = json.loads(Path(args.posts).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            sys.exit(f"错误：无法读取 --posts 文件：{e}")

    snap = {"date": d, "platform": args.platform, "profile": profile,
            "account_metrics": metrics, "post_snapshots": posts}

    # 与最近一条历史快照对比 delta（排除同日的旧值）
    last = None
    for s in reversed(prev):
        if s.get("date") != d:
            last = s
            break
    deltas = {}
    if last:
        lm = last.get("account_metrics", {})
        for k in metrics:
            deltas[k] = ss.delta(metrics.get(k), lm.get(k))

    path = snap_dir(profile, args.platform, for_write=True) / f"{d}.json"
    atomic_write(path, snap)
    print(json.dumps({"ok": True, "path": str(path), "snapshot": snap,
                      "delta_vs_last": deltas or None,
                      "last_snapshot_date": last.get("date") if last else None},
                     ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# trend
# --------------------------------------------------------------------------- #
def cmd_trend(args) -> None:
    profile = args.profile or "default"
    snaps = load_snapshots(profile)
    if args.platform:
        snaps = [s for s in snaps if s.get("platform") == args.platform]
    # 时间窗口
    if args.since:
        snaps = [s for s in snaps if s.get("date", "") >= args.since]
    if args.until:
        snaps = [s for s in snaps if s.get("date", "") <= args.until]

    metric = args.metric
    dates = [s.get("date") for s in snaps]
    series = [s.get("account_metrics", {}).get(metric) for s in snaps]

    n = len(series)
    if n == 0:
        sys.exit(f"错误：profile '{profile}' 无可用快照（路径 {snap_dir(profile)}）")

    growth = ss.daily_growth(series)
    growth_rate = ss.daily_growth_rate(series)
    ma7 = ss.moving_average(series, 7)

    # 近 7 天 vs 前 7 天日均增长，判断加速/稳定/减速
    recent = ss.clean(growth[-7:])
    prior = ss.clean(growth[-14:-7])
    recent_avg = ss.mean(recent)
    prior_avg = ss.mean(prior)
    if recent_avg is None:
        direction = "数据不足"
    elif prior_avg is None:
        direction = "稳定"
    elif recent_avg > prior_avg * 1.1:
        direction = "加速"
    elif recent_avg < prior_avg * 0.9:
        direction = "减速"
    else:
        direction = "稳定"

    # 里程碑外推（基于近 7 天日均增速，不超过 30 天）
    current = ss.clean(series)[-1] if ss.clean(series) else None
    milestone = ss.next_milestone(current) if current is not None else None
    eta = ss.milestone_eta(current, recent_avg, milestone, max_days=30) \
        if (current is not None and milestone is not None) else None

    per_point = [{"date": dates[i + 1],
                  "growth": growth[i], "growth_rate_pct": growth_rate[i]}
                 for i in range(len(growth))]

    result = {
        "profile": profile, "metric": metric,
        "range": {"start": dates[0], "end": dates[-1], "points": n},
        "current": current,
        "per_point": per_point,
        "moving_avg_7": {"dates": dates, "values": ma7},
        "recent7_avg_growth": recent_avg,
        "prior7_avg_growth": prior_avg,
        "trend_direction": direction,
        "max_daily_growth": max(ss.clean(growth)) if ss.clean(growth) else None,
        "min_daily_growth": min(ss.clean(growth)) if ss.clean(growth) else None,
        "milestone": milestone,
        "milestone_eta_days": eta,
        "warning": ss.sample_warning(n, 3, "快照数据点"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
def _match_post(post_snaps, title):
    for p in post_snaps:
        t = str(p.get("title", ""))
        if title in t or t in title:
            return p
    return None


def cmd_lifecycle(args) -> None:
    profile = args.profile or "default"
    snaps = load_snapshots(profile)
    if args.platform:
        snaps = [s for s in snaps if s.get("platform") == args.platform]
    metric = args.metric

    # 找目标帖子的发布日期与逐日指标
    series = []  # (date, value)
    published_at = None
    for s in snaps:
        p = _match_post(s.get("post_snapshots", []), args.post_title)
        if p is None:
            continue
        published_at = published_at or p.get("published_at")
        series.append((s.get("date"), p.get(metric)))
    if not series:
        sys.exit(f"错误：在 profile '{profile}' 的快照中未找到帖子 '{args.post_title}'")

    series.sort(key=lambda x: x[0] or "")
    base = _parse_date(published_at) or _parse_date(series[0][0])
    rows = []
    for d, v in series:
        dd = _parse_date(d)
        day_n = (dd - base).days if (dd and base) else None
        rows.append({"day": day_n, "date": d, metric: v})

    values = [r[metric] for r in rows]
    increments = ss.daily_growth(values)
    for i, r in enumerate(rows):
        r["increment"] = None if i == 0 else increments[i - 1]

    inc_clean = [(rows[i + 1]["day"], increments[i])
                 for i in range(len(increments)) if increments[i] is not None]
    peak_day = None
    peak_inc = None
    if inc_clean:
        peak_day, peak_inc = max(inc_clean, key=lambda x: x[1])

    # 半衰期：日增量降到峰值一半的天数
    half_life = None
    if peak_inc and peak_inc > 0:
        for day_n, inc in inc_clean:
            if day_n is not None and peak_day is not None and day_n > peak_day \
                    and inc <= peak_inc / 2:
                half_life = day_n - peak_day
                break

    lifecycle_type = _classify(rows, peak_day, peak_inc)

    result = {
        "profile": profile, "post_title": args.post_title, "metric": metric,
        "published_at": published_at,
        "series": rows,
        "peak_day": peak_day, "peak_increment": peak_inc,
        "half_life_days": half_life,
        "lifecycle_type": lifecycle_type,
        "warning": ss.sample_warning(len(rows), 3, "生命周期数据点"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_export_followers(args) -> None:
    """Export normalized follower snapshots for publish attribution."""
    names = {p.name for root in (LEGACY_SNAP_ROOT, SNAP_ROOT) if root.exists()
             for p in root.iterdir() if p.is_dir()}
    if args.profile:
        names = {_safe_segment(args.profile, "default")}

    rows = []
    for profile in sorted(names):
        for snap in load_snapshots(profile):
            metrics = snap.get("account_metrics") or {}
            followers = metrics.get("followers")
            platform = snap.get("platform")
            if followers is None or not platform:
                continue
            if args.platform and platform != args.platform:
                continue
            row = {
                "profile": snap.get("profile") or profile,
                "platform": platform,
                "recorded_at": snap.get("date"),
                "followers": followers,
            }
            if metrics.get("total_posts") is not None:
                row["total_posts"] = metrics["total_posts"]
            rows.append(row)

    rows.sort(key=lambda row: (row["recorded_at"] or "", row["profile"], row["platform"]))
    output = Path(args.output).expanduser() if args.output else \
        PROJECT_ROOT / "outputs" / "_analytics" / "follower-log.json"
    payload = {"version": "1.0", "snapshots": rows}
    atomic_write(output, payload)
    print(json.dumps({"ok": True, "path": str(output), "snapshots": len(rows)},
                     ensure_ascii=False, indent=2))


def _classify(rows, peak_day, peak_inc):
    """速爆型/稳增型/长尾型/数据不足。"""
    if peak_inc is None or peak_inc <= 0:
        return "数据不足"
    inc_by_day = {r["day"]: r["increment"] for r in rows
                  if r["day"] is not None and r["increment"] is not None}

    def inc_ge(day, ratio):
        return day in inc_by_day and inc_by_day[day] >= peak_inc * ratio

    # 长尾型：Day 30 仍有正向日增量
    d30 = max((d for d in inc_by_day if d >= 30), default=None)
    if d30 is not None and inc_by_day[d30] > 0:
        return "长尾型"
    # 稳增型：Day 7 仍有峰值 30% 以上
    d7 = min((d for d in inc_by_day if d >= 7), default=None)
    if d7 is not None and inc_by_day[d7] >= peak_inc * 0.3:
        return "稳增型"
    # 速爆型：峰值在 Day 0-1，Day 3 后跌破峰值 20%
    if peak_day is not None and peak_day <= 1:
        d3 = min((d for d in inc_by_day if d >= 3), default=None)
        if d3 is None or inc_by_day[d3] < peak_inc * 0.2:
            return "速爆型"
    return "稳增型"


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="社媒数据追踪（快照/趋势/生命周期）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot", help="记录当日账号指标快照")
    s.add_argument("--profile", default="default")
    s.add_argument("--platform", required=True)
    s.add_argument("--date", help="YYYY-MM-DD，默认今天")
    s.add_argument("--followers", type=int)
    s.add_argument("--total-likes", dest="total_likes", type=int)
    s.add_argument("--total-posts", dest="total_posts", type=int)
    s.add_argument("--posts", help="帖子逐条数据 JSON 文件（数组）")
    s.set_defaults(func=cmd_snapshot)

    t = sub.add_parser("trend", help="增长趋势分析")
    t.add_argument("--profile", default="default")
    t.add_argument("--platform")
    t.add_argument("--metric", default="followers",
                   help="followers/total_likes/total_posts")
    t.add_argument("--since")
    t.add_argument("--until")
    t.set_defaults(func=cmd_trend)

    lc = sub.add_parser("lifecycle", help="单帖生命周期分析")
    lc.add_argument("--profile", default="default")
    lc.add_argument("--post-title", dest="post_title", required=True)
    lc.add_argument("--platform", help="平台过滤；同一画像有多平台时建议指定")
    lc.add_argument("--metric", default="likes",
                    help="likes/collects/comments/shares")
    lc.set_defaults(func=cmd_lifecycle)

    ex = sub.add_parser("export-followers", help="导出归因分析所需 follower-log.json")
    ex.add_argument("--profile", help="只导出指定画像；默认全部")
    ex.add_argument("--platform", help="只导出指定平台；默认全部")
    ex.add_argument("--output", help="输出路径（默认 outputs/_analytics/follower-log.json）")
    ex.set_defaults(func=cmd_export_followers)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
