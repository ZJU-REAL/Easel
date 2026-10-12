#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ⑥ 排版网格：边距 / 重叠 / 焦点 检查（依据 shot-composition 基线：margin≥104、单一焦点）
用法：python check_layout.py --elements layout.json [--margin 104]
layout.json:
  {"frame": [1920, 1080], "min_margin": 104,
   "elements": [{"name": "hero", "rect": [640, 252, 640, 400]},
                {"name": "left", "rect": [170, 430, 560, 330]},
                {"name": "right", "rect": [1190, 430, 560, 330]},
                {"name": "chips", "rect": [660, 852, 600, 50], "edge": true}],
   "allow_overlap": [["left", "hero"], ["right", "hero"]]}
判定：非 edge 元素四边距 >= min_margin；未声明的重叠 = FAIL；输出焦点提示（最大元素）。
exit 0=过；1=违规
"""
import argparse, itertools, json, sys

def inter_area(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    x = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    y = max(0, min(ay + ah, by + bh) - max(ay, by))
    return x * y

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elements", required=True)
    ap.add_argument("--margin", type=int, default=None)
    args = ap.parse_args()
    d = json.load(open(args.elements, encoding="utf-8"))
    W, H = d["frame"]
    mm = args.margin or d.get("min_margin", 104)
    els = d["elements"]
    allow = {frozenset(p) for p in d.get("allow_overlap", [])}
    fails = []

    for e in els:
        if e.get("edge"):
            continue
        x, y, w, h = e["rect"]
        m = min(x, y, W - (x + w), H - (y + h))
        st = "PASS" if m >= mm else "FAIL"
        print(f"{st}  {e['name']}: 最小边距 {m}px (需 ≥{mm})")
        if m < mm:
            fails.append(f"{e['name']} 边距 {m}")

    for a, b in itertools.combinations(els, 2):
        ia = inter_area(a["rect"], b["rect"])
        if ia > 0 and frozenset({a["name"], b["name"]}) not in allow:
            print(f"FAIL  {a['name']} × {b['name']} 重叠 {ia}px²（未在 allow_overlap 声明）")
            fails.append(f"重叠 {a['name']}×{b['name']}")
    for a, b in allow:
        print(f"  (声明重叠: {a} × {b} — 按叠层设计放行)")

    big = max(els, key=lambda e: e["rect"][2] * e["rect"][3])
    print(f"\n焦点提示: 最大元素 = {big['name']} ({big['rect'][2]}×{big['rect'][3]})——全片应只有一个这类主角")
    print(f"== 门⑥ 排版网格：" + (f"{len(fails)} 处不过" if fails else "全过"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
