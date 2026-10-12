#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片分镜口播剧 → 包装级竖屏成片（ffmpeg 渲染路径）。

【Easel 内置改造 · 幻灯片成片渲染器】
SDK 原生 render 走 Remotion（真人出镜/独白片）。但 Easel 做出来的口播剧常是
「静态分镜图 + TTS 旁白 + SRT 台词」——本工具用 ffmpeg 把它包装成成片：
  · Ken Burns 逐场运镜（zoompan）
  · 逐场差异化入场（fade / 右滑 / 上滑 / 快推 / 黑场淡入）
  · SRT 台词烧成动态字幕（libass，粗描边白字，竖屏可读）
  · 转场处极轻 whoosh 音效（vol≤0.2，不抢旁白）
  · 旁白放大 + loudnorm I=-16:TP=-1.5:LRA=11（过响度门）

契约：读 <run-dir>/artifacts/scenes.json（见 SKILL 设计表流程产出）。
子命令：
  prep    生成 captions.ass / whoosh.wav / proj.json（供五件套门校验）到 <run-dir>/build/
  stills  逐场渲染 1 张代表帧（含运镜+字幕）到 <run-dir>/preview/（预览确认门用，成本低）
  render  全片渲染到 <run-dir>/workdir/out/final.mp4（预览点头后才跑）

路径解析：scenes.json 里的图/音路径可为绝对；相对则依次按 cwd、--workspace、
$EASEL_OPENCLAW_WORKSPACE 解析。字体走 fontconfig + --fontsdir（内置 MaShanZheng）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SDK_ROOT = Path(__file__).resolve().parent.parent
FPS = 30
W, H = 1080, 1920
FONTS_DIR = SDK_ROOT / "assets" / "fonts"          # MaShanZheng 在此
CAPTION_FONT = "Noto Sans CJK SC"                    # 系统字体（正文台词）
TITLE_FONT = "Ma Shan Zheng"                         # 内置毛笔字（标题/判词）


def run(cmd: list, timeout: int | None = None) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")


def resolve(path: str, workspace: Path | None) -> Path:
    p = Path(path)
    if p.is_absolute() and p.exists():
        return p
    for base in (Path.cwd(), workspace, Path(os.environ.get("EASEL_OPENCLAW_WORKSPACE", ""))):
        if base:
            cand = base / path
            if cand.exists():
                return cand.resolve()
    raise FileNotFoundError(f"找不到素材：{path}（cwd/workspace 均无）")


def load_scenes(rd: Path) -> dict:
    sp = rd / "artifacts" / "scenes.json"
    if not sp.is_file():
        raise FileNotFoundError(f"缺 scenes.json：{sp}")
    return json.loads(sp.read_text(encoding="utf-8"))


def esc_time(t: float) -> str:
    """秒 → ass 时间 h:mm:ss.cs"""
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "（").replace("}", "）")


def wrap_caption(text: str, max_len: int = 13) -> str:
    """中文台词无空格，libass 不会自动折行——手动按标点优先断成多行（\\N）。"""
    breakers = "，。！？…、；：,.!?"
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_len and (ch in breakers or len(cur) >= max_len + 2):
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    # 标点不许在行首（避头尾）：把行首的标点回补到上一行末
    for i in range(1, len(lines)):
        while lines[i] and lines[i][0] in breakers:
            lines[i - 1] += lines[i][0]
            lines[i] = lines[i][1:]
    lines = [ln for ln in lines if ln]
    # 合并过短的尾行到上一行，避免孤字
    if len(lines) >= 2 and len(lines[-1]) <= 3:
        lines[-2] += lines[-1]
        lines.pop()
    return "\\N".join(lines)


def build_ass(data: dict) -> str:
    """SRT 台词 → 带样式的 ass（正文动态字幕 + 开场标题 + 结案判词）。"""
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{CAPTION_FONT},46,&H00FFFFFF,&H000000FF,&H00202020,&H90000000,1,0,0,0,100,100,0,0,1,5,3,2,70,70,205,1
Style: Title,{TITLE_FONT},96,&H0038D2EE,&H000000FF,&H00101820,&H00000000,1,0,0,0,100,100,2,0,1,6,4,8,80,80,180,1
Style: Verdict,{TITLE_FONT},104,&H0034EB8F,&H000000FF,&H00101820,&H00000000,1,0,0,0,100,100,2,0,1,6,4,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    scenes = data["scenes"]
    for sc in scenes:
        st, en = float(sc["start"]), float(sc["end"])
        cap = wrap_caption(ass_escape(sc.get("caption", "").strip()))
        if cap:
            lines.append(f"Dialogue: 0,{esc_time(st)},{esc_time(en)},Caption,,0,0,0,,{{\\fad(220,220)}}{cap}")
    # 开场标题（场 1 前 3.2s）
    s1 = scenes[0]
    lines.append(f"Dialogue: 1,{esc_time(float(s1['start'])+0.3)},{esc_time(float(s1['start'])+3.4)},"
                 f"Title,,0,0,0,,{{\\fad(300,400)}}名侦探阿北\\N草莓大福失踪案")
    # 注：结案判词不另加浮层——shot5 原图已烧「结案！奶茶就是凶手」大字，避免叠字冲突
    return head + "\n".join(lines) + "\n"


def make_whoosh(out: Path) -> None:
    """合成一段极轻 whoosh（滤波噪声 + 淡入淡出），供转场音效。"""
    code, log = run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.5",
        "-af", "highpass=f=250,lowpass=f=2600,afade=t=in:st=0:d=0.12,"
               "afade=t=out:st=0.28:d=0.17,volume=0.9",
        "-ar", "48000", "-ac", "2", str(out)])
    if code != 0:
        raise RuntimeError(f"whoosh 合成失败：{log[-300:]}")


def kb_exprs(sc: dict, nf: int) -> tuple[str, str, str]:
    """Ken Burns 的 z / x / y 表达式（基于输出帧号 on）。"""
    kb = sc.get("kenburns", {})
    z0 = float(kb.get("from", 1.0))
    z1 = float(kb.get("to", 1.1))
    pan = kb.get("pan", "center")
    denom = max(nf - 1, 1)
    z = f"{z0}+({z1 - z0})*on/{denom}"
    x = "iw/2-(iw/zoom/2)"
    y = "ih/2-(ih/zoom/2)"
    if pan == "up":
        y = f"ih/2-(ih/zoom/2)-(ih*0.06)*on/{denom}"
    elif pan == "down":
        y = f"ih/2-(ih/zoom/2)+(ih*0.06)*on/{denom}"
    return z, x, y


def seg_filter(sc: dict, nf: int, still: bool = False, still_on: int = 0) -> str:
    """单场滤镜链：cover 裁切 → zoompan 运镜 → 入场效果。still=True 时锁定单帧。"""
    z, x, y = kb_exprs(sc, nf)
    if still:
        # 定格：把 on 用固定帧代入（zoompan 仍需 d/fps，取中段观感）
        z = z.replace("on", str(still_on))
        x = x  # x/y 里 zoom 已定，iw/ih 保留
        y = y.replace("on", str(still_on))
    base = (f"[0:v]scale=-1:{H*2},crop={W*2}:{H*2},"
            f"zoompan=d=1:s={W}x{H}:fps={FPS}:z='{z}':x='{x}':y='{y}'")
    trans = sc.get("transition", "fade")
    if still:
        return base + ",format=yuv420p[v]"
    if trans in ("wipeleft", "slideup"):
        if trans == "wipeleft":
            ov = "x='if(gte(t,0.5),0,(1-t/0.5)*W)':y=0"
        else:
            ov = "x=0:y='if(gte(t,0.5),0,(1-t/0.5)*H)'"
        dur = nf / FPS
        return (base + "[zp];"
                f"color=black:s={W}x{H}:r={FPS}:d={dur:.3f}[bg];"
                f"[bg][zp]overlay={ov}:shortest=1,format=yuv420p[v]")
    # fade 类入场
    d = 0.35 if trans == "circleopen" else 0.6
    return base + f",fade=t=in:st=0:d={d},format=yuv420p[v]"


def encode_segment(sc: dict, img: Path, out: Path, logdir: Path) -> None:
    dur = float(sc["end"]) - float(sc["start"])
    nf = max(int(round(dur * FPS)), 2)
    fc = seg_filter(sc, nf)
    cmd = ["ffmpeg", "-y", "-framerate", str(FPS), "-loop", "1", "-t", f"{dur:.3f}", "-i", str(img),
           "-filter_complex", fc, "-map", "[v]", "-r", str(FPS),
           "-frames:v", str(nf), "-c:v", "libx264", "-preset", "medium",
           "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
    code, log = run(cmd, timeout=600)
    (logdir / "render.log").open("a", encoding="utf-8").write(
        f"\n$ seg {sc['id']} nf={nf}\n{log[-1200:]}\n[exit {code}]\n")
    if code != 0 or not out.is_file():
        raise RuntimeError(f"场 {sc['id']} 渲染失败：{log[-400:]}")


def cmd_prep(rd: Path, workspace: Path) -> int:
    data = load_scenes(rd)
    build = rd / "build"
    (build / "public").mkdir(parents=True, exist_ok=True)
    (build / "sfx").mkdir(parents=True, exist_ok=True)
    # 字幕
    (build / "captions.ass").write_text(build_ass(data), encoding="utf-8")
    # whoosh
    make_whoosh(build / "sfx" / "whoosh.wav")
    # 五件套素材落位（供 check_meta --root build 校验存在性）
    narration = resolve(data["narration"], workspace)
    shutil.copy(narration, build / "public" / "voice.mp3")
    mats = []
    for sc in data["scenes"]:
        img = resolve(sc["image"], workspace)
        dst = build / "public" / Path(sc["image"]).name
        if not dst.exists():
            shutil.copy(img, dst)
        mats.append(f"public/{Path(sc['image']).name}")
    boundaries = [float(sc["start"]) for sc in data["scenes"][1:]]
    proj = {
        "source": "public/voice.mp3",
        "materials": mats,
        "animations": ["kenburns"],
        "transitions": [sc.get("transition") for sc in data["scenes"]],
        "sfx": [{"file": "sfx/whoosh.wav", "at": round(b, 3), "volume": 0.15} for b in boundaries],
    }
    (build / "proj.json").write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prep 完成：{build}/captions.ass · sfx/whoosh.wav · proj.json（{len(mats)} 素材）")
    return 0


def cmd_stills(rd: Path, workspace: Path) -> int:
    data = load_scenes(rd)
    prev = rd / "preview"
    prev.mkdir(parents=True, exist_ok=True)
    ass = rd / "build" / "captions.ass"
    # (场号, 输出名, 取帧时刻)；场 1 额外出一张标题帧（标题只在开头 ~3s）
    shots = []
    for sc in data["scenes"]:
        dur = float(sc["end"]) - float(sc["start"])
        shots.append((sc, f"scene{sc['id']}.png", float(sc["start"]) + dur / 2))
        if sc["id"] == data["scenes"][0]["id"]:
            shots.append((sc, "scene1_title.png", float(sc["start"]) + 1.6))
    for sc, name, tmid in shots:
        img = resolve(sc["image"], workspace)
        dur = float(sc["end"]) - float(sc["start"])
        nf = max(int(round(dur * FPS)), 2)
        still_on = min(int(round((tmid - float(sc["start"])) * FPS)), nf - 1)
        fc = seg_filter(sc, nf, still=True, still_on=still_on)
        # 在定格帧上烧字幕：把帧 pts 偏到取帧时刻，libass 才会渲染当时在场的台词
        out = prev / name
        vf = (fc.replace("[v]", f",setpts=PTS+{tmid:.3f}/TB,subtitles={_ass_arg(ass)}[v]")
              if ass.is_file() else fc)
        cmd = ["ffmpeg", "-y", "-framerate", str(FPS), "-loop", "1", "-t", "0.1", "-ss", f"{tmid:.3f}",
               "-i", str(img), "-filter_complex", vf, "-map", "[v]",
               "-frames:v", "1", str(out)]
        code, log = run(cmd, timeout=300)
        if code != 0 or not out.is_file():
            # 字幕烧制失败时退回无字幕定格，保证有预览
            code2, _ = run(["ffmpeg", "-y", "-framerate", str(FPS), "-loop", "1", "-t", "0.1", "-i", str(img),
                            "-filter_complex", fc, "-map", "[v]", "-frames:v", "1", str(out)], timeout=300)
            if code2 != 0:
                raise RuntimeError(f"场 {sc['id']} 定格失败：{log[-400:]}")
        print(f"预览帧：{out.name}")
    return 0


def _ass_arg(ass: Path) -> str:
    """subtitles 滤镜参数：路径转义 + fontsdir。"""
    p = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    fd = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
    return f"'{p}':fontsdir='{fd}'"


def cmd_render(rd: Path, workspace: Path) -> int:
    data = load_scenes(rd)
    scenes = data["scenes"]
    build = rd / "build"
    segdir = build / "segs"
    segdir.mkdir(parents=True, exist_ok=True)
    logdir = rd / "logs"
    logdir.mkdir(exist_ok=True)
    if not (build / "captions.ass").is_file():
        cmd_prep(rd, workspace)
    # 1) 逐场编码
    seglist = []
    for sc in scenes:
        img = resolve(sc["image"], workspace)
        seg = segdir / f"seg{sc['id']}.mp4"
        encode_segment(sc, img, seg, logdir)
        seglist.append(seg)
        print(f"段 {sc['id']} 就绪：{seg.name}")
    # 2) 合成：concat + 烧字幕 + 音频（旁白放大 + whoosh + loudnorm）
    outdir = rd / "workdir" / "out"
    outdir.mkdir(parents=True, exist_ok=True)
    final = outdir / "final.mp4"
    narration = build / "public" / "voice.mp3"
    whoosh = build / "sfx" / "whoosh.wav"
    ass = build / "captions.ass"
    boundaries = [float(sc["start"]) for sc in scenes[1:]]

    inputs = []
    for seg in seglist:
        inputs += ["-i", str(seg)]
    vidx = len(seglist)          # voice input index
    whx = vidx + 1               # whoosh input index
    inputs += ["-i", str(narration), "-i", str(whoosh)]

    vcat = "".join(f"[{i}:v]" for i in range(len(seglist)))
    fc = f"{vcat}concat=n={len(seglist)}:v=1:a=0[cat];[cat]subtitles={_ass_arg(ass)}[v];"
    # 音频
    fc += f"[{vidx}:a]volume=2.0[nar];"
    n_w = len(boundaries)
    if n_w:
        fc += f"[{whx}:a]asplit={n_w}" + "".join(f"[w{i}]" for i in range(n_w)) + ";"
        mixed = "[nar]"
        for i, b in enumerate(boundaries):
            ms = int(round(b * 1000))
            fc += f"[w{i}]adelay={ms}|{ms},volume=0.15[wa{i}];"
            mixed += f"[wa{i}]"
        fc += (f"{mixed}amix=inputs={n_w + 1}:normalize=0,"
               "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]")
    else:
        fc += "[nar]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]"

    dur = float(scenes[-1]["end"])
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc,
           "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final)]
    code, log = run(cmd, timeout=1200)
    (logdir / "render.log").open("a", encoding="utf-8").write(
        f"\n$ final\n{log[-2000:]}\n[exit {code}]\n")
    if code != 0 or not final.is_file():
        raise RuntimeError(f"成片渲染失败：{log[-500:]}")
    print(f"DONE 成片：{final}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="幻灯片口播剧 → 成片（ffmpeg）")
    ap.add_argument("mode", choices=["prep", "stills", "render"])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--workspace", default=os.environ.get("EASEL_OPENCLAW_WORKSPACE", ""))
    args = ap.parse_args()
    rd = Path(args.run_dir).resolve()
    ws = Path(args.workspace).resolve() if args.workspace else None
    try:
        if args.mode == "prep":
            return cmd_prep(rd, ws)
        if args.mode == "stills":
            return cmd_stills(rd, ws)
        return cmd_render(rd, ws)
    except Exception as e:  # noqa: BLE001
        print(f"[render_slideshow][error] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
