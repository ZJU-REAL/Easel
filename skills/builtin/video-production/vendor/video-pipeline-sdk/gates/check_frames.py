#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ① 帧检：渲染代表帧 + 区域断言（字幕 / 概念动画 / 卡片 / PiP / 脸区零侵入）
用法：
  python check_frames.py --comp FX-CardA --frames 60,120            # 只渲帧 + 拼图（人眼模式）
  python check_frames.py --comp FX-CardA --frames 120 --checks checks.json
checks.json 示例：
  [{"name":"胶囊存在","frame":120,"region":[500,64,1420,160],"type":"variance","min":12},
   {"name":"字幕白像素","frame":120,"region":[400,900,1520,1030],"type":"bright","min":1.5},
   {"name":"accent 青","frame":120,"region":[640,252,1280,652],"type":"color","target":[34,211,238],"min":800},
   {"name":"脸区零侵入","frame":120,"region":[700,150,1220,700],"type":"color","target":[201,90,58],"dist":60,"min":0,"max":200}]
type: variance(区域 std>=min) | bright(亮像素%>=min) | color(距 target<dist 像素数, 判 min<=n<=max)
exit 0=全过；1=有 FAIL
"""
import argparse, json, os, shutil, subprocess, sys

NPX = shutil.which("npx") or shutil.which("npx.cmd") or "npx"  # Windows：必须解析到 npx.cmd（CreateProcess 不认裸名）


def render_still(project, comp, frame, outpng):
    cmd = [NPX, "remotion", "still", "src/index.ts", comp, outpng, f"--frame={frame}", "--gl=angle"]
    r = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=900)
    return os.path.exists(outpng), (r.stderr or "")[-260:]

def analyze(img_path, checks):
    from PIL import Image
    import numpy as np
    a = np.asarray(Image.open(img_path).convert("RGB")).astype(int)
    out = []
    for c in checks:
        x1, y1, x2, y2 = c["region"]
        reg = a[y1:y2, x1:x2]
        t = c["type"]
        if t == "variance":
            v = float(reg.std()); ok = v >= c["min"]; d = f"std={v:.1f} (min {c['min']})"
        elif t == "bright":
            p = float((reg.sum(axis=2) > 600).mean() * 100); ok = p >= c["min"]; d = f"bright%={p:.2f} (min {c['min']})"
        elif t == "color":
            target = np.array(c["target"])
            n = int((np.abs(reg - target).sum(axis=2) < c.get("dist", 80)).sum())
            lo, hi = c["min"], c.get("max", 10 ** 9)
            ok = lo <= n <= hi; d = f"colorPx={n} (需 {lo}..{hi})"
        else:
            ok, d = False, f"未知 type={t}"
        out.append((c.get("name", "?"), ok, d))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("REMOTION_PROJECT", "."))
    ap.add_argument("--comp", required=True)
    ap.add_argument("--frames", required=True, help="逗号分隔，如 60,120")
    ap.add_argument("--checks", help="checks.json 路径（可选；不给=人眼模式）")
    ap.add_argument("--out", default=None, help="输出目录，默认 <project>/out/gate1")
    args = ap.parse_args()

    outdir = args.out or os.path.join(args.project, "out", "gate1")
    os.makedirs(outdir, exist_ok=True)
    frames = [int(x) for x in args.frames.split(",")]
    files = {}
    for f in frames:
        p = os.path.join(outdir, f"{args.comp}_f{f}.png")
        ok, err = render_still(args.project, args.comp, f, p)
        print(f"[render] {args.comp} f{f} -> {'OK' if ok else 'FAIL ' + err}")
        files[f] = p

    fails = 0
    if args.checks:
        checks = json.load(open(args.checks, encoding="utf-8"))
        for c in checks:
            fr = c.get("frame", frames[0])
            img = files.get(fr) or os.path.join(outdir, f"{args.comp}_f{fr}.png")
            if not os.path.exists(img):
                print(f"FAIL  {c.get('name')}: 帧 {fr} 未渲染"); fails += 1; continue
            for name, ok, d in analyze(img, [c]):
                print(f"{'PASS' if ok else 'FAIL'}  {name}: {d}")
                if not ok: fails += 1
    print(f"\n== 门① 帧检：{len(frames)} 帧渲染，" + (f"{fails} 项不过" if fails else "全过（人眼模式：看 {outdir}）"))
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
