#!/usr/bin/env python3
"""analyze.py — skill-publish-analytics 的确定性归因分析.

固化原 SKILL.md 里"用内联 Python"的四种分析模式，直接读 publish-log.json
输出结构化结果，LLM 只负责解读、写关键发现与建议。

子命令 (分析模式):
  time     模式 A — 最佳发布时段（时段桶 × 平均互动综合分）
  tags     模式 B — 标签效果（各标签平均互动 + 共现矩阵）
  types    模式 C — 内容类型对比（type × 平均指标 + winner）
  growth   模式 D — 增长归因（关联发布事件与 follower-log 的粉丝变化）
  all      A+B+C（growth 需 follower-log.json，单独跑）

数据源: <项目根>/outputs/_analytics/publish-log.json（--data 覆盖）
        <项目根>/outputs/_analytics/follower-log.json（--follower-log 覆盖）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_DATA = PROJECT_ROOT / "outputs" / "_analytics" / "publish-log.json"
DEFAULT_FOLLOWER = PROJECT_ROOT / "outputs" / "_analytics" / "follower-log.json"
LEGACY_DATA = PROJECT_ROOT / "outputs" / "publish-log.json"
LEGACY_FOLLOWER = PROJECT_ROOT / "outputs" / "follower-log.json"
METRIC_KEYS = ("views", "likes", "comments", "shares")

TIME_BUCKETS = [
    ("早晨", range(6, 9)), ("上午", range(9, 12)), ("午间", range(12, 14)),
    ("下午", range(14, 18)), ("晚间", range(18, 22)),
]
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load(path: Path, what: str) -> dict:
    if not path.exists():
        sys.exit(f"错误：未找到 {what}（{path}）。请先运行对应 SKILL 记录数据。")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"错误：无法读取 {path}：{e}")


def _parse_dt(s):
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _bucket(hour):
    for name, hrs in TIME_BUCKETS:
        if hour in hrs:
            return name
    return "深夜"


def _m(entry, key):
    return entry.get("initial_metrics", {}).get(key)


def _score(entry):
    return ss.engagement_score(**{k: _m(entry, k) for k in METRIC_KEYS})


def _filter_profile(entries, profile):
    return [e for e in entries if e.get("profile") == profile] if profile else entries


def _coverage_report(entries):
    return {k: ss.coverage([_m(e, k) for e in entries]) for k in METRIC_KEYS}


def _summary(entries):
    dts = [d for d in (_parse_dt(e.get("published_at", "")) for e in entries) if d]
    return {
        "total": len(entries),
        "date_range": {"start": min(dts).date().isoformat() if dts else None,
                       "end": max(dts).date().isoformat() if dts else None},
        "platforms": sorted({e.get("platform", "未知") for e in entries}),
        "metric_coverage": _coverage_report(entries),
        "global_warning": ss.sample_warning(len(entries), 10, "全量发布记录"),
    }


# --------------------------------------------------------------------------- #
# 模式 A — 最佳发布时段
# --------------------------------------------------------------------------- #
def analyze_time(entries):
    grid = {}  # (weekday, bucket) -> [scores]
    bucket_scores = {}
    for e in entries:
        dt = _parse_dt(e.get("published_at", ""))
        if not dt:
            continue
        wd = WEEKDAYS[dt.weekday()]
        bk = _bucket(dt.hour)
        grid.setdefault((wd, bk), []).append(_score(e))
        bucket_scores.setdefault(bk, []).append(_score(e))

    heatmap = [{"weekday": wd, "bucket": bk, "count": len(v),
                "avg_engagement_score": ss.mean(v)}
               for (wd, bk), v in grid.items()]
    heatmap.sort(key=lambda x: x["avg_engagement_score"] or -1, reverse=True)

    for cell in heatmap:
        cell["warning"] = ss.sample_warning(cell["count"], 5, "该时段样本")

    bucket_avg = {bk: {"count": len(v), "avg_engagement_score": ss.mean(v)}
                  for bk, v in bucket_scores.items()}
    top3 = heatmap[:3]
    return {"heatmap": heatmap, "top3_slots": top3, "by_bucket": bucket_avg}


# --------------------------------------------------------------------------- #
# 模式 B — 标签效果
# --------------------------------------------------------------------------- #
def analyze_tags(entries):
    global_avg = {k: ss.mean([_m(e, k) for e in entries]) for k in METRIC_KEYS}
    tag_entries = {}
    for e in entries:
        for tag in e.get("tags", []):
            tag_entries.setdefault(tag, []).append(e)

    ranking = []
    for tag, es in tag_entries.items():
        row = {"tag": tag, "count": len(es),
               "warning": ss.sample_warning(len(es), 5, f"标签'{tag}'样本")}
        for k in METRIC_KEYS:
            row[f"avg_{k}"] = ss.mean([_m(e, k) for e in es])
        row["avg_engagement_score"] = ss.mean([_score(e) for e in es])
        # 高效/低效：综合分对比全局
        g = ss.mean([_score(e) for e in entries])
        row["above_global"] = (row["avg_engagement_score"] is not None and g is not None
                               and row["avg_engagement_score"] > g)
        ranking.append(row)
    ranking.sort(key=lambda r: r["avg_engagement_score"] or -1, reverse=True)

    co = ss.cooccurrence([e.get("tags", []) for e in entries], min_count=2)
    co_list = [{"tags": list(k), "count": v} for k, v in
               sorted(co.items(), key=lambda x: x[1], reverse=True)]

    return {"global_avg": global_avg, "ranking": ranking,
            "top5": ranking[:5], "bottom5": ranking[-5:][::-1],
            "cooccurrence": co_list}


# --------------------------------------------------------------------------- #
# 模式 C — 内容类型对比
# --------------------------------------------------------------------------- #
def analyze_types(entries):
    by_type = {}
    for e in entries:
        by_type.setdefault(e.get("type") or "未知", []).append(e)

    rows = []
    for t, es in by_type.items():
        row = {"type": t, "count": len(es)}
        for k in METRIC_KEYS:
            row[f"avg_{k}"] = ss.mean([_m(e, k) for e in es])
        row["avg_engagement_score"] = ss.mean([_score(e) for e in es])
        rows.append(row)

    winners = {}
    for k in list(METRIC_KEYS) + ["engagement_score"]:
        field = f"avg_{k}" if k in METRIC_KEYS else "avg_engagement_score"
        best = max((r for r in rows if r[field] is not None),
                   key=lambda r: r[field], default=None)
        winners[k] = best["type"] if best else None

    # 平台 × 类型 交叉
    cross = {}
    for e in entries:
        key = f"{e.get('platform', '未知')}×{e.get('type') or '未知'}"
        cross.setdefault(key, []).append(_score(e))
    cross_table = {k: {"count": len(v), "avg_engagement_score": ss.mean(v)}
                   for k, v in cross.items()}

    return {"by_type": rows, "winners": winners, "platform_x_type": cross_table}


# --------------------------------------------------------------------------- #
# 模式 D — 增长归因
# --------------------------------------------------------------------------- #
def analyze_growth(entries, follower_data):
    snaps = follower_data.get("snapshots", [])
    parsed = []
    for s in snaps:
        dt = _parse_dt(s.get("recorded_at", ""))
        if dt and s.get("followers") is not None:
            parsed.append((dt, s.get("followers"), s.get("platform"), s.get("profile")))
    parsed.sort(key=lambda x: x[0])

    def followers_at(before_dt, platform, profile, after=False, within=None):
        """after=False: 取 before_dt 前最近；after=True: 取窗口内最近一个。"""
        cand = [(dt, f) for dt, f, pf, pr in parsed
                if pf == platform and (not profile or pr == profile)]
        if after:
            hi = before_dt + within
            pts = [(dt, f) for dt, f in cand if before_dt < dt <= hi]
            return pts[-1][1] if pts else None
        pts = [(dt, f) for dt, f in cand if dt <= before_dt]
        return pts[-1][1] if pts else None

    ranking = []
    for e in entries:
        dt = _parse_dt(e.get("published_at", ""))
        if not dt:
            continue
        base = followers_at(dt, e.get("platform"), e.get("profile"))
        row = {"id": e.get("id"), "title": e.get("title"),
               "platform": e.get("platform"),
               "published_at": e.get("published_at"),
               "type": e.get("type"), "tags": e.get("tags", [])}
        for label, win in (("24h", timedelta(hours=24)),
                           ("48h", timedelta(hours=48)),
                           ("7d", timedelta(days=7))):
            after = followers_at(dt, e.get("platform"), e.get("profile"),
                                 after=True, within=win)
            row[f"delta_{label}"] = ss.delta(after, base) if base is not None else None
        ranking.append(row)

    ranking.sort(key=lambda r: (r.get("delta_7d") is None, -(r.get("delta_7d") or 0)))
    return {"ranking": ranking,
            "note": "粉丝增量 = 发布后窗口内最近快照 - 发布前最近快照；无快照标 null"}


# --------------------------------------------------------------------------- #
# selftest（离线，合成数据，不依赖文件）
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    def mk(id_, dt, typ, tags, likes):
        return {"id": id_, "title": f"贴{id_}", "platform": "小红书", "type": typ,
                "published_at": dt, "profile": "达人", "tags": tags,
                "initial_metrics": {"views": likes * 10, "likes": likes,
                                    "comments": likes // 5, "shares": likes // 10}}
    entries = [
        mk(1, "2026-07-01T08:30:00", "图文", ["穿搭", "好物"], 100),
        mk(2, "2026-07-02T20:00:00", "视频", ["好物"], 300),
        mk(3, "2026-07-03T20:30:00", "视频", ["穿搭"], 250),
    ]
    a = analyze_time(entries)
    assert "heatmap" in a and "top3_slots" in a and a["heatmap"], "time 结果异常"
    b = analyze_tags(entries)
    assert b["ranking"] and any(r["tag"] == "好物" for r in b["ranking"]), "tags 结果异常"
    assert b["cooccurrence"] is not None, "共现缺失"
    c = analyze_types(entries)
    assert c["winners"] and any(r["type"] == "视频" for r in c["by_type"]), "types 结果异常"
    # growth：合成 follower-log
    fdata = {"snapshots": [
        {"recorded_at": "2026-07-02T00:00:00", "followers": 1000, "platform": "小红书", "profile": "达人"},
        {"recorded_at": "2026-07-03T00:00:00", "followers": 1200, "platform": "小红书", "profile": "达人"},
    ]}
    d = analyze_growth(entries, fdata)
    assert "ranking" in d, "growth 结果异常"
    # _summary 结构
    s = _summary(entries)
    assert s["total"] == 3 and s["platforms"] == ["小红书"], "summary 异常"
    print("✅ analyze.py selftest 通过（time/tags/types/growth/summary 结构校验）")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _run(modes, args):
    data_path = Path(args.data)
    if data_path == DEFAULT_DATA and not data_path.exists() and LEGACY_DATA.exists():
        data_path = LEGACY_DATA
    data = load(data_path, "publish-log.json")
    entries = _filter_profile(data.get("entries", []), args.profile)
    out = {"summary": _summary(entries)}
    if "time" in modes:
        out["mode_A_time"] = analyze_time(entries)
    if "tags" in modes:
        out["mode_B_tags"] = analyze_tags(entries)
    if "types" in modes:
        out["mode_C_types"] = analyze_types(entries)
    if "growth" in modes:
        fpath = Path(args.follower_log)
        if fpath == DEFAULT_FOLLOWER and not fpath.exists() and LEGACY_FOLLOWER.exists():
            fpath = LEGACY_FOLLOWER
        if not fpath.exists():
            out["mode_D_growth"] = {
                "skipped": True,
                "message": ("模式 D 需要粉丝数据。请在 outputs/_analytics/follower-log.json "
                            "记录粉丝快照，schema 见 references/follower-log-schema.md")}
        else:
            out["mode_D_growth"] = analyze_growth(
                entries, load(fpath, "follower-log.json"))
    print(json.dumps(out, ensure_ascii=False, indent=2))


def build_parser():
    p = argparse.ArgumentParser(description="发布数据归因分析（确定性计算）")
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.add_argument("--follower-log", dest="follower_log", default=str(DEFAULT_FOLLOWER))
    p.add_argument("--profile", help="按 profile 字段过滤")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, modes, help_ in (
        ("time", ["time"], "模式 A 最佳发布时段"),
        ("tags", ["tags"], "模式 B 标签效果"),
        ("types", ["types"], "模式 C 内容类型对比"),
        ("growth", ["growth"], "模式 D 增长归因"),
        ("all", ["time", "tags", "types"], "A+B+C 默认组合"),
    ):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(modes=modes)
    sub.add_parser("selftest", help="离线自检（合成数据）").set_defaults(modes=None)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        sys.exit(_selftest())
    _run(args.modes, args)


if __name__ == "__main__":
    main()
