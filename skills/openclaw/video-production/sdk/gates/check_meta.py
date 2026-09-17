#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ⑤ 五件套自检：素材 / 动画 / 转场 / 音效 / 原画面 齐备 + 音效挂载合法
用法：python check_meta.py --project proj.json [--root <REMOTION_PROJECT>]
proj.json:
  {"source": "public/assets/proxy.mp4",
   "materials": ["stock/a.mp4"], "animations": ["FxCardB"], "transitions": ["wipe","slide","zoom","fade"],
   "sfx": [{"file": "sfx/mk-1490-fast-whoosh-transition.mp3", "at": 105, "volume": 0.18}]}
判定：五类非空；sfx 每条有 file/at/volume 且 volume<=0.2、文件存在；source 文件存在。
exit 0=全过；1=缺件/违规
"""
import argparse, json, os, sys

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--root", default=os.environ.get("REMOTION_PROJECT", "."))
    args = ap.parse_args()
    d = json.load(open(args.project, encoding="utf-8"))

    fails = []
    for cat in ["source", "materials", "animations", "transitions", "sfx"]:
        v = d.get(cat)
        n = 1 if (cat == "source" and v) else (len(v) if isinstance(v, list) else 0)
        print(f"{'PASS' if n else 'FAIL'}  五件套[{cat}]: {n} 项")
        if not n:
            fails.append(f"{cat} 缺")

    src = d.get("source")
    if src and not os.path.exists(os.path.join(args.root, src)):
        print(f"FAIL  source 文件不存在: {src}")
        fails.append("source 文件")

    for s in d.get("sfx", []):
        f, at, vol = s.get("file"), s.get("at"), s.get("volume", 1)
        okf = f and os.path.exists(os.path.join(args.root, f))
        okv = isinstance(vol, (int, float)) and vol <= 0.2
        oka = isinstance(at, (int, float))
        st = "PASS" if (okf and okv and oka) else "FAIL"
        print(f"{st}  sfx {os.path.basename(f or '?')}: at={at} vol={vol} file={'有' if okf else '缺'}")
        if st == "FAIL":
            fails.append(f"sfx {f}")

    print(f"\n== 门⑤ 五件套：" + (f"{len(fails)} 处不过 -> {fails}" if fails else "全过（满配）"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
