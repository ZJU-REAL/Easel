#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ③ 查重 / 对照表：片内 形式×变体 唯一、转场相邻不重复；片间对照参照物出对照表骨架
用法：
  python check_dup.py --scenes scenes.json [--table table.md] [--ref ref.json]
scenes.json:
  {"scenes":[{"id":1,"cards":[{"slot":"center","form":"rings","variant":"v2"}],"transition":"wipe"},
             {"id":2,"cards":[{"slot":"left","form":"eq","variant":"v1"}],"transition":"slide"}, ...]}
ref.json（参照物/上一部机制清单）:
  {"items":[{"form":"rings","style":"青色扩散环+核心"}, {"form":"eq","style":"紫色柱条"}, ...]}
判定：同 (slot,form,variant) 出现 >1 次 = FAIL；相邻场同 transition = FAIL；
      与 ref 的重叠项只列出（供填对照表：机制可重合，风格必须写明差异）。
exit 0=过；1=片内重复
"""
import argparse, json, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--table", help="输出对照表骨架 md")
    ap.add_argument("--ref", help="参照物机制清单 json")
    args = ap.parse_args()

    data = json.load(open(args.scenes, encoding="utf-8"))
    scenes = data["scenes"]
    fails = []

    seen = {}
    for sc in scenes:
        for c in sc.get("cards", []):
            key = (c.get("slot"), c.get("form"), c.get("variant"))
            seen.setdefault(key, []).append(sc["id"])
    for key, ids in seen.items():
        if len(ids) > 1:
            fails.append(f"片内重复: slot/form/variant {key} 出现在场景 {ids}")

    for i in range(len(scenes) - 1):
        t1, t2 = scenes[i].get("transition"), scenes[i + 1].get("transition")
        if t1 and t2 and t1 == t2:
            fails.append(f"相邻场转场重复: f{scenes[i]['id']}与f{scenes[i+1]['id']} 都是 {t1}")

    refs = []
    if args.ref:
        refs = json.load(open(args.ref, encoding="utf-8"))["items"]

    print("== 门③ 查重报告 ==")
    if fails:
        for f in fails:
            print("FAIL ", f)
    else:
        print("PASS  片内无重复（形式×变体唯一、相邻转场不重复）")

    if args.ref:
        print(f"\n-- 与参照物的机制重叠（对照表素材，风格差异需人工写明）--")
        used_forms = [(c.get("form"), sc["id"]) for sc in scenes for c in sc.get("cards", [])]
        for rf in refs:
            hits = [sid for form, sid in used_forms if form == rf["form"]]
            if hits:
                print(f"  机制「{rf['form']}」（参照风格: {rf.get('style', '?')}）→ 本片用于场景 {hits}：风格差异______")

    if args.table:
        lines = ["| 场景 | 本片机制（form×variant） | 与本片参照物的差异（构图/材质/运动语言） |",
                 "|------|--------------------------|------------------------------------------|"]
        for sc in scenes:
            cards = "；".join(f"{c.get('slot')}:{c.get('form')}{('/' + c['variant']) if c.get('variant') else ''}" for c in sc.get("cards", []))
            lines.append(f"| {sc['id']} | {cards or '—'} | 待填 |")
        open(args.table, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print(f"\n对照表骨架已写: {args.table}")

    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
