#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门 ④ 素材↔台词对位：校验每支素材有台词映射、窗口合法；抽帧核验表 + 对位表
用法：
  python check_match.py --scenes match.json [--clipsdir <REMOTION_PROJECT>/public/stock] [--out asset-match.md] [--sheet]
match.json（与 FxMatch 的 SCENES 同构）：
  [{"scene":1,"no":"①","sub":"台词","clip":"stock_x.mp4","clip_start":1.0,"dur":4.0,"credit":"..."}, ...]
判定：clip 文件存在 && clip_start+dur <= 素材时长 && sub 非空；--sheet 时抽帧拼核验表。
exit 0=全过；1=有问题
"""
import argparse, json, os, subprocess, sys


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return -1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenes", required=True)
    ap.add_argument("--clipsdir", default=os.environ.get("REMOTION_PROJECT", ".") + "/public/stock")
    ap.add_argument("--out", help="对位表 md 输出")
    ap.add_argument("--sheet", action="store_true", help="抽帧拼核验表 png")
    ap.add_argument("--frame-font", default=os.environ.get("CJK_FONT", "C:/Windows/Fonts/simhei.ttf"))
    args = ap.parse_args()

    scenes = json.load(open(args.scenes, encoding="utf-8"))
    fails = 0
    rows, frames = [], []

    for s in scenes:
        clip = s.get("clip", "")
        p = clip if os.path.isabs(clip) else os.path.join(args.clipsdir, os.path.basename(clip))
        ok_exist = os.path.exists(p)
        dur = probe_duration(p) if ok_exist else -1
        need = float(s.get("clip_start", 0)) + float(s.get("dur", 0))
        ok_win = ok_exist and need <= dur + 0.05
        ok_sub = bool(s.get("sub", "").strip())
        status = "PASS" if (ok_exist and ok_win and ok_sub) else "FAIL"
        if status == "FAIL":
            fails += 1
        print(f"{status}  {s.get('no', '?')} {s.get('sub', '')[:22]!r} | {os.path.basename(clip)} 需{need:.1f}s/有{dur:.1f}s")
        rows.append(f"| {s.get('no', '?')} | {s.get('sub', '')} | {os.path.basename(clip)} | {s.get('clip_start', 0)}–{need:.1f}s | {s.get('credit', '')} |")
        if args.sheet and ok_exist:
            for k, tt in enumerate([s.get("clip_start", 0) + 0.15 * s.get("dur", 3), s.get("clip_start", 0) + 0.75 * s.get("dur", 3)]):
                fp = f"{os.path.splitext(args.out or 'match')[0]}_{s.get('scene', 'x')}_{k}.png"
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{tt:.2f}", "-i", p, "-frames:v", "1", fp],
                               capture_output=True)
                frames.append((fp, s.get("sub", "")[:14], s.get("no", "")))

    if args.out:
        md = ["# 素材 ↔ 台词对位表", "", "| 镜号 | 台词（对应） | 素材 | 用到的窗口 | 来源 |", "|------|--------------|------|-----------|------|"] + rows
        open(args.out, "w", encoding="utf-8").write("\n".join(md) + "\n")
        print(f"\n对位表: {args.out}")

    if frames:
        from PIL import Image, ImageDraw, ImageFont
        cw, ch = 480, 270
        n = len(frames)
        canvas = Image.new("RGB", (cw * min(n, 4), ch * ((n + 3) // 4) + 40), (10, 12, 16))
        dr = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(args.frame_font, 22)
        for i, (fp, sub, no) in enumerate(frames):
            if os.path.exists(fp):
                im = Image.open(fp).convert("RGB").resize((cw, ch))
                x, y = (i % 4) * cw, (i // 4) * ch
                canvas.paste(im, (x, y))
                dr.text((x + 8, y + ch - 30), f"{no} {sub}", font=font, fill=(255, 255, 255))
        sheetp = os.path.splitext(args.out or "match")[0] + "_sheet.png"
        canvas.save(sheetp)
        print(f"抽帧核验表: {sheetp}")

    print(f"\n== 门④ 对位：" + (f"{fails} 处不过" if fails else "全过"))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
