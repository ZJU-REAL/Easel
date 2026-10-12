#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人审包：每场定格帧 + 核对表（review-pack）——无视觉执行者的人眼兜底
用法：python make_review_pack.py --run-dir <run> [--video 成片路径]
产出：<run>/review/review-pack.md + still-<id>.png（各场中点定格）
说明：从成片抽帧（所见即交付）；核对表对照 scenes.json，供人逐场对照设计表核查。
      残留瑕疵（残影/闪切/错位/状态打架）只有眼睛能抓——这张表就是眼睛的作业单。
exit 0=生成成功；1=缺料
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--video")
    args = ap.parse_args()
    rd = Path(args.run_dir).resolve()
    if not (rd / "run-state.json").is_file() and (rd / "run" / "run-state.json").is_file():
        rd = rd / "run"  # 兼容传成交付目录
    st = json.loads((rd / "run-state.json").read_text(encoding="utf-8"))

    video = Path(args.video) if args.video else rd / "workdir" / "out" / "final.mp4"
    if not video.is_file():
        cand = Path(st.get("out_dir") or "") / "final.mp4"
        video = cand if cand.is_file() else video
    if not video.is_file():
        print(f"FAIL 找不到成片：{video}")
        sys.exit(1)
    scenes_p = rd / "artifacts" / "scenes.json"
    if not scenes_p.is_file():
        print(f"FAIL 缺 scenes.json：{scenes_p}")
        sys.exit(1)

    scenes = json.loads(scenes_p.read_text(encoding="utf-8"))
    sc = scenes.get("scenes") or scenes.get("segments") or []
    out = rd / "review"
    out.mkdir(exist_ok=True)

    rows = []
    for s in sc:
        a, b = s.get("start"), s.get("end")
        if a is None or b is None:
            continue
        mid = (float(a) + float(b)) / 2
        name = f"still-{s.get('id')}.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}", "-i", str(video),
                        "-frames:v", "1", str(out / name)], capture_output=True, text=True)
        ok = (out / name).is_file()
        rows.append((s.get("id"), float(a), float(b), s.get("state", "?"),
                     str(s.get("text") or s.get("kind") or "")[:30], name if ok else "（抽帧失败）"))

    lines = ["# 人审包（review-pack）· 逐场定格核对", "",
             f"> 成片：`{video}` ｜ 共 {len(rows)} 场 ｜ 每场定格帧在本目录 `still-*.png`", "",
             "**核对法**：逐帧对照设计表（`artifacts/design-table.md`）——每场演出/卡片/字幕是否按设计落地。",
             "**重点盯**：残影/重影、A↔B 状态打架、闪切、错位、字幕断档——这些像素门抓不到，只有眼睛能抓。", "",
             "| 场 | 时间 | 状态 | 内容 | 定格帧 | 核对 |",
             "|----|------|------|------|--------|------|"]
    for sid, a, b, stt, txt, name in rows:
        lines.append(f"| {sid} | {a:g}-{b:g}s | {stt} | {txt} | {name} | ☐ |")
    lines += ["", "> 核对后把发现写给执行者（第几场、什么问题、期望什么）——设计/实现的差距从这张表开始收敛。"]
    (out / "review-pack.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK 人审包已生成：{out / 'review-pack.md'}（{len(rows)} 场定格）")
    sys.exit(0)


if __name__ == "__main__":
    main()
