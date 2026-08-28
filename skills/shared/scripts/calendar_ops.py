#!/usr/bin/env python3
"""calendar_ops.py — 统一内容日历底座的确定性读写.

把"记录每次发布 / 排期 / 平台活动 → 供 Agent 读回规划"从 LLM 心算固化为代码。
读写与 Web 日历页 (`/api/schedule`) **同一个文件** `outputs/_schedule.json`，
条目 schema 与 web/app.py 的 ScheduleItem 对齐（id/title/date/platform/time/status/note
+ kind/url/source/event_type/end_date），旧数据缺 kind 视为 content。

子命令:
  record-publish  追加一条已发布记录（content 项，status=published）；并转发
                  skill-publish-log 保持归因指标底座同步（best-effort）。
  add-event       追加一条平台活动/节日/特殊日期（event 项）。
  import-events   从 JSON（stdin 或 --file）批量导入 event 项。
  upcoming        未来 N 天的排期 + 活动。
  context         规划摘要：各平台发布节奏/断更缺口 + 待发排期 + 临近节点 + 滞留选题。
  list            过滤查询（--kind/--platform/--since/--until）。
  selftest        临时库跑全链自检。

模块函数 record_publish(...) 供 publisher 脚本 import（异常安全，记录失败绝不影响发布）。
env EASEL_CALENDAR_AUTORECORD=0 时，脚本侧自动记录被禁用（发布页由 web 自己记录，防重复）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

def _find_root() -> Path:
    """定位项目根：优先 EASEL_ROOT env，否则向上找含 outputs/setup.sh 的目录。
    兼容两种布局——项目 skills/shared/scripts/（根在 parents[3]）与 OpenClaw workspace
    拍平后的 shared/scripts/（根在 parents[2]，其 outputs 为真项目 outputs 的软链）。
    硬编码 parents[N] 两边深度不同会算错，故用标记探测。"""
    env = os.environ.get("EASEL_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "outputs").exists() or (parent / "setup.sh").exists():
            return parent
    return here.parents[3] if len(here.parents) > 3 else here.parents[-1]


PROJECT_ROOT = _find_root()
DEFAULT_DATA = PROJECT_ROOT / "outputs" / "_schedule.json"
CST = timezone(timedelta(hours=8))

CONTENT_STATUSES = {"idea", "draft", "scheduled", "published"}
KINDS = {"content", "event"}
SOURCES = {"manual", "publish-page", "chat", "scheduler"}
# 平台码 → 中文名（与 web/app.py LOGIN_RUNNERS 的 cfg['name'] 对齐，日历页按中文名展示）
PLATFORM_NAMES = {
    "xiaohongshu": "小红书", "douyin": "抖音", "kuaishou": "快手",
    "weixin-channels": "微信视频号", "zhihu": "知乎", "bilibili": "B站",
}


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #
def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def atomic_write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _today() -> datetime:
    return datetime.now(CST)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _norm_platform(p: str) -> str:
    """平台码或中文名 → 中文名（日历统一展示中文）。"""
    if not p:
        return ""
    return PLATFORM_NAMES.get(p, p)


def _parse_date(s: str):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# publish-log 转发（保持归因指标底座同步，best-effort）
# --------------------------------------------------------------------------- #
def _forward_publish_log(platform: str, title: str, url: str, ptype: str,
                         tags: str, source: str) -> None:
    # 兼容两种布局：项目根 skills/openclaw/... 与 OpenClaw workspace 拍平后的 skills/...
    candidates = [
        PROJECT_ROOT / "skills" / "openclaw" / "skill-publish-log" / "scripts" / "log.py",
        PROJECT_ROOT / "skills" / "skill-publish-log" / "scripts" / "log.py",
    ]
    log_py = next((c for c in candidates if c.is_file()), None)
    if log_py is None:
        return  # 找不到 → 跳过（仅日历库落记录，best-effort）
    cmd = [sys.executable, str(log_py), "record", "--platform", platform,
           "--title", title, "--skill-source", source or "calendar-auto"]
    if url:
        cmd += ["--url", url]
    if ptype:
        cmd += ["--type", ptype]
    if tags:
        cmd += ["--tags", tags]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15,
                       env={**os.environ, "EASEL_CALENDAR_AUTORECORD": "0"})
    except Exception:
        pass  # 转发失败绝不影响主流程


# --------------------------------------------------------------------------- #
# record_publish：供 publisher 脚本 import 的入口（异常安全）
# --------------------------------------------------------------------------- #
def record_publish(platform: str, title: str, url: str = "", ptype: str = "",
                   tags: str = "", note: str = "", source: str = "chat",
                   data_path: Path | None = None, forward_log: bool = True) -> bool:
    """追加一条已发布记录到日历底座。返回是否写入。全程异常安全。
    env EASEL_CALENDAR_AUTORECORD=0 时直接跳过（发布页由 web 记录，防重复）。"""
    if os.environ.get("EASEL_CALENDAR_AUTORECORD") == "0":
        return False
    try:
        path = data_path or DEFAULT_DATA
        now = _today()
        item = {
            "id": _new_id(),
            "title": (title or "").strip() or "未命名",
            "date": now.strftime("%Y-%m-%d"),
            "platform": _norm_platform(platform),
            "time": now.strftime("%H:%M"),
            "status": "published",
            "note": (note or "")[:200],
            "kind": "content",
            "url": url or "",
            "source": source if source in SOURCES else "chat",
        }
        items = load(path)
        items.append(item)
        atomic_write(path, items)
    except Exception:
        return False  # 记录失败绝不影响发布
    if forward_log:
        _forward_publish_log(_norm_platform(platform), item["title"], url, ptype,
                             tags, "calendar-auto")
    return True


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_record_publish(args) -> None:
    ok = record_publish(args.platform, args.title, url=args.url or "",
                        ptype=args.type or "", tags=args.tags or "",
                        note=args.note or "", source=args.source or "chat",
                        data_path=Path(args.data), forward_log=not args.no_log)
    print(json.dumps({"ok": ok, "skipped": not ok and
                      os.environ.get("EASEL_CALENDAR_AUTORECORD") == "0"},
                     ensure_ascii=False))


def cmd_add_event(args) -> None:
    path = Path(args.data)
    items = load(path)
    item = {
        "id": _new_id(),
        "title": (args.title or "").strip() or "未命名活动",
        "date": args.date,
        "platform": _norm_platform(args.platform or ""),
        "time": args.time or "",
        "status": "idea",
        "note": args.note or "",
        "kind": "event",
        "event_type": args.event_type or "",
        "end_date": args.end_date or "",
    }
    items.append(item)
    atomic_write(path, items)
    print(json.dumps({"ok": True, "id": item["id"], "item": item},
                     ensure_ascii=False, indent=2))


def _merge_events(items: list[dict], events: list[dict]) -> int:
    """把 events 合并进 items（kind=event），按 (kind,title,date) 幂等去重。返回新增条数。"""
    added = 0
    existing = {(it.get("kind"), it.get("title"), it.get("date")) for it in items}
    for ev in events:
        title = (ev.get("title") or ev.get("name") or "").strip()
        date = ev.get("date") or ev.get("start_date") or ""
        if not title or not _parse_date(date):
            continue
        key = ("event", title, date)
        if key in existing:  # 同名同日不重复
            continue
        existing.add(key)
        items.append({
            "id": _new_id(), "title": title, "date": date,
            "platform": _norm_platform(ev.get("platform", "")),
            "time": ev.get("time", ""), "status": "idea", "note": ev.get("note", ""),
            "kind": "event", "event_type": ev.get("event_type", ev.get("type", "")),
            "end_date": ev.get("end_date", ""),
        })
        added += 1
    return added


def cmd_import_events(args) -> None:
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"错误：无法解析 JSON：{e}")
    events = payload if isinstance(payload, list) else payload.get("events", [])
    path = Path(args.data)
    items = load(path)
    added = _merge_events(items, events)
    atomic_write(path, items)
    print(json.dumps({"ok": True, "added": added, "total": len(items)},
                     ensure_ascii=False))


# --------------------------------------------------------------------------- #
# seed-holidays：一键铺固定节日（阳历固定日 + 阴历换算 + 第N个周几）
# --------------------------------------------------------------------------- #
# 阳历固定日：(月, 日, 名称, 类型, 蹭点方向)
_SOLAR_FESTIVALS = [
    (1, 1, "元旦", "法定节假日", "新年第一天，年度计划/复盘/立 flag"),
    (2, 14, "情人节", "国际节日", "爱情/礼物/约会/仪式感"),
    (3, 8, "三八女神节", "法定节日", "女性/美妆/她经济，电商大促"),
    (3, 12, "植树节", "公益节日", "环保/绿色/公益"),
    (4, 1, "愚人节", "国际节日", "整蛊/反转/创意脑洞"),
    (4, 4, "清明节", "法定节假日", "踏青/追思/春日（日期约 4.4-4.5，以当年官方为准）"),
    (5, 1, "劳动节", "法定节假日", "五一小长假，出游/生活方式"),
    (5, 4, "青年节", "纪念日", "青年/成长/热血"),
    (6, 1, "儿童节", "生活节点", "童趣/怀旧/亲子"),
    (6, 18, "618 大促", "电商大促", "年中最大促，仅次双11，全品类"),
    (7, 1, "建党节", "纪念日", "正能量主题"),
    (8, 1, "建军节", "纪念日", "致敬/正能量"),
    (8, 8, "88 会员节", "电商大促", "淘宝年度会员活动"),
    (9, 9, "99 划算节", "电商大促", "秋季促销预热"),
    (9, 10, "教师节", "纪念日", "感恩老师/教育/礼物"),
    (10, 1, "国庆节", "法定节假日", "黄金周 7 天，出游高峰，全赛道"),
    (10, 24, "程序员节", "网络节日", "科技/IT/AI/程序员梗"),
    (10, 31, "万圣节", "国际节日", "变装/妆容/创意/娱乐"),
    (11, 11, "双11", "电商大促", "年度最大促销，全品类购物节"),
    (12, 12, "双12", "电商大促", "年末返场促销"),
    (12, 24, "平安夜", "国际节日", "温馨/礼物/氛围感"),
    (12, 25, "圣诞节", "国际节日", "圣诞/礼物/装饰/氛围"),
]
# 阴历节日：用 skill-event-calendar/scripts/lunar.py 权威换算（键名须为其 festival 支持项）
_LUNAR_FESTIVALS = [
    ("除夕", "除夕", "法定节假日", "年夜饭/守岁/团圆"),
    ("春节", "春节", "法定节假日", "全民级节日，7 天假，全赛道"),
    ("元宵", "元宵节", "传统节日", "汤圆/花灯/灯谜"),
    ("龙抬头", "龙抬头", "传统节日", "理发/开运/习俗"),
    ("端午", "端午节", "法定节假日", "粽子/龙舟/小长假"),
    ("七夕", "七夕节", "传统节日", "中国情人节，礼物/情感，电商大促"),
    ("中秋", "中秋节", "法定节假日", "月饼/团圆/赏月/礼盒"),
    ("重阳", "重阳节", "传统节日", "敬老/登高/养生"),
    ("腊八", "腊八节", "传统节日", "腊八粥/年味渐浓"),
]
# 第 N 个周几：(月, weekday[周一=0..周日=6], 第几个, 名称, 类型, 蹭点方向)
_NTH_WEEKDAY_FESTIVALS = [
    (5, 6, 2, "母亲节", "国际节日", "感恩妈妈/家庭/礼物"),
    (6, 6, 3, "父亲节", "国际节日", "感恩爸爸/家庭"),
    (11, 3, 4, "感恩节", "国际节日", "感恩/温情/黑五促销"),
]


def _nth_weekday(year: int, month: int, weekday: int, nth: int):
    first = datetime(year, month, 1).date()
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (nth - 1) * 7
    return datetime(year, month, day).date()


def _locate_lunar():
    for c in (PROJECT_ROOT / "skills" / "openclaw" / "skill-event-calendar" / "scripts" / "lunar.py",
              PROJECT_ROOT / "skills" / "skill-event-calendar" / "scripts" / "lunar.py"):
        if c.is_file():
            return c
    return None


def _lunar_solar(lunar_py: Path, key: str, year: int):
    """调 lunar.py festival <key> <year> --json 拿公历日期；失败返回 None（best-effort）。
    注意必须带 --json——不加时 lunar.py 打印 Python dict repr（单引号），json.loads 解析不了。"""
    try:
        p = subprocess.run([sys.executable, str(lunar_py), "festival", key, str(year), "--json"],
                           capture_output=True, text=True, timeout=15)
        if p.returncode == 0 and p.stdout.strip():
            return json.loads(p.stdout).get("solar")
    except Exception:
        pass
    return None


def cmd_seed_holidays(args) -> None:
    year = args.year or _today().year
    events = []
    for mm, dd, name, typ, note in _SOLAR_FESTIVALS:
        events.append({"title": name, "date": f"{year}-{mm:02d}-{dd:02d}",
                       "event_type": typ, "note": note})
    for mon, wd, nth, name, typ, note in _NTH_WEEKDAY_FESTIVALS:
        events.append({"title": name, "date": _nth_weekday(year, mon, wd, nth).isoformat(),
                       "event_type": typ, "note": note})
    missed = []
    lunar_py = _locate_lunar()
    if lunar_py:
        for key, name, typ, note in _LUNAR_FESTIVALS:
            solar = _lunar_solar(lunar_py, key, year)
            if solar:
                events.append({"title": name, "date": solar, "event_type": typ, "note": note})
            else:
                missed.append(name)
    else:
        missed = [n for _, n, _, _ in _LUNAR_FESTIVALS]  # 找不到 lunar.py → 阴历节日跳过

    path = Path(args.data)
    items = load(path)
    added = _merge_events(items, events)
    atomic_write(path, items)
    out = {"ok": True, "year": year, "added": added, "total": len(items),
           "lunar_source": str(lunar_py) if lunar_py else None}
    if missed:
        out["lunar_skipped"] = missed  # 无 lunar.py 或换算失败的阴历节日
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _in_window(item, start, end) -> bool:
    d = _parse_date(item.get("date", ""))
    return d is not None and start <= d <= end


def cmd_upcoming(args) -> None:
    items = load(Path(args.data))
    today = _today().date()
    end = today + timedelta(days=args.days)
    out = [it for it in items if _in_window(it, today, end)]
    if args.kind:
        out = [it for it in out if (it.get("kind") or "content") == args.kind]
    out.sort(key=lambda it: (it.get("date", ""), it.get("time", "")))
    print(json.dumps({"count": len(out), "from": today.isoformat(),
                      "to": end.isoformat(), "items": out},
                     ensure_ascii=False, indent=2))


def cmd_list(args) -> None:
    items = load(Path(args.data))
    since, until = _parse_date(args.since or ""), _parse_date(args.until or "")
    out = []
    for it in items:
        if args.kind and (it.get("kind") or "content") != args.kind:
            continue
        if args.platform and it.get("platform") != _norm_platform(args.platform):
            continue
        d = _parse_date(it.get("date", ""))
        if since and (d is None or d < since):
            continue
        if until and (d is None or d > until):
            continue
        out.append(it)
    out.sort(key=lambda it: (it.get("date", ""), it.get("time", "")))
    print(json.dumps({"count": len(out), "items": out}, ensure_ascii=False, indent=2))


def cmd_context(args) -> None:
    """规划摘要：Agent 读它来决定接下来做什么、怎么做。"""
    items = load(Path(args.data))
    today = _today().date()
    back = today - timedelta(days=args.days)
    fwd = today + timedelta(days=args.days)

    published = [it for it in items if it.get("status") == "published"
                 and (it.get("kind") or "content") == "content"]
    # 各平台节奏 + 断更缺口
    per_platform: dict[str, dict] = {}
    for it in published:
        d = _parse_date(it.get("date", ""))
        if d is None:
            continue
        pf = it.get("platform") or "未标平台"
        rec = per_platform.setdefault(pf, {"platform": pf, "recent_count": 0,
                                            "last_date": None})
        if back <= d <= today:
            rec["recent_count"] += 1
        if rec["last_date"] is None or d.isoformat() > rec["last_date"]:
            rec["last_date"] = d.isoformat()
    for rec in per_platform.values():
        ld = _parse_date(rec["last_date"] or "")
        rec["days_since_last"] = (today - ld).days if ld else None

    upcoming_sched = sorted(
        [it for it in items if (it.get("kind") or "content") == "content"
         and it.get("status") in ("idea", "draft", "scheduled")
         and _in_window(it, today, fwd)],
        key=lambda it: (it.get("date", ""), it.get("time", "")))
    upcoming_events = sorted(
        [it for it in items if (it.get("kind") or "content") == "event"
         and _in_window(it, today, fwd)],
        key=lambda it: it.get("date", ""))

    # 启发式建议（确定性，非 LLM 心算）
    suggestions = []
    for rec in sorted(per_platform.values(),
                      key=lambda r: (r["days_since_last"] is None, -(r["days_since_last"] or 0))):
        dsl = rec["days_since_last"]
        if dsl is not None and dsl >= args.gap:
            suggestions.append(f"「{rec['platform']}」已 {dsl} 天未发（近 {args.days} 天 "
                               f"{rec['recent_count']} 条），考虑补内容")
    sched_dates = {it.get("date") for it in upcoming_sched}
    for ev in upcoming_events:
        d = _parse_date(ev.get("date", ""))
        lead = (d - today).days if d else None
        if lead is not None and 0 <= lead <= 7 and ev.get("date") not in sched_dates:
            suggestions.append(f"{ev.get('date')}「{ev.get('title')}」临近（{lead} 天）"
                               f"但当天无排期，可提前备蹭点内容")

    result = {
        "today": today.isoformat(),
        "window_days": args.days,
        "published_recent": sum(r["recent_count"] for r in per_platform.values()),
        "per_platform": sorted(per_platform.values(), key=lambda r: r["platform"]),
        "upcoming_schedules": upcoming_sched,
        "upcoming_events": upcoming_events,
        "suggestions": suggestions,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_selftest(_a) -> None:
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix="cal_ops_"))
    try:
        data = tmp / "_schedule.json"
        today = _today().date()
        # record-publish（禁转发 publish-log，纯日历自检）
        assert record_publish("xiaohongshu", "测试笔记", note="正文", source="chat",
                               data_path=data, forward_log=False)
        items = load(data)
        assert len(items) == 1 and items[0]["status"] == "published"
        assert items[0]["platform"] == "小红书" and items[0]["kind"] == "content"
        assert items[0]["source"] == "chat"
        # AUTORECORD=0 应跳过
        os.environ["EASEL_CALENDAR_AUTORECORD"] = "0"
        assert record_publish("douyin", "不该写", data_path=data, forward_log=False) is False
        del os.environ["EASEL_CALENDAR_AUTORECORD"]
        assert len(load(data)) == 1, "AUTORECORD=0 未生效"
        # add-event + import 幂等
        ev_date = (today + timedelta(days=3)).isoformat()
        _run(["--data", str(data), "add-event", "--title", "双11", "--date", ev_date,
              "--event-type", "电商"])
        payload = json.dumps([{"title": "双11", "date": ev_date},  # 同名同日→去重
                              {"title": "开学季", "date": (today + timedelta(days=5)).isoformat()}])
        _run(["--data", str(data), "import-events"], stdin=payload)
        events = [it for it in load(data) if it.get("kind") == "event"]
        assert len(events) == 2, f"事件去重失败：{len(events)}"
        # upcoming / context 不抛异常且结构正确
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_context(argparse.Namespace(data=str(data), days=14, gap=5))
        ctx = json.loads(buf.getvalue())
        assert "suggestions" in ctx and "per_platform" in ctx
        assert len(ctx["upcoming_events"]) == 2
        # seed-holidays：阳历固定日必到 + 第N个周几 + 幂等
        seed = tmp / "seed.json"
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            cmd_seed_holidays(argparse.Namespace(data=str(seed), year=2026))
        r1 = json.loads(buf2.getvalue())
        assert r1["added"] >= len(_SOLAR_FESTIVALS) + len(_NTH_WEEKDAY_FESTIVALS), "阳历/周几节日漏种"
        seeded = load(seed)
        assert any(e["title"] == "国庆节" and e["date"] == "2026-10-01" for e in seeded), "国庆节缺"
        assert any(e["title"] == "情人节" and e["date"] == "2026-02-14" for e in seeded), "情人节缺"
        assert any(e["title"] == "母亲节" and e["date"] == "2026-05-10" for e in seeded), "母亲节(5月第2周日)算错"
        buf3 = io.StringIO()
        with redirect_stdout(buf3):
            cmd_seed_holidays(argparse.Namespace(data=str(seed), year=2026))
        assert json.loads(buf3.getvalue())["added"] == 0, "seed 幂等失败"
        print("✅ selftest 通过（record/AUTORECORD 门/event 去重/context 结构/seed-holidays 幂等）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run(argv, stdin=None):
    """selftest 内部复用：直接跑子命令（可注入 stdin）。"""
    if stdin is not None:
        import io
        old = sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            main(argv)
        finally:
            sys.stdin = old
    else:
        main(argv)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    p = argparse.ArgumentParser(description="统一内容日历底座（确定性读写/读回）")
    p.add_argument("--data", default=str(DEFAULT_DATA), help="_schedule.json 路径")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record-publish", help="记录一条已发布内容")
    r.add_argument("--platform", required=True, help="平台码或中文名")
    r.add_argument("--title", required=True)
    r.add_argument("--url")
    r.add_argument("--type", help="图文/视频/…")
    r.add_argument("--tags", help="逗号分隔")
    r.add_argument("--note")
    r.add_argument("--source", default="chat", choices=sorted(SOURCES))
    r.add_argument("--no-log", action="store_true", help="不转发 publish-log")
    r.set_defaults(func=cmd_record_publish)

    e = sub.add_parser("add-event", help="记录平台活动/节日/特殊日期")
    e.add_argument("--title", required=True)
    e.add_argument("--date", required=True, help="YYYY-MM-DD")
    e.add_argument("--platform")
    e.add_argument("--time")
    e.add_argument("--event-type", dest="event_type", help="节日/电商/平台活动/行业")
    e.add_argument("--end-date", dest="end_date", help="活动区间结束日 YYYY-MM-DD")
    e.add_argument("--note")
    e.set_defaults(func=cmd_add_event)

    i = sub.add_parser("import-events", help="从 JSON 批量导入活动（stdin 或 --file）")
    i.add_argument("--file", help="JSON 文件；缺省读 stdin")
    i.set_defaults(func=cmd_import_events)

    sh = sub.add_parser("seed-holidays", help="一键铺某年固定节日（阳历+阴历+第N个周几，幂等）")
    sh.add_argument("--year", type=int, help="公历年份（默认今年）")
    sh.set_defaults(func=cmd_seed_holidays)

    u = sub.add_parser("upcoming", help="未来 N 天排期 + 活动")
    u.add_argument("--days", type=int, default=14)
    u.add_argument("--kind", choices=sorted(KINDS))
    u.set_defaults(func=cmd_upcoming)

    ls = sub.add_parser("list", help="过滤查询")
    ls.add_argument("--kind", choices=sorted(KINDS))
    ls.add_argument("--platform")
    ls.add_argument("--since")
    ls.add_argument("--until")
    ls.set_defaults(func=cmd_list)

    c = sub.add_parser("context", help="规划摘要（供 Agent 读回）")
    c.add_argument("--days", type=int, default=14, help="回看/前瞻窗口天数")
    c.add_argument("--gap", type=int, default=5, help="断更提醒阈值（天）")
    c.set_defaults(func=cmd_context)

    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
