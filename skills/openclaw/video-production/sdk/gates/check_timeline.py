#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ⑧ 分场时间轴：重叠 / 长间隙 / 过短场（防 A/B 舞台打架、闪切）
用法：python check_timeline.py --scenes scenes.json [--min-dur 0.8] [--max-gap 0.6]
判定：① 任意两场时间重叠 = FAIL（两个舞台同时在场 → 画面打架/闪切）
      ② 相邻间隙 > max-gap = FAIL（空窗：要么补场、要么调整边界）
      ③ 单场时长 < min-dur = FAIL（过短，来不及读）
exit 0=过；1=有问题
来源：真机片 A/B 闪切实录（scenes 时间轴重叠 2s+，其余七门全过也抓不住）2026-09-17
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--min-dur", type=float, default=0.8)
    ap.add_argument("--max-gap", type=float, default=0.6)
    args = ap.parse_args()

    data = json.load(open(args.scenes, encoding="utf-8"))
    sc = data.get("scenes") or data.get("segments") or []
    items = [s for s in sc if s.get("start") is not None and s.get("end") is not None]
    items.sort(key=lambda s: float(s["start"]))

    fails, notes = [], []
    for s in items:
        dur = float(s["end"]) - float(s["start"])
        if dur < args.min_dur:
            fails.append(f"场 {s.get('id')} 过短：{dur:.2f}s < {args.min_dur}s（闪切风险；并场或写明短促演出的理由）")
    for i in range(len(items) - 1):
        a, b = items[i], items[i + 1]
        if float(b["start"]) < float(a["end"]) - 0.001:
            ov = float(a["end"]) - float(b["start"])
            fails.append(f"重叠：场 {a.get('id')}({float(a['start']):.2f}-{float(a['end']):.2f}) × 场 {b.get('id')}"
                         f"({float(b['start']):.2f}-{float(b['end']):.2f}) 重叠 {ov:.2f}s —— 两套舞台会同时在场（打架/闪切）")
        else:
            gap = float(b["start"]) - float(a["end"])
            if gap > args.max_gap:
                fails.append(f"长间隙：场 {a.get('id')}→{b.get('id')} 之间 {gap:.2f}s 无任何场（空窗；补场或调整边界）")
            elif gap > 0.05:
                notes.append(f"小间隙：场 {a.get('id')}→{b.get('id')} 间隔 {gap:.2f}s（容差内）")

    print("== 门⑧ 分场时间轴报告 ==")
    for n in notes:
        print("note ", n)
    if fails:
        for f in fails:
            print("FAIL ", f)
        print(f"\n── 共 {len(fails)} 项问题：时间轴不过，先修场表")
    else:
        print(f"PASS  时间轴干净（{len(items)} 场；无重叠、无长间隙、无过短场）")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
