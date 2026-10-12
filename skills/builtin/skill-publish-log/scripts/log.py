#!/usr/bin/env python3
"""log.py — skill-publish-log 的确定性发布记录管理.

把"读写 publish-log.json / id 自增 / 过滤 / 聚合"从 LLM 心算固化为代码。
LLM 只负责解析用户意图、组织参数、解读结果。

子命令:
  record   写入一条发布记录（id 自增，原子写）
  query    按平台/时间/关键词/profile 过滤记录
  stat     按平台/类型/月份聚合数量与互动总量

数据文件默认 <项目根>/outputs/_analytics/publish-log.json，可用 --data 覆盖。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import social_stats as ss  # noqa: E402

# PROJECT_ROOT：优先 EASEL_ROOT env，否则按 __file__ 上溯（workspace 拍平副本会算错，
# 故 env 兜底不可省，见 manifest.py 同款说明）。
PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[4])
DEFAULT_DATA = PROJECT_ROOT / "outputs" / "_analytics" / "publish-log.json"
LEGACY_DATA = PROJECT_ROOT / "outputs" / "publish-log.json"
CST = timezone(timedelta(hours=8))
METRIC_KEYS = ("views", "likes", "comments", "shares")


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #
def load(path: Path) -> dict:
    # Read the pre-migration root file until the first write creates the new copy.
    if path == DEFAULT_DATA and not path.exists() and LEGACY_DATA.exists():
        path = LEGACY_DATA
    if not path.exists():
        return {"version": "1.0", "entries": []}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"错误：无法读取 {path}：{e}")
    data.setdefault("version", "1.0")
    data.setdefault("entries", [])
    return data


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


def _now_iso() -> str:
    return datetime.now(CST).replace(microsecond=0).isoformat()


def _parse_dt(s: str):
    """宽松解析时间戳，失败返回 None。"""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------- #
# record
# --------------------------------------------------------------------------- #
def cmd_record(args) -> None:
    path = Path(args.data)
    data = load(path)
    new_id = max((e.get("id", 0) for e in data["entries"]), default=0) + 1

    metrics = {}
    for k in METRIC_KEYS:
        metrics[k] = getattr(args, k)

    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    entry = {
        "id": new_id,
        "platform": args.platform,
        "title": args.title,
        "url": args.url or "",
        "type": args.type or "",
        "published_at": args.published_at or _now_iso(),
        "logged_at": _now_iso(),
        "initial_metrics": metrics,
        "skill_source": args.skill_source or "",
        "profile": args.profile or "",
        "persona_check": {
            "score": args.persona_score,
            "verdict": args.persona_verdict or "",
        },
        "tags": [t for t in tags if t],
        "notes": args.notes or "",
    }
    data["entries"].append(entry)
    atomic_write(path, data)
    print(json.dumps({"ok": True, "id": new_id, "entry": entry,
                      "total_entries": len(data["entries"])},
                     ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #
def _filter(entries, args):
    since = _parse_dt(args.since) if args.since else None
    until = _parse_dt(args.until) if args.until else None
    kw = args.keyword.lower() if args.keyword else None
    out = []
    for e in entries:
        if args.platform and e.get("platform") != args.platform:
            continue
        if args.profile and e.get("profile") != args.profile:
            continue
        pub = _parse_dt(e.get("published_at", ""))
        if since and (pub is None or pub.replace(tzinfo=None) < since.replace(tzinfo=None)):
            continue
        if until and (pub is None or pub.replace(tzinfo=None) > until.replace(tzinfo=None)):
            continue
        if kw:
            hay = " ".join([str(e.get("title", "")), str(e.get("notes", "")),
                            " ".join(e.get("tags", []))]).lower()
            if kw not in hay:
                continue
        out.append(e)
    return out


def cmd_query(args) -> None:
    data = load(Path(args.data))
    entries = _filter(data["entries"], args)
    entries.sort(key=lambda e: e.get("published_at", ""), reverse=True)
    if args.latest:
        entries = entries[:1]
    elif args.limit:
        entries = entries[:args.limit]
    print(json.dumps({"count": len(entries), "entries": entries},
                     ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# stat
# --------------------------------------------------------------------------- #
def _month_key(e):
    dt = _parse_dt(e.get("published_at", ""))
    return dt.strftime("%Y-%m") if dt else None


def cmd_stat(args) -> None:
    data = load(Path(args.data))
    entries = _filter(data["entries"], args)
    n = len(entries)

    key_fns = {
        "platform": lambda e: e.get("platform") or "未知",
        "type": lambda e: e.get("type") or "未知",
        "month": _month_key,
    }
    key_fn = key_fns[args.by]

    by_group = ss.group_aggregate(entries, key_fn, agg="count")

    # 互动总量（各指标 sum，忽略 None）
    metric_totals = {}
    for k in METRIC_KEYS:
        vals = ss.clean(e.get("initial_metrics", {}).get(k) for e in entries)
        metric_totals[k] = sum(vals) if vals else None

    # 分组 × 互动综合分均值
    group_score = ss.group_aggregate(
        entries, key_fn,
        lambda e: ss.engagement_score(**{m: e.get("initial_metrics", {}).get(m)
                                         for m in METRIC_KEYS}),
        agg="mean")

    result = {
        "total": n,
        "group_by": args.by,
        "counts": by_group,
        "metric_totals": metric_totals,
        "avg_engagement_score_by_group": group_score,
        "warning": ss.sample_warning(n, args.min_n, "发布记录"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="发布记录管理（确定性读写/过滤/聚合）")
    p.add_argument("--data", default=str(DEFAULT_DATA), help="publish-log.json 路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="写入一条发布记录")
    r.add_argument("--platform", required=True)
    r.add_argument("--title", required=True)
    r.add_argument("--url")
    r.add_argument("--type")
    r.add_argument("--published-at", dest="published_at")
    r.add_argument("--views", type=int)
    r.add_argument("--likes", type=int)
    r.add_argument("--comments", type=int)
    r.add_argument("--shares", type=int)
    r.add_argument("--skill-source", dest="skill_source")
    r.add_argument("--profile")
    r.add_argument("--persona-score", dest="persona_score", type=int,
                   help="发布前人设一致性评分（skill-persona-check）")
    r.add_argument("--persona-verdict", dest="persona_verdict",
                   choices=["pass", "warn"], help="人设检查结论（低分仅 warn，不阻断发布）")
    r.add_argument("--tags", help="逗号分隔")
    r.add_argument("--notes")
    r.set_defaults(func=cmd_record)

    q = sub.add_parser("query", help="过滤查询记录")
    q.add_argument("--platform")
    q.add_argument("--profile")
    q.add_argument("--since", help="起始日期 YYYY-MM-DD")
    q.add_argument("--until", help="结束日期 YYYY-MM-DD")
    q.add_argument("--keyword", help="标题/备注/标签关键词")
    q.add_argument("--latest", action="store_true", help="只取最近一条")
    q.add_argument("--limit", type=int)
    q.set_defaults(func=cmd_query)

    s = sub.add_parser("stat", help="按维度聚合")
    s.add_argument("--by", choices=["platform", "type", "month"], default="platform")
    s.add_argument("--platform")
    s.add_argument("--profile")
    s.add_argument("--since")
    s.add_argument("--until")
    s.add_argument("--keyword")
    s.add_argument("--min-n", dest="min_n", type=int, default=10)
    s.set_defaults(func=cmd_stat)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
