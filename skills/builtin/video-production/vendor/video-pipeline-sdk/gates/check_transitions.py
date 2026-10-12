#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ② 转场可感知：对每个 A↔B 切点取 cut±span 两帧，算像素变化覆盖率
用法：
  python check_transitions.py --comp FX-Match --cuts 120,213,306,396
  python check_transitions.py --pair a.png b.png              # 直接比对两张现成图
判定：覆盖率 >= threshold(默认 6%) = 可感知 PASS（转场窗口内的全屏变化）
exit 0=全过；1=有 FAIL
"""
import argparse, os, shutil, subprocess, sys

NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"  # Windows：必须解析到 npx.cmd（CreateProcess 不认裸名）


def render_still(project, comp, frame, outpng):
    cmd = [NPX, "remotion", "still", "src/index.ts", comp, outpng, f"--frame={frame}", "--gl=angle"]
    r = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=900)
    return os.path.exists(outpng), (r.stderr or "")[-260:]

def diff_ratio(p1, p2):
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(p1).convert("RGB").resize((640, 360))).astype(int)
    b = np.asarray(Image.open(p2).convert("RGB").resize((640, 360))).astype(int)
    delta = np.abs(a - b).sum(axis=2)
    changed = float((delta > 30).mean())
    return changed, float(delta.mean())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("REMOTION_PROJECT", "."))
    ap.add_argument("--comp")
    ap.add_argument("--cuts", help="逗号分隔切点帧号")
    ap.add_argument("--span", type=int, default=4)
    ap.add_argument("--threshold", type=float, default=0.06)
    ap.add_argument("--pair", nargs=2, help="直接比对两张图")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    fails = 0
    if args.pair:
        ch, md = diff_ratio(*args.pair)
        ok = ch >= args.threshold
        print(f"{'PASS' if ok else 'FAIL'}  pair: 覆盖率 {ch * 100:.1f}% (阈值 {args.threshold * 100:.0f}%) 平均差 {md:.1f}")
        sys.exit(0 if ok else 1)

    if not (args.comp and args.cuts):
        print("需要 --comp 与 --cuts（或用 --pair）"); sys.exit(2)
    outdir = args.out or os.path.join(args.project, "out", "gate2")
    os.makedirs(outdir, exist_ok=True)
    for cut in [int(x) for x in args.cuts.split(",")]:
        ps = []
        for off in (-args.span, args.span):
            p = os.path.join(outdir, f"{args.comp}_f{cut + off}.png")
            ok, err = render_still(args.project, args.comp, cut + off, p)
            if not ok:
                print(f"FAIL  切点 f{cut}: 渲染失败 {err}"); fails += 1; break
            ps.append(p)
        if len(ps) == 2:
            ch, md = diff_ratio(*ps)
            ok = ch >= args.threshold
            print(f"{'PASS' if ok else 'FAIL'}  切点 f{cut} (±{args.span}f): 覆盖率 {ch * 100:.1f}% 平均差 {md:.1f}")
            if not ok: fails += 1
    print(f"\n== 门② 转场可感知：" + (f"{fails} 个切点不过" if fails else "全过"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
