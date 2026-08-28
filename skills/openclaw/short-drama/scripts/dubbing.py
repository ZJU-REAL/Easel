#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dubbing.py — 短剧多角色配音（--series/--episode 便利层，委派通用引擎 multivoice.py）。

短剧的配音核心逻辑已下沉到 `skills/shared/scripts/multivoice.py`（可复用引擎：
cast + lines → 多声线 voice.mp3 + srt）。本脚本只做短剧特有的**路径便利**：
把 `--series/--episode` 映射到 `outputs/<剧名>/cast.json` 与
`episodes/epNN/lines.json`，再委派引擎。其它工作流（论文双人问答、访谈…）直接用
multivoice.py + 显式文件路径，或走 multi-voice-dubbing SKILL。

子命令（同引擎，只是路径由 series/episode 推导）：
    cast init/add/list/check --series <剧名>
    plan  --series <剧名> --episode N              生视频前：按台词估每镜时长 + 检查能否塞进片段档（塞不下拆镜）
    dub   --series <剧名> --episode N              旧：逐行配音（均分，画面/字幕可能对不齐）
    align --series <剧名> --episode N              真配音后：逐镜对齐锁定精确时长（推荐）
    selftest    委派引擎自检

用法：
    dubbing.py cast init --series "逆袭甜妻"
    dubbing.py cast add  --series "逆袭甜妻" --name 林策 --engine clone --provider openai-compatible \
        --voice-id FunAudioLLM/CosyVoice2-0.5B:alex --note "冷峻男主，低沉磁性（贴定妆图）"
    dubbing.py plan      --series "逆袭甜妻" --episode 1   # 生视频前规划每镜时长
    dubbing.py align     --series "逆袭甜妻" --episode 1   # 真配音后锁定（lines.json 每行需标 shot）
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared" / "scripts"))
import multivoice as mv  # noqa: E402  通用配音引擎

DEFAULT_ROOT = "outputs"


def _series_dir(root: str, series: str) -> Path:
    if not series.strip():
        mv._die("--series 剧名不能为空")
    return (Path(root).expanduser() / series).resolve()


def _cast_file(root: str, series: str) -> Path:
    return _series_dir(root, series) / "cast.json"


def _ep_dir(root: str, series: str, episode: int) -> Path:
    return _series_dir(root, series) / "episodes" / f"ep{episode:02d}"


def _ref_characters(root: str, series: str) -> list[dict]:
    """读 ref_index.json 里已登记的**角色定妆图**（kind==character）→ [{code,name}]。
    用于 cast check 交叉核对：有定妆图的角色都应被配音，且音色贴合其画面形象。"""
    ri = _series_dir(root, series) / "ref_index.json"
    data = mv._load_json(ri, {"refs": []})
    return [{"code": r.get("code"), "name": r.get("name")}
            for r in data.get("refs", []) if r.get("kind") == "character" and r.get("name")]


def _align(root: str, series: str, episode: int, out: Path | None,
           gap: float, min_shot: float, tail: float, proxy: str | None,
           lenient: bool = False, allow_edge: bool = False) -> int:
    """逐镜对齐配音：画面时长=该镜台词时长，配音/字幕与画面帧对齐。

    读 lines.json（每行带 shot）+ shots.json，无台词的动作镜用其 clip 实测时长，
    调 mv.dub_grouped，并把每镜时长写回 shots.json 的 duration（供 storyboard/assemble）。
    lines 未标 shot 或缺 shots.json → 退回旧 dub（均分，画面/字幕可能对不齐）。
    """
    ep = _ep_dir(root, series, episode)
    cast_file = _cast_file(root, series)
    lines_file = ep / "lines.json"
    shots_file = ep / "shots.json"
    out = out or (ep / "voice.mp3")
    if not lines_file.exists():
        mv._die(f"未找到 {lines_file}（先让 LLM 把脚本抽成逐行对白 lines.json，每行标 speaker+shot）")
    lines = mv._load_json(lines_file, {}).get("lines", [])
    if not lines:
        mv._die("lines.json 的 lines 为空")

    has_shot = any(ln.get("shot") is not None for ln in lines)
    if not has_shot or not shots_file.exists():
        print("⚠️ lines.json 未标注 shot（或缺 shots.json）→ 退回旧均分配音，"
              "画面/字幕可能对不齐；建议给每行加 shot 后用 align 逐镜对齐。", file=sys.stderr)
        r = mv.dub(cast_file, lines_file, out, None, gap, proxy, allow_edge=allow_edge)
        print(f"✅ 配音完成（旧均分）：{r['voice']}（{r['lines']} 行，{r['duration']}s，"
              f"{len(r['voices'])} 种声线）\n   字幕：{r['srt']}")
        return 0

    shots_data = mv._load_json(shots_file, {})
    shots = shots_data.get("shots", [])
    group_order = [s.get("idx") for s in shots if s.get("idx") is not None]
    if not group_order:
        mv._die("shots.json 无有效镜头 idx")

    # 严格校验台词归属：speaker 必须在 cast、shot 必须在分镜内（治「配音配错角色」）
    cast = mv.cast_load(cast_file)
    probs = mv.validate_lines(cast, lines, set(group_order))
    if probs:
        msg = ("台词归属校验未通过（会导致配错角色/时机）：\n  - "
               + "\n  - ".join(probs)
               + "\n修正 lines.json 的 speaker/shot（写剧本时就把谁说哪句分清），"
                 "或确需继续用 --lenient（未知说话人会回退旁白音色）。")
        if lenient:
            print(f"⚠️ {msg}", file=sys.stderr)
        else:
            mv._die(msg)

    def _resolve_clip(clip: str | None) -> Path | None:
        """按多个基准找 clip 文件：原样(CWD)→ episode 目录 → series 目录。找不到返回 None。"""
        if not clip:
            return None
        for cand in (Path(clip), ep / clip, ep.parent.parent / clip):
            if cand.is_file():
                return cand
        return None

    # 探测每个**真实生成的视频片段**时长（=画面自然时长）。align 必须在片段都生成好之后跑：
    # 画面时长严格 = 真实片段时长，绝不用台词长度去凑（那才会导致 assemble 冻结/拉伸、画面割裂）。
    line_shots = {ln.get("shot") for ln in lines if ln.get("shot") is not None}
    action_durs: dict = {}   # 无台词镜 → 画面时长（真实片段）
    clip_durs: dict = {}     # 有台词镜 → 真实片段时长
    missing: list = []       # 有台词却没有可用视频片段的镜
    for s in shots:
        idx = s.get("idx")
        rp = _resolve_clip(s.get("clip"))
        d = mv._probe_dur(rp) if rp else 0.0
        if d <= 0:
            if idx in line_shots:
                missing.append(idx)
            continue
        if idx in line_shots:
            clip_durs[idx] = round(d, 3)
        else:
            action_durs[idx] = round(d, 3)
    if missing and not lenient:
        mv._die(
            f"这些有台词的镜还没有可用的视频片段(clip)：{sorted(missing)}。\n"
            f"⚠️ align 必须在**每镜都生成好 I2V 视频片段之后**跑——它按真实片段时长对齐配音；"
            f"片段缺失会导致画面被迫冻结/拉伸凑台词长度、割裂不流畅。\n"
            f"请先对这些镜用 ai-video-gen 图生视频，把 clip 路径写回 shots.json，再重跑 align。")

    # 硬门：align 前必须先跑 audit（步骤18）。audit 逐镜判 native/dub/regenerate；缺了它就没有任何镜是
    # native → 所有画内对白都被当 dub 走 TTS、丢弃视频模型原声——这正是「没用原声、直接 TTS」的根因。
    # 过去这里对缺失文件默认空 dict、静默降级成全配音（抄近路不报错），现改为硬失败。
    audit_path = ep / "clip-audit.json"
    dialogue_shots = {ln.get("shot") for ln in lines
                      if ln.get("shot") is not None and ln.get("speaker") != mv.NARRATOR}
    if dialogue_shots:
        if not audit_path.exists():
            _msg = (f"缺 {audit_path.name}：还没跑 audit（步骤18）。没有逐镜 native/dub 决策，align 会把所有\n"
                    f"画内对白当 dub 全程 TTS、丢弃视频模型原声（=没用原声、直接配音）。\n"
                    f"请先跑：dubbing.py audit --series \"{series}\" --episode {episode} --language <zh-CN>，再 align。")
            if lenient:
                print(f"⚠️ {_msg}", file=sys.stderr)
            else:
                mv._die(_msg)
        else:
            _covered = {x.get("shot") for x in mv._load_json(audit_path, {}).get("shots", [])}
            _uncovered = sorted(dialogue_shots - _covered)
            if _uncovered and not lenient:
                mv._die(f"clip-audit.json 未覆盖这些有台词的镜：{_uncovered}（分镜/台词变更后需重跑 audit）。\n"
                        f"请重跑：dubbing.py audit --series \"{series}\" --episode {episode} --language <zh-CN>，再 align。")
    audit = mv._load_json(audit_path, {})
    audit_by_shot = {x.get("shot"): x for x in audit.get("shots", [])}
    native_shots = {idx for idx, item in audit_by_shot.items() if item.get("decision") == "native"}
    conflicts = [idx for idx in native_shots
                 if audit_by_shot[idx].get("target")
                 and any(ln.get("shot") == idx and ln.get("speaker") == mv.NARRATOR for ln in lines)]
    if conflicts:
        mv._die(f"镜 {conflicts} 同时包含原生画内对白和旁白，无法保证两条人声不重叠；"
                "请把旁白移到相邻动作镜或拆镜后重新 prepare/audit。")
    # 通过审计的画内对白直接使用视频原音；旁白始终保留在独立配音轨。
    synth_lines = [ln for ln in lines
                   if not (ln.get("shot") in native_shots and ln.get("speaker") != mv.NARRATOR)]
    r = mv.dub_grouped(cast_file, synth_lines, group_order, action_durs, out,
                       srt_out=None, timing_out=ep / "timing.json",
                       gap=gap, min_shot=min_shot, tail=tail, proxy=proxy,
                       clip_durs=clip_durs, strict=not lenient, allow_edge=allow_edge,
                       allow_empty=True)
    # 把原生对白的 ASR 时间戳合并回字幕/时间轴；配音轨对应位置保持静音，合成时由原片 AAC 提供声音。
    if native_shots:
        timing_path = Path(r["timing"])
        timing_data = mv._load_json(timing_path, {})
        merged = list(timing_data.get("lines", []))
        offset = 0.0
        shot_offsets = {}
        for shot_id in r["shot_durations"]:
            shot_offsets[shot_id] = offset
            offset += float(r["shot_durations"][shot_id])
        # 按镜分组原生对白行（一镜可多句）
        native_by_shot: dict = {}
        for original_idx, ln in enumerate(lines):
            shot_id = ln.get("shot")
            if shot_id in native_shots and ln.get("speaker") != mv.NARRATOR:
                native_by_shot.setdefault(shot_id, []).append((original_idx, ln))
        for shot_id, items in native_by_shot.items():
            aud = audit_by_shot[shot_id]
            asr_start, asr_end = aud.get("speech_start"), aud.get("speech_end")
            shot_dur = float(r["shot_durations"].get(shot_id, 0.0))
            if len(items) == 1 and asr_start is not None:
                # 单句：直接用 ASR 实测起止（最准）
                spans = [(float(asr_start), float(asr_end if asr_end is not None else asr_start))]
            else:
                # 多句（或无 ASR 起止）：按 at 定位，缺 at 从 asr_start/0 顺排 + 句间小停顿
                spans, cursor = [], (float(asr_start) if asr_start is not None else 0.0)
                for _, ln in items:
                    st = max(float(ln["at"]) if ln.get("at") is not None else cursor, cursor, 0.0)
                    en = round(st + mv.estimate_line_seconds(str(ln.get("text") or ""), ln.get("emotion")), 3)
                    if shot_dur:
                        en = min(en, shot_dur)
                    spans.append((round(st, 3), en))
                    cursor = round(en + 0.2, 3)
            for (original_idx, ln), (start_in, end_in) in zip(items, spans):
                merged.append({"idx": original_idx, "shot": shot_id, "speaker": ln.get("speaker"),
                               "text": ln.get("text"), "at": round(start_in, 3),
                               "start": round(shot_offsets[shot_id] + start_in, 3),
                               "end": round(shot_offsets[shot_id] + end_in, 3), "audio": "native"})
        merged.sort(key=lambda x: (x["start"], x["end"]))
        timing_data["lines"] = merged
        timing_path.write_text(json.dumps(timing_data, ensure_ascii=False, indent=2), encoding="utf-8")
        srt_path = Path(r["srt"])
        srt_path.write_text("\n".join(
            f"{i}\n{mv._srt_ts(x['start'])} --> {mv._srt_ts(x['end'])}\n{x['text']}\n"
            for i, x in enumerate(merged, 1)), encoding="utf-8")
    # 把每镜时长写回 shots.json（供 drama_ops storyboard / assemble 逐镜精确对齐）
    sd = r["shot_durations"]
    for s in shots:
        if s.get("idx") in sd:
            s["duration"] = sd[s["idx"]]
    shots_file.write_text(json.dumps(shots_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 逐镜对齐配音完成：{r['voice']}（{r['lines']} 行，{r['duration']}s，"
          f"{len(r['voices'])} 种声线）\n   字幕：{r['srt']}\n   时间轴：{r['timing']}"
          f"\n   声线：{'、'.join(r['voices'])}\n   已写回 {len(sd)} 个镜头时长到 shots.json")
    return 0


def _plan(root: str, series: str, episode: int, gap: float, min_shot: float, tail: float,
          clip_cap: float = 5.0, clip_max: float = 10.0) -> int:
    """生视频前规划：按台词估每镜停留时长，并**检查能否塞进一个可生成的片段**。

    现实约束：AI 视频只能生成**固定档位**（多为 5s，部分 5/10s），**无法按任意秒数出片**。
    所以规划的目的是：①估出每镜台词时长（=最终画面应停留的时间）②**保证每镜台词能塞进一个片段档**
    （塞不下就拆镜/精简台词，别硬生成后靠拉伸）③给出该镜建议生成的片段档位。
    生成后 assemble 会把固定档片段**裁到精确台词时长**（画面连续、不冻结）。
    """
    ep = _ep_dir(root, series, episode)
    lines_file = ep / "lines.json"
    shots_file = ep / "shots.json"
    if not lines_file.exists() or not shots_file.exists():
        mv._die(f"需要 {lines_file} 与 {shots_file}（先写好逐行对白+分镜，每行标 speaker+shot）")
    lines = mv._load_json(lines_file, {}).get("lines", [])
    if not lines:
        mv._die("lines.json 的 lines 为空")
    shots_data = mv._load_json(shots_file, {})
    shots = shots_data.get("shots", [])
    group_order = [s.get("idx") for s in shots if s.get("idx") is not None]
    if not group_order:
        mv._die("shots.json 无有效镜头 idx")
    line_shots = {ln.get("shot") for ln in lines}
    action_hint = {s["idx"]: float(s["target_duration"])
                   for s in shots if s.get("idx") not in line_shots and s.get("target_duration")}
    lay = mv.plan_shot_durations(lines, group_order, action_hint, gap, min_shot, tail)
    for w in lay["warns"]:
        print(f"⚠️ {w}", file=sys.stderr)
    sd = lay["shot_durations"]

    over = []  # 台词超过单片段档、需拆镜的镜
    print(f"# 第 {episode} 集 时长规划（按台词估算，总 ~{lay['total']}s）")
    print(f"{'镜':<4}{'字数':<6}{'台词时长(s)':<12}{'建议片段档(s)':<14}{'提示'}")
    for s in shots:
        idx = s.get("idx")
        if idx not in sd:
            continue
        est = sd[idx]
        chars = sum(len((ln.get("text") or "").strip()) for ln in lines if ln.get("shot") == idx)
        # 建议生成档位：最小的 ≥est 的允许档（clip_cap，其次 clip_max）
        if est <= clip_cap:
            gen = clip_cap; tip = ""
        elif est <= clip_max:
            gen = clip_max; tip = "台词较长，用大档"
        else:
            gen = clip_max; tip = "⚠️ 台词超过最大片段档 → 拆镜或精简台词"
            over.append(idx)
        s["target_duration"] = est          # 最终画面应停留的时长（=台词时长）
        s["gen_duration"] = gen             # 生视频请求的片段档位（provider 允许值）
        s["span"] = f"0-{est}s"
        kind = "台词" if idx in line_shots else "动作"
        print(f"{idx:<4}{chars:<6}{est:<12}{gen:<14}{tip}（{kind}）")
    shots_file.write_text(json.dumps(shots_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 已写回 target_duration/gen_duration/span 到 shots.json")
    if over:
        print(f"❌ 镜 {over} 台词超过单片段最大档（{clip_max}s）→ 必须拆成多镜或精简台词；"
              f"在修正前禁止进入视频生成。", file=sys.stderr)
        return 1
    print("   生视频：`ai-video-gen ... --duration <该镜 gen_duration>`（provider 只认固定档，"
          "多为 5s/部分 5·10s）；生成后 align + assemble 会按台词把片段**裁到精确时长**（画面连续、不冻结）。")
    return 0


def _norm_text(text: str) -> str:
    # \u7e41\u4f53\u2192\u7b80\u4f53\uff1awhisper \u5e38\u628a\u7b80\u4f53\u4e2d\u6587\u8f6c\u5199\u6210\u7e41\u4f53\uff0c\u82e5\u4e0d\u5f52\u4e00\u4f1a\u8ba9\u672c\u6765\u8bf4\u5bf9\u7684\u539f\u751f\u5bf9\u767d\u76f8\u4f3c\u5ea6\u865a\u4f4e\u3001
    # \u88ab audit \u8bef\u5224 mismatch \u964d\u7ea7\u6210 dub\uff08\u4e0e ai_video \u63a2\u9488\u540c\u4e00\u5904\u7406\uff09\u3002
    text = text or ""
    try:
        import zhconv
        text = zhconv.convert(text, "zh-cn")
    except Exception:  # noqa: BLE001 \u2014 \u7f3a zhconv \u5c31\u9000\u56de\u539f\u6587\uff08\u4e0d\u5f71\u54cd\u82f1\u6587/\u5df2\u7b80\u4f53\uff09
        pass
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.lower())


def _has_audio(path: Path) -> bool:
    cp = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
                        text=True, capture_output=True)
    return cp.returncode == 0 and bool(cp.stdout.strip())


def _dialogue_faithful(dialogue_mode: str, provider: str | None = None,
                       model: str | None = None) -> tuple[bool, str, str | None, str | None]:
    """当前配置的视频模型能否逐字忠实生成台词。返回 (faithful, source, provider, model)。
    dialogue_mode: auto=按 ai_video capability；faithful/dub=强制。
    source: forced（显式指定）/ env（VIDEO_CAPABILITIES_JSON）/ probe（探针实测）/ default（未实测默认）/ error。"""
    try:
        import ai_video  # shared/scripts 已在 sys.path
        provider = ai_video.resolve_provider(provider)
        model = ai_video.resolve_model(provider, model, image=True)
        if dialogue_mode == "faithful":
            return True, "forced", provider, model
        if dialogue_mode == "dub":
            return False, "forced", provider, model
        cap = ai_video.provider_capabilities(provider, model)
        return bool(cap.get("dialogue_faithful")), ai_video.dialogue_faithful_source(provider, model), provider, model
    except (Exception, SystemExit):  # noqa: BLE001 — provider 缺失时 resolve_provider 会 sys.exit
        if dialogue_mode == "faithful":
            return True, "forced", provider, model
        if dialogue_mode == "dub":
            return False, "forced", provider, model
        return False, "error", None, None


def _prepare(root: str, series: str, episode: int, language: str,
             dialogue_mode: str = "auto", force_dub: bool = False,
             video_provider: str | None = None, video_model: str | None = None) -> int:
    """生成 provider 无关的音频契约和 prompt；具体请求字段由 ai_video capability 适配。

    **默认 native-first（能说就用模型原声）**；只有 probe-dialogue 实测判「不逐字忠实」（或 --dialogue-mode dub）
    才对画内对白改用 dub-reserve。两种画内对白契约：
    - 忠实（默认）→ native-first：要求模型逐字说出台词，成片直接用原生对白（audit 通过则不配音，这是常态）。
    - 不忠实 → dub-reserve：生成阶段**不给台词**，人物只做清晰说话口型 + 预留说话时长（利于后期配音对口型），
      台词后期 TTS 配上。注意：该镜 audit 会判 dub，assemble 会**丢弃其原生轨、纯 TTS**（无人声分离时保留会与配音重复），
      故 dub 镜不保留环境音。
    """
    ep = _ep_dir(root, series, episode)
    shots_file = ep / "shots.json"
    data = mv._load_json(shots_file, {})
    shots = data.get("shots", [])
    lines = mv._load_json(ep / "lines.json", {}).get("lines", [])
    faithful, faithful_src, fp, fm = _dialogue_faithful(
        dialogue_mode, video_provider, video_model)
    has_dialogue = any(x.get("speaker") != mv.NARRATOR for x in lines)
    # 硬门：别用 --dialogue-mode dub 一键绕开 native-first。全剧 dub = 台词根本不喂模型、放弃原生音频与
    # 环境音，只有「实测模型不忠实」或「用户明确要 dub」才该走。撞到「多句同镜」不是理由——多句可直接
    # 一起写进 generation_prompt（本函数已支持）。逼 agent 别顺手 dub。
    if dialogue_mode == "dub" and has_dialogue and not force_dub:
        auto_f, auto_src, _, _ = _dialogue_faithful("auto", video_provider, video_model)
        if not (auto_src == "probe" and auto_f is False):
            mv._die(
                "拒绝全剧 dub：--dialogue-mode dub 会让台词不进视频模型、放弃原生音频与环境音。\n"
                "默认 native-first——让模型直接说台词，audit 再对**真说错的镜**逐镜换 TTS（多数镜仍用原声/环境音）。\n"
                "多句对白同镜？把多句都写进 generation_prompt 即可（已支持），不必为此改 dub。\n"
                "真要全剧 dub：先 `ai_video.py probe-dialogue` 实测模型不忠实，或显式加 `--force-dub` 覆盖。")
    if dialogue_mode == "dub" and force_dub:
        print("⚠️ --force-dub：全剧走 dub-reserve，放弃原生音频/环境音（对白全后期 TTS）。", file=sys.stderr)
    # dialogue_faithful 只是**可选诊断**、不强制、不阻塞（真正治「台词全对不上」的是把台词喂进
    # generation_prompt，由 shots validate --pre-video 硬门保证）。auto 未实测/读不到能力 → **默认
    # native-first**（直接让模型逐字说台词），audit 会逐镜兜底（说错的镜自动转 dub、保环境音）。
    # 只有探针/配置**实测判 false** 才走 dub-reserve；对白不准时再按提示跑 probe-dialogue 诊断。
    if dialogue_mode == "auto" and faithful_src in ("default", "error") and has_dialogue:
        faithful = True
        print(f"ℹ️ 视频模型 {fp or '?'}:{fm or '默认'} dialogue_faithful 未实测 → 默认 native-first（直接让模型说台词，"
              "audit 逐镜兜底）。若成片对白不准，可选做 `ai_video.py probe-dialogue` 检测，不忠实再 `--dialogue-mode dub`。",
              file=sys.stderr)
    n_faithful = n_dubreserve = n_ambient = 0
    problems = []
    for shot in shots:
        idx = shot.get("idx")
        dialogue = [x for x in lines if x.get("shot") == idx and x.get("speaker") != mv.NARRATOR]
        narrations = [x for x in lines if x.get("shot") == idx and x.get("speaker") == mv.NARRATOR]
        if dialogue and narrations:
            problems.append(f"镜 {idx} 同时有画内对白和旁白；请拆镜，避免原生人声与旁白重叠")
            continue
        base = str(shot.get("prompt") or shot.get("desc") or "").strip()
        if dialogue:
            # 一镜可有多句画内对白（视频模型能连着说）——逐句按 at 排时间窗（缺 at 则顺排+句间小停顿），
            # 全部塞进 generation_prompt。累计末尾须塞进片段档。
            cap = float(shot.get("gen_duration") or shot.get("target_duration") or 0)
            placed = []          # [(line, start, end)]
            cursor = 0.0
            for li in dialogue:
                st = float(li["at"]) if li.get("at") is not None else (0.6 if not placed else cursor)
                st = max(st, cursor, 0.0)
                en = round(st + mv.estimate_line_seconds(str(li.get("text") or ""), li.get("emotion")), 2)
                placed.append((li, round(st, 2), en))
                cursor = round(en + 0.3, 2)   # 句间小停顿
            last_end = placed[-1][2]
            if cap and last_end > cap - mv.DEFAULT_TAIL:
                n = len(placed)
                problems.append(f"镜 {idx} {n} 句对白预计到 {last_end}s，超过片段可用时间 {cap}s → 精简台词或拆镜")
                continue
            req_lines = [{"speaker": li.get("speaker"), "text": li.get("text"),
                          "start": s, "end": e} for li, s, e in placed]
            if faithful:
                # 模型逐字忠实 → 让它按顺序直接说台词，成片用原生对白
                n_faithful += 1
                request = {"mode": "native-first", "language": language, "lines": req_lines}
                seq = "；".join(
                    f'{s:.2f} 秒起 角色“{li.get("speaker")}”逐字说：\"{li.get("text")}\"'
                    for li, s, e in placed)
                speakers = "、".join(dict.fromkeys(li.get("speaker") for li, _, _ in placed))
                contract = (
                    f"\n\n【音频硬约束】生成有声视频。使用{language}，按时间顺序：{seq}。"
                    f"只允许上述说话人（{speakers}）在各自时段开口，其他角色全程不得开口；"
                    "必须逐字说，禁止翻译、改写、增删或重复台词。"
                    "说话期间说话者嘴部清晰可见并与声音同步；台词之间与结束后只保留与动作同步的"
                    "自然环境声和音效，不添加旁白或背景音乐。")
            else:
                # 模型不逐字忠实 → 生成阶段不给台词：只做说话口型 + 预留说话时长，后期配音
                n_dubreserve += 1
                request = {"mode": "dub-reserve", "language": language, "lines": req_lines}
                seq = "；".join(
                    f'{s:.2f}–{e:.2f} 秒 角色“{li.get("speaker")}”做清晰自然的说话口型'
                    for li, s, e in placed)
                contract = (
                    f"\n\n【音频硬约束】生成有声视频。{seq}（像正在讲话），"
                    "但**绝对不要产生任何可辨识的台词、词句、歌声或人声语音内容**——具体台词由后期配音补上。"
                    "整段只保留与画面动作同步的自然环境声和动作音效，不添加旁白或背景音乐；未列出的角色全程不得开口。"
                    "请务必为各说话时段预留口型与时长。")
        else:
            n_ambient += 1
            request = {"mode": "ambient-only", "language": language}
            contract = ("\n\n【音频硬约束】生成有声视频，但所有人物全程不得说话，不得生成旁白、"
                        "歌声或可识别语音；只生成与画面动作同步的自然环境声和动作音效，不添加背景音乐。")
        shot["audio_request"] = request
        shot["generation_prompt"] = base + contract
    if problems:
        mv._die("原生对白准备失败：\n  - " + "\n  - ".join(problems))
    if fp:
        data["video_generation"] = {"provider": fp, "model": fm or ""}
    shots_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _src_label = {"forced": "强制指定", "env": "VIDEO_CAPABILITIES_JSON 配置",
                  "probe": "探针实测", "default": "未实测默认", "error": "能力读取失败·保守"}.get(faithful_src, faithful_src)
    print(f"✅ 已写入 {len(shots)} 镜 provider 无关 audio_request/generation_prompt：{shots_file}")
    print(f"   模型逐字忠实={faithful}（来源：{_src_label}）")
    if fp:
        print(f"   已锁定视频模型：{fp}:{fm or '默认'}（generate 必须复用）")
    print(f"   契约分布：native-first(原生对白直通) {n_faithful} / "
          f"dub-reserve(不给台词·留口型·后期配音) {n_dubreserve} / ambient-only(无对白) {n_ambient}")
    if n_dubreserve:
        print("   ↳ dub-reserve 镜：生成的原生轨应只有环境音；台词由 align 后期 TTS 配入预留窗口。")
    return 0


def _decide_audio(*, has_audio: bool, asr_ok: bool, target: str, score: float,
                  language_ok: bool, n_dialogue: int, has_segs: bool,
                  threshold: float) -> tuple[str, str]:
    """由片段音频/ASR 结果决定 (decision, reason)。环境音优先，纯函数便于单测。

    - 无原音 → dub（no_native_audio）：无环境音可留，纯配音。
    - ASR 读不出 → regenerate（asr_unreadable）：无法判人声好坏，重生成。
    - 有画内对白（≥1 句）+ 语言正确 + 整段相似度达标 → native：整轨原音（人声+环境音）直通 + 字幕。
    - 有对白但人声坏了（语言错/内容不符）→ dub（native_dialogue_bad）：换配音，
      该镜原生轨在 assemble 里整轨丢弃、纯 TTS（无人声分离时保留会与配音双重人声）。
    - 动作镜意外语音 → regenerate（unexpected_native_speech）：无 TTS 可掩盖、无分离无法单独去除。
    - 纯动作/环境音 → native（ambient_or_action_audio）：保留原生环境音。
    """
    if not has_audio:
        return "dub", "no_native_audio"
    if not asr_ok:
        return "regenerate", "asr_unreadable"
    if n_dialogue >= 1 and target and score >= threshold and language_ok:
        return "native", "native_dialogue_matches"
    if target:
        return "dub", "native_dialogue_bad"
    if has_segs:
        return "regenerate", "unexpected_native_speech"
    return "native", "ambient_or_action_audio"


def _audit(root: str, series: str, episode: int, model: str, threshold: float,
           expected_language: str) -> int:
    """用原片 ASR 复核生成模型实际说了什么、何时说，避免盲目沿用计划 at。"""
    if not shutil.which("ffprobe"):
        mv._die("audit 需要 ffprobe")
    ep = _ep_dir(root, series, episode)
    shots = mv._load_json(ep / "shots.json", {}).get("shots", [])
    lines = mv._load_json(ep / "lines.json", {}).get("lines", [])
    # 硬门：audit 前必须先跑 prepare（步骤16）。prepare 把逐字台词写进每镜 generation_prompt/audio_request，
    # 生视频时再喂给模型；缺这俩字段 = 没跑 prepare 就直接生了视频（抄近路），台词没喂给模型、原生对白必然对不上。
    # 不拦的话 audit 会把这些镜判 dub、下游全程 TTS，用户就看到「没喂台词、没用原声、直接配音」。
    _missing_prep = sorted(
        s.get("idx") for s in shots
        if any(x.get("shot") == s.get("idx") and x.get("speaker") != mv.NARRATOR for x in lines)
        and not (s.get("generation_prompt") and s.get("audio_request")))
    if _missing_prep:
        mv._die(
            f"这些有台词的镜没有 generation_prompt/audio_request：{_missing_prep}。\n"
            f"说明没跑 prepare（步骤16）就直接生了视频——台词没喂给模型，成片原生对白必然对不上。\n"
            f"请先跑：dubbing.py prepare --series \"{series}\" --episode {episode} --language <zh-CN>，"
            f"对这些镜**带 generation_prompt 重新生视频**，再回来 audit。")
    asr_script = Path(__file__).resolve().parents[3] / "shared" / "scripts" / "asr.py"
    report = {"episode": episode, "policy": "native-first", "threshold": threshold,
              "expected_language": expected_language, "shots": []}
    hard_fail = False
    for shot in shots:
        idx = shot.get("idx")
        clip = shot.get("clip")
        dialogue_lines = [x for x in lines
                          if x.get("shot") == idx and x.get("speaker") != mv.NARRATOR]
        target = "".join(str(x.get("text") or "") for x in dialogue_lines)
        rp = None
        if clip:
            for candidate in (Path(clip), ep / clip, ep.parent.parent / clip):
                if candidate.is_file():
                    rp = candidate
                    break
        item = {"shot": idx, "clip": str(rp) if rp else clip, "target": target,
                "native_audio": False, "segments": [], "match": 0.0, "decision": "regenerate"}
        if rp is None:
            item["reason"] = "clip_missing"
            hard_fail = True
        elif not _has_audio(rp):
            d, r = _decide_audio(has_audio=False, asr_ok=False, target="", score=0.0,
                                 language_ok=False, n_dialogue=0, has_segs=False, threshold=threshold)
            item.update({"decision": d, "reason": r})
        else:
            item["native_audio"] = True
            asr_out = ep / f".audit-shot-{idx}.json"
            cp = subprocess.run([sys.executable, str(asr_script), "transcribe", "-i", str(rp),
                                 "--model", model, "--format", "json", "-o", str(asr_out)],
                                text=True, capture_output=True)
            if cp.returncode != 0 or not asr_out.exists():
                d, r = _decide_audio(has_audio=True, asr_ok=False, target=target, score=0.0,
                                     language_ok=False, n_dialogue=len(dialogue_lines),
                                     has_segs=False, threshold=threshold)
                item.update({"decision": d, "reason": r, "asr_error": cp.stderr.strip()[-500:]})
            else:
                data = mv._load_json(asr_out, {})
                asr_out.unlink(missing_ok=True)
                segs = data.get("segments", [])
                heard = "".join(str(s.get("text") or "") for s in segs)
                score = difflib.SequenceMatcher(None, _norm_text(target), _norm_text(heard)).ratio() if target else 0.0
                item.update({"language": data.get("language"), "heard": heard, "segments": segs,
                             "speech_start": segs[0].get("start") if segs else None,
                             "speech_end": segs[-1].get("end") if segs else None,
                             "match": round(score, 3)})
                lang = str(data.get("language") or "").lower()
                expected = expected_language.split("-")[0].lower()
                language_ok = not expected or lang.startswith(expected)
                item["language_ok"] = language_ok
                d, r = _decide_audio(has_audio=True, asr_ok=True, target=target, score=score,
                                     language_ok=language_ok, n_dialogue=len(dialogue_lines),
                                     has_segs=bool(segs), threshold=threshold)
                item.update({"decision": d, "reason": r})
        report["shots"].append(item)
        print(f"镜 {idx}: audio={item['native_audio']} match={item['match']:.3f} → {item['decision']}（{item.get('reason','')}）")
    out = ep / "clip-audit.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    counts: dict = {}
    for it in report["shots"]:
        counts[it["decision"]] = counts.get(it["decision"], 0) + 1
    print(f"✅ 片段音频审计：{out}")
    print(f"   决策汇总：native(整轨原音直通) {counts.get('native', 0)} / "
          f"dub(换配音，环境音靠侧链闪避保留) {counts.get('dub', 0)} / "
          f"regenerate(需重生成) {counts.get('regenerate', 0)}")
    if counts.get("regenerate"):
        print("   ↳ regenerate 镜：带失败反馈重生成，拿到好原声即转 native（最多两次）。")
    return 1 if hard_fail else 0


def main() -> int:
    # 加载 .env（VIDEO_PROVIDER / VOICE_PROVIDER / *_API_KEY 等常只写在 .env）——与 ai_video/ai_image 一致，
    # 否则 cast init 会误退 edge、prepare 读不到视频模型能力。
    try:
        import ai_video
        ai_video.load_env_file(ai_video.find_default_env_file())
    except Exception:  # noqa: BLE001 — 加载失败不致命，仍可用显式参数/已有环境变量
        pass
    ap = argparse.ArgumentParser(
        description="短剧多角色配音（委派 multivoice.py）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("cast", help="选角（角色→音色）")
    csub = pc.add_subparsers(dest="castcmd", required=True)
    for name in ("init", "add", "list", "check"):
        sp = csub.add_parser(name)
        sp.add_argument("--series", required=True)
        sp.add_argument("--root", default=DEFAULT_ROOT)
        if name == "add":
            sp.add_argument("--name", required=True)
            sp.add_argument("--role", default="")
            # 默认 clone（闭源云 provider 优先，更像真人）；缺 provider 时取环境变量 VOICE_PROVIDER。
            sp.add_argument("--engine", default="clone", choices=["edge", "clone"])
            sp.add_argument("--voice", default="")
            sp.add_argument("--rate", help="负值用等号：--rate=-5%%")
            sp.add_argument("--pitch", help="负值用等号：--pitch=-3Hz")
            sp.add_argument("--volume")
            sp.add_argument("--provider"); sp.add_argument("--voice-id", dest="voice_id")
            sp.add_argument("--archetype", default="",
                            help="形象原型（看定妆图判断：萝莉/御姐/大叔/冷峻男主…）——音色必须贴合它")
            sp.add_argument("--ref", default="", help="该角色定妆图的 C 编号（如 C01），绑定音色↔画面形象")
            sp.add_argument("--note", default="")

    pd = sub.add_parser("dub", help="逐行多声线配音 → episodes/epNN/voice.mp3 + voice.srt")
    pd.add_argument("--series", required=True)
    pd.add_argument("--root", default=DEFAULT_ROOT)
    pd.add_argument("--episode", type=int, required=True)
    pd.add_argument("--gap", type=float, default=mv.DEFAULT_GAP)
    pd.add_argument("--proxy")
    pd.add_argument("--allow-edge", dest="allow_edge", action="store_true",
                    help="放行 edge(AI 音色)：默认配了闭源(VOICE_PROVIDER)就硬拦 edge，确无 key 才加此项")
    pd.add_argument("-o", "--output", help="voice.mp3 输出路径（默认 episodes/epNN/voice.mp3）")

    pa = sub.add_parser("align", help="逐镜对齐配音（画面时长=台词时长，配音/字幕对齐画面）")
    pa.add_argument("--series", required=True)
    pa.add_argument("--root", default=DEFAULT_ROOT)
    pa.add_argument("--episode", type=int, required=True)
    pa.add_argument("--gap", type=float, default=mv.DEFAULT_GAP)
    pa.add_argument("--min-shot", dest="min_shot", type=float, default=mv.DEFAULT_MIN_SHOT,
                    help=f"每镜最短视觉时长（默认 {mv.DEFAULT_MIN_SHOT}s）")
    pa.add_argument("--tail", type=float, default=mv.DEFAULT_TAIL,
                    help=f"台词说完镜头多留尾巴（默认 {mv.DEFAULT_TAIL}s）")
    pa.add_argument("--lenient", action="store_true",
                    help="放宽台词归属校验（未知说话人回退旁白；默认严格拦截，防配错角色）")
    pa.add_argument("--allow-edge", dest="allow_edge", action="store_true",
                    help="放行 edge(AI 音色)：默认配了闭源(VOICE_PROVIDER)就硬拦 edge，确无 key 才加此项")
    pa.add_argument("--proxy")
    pa.add_argument("-o", "--output", help="voice.mp3 输出路径（默认 episodes/epNN/voice.mp3）")

    pp = sub.add_parser("plan", help="生视频前：按台词估每镜停留时长，写回 shots.json（自然的关键）")
    pp.add_argument("--series", required=True)
    pp.add_argument("--root", default=DEFAULT_ROOT)
    pp.add_argument("--episode", type=int, required=True)
    pp.add_argument("--gap", type=float, default=mv.DEFAULT_GAP)
    pp.add_argument("--min-shot", dest="min_shot", type=float, default=mv.DEFAULT_MIN_SHOT)
    pp.add_argument("--tail", type=float, default=mv.DEFAULT_TAIL)
    pp.add_argument("--clip-cap", dest="clip_cap", type=float, default=5.0,
                    help="单个可生成片段的常用档位秒数（多数 provider=5s）")
    pp.add_argument("--clip-max", dest="clip_max", type=float, default=10.0,
                    help="单个片段的最大档位秒数（部分 provider 支持 10s）；超过则须拆镜")

    pg = sub.add_parser("prepare", help="生成 provider 无关的原生对白契约与视频 prompt")
    pg.add_argument("--series", required=True)
    pg.add_argument("--root", default=DEFAULT_ROOT)
    pg.add_argument("--episode", type=int, required=True)
    pg.add_argument("--language", default="zh-CN")
    pg.add_argument("--provider", help="视频 provider（默认 env VIDEO_PROVIDER；会写入 shots.json 锁定）")
    pg.add_argument("--video-model", dest="video_model",
                    help="视频模型（默认按 provider env/内置值解析；会写入 shots.json 锁定）")
    pg.add_argument("--dialogue-mode", dest="dialogue_mode", choices=["auto", "faithful", "dub"],
                    default="auto",
                    help="画内对白契约：auto=按视频模型 dialogue_faithful 能力（探针/配置/默认）自动选；"
                         "faithful=强制让模型逐字说台词；dub=强制不给台词、后期配音（默认 auto）")
    pg.add_argument("--force-dub", dest="force_dub", action="store_true",
                    help="配合 --dialogue-mode dub：无 probe 证据时也强制全剧 dub（放弃原生音频/环境音）——"
                         "别用它躲避 native-first/拆镜，只在确实要全 TTS 时用")

    pu = sub.add_parser("audit", help="生成后逐镜 ASR 审计原生对白、语言与说话时间")
    pu.add_argument("--series", required=True)
    pu.add_argument("--root", default=DEFAULT_ROOT)
    pu.add_argument("--episode", type=int, required=True)
    pu.add_argument("--model", default="base", help="faster-whisper 模型（默认 base）")
    pu.add_argument("--threshold", type=float, default=0.6,
                    help="原生人声采用阈值（默认 0.6，偏向「可用就留原声」；语言正确为强制前置门，"
                         "语言错一律判坏。低于此且内容明显不符才换配音）")
    pu.add_argument("--language", default="zh-CN", help="期望对白语言（默认 zh-CN）")

    sub.add_parser("selftest", help="自检（委派引擎）")

    a = ap.parse_args()
    if a.cmd == "selftest":
        return mv._selftest()
    if a.cmd == "cast":
        cf = _cast_file(a.root, a.series)
        if a.castcmd == "init":
            r = mv.cast_init(cf, a.series, narrator_provider=os.environ.get("VOICE_PROVIDER"))
            print(f"✅ {r['path']}" + ("（新建）" if r["created"] else "（已存在，未覆盖）"))
        elif a.castcmd == "add":
            # 闭源优先：engine=clone 但没写 provider 时，取环境变量 VOICE_PROVIDER（.env 里配的闭源默认）
            provider = a.provider
            if a.engine == "clone" and not provider:
                provider = os.environ.get("VOICE_PROVIDER", "").strip() or None
            e = mv.cast_add(cf, {"name": a.name, "role": a.role, "engine": a.engine,
                                 "voice": a.voice or None, "rate": a.rate, "pitch": a.pitch,
                                 "volume": a.volume, "provider": provider,
                                 "voice_id": a.voice_id, "archetype": a.archetype,
                                 "ref": a.ref, "note": a.note})
            print(f"✅ {e['name']} → {e.get('voice') or e.get('voice_id')}（{e['engine']}"
                  + (f"·{provider}" if provider else "") + "）")
        elif a.castcmd == "list":
            for c in mv.cast_load(cf).get("cast", []):
                tag = c.get("voice") if c.get("engine") == "edge" else f"clone:{c.get('voice_id')}"
                print(f"  {c.get('name')} [{c.get('role','')}] {tag} rate={c.get('rate')} pitch={c.get('pitch')}"
                      f" 形象={c.get('archetype','?')} ref={c.get('ref','?')} — {c.get('note','')}")
        elif a.castcmd == "check":
            data = mv.cast_load(cf)
            probs = mv.cast_check(data, closed_source_configured=mv._closed_source_configured())
            # 交叉核对定妆图：ref_index 里的每个角色都应被配音（先看图再定音色，别漏配/凭空配）
            cast_names = {c.get("name") for c in data.get("cast", [])}
            for rc in _ref_characters(a.root, a.series):
                if rc["name"] not in cast_names:
                    probs.append(f"角色「{rc['name']}」({rc['code']}) 有定妆图却没配音色——"
                                 f"请 cast add 并**按其定妆图形象**选贴合音色（--archetype）")
            if probs:
                print(f"⚠️ 选角有 {len(probs)} 个问题：")
                for p in probs:
                    print(f"  - {p}")
                return 1
            print("✅ 选角校验通过")
            for tip in mv.cast_advisories(data):
                print(f"  💡 {tip}")
        return 0
    if a.cmd == "dub":
        ep = _ep_dir(a.root, a.series, a.episode)
        out = Path(a.output).expanduser() if a.output else (ep / "voice.mp3")
        r = mv.dub(_cast_file(a.root, a.series), ep / "lines.json", out,
                   None, a.gap, a.proxy, allow_edge=a.allow_edge)
        print(f"✅ 配音完成：{r['voice']}（{r['lines']} 行，{r['duration']}s，"
              f"{len(r['voices'])} 种声线）\n   字幕：{r['srt']}\n   声线：{'、'.join(r['voices'])}")
        return 0
    if a.cmd == "align":
        out = Path(a.output).expanduser() if a.output else None
        return _align(a.root, a.series, a.episode, out, a.gap, a.min_shot, a.tail,
                      a.proxy, a.lenient, a.allow_edge)
    if a.cmd == "plan":
        return _plan(a.root, a.series, a.episode, a.gap, a.min_shot, a.tail, a.clip_cap, a.clip_max)
    if a.cmd == "prepare":
        return _prepare(a.root, a.series, a.episode, a.language, a.dialogue_mode,
                        getattr(a, "force_dub", False), a.provider, a.video_model)
    if a.cmd == "audit":
        return _audit(a.root, a.series, a.episode, a.model, a.threshold, a.language)
    return 1


if __name__ == "__main__":
    sys.exit(main())
