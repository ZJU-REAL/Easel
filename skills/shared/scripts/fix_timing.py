#!/usr/bin/env python3
"""
fix_timing.py - 基于 SRT 时间戳和 shots.json 的 lines 字段，
重建 storyboard.json 中每个镜头的 duration，
使视频镜头时长与配音/字幕完全对齐。

用法：
  python skills/shared/scripts/fix_timing.py \
    --shots   episodes/ep01/shots.json \
    --srt     episodes/ep01/voice.srt \
    --lines   episodes/ep01/lines.json \
    --storyboard episodes/ep01/storyboard.json   # 原版
    -o        episodes/ep01/storyboard_fixed.json # 输出新版
"""
import argparse, json, re, sys
from pathlib import Path


def parse_srt_time(ts: str) -> float:
    """'00:01:23,456' → 83.456"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_srt(srt_path: Path) -> list[tuple[float, float, str]]:
    """返回 [(start, end, text), ...]，按顺序。"""
    text = srt_path.read_text(encoding="utf-8").replace("\r", "")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    result = []
    for b in blocks:
        lines = [l for l in b.split("\n") if l.strip()]
        ts = next((l for l in lines if "-->" in l), None)
        if not ts:
            continue
        start_str, _, end_str = ts.partition("-->")
        content = " ".join(l for l in lines[lines.index(ts) + 1:] if l.strip())
        result.append((parse_srt_time(start_str), parse_srt_time(end_str), content))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots",       required=True)
    ap.add_argument("--srt",         required=True)
    ap.add_argument("--lines",       required=True)
    ap.add_argument("--storyboard",  required=True)
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--min-shot-dur", type=float, default=2.5,
                    help="无台词镜头的最小时长（秒），默认2.5")
    ap.add_argument("--gap", type=float, default=0.25,
                    help="行间间隙额外时长（秒），默认0.25")
    args = ap.parse_args()

    shots_data  = json.loads(Path(args.shots).read_text(encoding="utf-8"))
    lines_data  = json.loads(Path(args.lines).read_text(encoding="utf-8"))
    sb_data     = json.loads(Path(args.storyboard).read_text(encoding="utf-8"))
    srt_blocks  = parse_srt(Path(args.srt))

    shots = shots_data.get("shots", [])
    lines_list = lines_data if isinstance(lines_data, list) else lines_data.get("lines", [])

    # 建立 line_id → SRT index 的映射（lines.json 与 SRT 按顺序对应）
    line_id_to_srt: dict[str, int] = {}
    for i, line in enumerate(lines_list):
        lid = line.get("id", f"L{i+1:02d}")
        if i < len(srt_blocks):
            line_id_to_srt[lid] = i

    # 计算每个镜头的 [start, end] 时间
    shot_times: list[tuple[float, float]] = []
    total_audio = srt_blocks[-1][1] if srt_blocks else 30.0

    for shot in shots:
        line_ids = shot.get("lines", [])
        if not line_ids:
            shot_times.append((None, None))   # 无台词，稍后填充
            continue
        valid_srt_idxs = [line_id_to_srt[lid] for lid in line_ids if lid in line_id_to_srt]
        if not valid_srt_idxs:
            shot_times.append((None, None))
            continue
        first_idx = min(valid_srt_idxs)
        last_idx  = max(valid_srt_idxs)
        start = srt_blocks[first_idx][0]
        end   = srt_blocks[last_idx][1] + args.gap
        shot_times.append((start, end))

    # 建立每个镜头的 [start, duration] 时间线
    # 核心思路：有台词的镜头以 SRT 为准；无台词的镜头从上一镜结束播到下一镜开始

    # 第一步：计算每个镜头的 「期望开始时间」（基于最早台词）
    anchor_starts: list[float | None] = [None] * len(shots)
    anchor_ends:   list[float | None] = [None] * len(shots)  # 该镜头最后一句台词结束

    for i, (s, e) in enumerate(shot_times):
        if s is not None:
            anchor_starts[i] = s
            anchor_ends[i]   = e

    # 第二步：用「前一镜结束时间」填充无台词镜头的 anchor_start
    # 同时用「后一镜开始时间」确定结束时间
    for i in range(len(shots)):
        if anchor_starts[i] is None:
            # 找前一个已知结束时间
            prev_end = next((anchor_ends[j] for j in range(i-1, -1, -1) if anchor_ends[j] is not None), None)
            # 找后一个已知开始时间
            nxt_start = next((anchor_starts[j] for j in range(i+1, len(shots)) if anchor_starts[j] is not None), None)

            if prev_end is None:
                anchor_starts[i] = 0.0
            else:
                anchor_starts[i] = prev_end  # 紧接上一镜台词结束

            if nxt_start is None:
                anchor_ends[i] = min(anchor_starts[i] + args.min_shot_dur, total_audio)
            else:
                anchor_ends[i] = nxt_start   # 下一镜台词开始时结束

    # 第三步：计算每个镜头 duration
    durations: list[float] = []
    for i, shot in enumerate(shots):
        line_ids = shot.get("lines", [])
        s_start = anchor_starts[i] or 0.0
        s_end   = anchor_ends[i]

        if line_ids and s_end is not None:
            dur = max(args.min_shot_dur, s_end - s_start)
        elif s_end is not None:
            dur = max(args.min_shot_dur, s_end - s_start)
        else:
            dur = args.min_shot_dur
        durations.append(round(dur, 3))

    # 输出统计
    total_video = sum(durations)
    print(f"重算时长：{len(shots)} 镜，总视频={total_video:.1f}s，音频={total_audio:.1f}s")
    for i, (d, s) in enumerate(zip(durations, shots)):
        lines_str = ",".join(s.get("lines", [])) or "(无台词)"
        print(f"  shot{i+1:02d} {d:.2f}s  [{lines_str}]")

    # 更新 storyboard.json
    sb_shots = sb_data.get("shots", [])
    # storyboard 里的 shots 只有 caption/video 字段，按顺序对应
    for i, (shot_entry, dur) in enumerate(zip(sb_shots, durations)):
        shot_entry["duration"] = dur

    Path(args.output).write_text(
        json.dumps(sb_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已写入：{args.output}")


if __name__ == "__main__":
    main()
