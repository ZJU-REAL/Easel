#!/usr/bin/env python3
"""publish_queue.py — 批量定时发布队列管理（排期 → 到期派发）。

管理一张"内容 × 平台 × 发布时间"的排期表：导入排期、查看队列、计算到期项、标记状态、
到期派发（默认 dry-run 打印派发计划；真实发布由各平台 publisher SKILL 执行）。纯标准库。

队列状态持久化为 JSON。调度逻辑（到期计算/状态流转）可离线测试；实际发布走平台 SKILL。

子命令：
    import    从 CSV/JSON 排期表导入队列
    add       手动加一条排期
    list      查看队列
    due       计算此刻到期的项（--now 可覆盖用于测试/预演）
    run       到期项派发（默认 dry-run 打印计划；--exec 交由上层真实调用）
    mark      标记某项 done/failed/pending
    selftest  自检（调度逻辑）

用法举例：
    publish_queue.py import --file plan.csv --queue outputs/publish-queue/q.json
    publish_queue.py list --queue q.json
    publish_queue.py due  --queue q.json
    publish_queue.py run  --queue q.json            # dry-run 打印到期派发计划
    publish_queue.py mark --queue q.json --id 3 --status done
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

STATUSES = ("pending", "done", "failed", "skipped")


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _parse_dt(s: str) -> datetime:
    s = (s or "").strip().replace("/", "-")
    if not s:
        _die("发布时间为空")
    # 允许 "YYYY-MM-DD HH:MM[:SS]" / ISO / 仅日期
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    _die(f"无法解析发布时间：{s}（用 YYYY-MM-DD HH:MM）")
    raise AssertionError


def _load(queue: str) -> dict:
    p = Path(queue).expanduser()
    if not p.is_file():
        return {"items": [], "next_id": 1}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _die(f"队列文件损坏：{e}")
    raise AssertionError


def _save(queue: str, data: dict) -> None:
    p = Path(queue).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _add_item(data: dict, publish_at: str, platform: str, content: str,
              title: str = "", note: str = "") -> dict:
    dt = _parse_dt(publish_at)  # 校验
    item = {"id": data["next_id"], "publish_at": dt.strftime("%Y-%m-%d %H:%M"),
            "platform": platform.strip(), "content": content.strip(),
            "title": title.strip(), "status": "pending", "note": note.strip()}
    data["items"].append(item)
    data["next_id"] += 1
    return item


def cmd_import(a) -> int:
    data = _load(a.queue)
    src = Path(a.file).expanduser()
    if not src.is_file():
        _die(f"排期文件不存在：{src}")
    n = 0
    if src.suffix.lower() == ".json":
        rows = json.loads(src.read_text(encoding="utf-8"))
        rows = rows.get("items", rows) if isinstance(rows, dict) else rows
        for r in rows:
            _add_item(data, r.get("publish_at", ""), r.get("platform", ""),
                      r.get("content", ""), r.get("title", ""), r.get("note", ""))
            n += 1
    else:  # CSV：表头需含 publish_at, platform, content[, title, note]
        with src.open(encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            need = {"publish_at", "platform", "content"}
            if not need.issubset({(h or "").strip() for h in (reader.fieldnames or [])}):
                _die(f"CSV 需含列：{', '.join(sorted(need))}（另可选 title/note）")
            for r in reader:
                _add_item(data, r.get("publish_at", ""), r.get("platform", ""),
                          r.get("content", ""), r.get("title", ""), r.get("note", ""))
                n += 1
    _save(a.queue, data)
    print(f"✅ 导入 {n} 条 → {a.queue}（队列共 {len(data['items'])} 条）")
    return 0


def cmd_add(a) -> int:
    data = _load(a.queue)
    it = _add_item(data, a.publish_at, a.platform, a.content, a.title or "", a.note or "")
    _save(a.queue, data)
    print(f"✅ 已加入 #{it['id']}：{it['publish_at']} · {it['platform']} · {it['content']}")
    return 0


def _fmt_row(it: dict) -> str:
    mark = {"pending": "⏳", "done": "✅", "failed": "❌", "skipped": "⏭"}.get(it["status"], "?")
    t = f" 《{it['title']}》" if it.get("title") else ""
    return f"  {mark} #{it['id']} {it['publish_at']} [{it['platform']}]{t} {it['content']}"


def cmd_list(a) -> int:
    data = _load(a.queue)
    items = sorted(data["items"], key=lambda x: x["publish_at"])
    if a.status:
        items = [x for x in items if x["status"] == a.status]
    if not items:
        print("（队列为空）")
        return 0
    by = {}
    for it in items:
        by[it["status"]] = by.get(it["status"], 0) + 1
    print(f"队列 {a.queue}：共 {len(items)} 条 · " +
          " ".join(f"{k}={v}" for k, v in by.items()))
    for it in items:
        print(_fmt_row(it))
    return 0


def _due_items(data: dict, now: datetime) -> list[dict]:
    out = []
    for it in data["items"]:
        if it["status"] != "pending":
            continue
        if _parse_dt(it["publish_at"]) <= now:
            out.append(it)
    return sorted(out, key=lambda x: x["publish_at"])


def cmd_due(a) -> int:
    data = _load(a.queue)
    now = _parse_dt(a.now) if a.now else datetime.now()
    due = _due_items(data, now)
    print(json.dumps({"now": now.strftime("%Y-%m-%d %H:%M"), "due_count": len(due),
                      "items": due}, ensure_ascii=False, indent=2))
    return 0


def cmd_run(a) -> int:
    data = _load(a.queue)
    now = _parse_dt(a.now) if a.now else datetime.now()
    due = _due_items(data, now)
    if not due:
        print("（此刻无到期项）")
        return 0
    print(f"到期 {len(due)} 条（now={now.strftime('%Y-%m-%d %H:%M')}）："
          f"{'真实派发' if a.exec else 'dry-run 派发计划'}")
    for it in due:
        print(f"  → [{it['platform']}] {it['content']}"
              f"{('《'+it['title']+'》') if it.get('title') else ''}")
        print(f"    委派：调用对应平台 publisher SKILL（skill-{it['platform']}-... / "
              f"cross-platform-publish）执行发布")
        if a.exec:
            # 真实发布由上层（OpenClaw agent）按此计划委派各平台 publisher SKILL；
            # 本脚本不直接驱动浏览器，只负责调度与状态。此处标记为待上层回填。
            it["note"] = (it.get("note", "") + " [run:待平台SKILL回填结果]").strip()
    if a.exec:
        _save(a.queue, data)
        print("已输出派发计划；请由上层按计划调用各平台 SKILL，完成后用 mark 回填状态。")
    return 0


def cmd_mark(a) -> int:
    if a.status not in STATUSES:
        _die(f"--status 需为 {STATUSES} 之一")
    data = _load(a.queue)
    for it in data["items"]:
        if it["id"] == a.id:
            it["status"] = a.status
            if a.note:
                it["note"] = a.note
            _save(a.queue, data)
            print(f"✅ #{a.id} → {a.status}")
            return 0
    _die(f"未找到 #{a.id}")
    return 1


def cmd_selftest(_a) -> int:
    print("publish_queue 自检 ...", file=sys.stderr)
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        q = str(d / "q.json")
        plan = d / "plan.csv"
        plan.write_text(
            "publish_at,platform,content,title\n"
            "2026-07-01 09:00,xiaohongshu,note1.md,早间笔记\n"
            "2026-07-01 20:00,douyin,clip.mp4,晚间视频\n"
            "2026-12-31 10:00,bilibili,vlog.mp4,跨年\n",
            encoding="utf-8")

        cmd_import(argparse.Namespace(file=str(plan), queue=q))
        data = _load(q)
        assert len(data["items"]) == 3, "导入条数不对"

        # due @ 2026-07-01 12:00 → 只有 09:00 那条到期
        due = _due_items(data, _parse_dt("2026-07-01 12:00"))
        assert len(due) == 1 and due[0]["platform"] == "xiaohongshu", f"到期计算错：{due}"

        # due @ 2026-07-01 21:00 → 两条（09:00 + 20:00）
        due2 = _due_items(data, _parse_dt("2026-07-01 21:00"))
        assert len(due2) == 2, f"应 2 条到期，实得 {len(due2)}"

        # 标记第 1 条 done → 再算到期应少 1
        cmd_mark(argparse.Namespace(queue=q, id=1, status="done", note=""))
        data = _load(q)
        due3 = _due_items(data, _parse_dt("2026-07-01 21:00"))
        assert len(due3) == 1 and due3[0]["id"] == 2, "done 项仍被计为到期"

        # add 手动一条
        cmd_add(argparse.Namespace(queue=q, publish_at="2026-07-02 08:00",
                                   platform="wechat", content="art.md", title="", note=""))
        assert len(_load(q)["items"]) == 4, "add 未生效"

        # 时间解析健壮性
        assert _parse_dt("2026/07/01 9:00").hour == 9
        assert _parse_dt("2026-07-01").hour == 0

    print("✅ selftest 通过（import/due 计算/mark 流转/add/时间解析）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="批量定时发布队列（排期 → 到期派发，纯标准库）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("import", help="从 CSV/JSON 导入排期")
    p.add_argument("--file", required=True)
    p.add_argument("--queue", required=True)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("add", help="手动加一条排期")
    p.add_argument("--queue", required=True)
    p.add_argument("--publish-at", required=True, help="YYYY-MM-DD HH:MM")
    p.add_argument("--platform", required=True)
    p.add_argument("--content", required=True, help="内容路径/标识")
    p.add_argument("--title")
    p.add_argument("--note")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="查看队列")
    p.add_argument("--queue", required=True)
    p.add_argument("--status", choices=STATUSES)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("due", help="计算到期项")
    p.add_argument("--queue", required=True)
    p.add_argument("--now", help="覆盖当前时间（YYYY-MM-DD HH:MM），用于测试/预演")
    p.set_defaults(func=cmd_due)

    p = sub.add_parser("run", help="到期派发（默认 dry-run）")
    p.add_argument("--queue", required=True)
    p.add_argument("--now", help="覆盖当前时间")
    p.add_argument("--exec", action="store_true", help="输出派发计划并标记（真实发布由上层委派平台 SKILL）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("mark", help="标记状态")
    p.add_argument("--queue", required=True)
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--status", required=True, choices=STATUSES)
    p.add_argument("--note")
    p.set_defaults(func=cmd_mark)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
