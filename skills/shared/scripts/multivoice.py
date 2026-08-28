#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""multivoice.py — 多角色/对话配音引擎（确定性 IO + 委派 tts.py / voice_clone.py）。

通用可复用：给一份「选角 cast.json」+「逐行对白 lines.json」，逐行用**各角色自己的音色**
合成，拼成一条**多声线 voice.mp3** + 带角色名的 **voice.srt**。任何需要「多人对话/多角色/
双人问答口播」的工作流都能用（短剧对白、论文双人问答讲解、访谈、有声剧…）。

与相邻能力区别：
  - tts.py（tts-voiceover）：单一音色整段口播；本引擎是**逐行多音色**。
  - voice_clone.py（voice-clone）：克隆你自己的声音；本引擎按角色**分配**音色（可含克隆音色）。

创意（谁说什么、什么情绪）由上层 LLM 产出到 lines.json；音色映射在 cast.json。
本脚本只做确定性编排：逐行合成 + 情绪→韵律 + ffmpeg 拼接 + SRT 时序。**路径无关**：
输入/输出都用显式文件路径，不绑定任何目录约定（短剧的 --series/--episode 便利层见
skills/openclaw/short-drama/scripts/dubbing.py，它委派本引擎）。

子命令：
    cast init   --cast FILE            生成 cast.json 模板（含旁白）
    cast add    --cast FILE ...        追加/覆盖一个角色音色
    cast list   --cast FILE
    cast check  --cast FILE            校验（音色有效 / 旁白独立 / 无撞音色）
    dub  --cast FILE --lines FILE -o OUT.mp3 [--srt OUT.srt] [--gap S] [--proxy URL]
    selftest

音色选型指南见 skills/shared/references/voice-casting.md。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NARRATOR = "旁白"
DEFAULT_GAP = 0.35  # 行间停顿秒数

# edge-tts 常用中文音色（与 tts.py COMMON_ZH_VOICES 对齐，用于 cast check 校验）
KNOWN_EDGE_VOICES = {
    "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural",
    "zh-CN-YunyangNeural", "zh-CN-YunjianNeural", "zh-CN-YunxiaNeural",
    "zh-CN-XiaoshuangNeural",  # 女童声（萝莉/小女孩）
    "zh-CN-liaoning-XiaobeiNeural", "zh-CN-shaanxi-XiaoniNeural",
    "zh-TW-HsiaoChenNeural", "zh-TW-YunJheNeural",
    "zh-HK-HiuMaanNeural", "zh-HK-WanLungNeural",
}
DEFAULT_NARRATOR_VOICE = "zh-CN-YunyangNeural"  # 旁白 edge 兜底音色（仅无闭源 key 时）
# 闭源 provider 的默认预置音色（有现成音色、无需 enroll）——用于旁白/普通配音默认走闭源、不用 AI 味 edge。
PRESET_NARRATOR_VOICE = {
    "openai-compatible": "FunAudioLLM/CosyVoice2-0.5B:alex",  # SiliconFlow CosyVoice2 沉稳男声
    "gemini": "Charon",                                       # gemini 男声
}

# 情绪 → 韵律增量（rate% / pitchHz / volume%），叠加在角色基础音色之上（子串匹配）。
_EMOTION_PROSODY: list[tuple[tuple[str, ...], tuple[int, int, int]]] = [
    (("怒", "愤", "吼", "斥"), (8, -1, 15)),
    (("紧张", "急", "慌", "催"), (12, 2, 5)),
    (("悲", "哭", "难过", "伤", "泣"), (-10, -2, -5)),
    (("温柔", "柔", "宠", "安慰"), (-6, -1, -3)),
    (("冷", "漠", "淡", "讥", "嘲"), (-3, -2, 0)),
    (("惊", "震", "诧", "愕"), (6, 4, 10)),
    (("喜", "开心", "兴奋", "笑", "得意"), (6, 3, 5)),
    (("坚定", "决", "郑重"), (-2, -1, 5)),
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _shared_script(name: str) -> str:
    """定位同目录（skills/shared/scripts/）的 tts.py / voice_clone.py。"""
    sib = Path(__file__).resolve().parent / name
    if sib.is_file():
        return str(sib)
    root = os.environ.get("EASEL_ROOT")
    if root and (Path(root) / "skills" / "shared" / "scripts" / name).is_file():
        return str(Path(root) / "skills" / "shared" / "scripts" / name)
    return str(sib)  # best effort


def _load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 韵律（纯函数，可测）────────────────────────────────────────────────
def emotion_prosody(emotion: str | None) -> tuple[int, int, int]:
    """情绪 → (rate%, pitchHz, volume%) 增量。未识别/空 → (0,0,0)。"""
    if not emotion:
        return (0, 0, 0)
    e = str(emotion).strip()
    for keys, delta in _EMOTION_PROSODY:
        if any(k in e for k in keys):
            return delta
    return (0, 0, 0)


# 中文语音估时：正常约 4.5 字/秒；情绪 rate 增量按比例调整（快→字数/秒更多，慢→更少）。
CHARS_PER_SEC = 4.5
_PAUSE_PUNCT = "，。！？、；：…,.!?;:"


def estimate_line_seconds(text: str, emotion: str | None = None) -> float:
    """**不合成、纯估算**一句台词的口播时长（秒）——用于生视频前规划每镜停留时间。

    字数/语速 + 标点停顿 + 情绪语速修正。让画面时长在**生成阶段**就贴合台词，
    从源头保证自然（而不是后期靠拉伸/循环补救）。
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    n = sum(1 for ch in t if not ch.isspace())
    rate_delta = emotion_prosody(emotion)[0]          # 百分比（怒+8 快 / 悲-10 慢…）
    cps = max(2.0, CHARS_PER_SEC * (1 + rate_delta / 100.0))
    pauses = sum(t.count(p) for p in _PAUSE_PUNCT) * 0.15
    return round(n / cps + pauses, 3)


def _parse_num(s: str | None) -> float:
    if not s:
        return 0.0
    t = str(s).strip().rstrip("%").rstrip("Hz").rstrip("hz")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _fmt(value: float, unit: str) -> str:
    iv = int(round(value))
    return f"{'+' if iv >= 0 else ''}{iv}{unit}"


def combine_prosody(base_rate: str | None, base_pitch: str | None,
                    base_volume: str | None, emotion: str | None
                    ) -> tuple[str, str, str]:
    """角色基础音色 + 情绪增量 → (rate, pitch, volume)，各自 clamp 到安全区间。"""
    dr, dp, dv = emotion_prosody(emotion)
    rate = max(-50.0, min(50.0, _parse_num(base_rate) + dr))
    pitch = max(-50.0, min(50.0, _parse_num(base_pitch) + dp))
    vol = max(-50.0, min(50.0, _parse_num(base_volume) + dv))
    return _fmt(rate, "%"), _fmt(pitch, "Hz"), _fmt(vol, "%")


# ── cast（显式文件路径）────────────────────────────────────────────────
def _closed_source_configured() -> bool:
    """是否已配闭源云 provider（环境变量 VOICE_PROVIDER 非空）——据此强制不许再用 edge(AI 音色)。"""
    return bool((os.environ.get("VOICE_PROVIDER") or "").strip())


def cast_init(cast_file: Path, title: str = "", narrator_provider: str | None = None) -> dict:
    """建 cast.json 模板。**旁白/普通配音默认也走闭源云 provider**（不用 AI 味 edge）：
    给了 narrator_provider（通常来自环境变量 VOICE_PROVIDER）且该 provider 有预置音色
    （openai-compatible/gemini）→ 旁白直接 clone 闭源预置音色；否则（无 key 或 provider 需 enroll）
    退回 edge 并在 note 里标注「务必升级闭源」。"""
    if cast_file.exists():
        return {"path": str(cast_file), "created": False}
    np = (narrator_provider or "").strip() or None
    preset = PRESET_NARRATOR_VOICE.get(np) if np else None
    if np and preset:
        narrator = {"name": NARRATOR, "role": "narrator", "engine": "clone",
                    "provider": np, "voice_id": preset, "archetype": "旁白/画外音",
                    "rate": None, "pitch": None, "volume": None,
                    "note": "旁白/画外音，沉稳中性，与所有角色音色不同（闭源，有质感）"}
    else:
        narrator = {"name": NARRATOR, "role": "narrator", "engine": "edge",
                    "voice": DEFAULT_NARRATOR_VOICE, "archetype": "旁白/画外音",
                    "rate": None, "pitch": None, "volume": None,
                    "note": "⚠️ 暂用 edge(AI味)——请配 VOICE_PROVIDER 后改闭源（旁白也不该用 AI 音色）"
                            + (f"；provider={np} 需 enroll 一个 voice_id" if np else "")}
    data = {
        "title": title,
        "_guide": "按 skills/shared/references/voice-casting.md 为每个说话人定音色：**先看该角色的定妆参考图**"
                  "（萝莉→萝莉音、大叔→低沉音，绝不错位），在 archetype 写形象原型、ref 写定妆图 C 编号。"
                  "【闭源强制优先】所有角色含旁白/普通配音一律 engine=clone + 闭源云 provider"
                  "（openai-compatible CosyVoice2/minimax/dashscope/gemini，有情感、像真人；provider 不填取 VOICE_PROVIDER）；"
                  "engine=edge 只在完全没配 key 时兜底（AI 味、平），配了 key 后 cast check 会拦。",
        "cast": [narrator],
    }
    _write_json(cast_file, data)
    return {"path": str(cast_file), "created": True}


def cast_advisories(cast: dict) -> list[str]:
    """软建议（不影响校验通过）：升级闭源 / 补形象原型。

    与 cast_check 分离：check 管硬错误（fail），advisories 管质量建议（提示不拦）。
    """
    tips: list[str] = []
    for c in cast.get("cast") or []:
        nm = c.get("name")
        if not nm:
            continue
        if c.get("engine", "edge") == "edge" and c.get("role") not in ("narrator", "extra"):
            tips.append(f"{nm} 用 edge-tts（免费但无情感、机器味）——改闭源云 provider "
                        f"（--engine clone --provider <minimax|dashscope|openai-compatible|gemini>），更像真人")
        # 形象原型缺失：提醒「先看定妆图再定音色」（萝莉→萝莉音、大叔→大叔音）
        if c.get("role") not in ("narrator", "extra") and not (c.get("archetype") or "").strip():
            tips.append(f"{nm} 没写 archetype（形象原型）——请先看该角色定妆图判断（萝莉/御姐/大叔/冷峻男主…）"
                        f"再对号入座选音色（--archetype），确认音色贴合画面形象")
    return tips


def cast_check(cast: dict, closed_source_configured: bool = False) -> list[str]:
    """校验选角，返回问题清单（空=通过）。纯函数。

    closed_source_configured=True（已配 VOICE_PROVIDER）时：任何角色仍用 edge(AI 音色) → **硬错误**
    （包括旁白/普通配音——都必须优先闭源）；未配 key 时 edge 只作兜底、不拦。
    """
    problems: list[str] = []
    lst = cast.get("cast") or []
    if not lst:
        problems.append("cast 为空")
        return problems
    names = [c.get("name") for c in lst]
    if NARRATOR not in names:
        problems.append(f"缺「{NARRATOR}」条目（旁白必须单列一个音色）")
    seen_voice: dict[str, str] = {}
    narrator_voice = None
    for c in lst:
        nm, eng, vc = c.get("name"), c.get("engine", "edge"), c.get("voice")
        if not nm:
            problems.append("有条目缺 name")
            continue
        if eng == "edge":
            if closed_source_configured:
                problems.append(f"{nm} 用 edge（AI 音色、机器味）但已配闭源 provider —— "
                                f"必须改闭源（--engine clone，含旁白/普通配音都不许用 AI 音色）")
            if not vc:
                problems.append(f"{nm} 缺 voice")
            elif vc not in KNOWN_EDGE_VOICES:
                problems.append(f"{nm} 的 voice「{vc}」不在已知 edge 音色内（查 voice-casting.md / tts.py voices）")
        elif eng == "clone":
            if not c.get("voice_id"):
                problems.append(f"{nm} engine=clone 但缺 voice_id")
        if c.get("role") == "narrator":
            narrator_voice = vc
        if vc:
            if vc in seen_voice and seen_voice[vc] != nm:
                problems.append(f"{nm} 与 {seen_voice[vc]} 用了同一音色「{vc}」（同性别多角色请用 pitch/rate 区分或换音色）")
            seen_voice[vc] = nm
    for c in lst:
        if c.get("role") != "narrator" and c.get("voice") and c.get("voice") == narrator_voice:
            problems.append(f"旁白音色与角色 {c.get('name')} 相同——旁白须独立音色")
            break
    return problems


def validate_lines(cast: dict, lines: list[dict], valid_shots: set | None = None) -> list[str]:
    """校验逐行对白，返回问题清单（空=通过）。纯函数。

    治「配音配错角色 / 谁说哪句没分清」：speaker **必须精确在选角表 cast**（不再静默回退旁白），
    text 非空；用逐镜对齐时每行 shot 必须在分镜列表内。写剧本/抽 lines.json 时就把说话人分清楚。
    """
    problems: list[str] = []
    names = {c.get("name") for c in cast.get("cast", []) if c.get("name")}
    for i, ln in enumerate(lines):
        spk = (ln.get("speaker") or "").strip()
        if not spk:
            problems.append(f"第 {i} 行缺 speaker（没写谁说的）")
        elif spk not in names:
            problems.append(f"第 {i} 行 speaker「{spk}」不在选角表 → 会配错音色；请修正台词归属或先 cast add「{spk}」")
        if not (ln.get("text") or "").strip():
            problems.append(f"第 {i} 行 text 为空")
        if valid_shots is not None:
            s = ln.get("shot")
            if s is None:
                problems.append(f"第 {i} 行缺 shot（逐镜对齐需标该句所属镜头 idx）")
            elif s not in valid_shots:
                problems.append(f"第 {i} 行 shot={s} 不在分镜列表 {sorted(valid_shots)}")
    return problems


def cast_add(cast_file: Path, entry: dict) -> dict:
    data = _load_json(cast_file, {"cast": []})
    data.setdefault("cast", [])
    data["cast"] = [c for c in data["cast"] if c.get("name") != entry["name"]]
    data["cast"].append(entry)
    _write_json(cast_file, data)
    return entry


def cast_load(cast_file: Path) -> dict:
    if not cast_file.exists():
        _die(f"未找到 {cast_file}（先 `cast init` 并选角）")
    return _load_json(cast_file, {"cast": []})


# ── 逐行合成计划（纯函数，可测）────────────────────────────────────────
def build_plan(cast: dict, lines: list[dict]) -> tuple[list[dict], list[str]]:
    """把 lines 逐行解析成合成计划。返回 (plan, warnings)。
    未在 cast 里的说话人 → 回退旁白音色并告警。"""
    cmap = {c.get("name"): c for c in cast.get("cast", []) if c.get("name")}
    narrator = cmap.get(NARRATOR) or {"name": NARRATOR, "engine": "edge",
                                      "voice": DEFAULT_NARRATOR_VOICE}
    plan: list[dict] = []
    warns: list[str] = []
    for i, ln in enumerate(lines):
        spk = (ln.get("speaker") or "").strip() or NARRATOR
        text = (ln.get("text") or "").strip()
        if not text:
            warns.append(f"第 {i} 行空台词，跳过")
            continue
        c = cmap.get(spk)
        if c is None:
            warns.append(f"第 {i} 行说话人「{spk}」不在选角表，回退旁白音色")
            c = narrator
        rate, pitch, vol = combine_prosody(c.get("rate"), c.get("pitch"),
                                           c.get("volume"), ln.get("emotion"))
        plan.append({
            "idx": len(plan), "speaker": spk, "text": text,
            "engine": c.get("engine", "edge"),
            "voice": c.get("voice", DEFAULT_NARRATOR_VOICE),
            "provider": c.get("provider"), "voice_id": c.get("voice_id"),
            "rate": rate, "pitch": pitch, "volume": vol,
            "emotion": ln.get("emotion", ""),
            # shot：该行台词所属镜头 idx（短剧逐镜对齐用；无则 None）。透传给 dub_grouped 分组。
            "shot": ln.get("shot"),
            # at：该行在**本镜片段内**的起始秒（对齐说话/嘴动时刻；无则顺序排）。
            "at": ln.get("at"),
        })
    return plan, warns


def _srt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(plan: list[dict], durations: list[float], gap: float,
              with_speaker: bool = False) -> str:
    """按逐行实测时长 + 行间 gap 生成对齐 SRT。纯函数。

    with_speaker=False（默认）：字幕只显台词——成片画面有角色脸，前缀「角色名：」是冗余。
    with_speaker=True：字幕带「角色名：台词」（旁白行不加名）。
    """
    out: list[str] = []
    t = 0.0
    for i, (p, dur) in enumerate(zip(plan, durations), start=1):
        start, end = t, t + dur
        label = f"{p['speaker']}：{p['text']}" if with_speaker and p["speaker"] != NARRATOR else p["text"]
        out.append(f"{i}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{label}\n")
        t = end + gap
    return "\n".join(out)


# ── 合成（联网 + ffmpeg）──────────────────────────────────────────────
def _synth_line(p: dict, out_mp3: Path, proxy: str | None,
                strict_closed: bool = False) -> tuple[bool, str]:
    """合成一行。engine=clone 缺 key/失败 → 回退 edge（除非 strict_closed=禁回退硬失败）。返回 (ok, note)。"""
    note = ""
    if p["engine"] == "clone" and p.get("voice_id"):
        cmd = [sys.executable, _shared_script("voice_clone.py"), "clone",
               "--text", p["text"], "-o", str(out_mp3)]
        if p.get("provider"):
            cmd += ["--provider", p["provider"]]
        cmd += ["--voice-id", p["voice_id"]]
        # 逐行情绪喂进云 provider 的真情感通道（治「像 AI 平读」的关键）——
        # voice_clone 会按 provider 转成 minimax emotion 枚举 / dashscope·openai 自然语言指令。
        if p.get("emotion"):
            cmd += ["--emotion", str(p["emotion"])]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and out_mp3.is_file() and out_mp3.stat().st_size > 0:
            return True, "clone"
        err = (r.stderr or '').strip().splitlines()[-1:] or ['?']
        if strict_closed:
            # 已配闭源却 clone 失败 → 不许静默用 edge(AI 味) 顶替，硬失败让人修 key/voice-id
            return False, f"clone 合成失败且已配闭源(禁回退 edge)：{err}"
        note = f"clone 失败回退 edge（{err}）"
    elif strict_closed:
        # 配了闭源却这行不是可用的 clone（engine!=clone 或缺 voice_id）→ 硬失败，别出 edge
        return False, ("已配闭源(VOICE_PROVIDER)但该行不是可用闭源音色"
                       "（需 engine=clone + provider + voice_id）——请修 cast，别用 edge")
    # edge-tts。rate/pitch/volume 可能是负值（如 -4Hz），必须 --opt=value 形式，
    # 否则 argparse 把「-4Hz」当选项名报错。
    cmd = [sys.executable, _shared_script("tts.py"), "speak",
           "-t", p["text"], "-o", str(out_mp3), "-v", p["voice"],
           f"--rate={p['rate']}", f"--pitch={p['pitch']}", f"--volume={p['volume']}"]
    if proxy:
        cmd += [f"--proxy={proxy}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0 and out_mp3.is_file() and out_mp3.stat().st_size > 0
    if not ok:
        note = (note + " | " if note else "") + f"edge 合成失败：{(r.stderr or r.stdout or '').strip()[-200:]}"
    return ok, note or "edge"


def _probe_dur(path: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(path)],
                           capture_output=True, text=True)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def _concat_audio(clips: list[Path], gap: float, out_mp3: Path) -> None:
    """按序拼接 + 行间插 gap 秒静音，统一 44100 mono，输出 mp3。需 ffmpeg。"""
    inputs: list[str] = []
    filters: list[str] = []
    segs: list[str] = []
    n = 0
    for i, clip in enumerate(clips):
        inputs += ["-i", str(clip)]
        filters.append(f"[{n}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{n}]")
        segs.append(f"[a{n}]")
        n += 1
        if gap > 0 and i < len(clips) - 1:
            inputs += ["-f", "lavfi", "-t", f"{gap}", "-i", "anullsrc=r=44100:cl=mono"]
            filters.append(f"[{n}:a]aformat=sample_fmts=fltp:channel_layouts=mono[a{n}]")
            segs.append(f"[a{n}]")
            n += 1
    fc = ";".join(filters) + ";" + "".join(segs) + f"concat=n={n}:v=0:a=1[out]"
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[out]",
           "-q:a", "4", str(out_mp3)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_mp3.is_file():
        _die(f"ffmpeg 拼接失败：{(r.stderr or '')[-400:]}")


def _place_on_timeline(clips: list[Path], offsets: list[float], total: float,
                       out_mp3: Path) -> None:
    """把若干音频按各自起始秒 offset 叠到一条 total 秒的静音床上（44100 mono）。需 ffmpeg。

    用于逐镜配音：台词只占片段的一部分，其余时间是动作/停顿/音效——所以不是首尾相接填满，
    而是各行**按 at 偏移**放在完整片段时长的床上（adelay + amix），画面自然、说话时刻对得上。
    """
    total = max(0.05, float(total))
    inputs: list[str] = ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=mono"]
    filters: list[str] = ["[0:a]aformat=sample_fmts=fltp:channel_layouts=mono[base]"]
    labels: list[str] = ["[base]"]
    for i, (clip, off) in enumerate(zip(clips, offsets), start=1):
        ms = max(0, int(round(float(off) * 1000)))
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,"
                       f"adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    # amix：以床为准的固定时长（duration=first），台词叠加其上；再硬裁到 total 保险。
    fc = (";".join(filters) + ";" + "".join(labels)
          + f"amix=inputs={len(labels)}:duration=first:normalize=0[out]")
    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[out]",
           "-t", f"{total:.3f}", "-q:a", "4", str(out_mp3)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_mp3.is_file():
        _die(f"ffmpeg 铺音轨失败：{(r.stderr or '')[-400:]}")


def _silence(dur: float, out_mp3: Path) -> None:
    """生成 dur 秒静音 mp3（44100 mono）。用于无台词的动作镜。"""
    dur = max(0.05, float(dur))
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", f"{dur:.3f}",
         "-i", "anullsrc=r=44100:cl=mono", "-q:a", "4", str(out_mp3)],
        capture_output=True, text=True)
    if r.returncode != 0 or not out_mp3.is_file():
        _die(f"ffmpeg 生成静音失败：{(r.stderr or '')[-300:]}")


def _pad_to(in_mp3: Path, target: float, out_mp3: Path) -> None:
    """把 in_mp3 尾部补静音到精确 target 秒（若已≥target 则裁到 target）。"""
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(in_mp3), "-af", "apad",
         "-t", f"{float(target):.3f}", "-q:a", "4", str(out_mp3)],
        capture_output=True, text=True)
    if r.returncode != 0 or not out_mp3.is_file():
        _die(f"ffmpeg 补齐时长失败：{(r.stderr or '')[-300:]}")


def _edge_resolved(plan: list[dict]) -> list[dict]:
    """会落到 edge(AI 音色) 的行：engine!=clone，或 clone 但缺 voice_id。"""
    return [p for p in plan if p.get("engine") != "clone" or not p.get("voice_id")]


def _preflight_closed_source(plan: list[dict], allow_edge: bool) -> bool:
    """已配闭源(VOICE_PROVIDER)且未 --allow-edge 时：合成前先拦下会用 edge 的行（硬失败）。
    返回 strict_closed（供 _synth_line 禁止 clone 失败时回退 edge）。"""
    strict = _closed_source_configured() and not allow_edge
    if strict:
        bad = _edge_resolved(plan)
        if bad:
            who = "、".join(sorted({str(p.get("speaker")) for p in bad}))
            _die(f"已配闭源（VOICE_PROVIDER={os.environ.get('VOICE_PROVIDER')}）却有角色会用 edge(AI 音色)：{who}。"
                 f"\n请把这些角色改成闭源：cast add --engine clone --provider <..> --voice-id <..>"
                 f"（先 `voice_clone.py check --provider <..>` 验 key、`cast check` 复核）。"
                 f"\n确实没有任何闭源 key、只能用 edge 时，才显式加 --allow-edge 放行。")
    return strict


def _synth_plan(plan: list[dict], proxy: str | None, workdir: Path,
                strict_closed: bool = False
                ) -> tuple[list[Path], list[float], set[str]]:
    """逐行合成 plan → (每行 clip 路径, 每行时长, 用到的声线集合)。合成失败即 _die。"""
    clips: list[Path] = []
    durations: list[float] = []
    voices_used: set[str] = set()
    for p in plan:
        cp = workdir / f"line_{p['idx']:03d}.mp3"
        ok, note = _synth_line(p, cp, proxy, strict_closed=strict_closed)
        if not ok:
            _die(f"第 {p['idx']} 行（{p['speaker']}）合成失败：{note}")
        if note.startswith("clone 失败"):
            print(f"⚠️ 第 {p['idx']} 行 {note}", file=sys.stderr)
        clips.append(cp)
        durations.append(_probe_dur(cp))
        voices_used.add(p["voice"] if p["engine"] == "edge" else f"clone:{p.get('voice_id')}")
    return clips, durations, voices_used


def dub(cast_file: Path, lines_file: Path, out_mp3: Path,
        srt_out: Path | None = None, gap: float = DEFAULT_GAP,
        proxy: str | None = None, allow_edge: bool = False) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        _die("需要 ffmpeg/ffprobe（拼接多声线音轨与探测时长）")
    if not lines_file.exists():
        _die(f"未找到 {lines_file}（先让 LLM 把脚本抽成逐行对白 lines.json）")
    lines = _load_json(lines_file, {}).get("lines", [])
    if not lines:
        _die("lines.json 的 lines 为空")
    cast = cast_load(cast_file)
    plan, warns = build_plan(cast, lines)
    for w in warns:
        print(f"⚠️ {w}", file=sys.stderr)
    if not plan:
        _die("没有可合成的台词")
    strict_closed = _preflight_closed_source(plan, allow_edge)

    srt_out = srt_out or out_mp3.with_suffix(".srt")
    with tempfile.TemporaryDirectory() as td:
        clips, durations, voices_used = _synth_plan(plan, proxy, Path(td), strict_closed)
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        _concat_audio(clips, gap, out_mp3)

    srt_out.write_text(build_srt(plan, durations, gap), encoding="utf-8")
    total = sum(durations) + gap * max(0, len(plan) - 1)
    return {"voice": str(out_mp3), "srt": str(srt_out), "lines": len(plan),
            "voices": sorted(voices_used), "duration": round(total, 1)}


# 逐镜对齐默认参数（短剧：画面时长 = 真实片段时长，配音塞进片段内）
DEFAULT_MIN_SHOT = 1.2   # 每镜最短视觉时长（很短的台词也至少显示这么久）
DEFAULT_TAIL = 0.3       # 台词说完后镜头多留的尾巴（避免末字被下一镜切断）
DEFAULT_ACTION_SHOT = 2.0  # 无台词的动作/空镜默认时长（无 clip 探测值时）
CLIP_EPS = 0.15          # 片段 vs 台词时长比较容差（秒），吸收 provider 出片/探测的微小误差


def shot_layout(plan: list[dict], group_order: list, action_durs: dict,
                dur_by_idx: dict, gap: float = DEFAULT_GAP,
                min_shot: float = DEFAULT_MIN_SHOT, tail: float = DEFAULT_TAIL,
                clip_durs: dict | None = None
                ) -> dict:
    """纯函数：给定每行台词时长（+ 真实片段时长），算出「逐镜对齐」布局。可单测（不碰 ffmpeg）。

    **画面时长由真实片段主导（picture-led），保证自然播放**：
      - 有台词镜：needed=max(台词音频+tail, min_shot)；给了该镜真实片段时长 clip_durs[镜]：
          · 片段 ≥ 台词音频 → visual=min(needed, clip)（片段够长就裁到需要，绝不慢放/循环/冻结）；
          · 片段 < 台词音频（片段连台词都盖不住）→ 记入 **violations**，visual 暂用 needed（供报告）。
        没给 clip（生视频前/无片段）→ visual=needed（回退旧行为，plan 阶段用）。
      - 无台词镜：visual=action_durs（=该镜真实片段时长）或默认。
    返回 {order, by_shot, shot_durations, srt, timing, total, warns, **violations**}。
    每行全局起止对齐 master 音轨。violations 非空 = 有镜的画面盖不住台词，应重生成该镜/拆镜（上层硬拦）。
    """
    clip_durs = clip_durs or {}
    order = list(group_order) if group_order else sorted(
        {p.get("shot") for p in plan if p.get("shot") is not None},
        key=lambda x: (isinstance(x, str), x))
    by_shot: dict = {g: [] for g in order}
    warns: list[str] = []
    for p in plan:
        s = p.get("shot")
        if s not in by_shot:
            tgt = order[-1] if order else s
            warns.append(f"第 {p['idx']} 行 shot={s} 不在镜头列表，归入 {tgt}")
            s = tgt
            by_shot.setdefault(s, [])
            if s not in order:
                order.append(s)
        by_shot[s].append(p)

    shot_durations: dict = {}
    srt: list[tuple] = []
    timing: list[dict] = []
    violations: list[dict] = []
    placements: dict = {}   # shot_id → [(line_idx, at_in_shot, dur)]，供 dub_grouped 按偏移铺音
    global_t = 0.0
    for shot_id in order:
        members = by_shot.get(shot_id, [])
        cd = clip_durs.get(shot_id)   # 该镜真实片段时长（画面自然全长）；plan 阶段无片段则 None
        if members:
            # 逐行定位：显式 at（该行在本镜内的起始秒，对齐说话/嘴动时刻）优先，否则顺序排（gap 间隔）。
            placed: list[tuple] = []
            cursor = 0.0
            prev_end = 0.0
            for p in members:
                d = dur_by_idx.get(p["idx"], 0.0)
                at = p.get("at")
                at = cursor if at is None else float(at)
                # 旁白(画外音)的 at 只是编排偏好、无口型约束：越界但台词能装下 → 自动前移到刚好装下，
                # 免去人工反复调 at。画内对白的 at 要对齐嘴动，**绝不自动挪**（越界仍走下方 overflow 硬门）。
                if (cd is not None and p.get("speaker") == NARRATOR
                        and d <= cd + CLIP_EPS and at + d > cd + CLIP_EPS):
                    fit_at = max(0.0, round(cd - d - CLIP_EPS, 3))
                    if fit_at >= prev_end - 1e-3:
                        warns.append(f"镜 {shot_id} 旁白 at={at}s 越界，已自动前移到 {fit_at}s 适配片段（{cd}s）")
                        at = fit_at
                if at < 0:
                    violations.append({"type": "negative_at", "shot": shot_id, "idx": p["idx"],
                                       "at": round(at, 3)})
                if at < prev_end - 1e-3:
                    warns.append(f"镜 {shot_id} 第 {p['idx']} 行 at={at}s 与上一行重叠（上行到 {round(prev_end,3)}s）")
                    violations.append({"type": "overlap", "shot": shot_id, "idx": p["idx"],
                                       "at": round(at, 3), "previous_end": round(prev_end, 3),
                                       "over_by": round(prev_end - at, 3)})
                placed.append((p, at, d))
                prev_end = at + d
                cursor = at + d + gap
            content_end = max((at + d for _, at, d in placed), default=0.0)
            # 画面时长：有真实片段 → 用**完整片段**（台词只占其中一段，其余是动作/停顿/音效，自然）；
            # 无片段（plan 阶段）→ 用「台词跨度 + 尾巴」估算，供选片段档。
            if cd is None:
                visual = max(content_end + tail, min_shot)
            else:
                visual = cd
                for p, at, d in placed:
                    if at + d > cd + CLIP_EPS:   # 该行台词在片段内放不下 → 硬伤（片段太短/at 太靠后）
                        violations.append({"type": "overflow", "shot": shot_id, "idx": p["idx"],
                                           "at": round(at, 3), "line_end": round(at + d, 3),
                                           "clip": round(cd, 3), "over_by": round(at + d - cd, 3)})
            for p, at, d in placed:
                gs = global_t + at
                srt.append((gs, gs + d, p["text"]))
                timing.append({"idx": p["idx"], "shot": shot_id, "speaker": p["speaker"],
                               "text": p["text"], "at": round(at, 3),
                               "start": round(gs, 3), "end": round(gs + d, 3)})
            placements[shot_id] = [(p["idx"], at, d) for p, at, d in placed]
        else:
            # 纯动作/空镜：完整片段时长（留给动作/音效）；无片段用 action_durs 或默认。
            visual = float(cd if cd is not None else action_durs.get(shot_id, DEFAULT_ACTION_SHOT))
            placements[shot_id] = []
        shot_durations[shot_id] = round(visual, 3)
        global_t += visual
    return {"order": order, "by_shot": by_shot, "shot_durations": shot_durations,
            "srt": srt, "timing": timing, "total": round(global_t, 3),
            "warns": warns, "violations": violations, "placements": placements}


def plan_shot_durations(lines: list[dict], group_order: list, action_hint: dict | None = None,
                        gap: float = DEFAULT_GAP, min_shot: float = DEFAULT_MIN_SHOT,
                        tail: float = DEFAULT_TAIL) -> dict:
    """**生视频前**按台词估算每镜应停留的时长（不合成、不联网）。纯函数。

    用 estimate_line_seconds 估每行时长，复用 shot_layout 布局 → 返回 {shot_durations, total, ...}。
    据此把每镜的 I2V clip 生成成 ~该时长，画面/台词从源头贴合、自然，后期无需拉伸/循环。
    action_hint：{无台词镜idx: 期望秒}（LLM 意图，如空镜留 2s）；缺则用 DEFAULT_ACTION_SHOT。
    """
    plan: list[dict] = []
    dur_by_idx: dict = {}
    for i, ln in enumerate(lines):
        if not (ln.get("text") or "").strip():
            continue
        plan.append({"idx": i, "shot": ln.get("shot"), "speaker": ln.get("speaker", ""),
                     "text": ln.get("text", ""), "at": ln.get("at")})
        dur_by_idx[i] = estimate_line_seconds(ln.get("text", ""), ln.get("emotion"))
    return shot_layout(plan, group_order, action_hint or {}, dur_by_idx, gap, min_shot, tail)


def dub_grouped(cast_file: Path, lines: list[dict], group_order: list,
                action_durs: dict, out_mp3: Path,
                srt_out: Path | None = None, timing_out: Path | None = None,
                gap: float = DEFAULT_GAP, min_shot: float = DEFAULT_MIN_SHOT,
                tail: float = DEFAULT_TAIL, proxy: str | None = None,
                clip_durs: dict | None = None, strict: bool = True,
                allow_edge: bool = False, allow_empty: bool = False) -> dict:
    """逐镜时间线配音：**画面 = 完整片段**（自然全长），台词只占片段内的一段、按 `at` 偏移放置。

    模型（借鉴时间线/轨道式合成）：每镜是一条 clip_dur 长的时间线，台词行按各自 `at`（镜内起始秒，
    对齐说话/嘴动时刻）叠到静音床上；台词之间/前后的空白留给**动作/停顿/音效**（片段时长通常 > 台词总长）。
    - lines：逐行对白，每行带 `shot`（所属镜头 idx）+ 可选 `at`（镜内起始秒，无则顺序排）。
    - group_order：按播放顺序排列的**全部镜头 idx**（含无台词的动作镜）。
    - action_durs：{镜idx: 秒}，无台词镜且无 clip 时的兜底视觉时长。
    - clip_durs：{镜idx: 秒}，**每镜真实片段时长**——画面即用它（不裁、不拉伸、不循环、不冻结）。
    - strict：True（默认）时，若某行台词在其片段内放不下（at+时长 > 片段）→ **硬失败**并报告，
      让上层按更大片段档重生成该镜 / 拆镜 / 精简台词 / 把 at 提前（而不是事后拉伸糊弄）。False 仅告警。
    产出镜对齐的 voice.mp3 + 同一时间轴的 voice.srt + 每镜时长表 shot_durations + timing.json（含每行 at）。
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        _die("需要 ffmpeg/ffprobe（逐镜拼接音轨与探测时长）")
    cast = cast_load(cast_file)
    plan, warns = build_plan(cast, lines)
    for w in warns:
        print(f"⚠️ {w}", file=sys.stderr)
    if not plan and not allow_empty:
        _die("没有可合成的台词")
    strict_closed = _preflight_closed_source(plan, allow_edge) if plan else False

    srt_out = srt_out or out_mp3.with_suffix(".srt")
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td)
        clips, durations, voices_used = _synth_plan(plan, proxy, wd, strict_closed) if plan else ([], [], set())
        dur_by_idx = {p["idx"]: d for p, d in zip(plan, durations)}
        clip_by_idx = {p["idx"]: c for p, c in zip(plan, clips)}

        lay = shot_layout(plan, group_order, action_durs, dur_by_idx, gap, min_shot, tail,
                          clip_durs=clip_durs)
        for w in lay["warns"]:
            print(f"⚠️ {w}", file=sys.stderr)
        # 一致性门：真实配音出来后，检查每行台词是否在其镜片段内放得下（治「片段短了只能拉伸/冻结」）
        if lay["violations"]:
            report = "\n  - ".join(
                (f"镜 {v['shot']} 第 {v['idx']} 行：台词在 at={v['at']}s 处到 {v['line_end']}s，"
                 f"超出片段 {v['clip']}s（超 {v['over_by']}s）")
                if v.get("type") == "overflow" else
                (f"镜 {v['shot']} 第 {v['idx']} 行：at={v['at']}s 与上一句重叠 "
                 f"{v['over_by']}s（上一句到 {v['previous_end']}s）")
                if v.get("type") == "overlap" else
                f"镜 {v['shot']} 第 {v['idx']} 行：at={v['at']}s 不能为负数"
                for v in lay["violations"])
            msg = ("台词时间线不合法（越界、重叠或负起点）：\n  - " + report
                   + "\n修法（择一，别靠后期拉伸）：① 用更大片段档重生成该镜（ai-video-gen --duration 10）；"
                     "② 把该镜拆成多镜、台词分摊；③ 精简台词或把该行 at 提前，让它在片段内说完。"
                     "改完重跑 align。")
            if strict:
                _die(msg)
            print(f"⚠️ {msg}", file=sys.stderr)

        # 逐镜铺音：每镜=完整片段时长的静音床，台词按 at 偏移叠入（不首尾相接填满）——
        # 留出的空白正是动作/停顿/音效的时间，画面自然、说话时刻对得上。
        shot_tracks: list[Path] = []
        for gi, shot_id in enumerate(lay["order"]):
            track = wd / f"shot_{gi:03d}.mp3"
            visual = lay["shot_durations"][shot_id]
            placed = lay["placements"].get(shot_id, [])
            if placed:
                _place_on_timeline([clip_by_idx[idx] for idx, _at, _d in placed],
                                   [at for _idx, at, _d in placed], visual, track)
            else:
                _silence(visual, track)
            shot_tracks.append(track)

        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        _concat_audio(shot_tracks, 0.0, out_mp3)

    srt_text = "\n".join(
        f"{i}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{lab}\n"
        for i, (s, e, lab) in enumerate(lay["srt"], start=1))
    srt_out.write_text(srt_text, encoding="utf-8")

    timing_out = timing_out or out_mp3.with_name("timing.json")
    _write_json(timing_out, {"shot_durations": lay["shot_durations"],
                             "lines": lay["timing"], "total": lay["total"],
                             "order": lay["order"]})

    return {"voice": str(out_mp3), "srt": str(srt_out), "timing": str(timing_out),
            "lines": len(plan), "voices": sorted(voices_used),
            "shot_durations": lay["shot_durations"], "duration": round(lay["total"], 1)}


# ── selftest ──────────────────────────────────────────────────────────
def _selftest() -> int:
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    chk("emotion 怒 vs 温柔 不同", emotion_prosody("愤怒") != emotion_prosody("温柔"))
    chk("emotion 未识别=0", emotion_prosody("莫名其妙") == (0, 0, 0))
    r, p, v = combine_prosody("-5%", "-3Hz", None, "怒")
    chk("combine 叠加 rate", r == "+3%")
    chk("combine 叠加 pitch", p == "-4Hz")
    chk("combine clamp", combine_prosody("60%", None, None, "紧张")[0] == "+50%")
    chk("同角色不同情绪韵律不同",
        combine_prosody("0%", "0Hz", "0%", "怒") != combine_prosody("0%", "0Hz", "0%", "温柔"))

    with tempfile.TemporaryDirectory() as td:
        cf = Path(td) / "cast.json"
        cast_init(cf, "测试")
        cast_add(cf, {"name": "林策", "role": "male_lead", "engine": "edge",
                      "voice": "zh-CN-YunxiNeural", "rate": "-5%", "pitch": "-3Hz",
                      "volume": None, "note": "冷峻男主"})
        cast_add(cf, {"name": "苏晚", "role": "female_lead", "engine": "edge",
                      "voice": "zh-CN-XiaoxiaoNeural", "note": "温婉女主"})
        cast = cast_load(cf)
        chk("cast init+add 3 条", len(cast["cast"]) == 3)
        chk("cast_check 通过", cast_check(cast) == [])
        chk("cast_check 抓旁白/角色同音色 或 重复音色",
            cast_check({"cast": [{"name": NARRATOR, "role": "narrator", "voice": "zh-CN-YunxiNeural"},
                                 {"name": "A", "voice": "zh-CN-YunxiNeural"}]}) != [])
        chk("cast_check 抓未知音色", any("不在已知" in x for x in
            cast_check({"cast": [{"name": NARRATOR, "role": "narrator", "voice": "zh-CN-YunxiNeural"},
                                 {"name": "B", "voice": "zh-XX-FooNeural"}]})))
        # 闭源强制：配了闭源后任何 edge（含旁白）都是硬错误
        chk("配闭源后 edge(含旁白) 被硬拦", any("必须改闭源" in x for x in
            cast_check(cast, closed_source_configured=True)))
        # 旁白默认闭源：给 narrator_provider 有预置音色 → 旁白是 clone、非 edge(AI味)
        cf2 = Path(td) / "cast2.json"
        cast_init(cf2, "测试2", narrator_provider="openai-compatible")
        nar = cast_load(cf2)["cast"][0]
        chk("cast_init 旁白默认闭源(clone+预置voice_id)",
            nar["engine"] == "clone" and nar.get("voice_id") == PRESET_NARRATOR_VOICE["openai-compatible"])
        # 无 provider → 旁白退 edge 但 note 标注务必升级
        cf3 = Path(td) / "cast3.json"
        cast_init(cf3, "测试3")
        chk("无 provider 时旁白退 edge 且 note 提示升级",
            cast_load(cf3)["cast"][0]["engine"] == "edge"
            and "闭源" in cast_load(cf3)["cast"][0]["note"])
        # 形象原型缺失 → advisories 提醒（先看定妆图再定音色）
        chk("advisories 提醒补 archetype",
            any("archetype" in t and "林策" in t for t in cast_advisories(cast)))

        # 合成时闭源硬闸门：配了 VOICE_PROVIDER 就在合成前拦下会用 edge 的行
        chk("_edge_resolved 识别 edge / clone缺voice_id",
            _edge_resolved([{"engine": "edge"}]) and _edge_resolved([{"engine": "clone", "voice_id": None}])
            and not _edge_resolved([{"engine": "clone", "voice_id": "v"}]))
        _saved = os.environ.get("VOICE_PROVIDER")
        os.environ["VOICE_PROVIDER"] = "openai-compatible"
        try:
            edge_plan = [{"idx": 0, "speaker": "A", "engine": "edge", "voice": "x"}]
            died = False
            try:
                _preflight_closed_source(edge_plan, allow_edge=False)
            except SystemExit:
                died = True
            chk("配闭源+edge行→合成前硬失败", died)
            chk("--allow-edge 放行 edge（不拦）", _preflight_closed_source(edge_plan, allow_edge=True) is False)
            chk("闭源 clone 行→通过(strict)",
                _preflight_closed_source([{"idx": 0, "speaker": "A", "engine": "clone", "voice_id": "v"}],
                                         allow_edge=False) is True)
        finally:
            if _saved is None:
                os.environ.pop("VOICE_PROVIDER", None)
            else:
                os.environ["VOICE_PROVIDER"] = _saved

        lines = [{"speaker": "旁白", "text": "三年后。", "emotion": "平"},
                 {"speaker": "林策", "text": "你输了。", "emotion": "冷"},
                 {"speaker": "路人甲", "text": "谁啊？", "emotion": "惊"}]
        plan, warns = build_plan(cast, lines)
        chk("build_plan 3 行", len(plan) == 3)
        chk("未知说话人回退旁白", plan[2]["voice"] == cast["cast"][0]["voice"] and any("路人甲" in w for w in warns))
        chk("林策音色正确", plan[1]["voice"] == "zh-CN-YunxiNeural")
        srt = build_srt(plan, [1.0, 2.0, 1.5], 0.5)
        chk("srt 3 段 + 默认无角色名前缀", srt.count("-->") == 3 and "林策：" not in srt and "你输了。" in srt)
        chk("srt with_speaker=True 带角色名", "林策：" in build_srt(plan, [1.0, 2.0, 1.5], 0.5, with_speaker=True))
        chk("srt 第2段起点=1.0+0.5", "00:00:01,500 -->" in srt)

        # clone 引擎：逐行 emotion 应带入合成计划（供 _synth_line 转发给云 provider 情感通道）
        cast_add(cf, {"name": "霸总", "role": "male_lead", "engine": "clone",
                      "provider": "minimax", "voice_id": "vc_boss", "note": "克隆音色"})
        cast2 = cast_load(cf)
        plan2, _ = build_plan(cast2, [{"speaker": "霸总", "text": "你敢背叛我？", "emotion": "愤怒"}])
        chk("clone 计划带 emotion + voice_id",
            plan2[0]["engine"] == "clone" and plan2[0]["voice_id"] == "vc_boss"
            and plan2[0]["emotion"] == "愤怒")

        # cast_advisories：说话角色用 edge → 出建议；旁白不算
        adv = cast_advisories(cast)
        chk("advisories 提示 edge 主角升级闭源", any("林策" in t for t in adv) and all("旁白" not in t for t in adv))

        # validate_lines：抓「speaker 不在 cast（配错角色）/ 缺 shot / shot 越界」
        vl_ok = validate_lines(cast, [{"speaker": "林策", "text": "hi", "shot": 1}], {1, 2})
        chk("validate_lines 合法=空", vl_ok == [])
        vl_bad = validate_lines(cast, [{"speaker": "路人乙", "text": "hi", "shot": 9}], {1, 2})
        chk("validate_lines 抓未知 speaker + shot 越界",
            any("路人乙" in p for p in vl_bad) and any("shot=9" in p for p in vl_bad))
        chk("validate_lines 抓缺 shot",
            any("缺 shot" in p for p in validate_lines(cast, [{"speaker": "林策", "text": "hi"}], {1})))

        # estimate_line_seconds：字越多越久；急促比悲伤短
        chk("估时 长句 > 短句",
            estimate_line_seconds("这是一句相当长的台词用来测试估时") > estimate_line_seconds("好"))
        chk("估时 悲(慢) > 怒(快) 同文本",
            estimate_line_seconds("我不敢相信会这样", "悲") > estimate_line_seconds("我不敢相信会这样", "怒"))
        chk("估时 空文本=0", estimate_line_seconds("", None) == 0.0)

        # plan_shot_durations：生视频前按台词估每镜时长（不联网）
        plines = [{"speaker": "林策", "text": "你以为你赢了？", "emotion": "冷笑", "shot": 1},
                  {"speaker": "苏晚", "text": "我从没想过输。", "emotion": "坚定", "shot": 1},
                  {"speaker": "旁白", "text": "夜色渐深。", "shot": 3}]
        pl = plan_shot_durations(plines, [1, 2, 3], action_hint={2: 2.5})
        chk("plan 镜1有台词>min_shot", pl["shot_durations"][1] > DEFAULT_MIN_SHOT)
        chk("plan 镜2(无台词)用 action_hint=2.5", pl["shot_durations"][2] == 2.5)
        chk("plan 总时长>0 且=各镜和",
            pl["total"] > 0 and abs(pl["total"] - sum(pl["shot_durations"].values())) < 0.01)

        # shot_layout（纯函数逐镜对齐）：line 带 shot；无台词的镜 2 用 action_durs
        lplan = [{"idx": 0, "speaker": "旁白", "text": "夜。", "shot": 1},
                 {"idx": 1, "speaker": "林策", "text": "你输了。", "shot": 1},
                 {"idx": 2, "speaker": "苏晚", "text": "不可能。", "shot": 3}]
        dbi = {0: 1.0, 1: 1.0, 2: 2.0}
        lay = shot_layout(lplan, [1, 2, 3], {2: 4.0}, dbi, gap=0.5, min_shot=1.2, tail=0.3)
        # 镜1：两行 audio=1.0+0.5+1.0=2.5，visual=max(2.5+0.3,1.2)=2.8；镜2：无台词=4.0；镜3：2.0+0.3=2.3
        chk("镜1时长=2.8", lay["shot_durations"][1] == 2.8)
        chk("镜2(无台词)用 action_durs=4.0", lay["shot_durations"][2] == 4.0)
        chk("镜3时长=2.3", lay["shot_durations"][3] == 2.3)
        chk("总时长=2.8+4.0+2.3=9.1", lay["total"] == 9.1)
        # 镜3 台词全局起点 = 镜1(2.8)+镜2(4.0)=6.8
        chk("镜3行全局起点=6.8", any(t["shot"] == 3 and t["start"] == 6.8 for t in lay["timing"]))
        chk("srt 段数=3 行台词", len(lay["srt"]) == 3)
        chk("无 clip 时 violations 空", lay["violations"] == [])

        # 时间线模型（画面=完整片段，台词只占其中一段）：镜1 台词跨度 content_end=2.5
        layc = shot_layout(lplan, [1, 2, 3], {2: 4.0}, dbi, gap=0.5, min_shot=1.2, tail=0.3,
                           clip_durs={1: 5.0, 3: 5.0})
        chk("片段5.0→画面=完整5.0(非裁到台词)、台词放得下、无违规",
            layc["shot_durations"][1] == 5.0 and layc["violations"] == [])
        layv = shot_layout(lplan, [1, 2, 3], {2: 4.0}, dbi, gap=0.5, min_shot=1.2, tail=0.3,
                           clip_durs={1: 2.0})
        chk("片段2.0<台词跨度2.5→记违规(该硬拦重生成/拆镜)",
            layv["shot_durations"][1] == 2.0
            and any(v["shot"] == 1 and v["over_by"] > 0 for v in layv["violations"]))

        # 显式 at：台词按镜内偏移放置（对齐说话时刻），画面仍是完整片段，其余时间留给动作/音效
        lay_at = shot_layout([{"idx": 0, "speaker": "林策", "text": "你输了", "shot": 1, "at": 1.5}],
                             [1], {}, {0: 1.0}, clip_durs={1: 5.0})
        chk("at 放置：画面=完整5.0 + 台词全局起点=1.5 + placements 带偏移",
            lay_at["shot_durations"][1] == 5.0
            and any(t["at"] == 1.5 and t["start"] == 1.5 for t in lay_at["timing"])
            and lay_at["placements"][1] == [(0, 1.5, 1.0)])
        lay_over = shot_layout([{"idx": 0, "speaker": "A", "text": "x", "shot": 1, "at": 4.5}],
                               [1], {}, {0: 1.0}, clip_durs={1: 5.0})
        chk("画内对白 at 越界(4.5+1.0>5.0)→记违规(不自动挪,保口型)",
            any(v["idx"] == 0 and v["over_by"] > 0 for v in lay_over["violations"]))
        # 旁白 at 越界但能装下 → 自动前移适配、不记违规（画外音无口型约束）
        lay_narr = shot_layout([{"idx": 0, "speaker": NARRATOR, "text": "旁白很长的一句", "shot": 1, "at": 4.5}],
                               [1], {}, {0: 1.0}, clip_durs={1: 5.0})
        chk("旁白 at 越界→自动前移适配(无违规)",
            not any(v.get("type") == "overflow" for v in lay_narr["violations"])
            and all(t["start"] + 1.0 <= 5.0 + 0.15 for t in lay_narr["timing"]))
        lay_overlap = shot_layout([
            {"idx": 0, "speaker": "A", "text": "x", "shot": 1, "at": 0.0},
            {"idx": 1, "speaker": "B", "text": "y", "shot": 1, "at": 0.5},
        ], [1], {}, {0: 2.0, 1: 1.0}, clip_durs={1: 5.0})
        chk("同镜台词重叠→记硬违规",
            any(v.get("type") == "overlap" for v in lay_overlap["violations"]))
        lay_negative = shot_layout([
            {"idx": 0, "speaker": "A", "text": "x", "shot": 1, "at": -0.2},
        ], [1], {}, {0: 1.0}, clip_durs={1: 5.0})
        chk("负 at→记硬违规",
            any(v.get("type") == "negative_at" for v in lay_negative["violations"]))

        # 未知 shot 归到最后一镜 + 告警
        lay2 = shot_layout([{"idx": 0, "speaker": "A", "text": "x", "shot": 9}], [1, 2], {}, {0: 1.0})
        chk("未知 shot 归最后一镜 + 告警", lay2["by_shot"].get(2) and lay2["warns"])

    print("✅ selftest 通过" if ok else "❌ selftest 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="多角色/对话配音引擎（cast + lines → 多声线 voice.mp3 + srt）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("cast", help="选角（角色→音色）")
    csub = pc.add_subparsers(dest="castcmd", required=True)
    ci = csub.add_parser("init", help="生成 cast.json 模板")
    ci.add_argument("--cast", required=True, help="cast.json 路径")
    ci.add_argument("--title", default="")
    ca = csub.add_parser("add", help="追加/覆盖一个角色音色")
    ca.add_argument("--cast", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--role", default="")
    # 默认 clone（闭源优先）；缺 provider 时取环境变量 VOICE_PROVIDER。edge 仅无 key 兜底。
    ca.add_argument("--engine", default="clone", choices=["edge", "clone"])
    ca.add_argument("--voice", default="")
    ca.add_argument("--rate", help="语速微调，负值用等号：--rate=-5%%")
    ca.add_argument("--pitch", help="音调微调，负值用等号：--pitch=-3Hz")
    ca.add_argument("--volume", help="音量微调，如 --volume=+10%%")
    ca.add_argument("--provider"); ca.add_argument("--voice-id", dest="voice_id")
    ca.add_argument("--archetype", default="",
                    help="形象原型（看定妆图判断：萝莉/御姐/大叔/冷峻男主…）——音色必须贴合它")
    ca.add_argument("--ref", default="", help="该角色定妆图的 C 编号（如 C01），绑定音色↔画面形象")
    ca.add_argument("--note", default="")
    cl = csub.add_parser("list", help="列出选角"); cl.add_argument("--cast", required=True)
    cc = csub.add_parser("check", help="校验选角"); cc.add_argument("--cast", required=True)

    pd = sub.add_parser("dub", help="逐行多声线配音 → voice.mp3 + voice.srt")
    pd.add_argument("--cast", required=True, help="cast.json 路径")
    pd.add_argument("--lines", required=True, help="lines.json 路径（[{speaker,text,emotion}]）")
    pd.add_argument("-o", "--output", required=True, help="voice.mp3 输出路径")
    pd.add_argument("--srt", help="字幕输出路径（默认与 voice 同名 .srt）")
    pd.add_argument("--gap", type=float, default=DEFAULT_GAP, help=f"行间停顿秒（默认 {DEFAULT_GAP}）")
    pd.add_argument("--proxy", help="外网代理（默认读环境变量，edge-tts 需外网）")
    pd.add_argument("--allow-edge", dest="allow_edge", action="store_true",
                    help="放行 edge(AI 音色)：默认配了闭源(VOICE_PROVIDER)就硬拦 edge，确无 key 才加此项")

    sub.add_parser("selftest", help="自检")

    a = ap.parse_args()
    if a.cmd == "selftest":
        return _selftest()
    if a.cmd == "cast":
        cf = Path(a.cast).expanduser()
        if a.castcmd == "init":
            r = cast_init(cf, a.title, narrator_provider=os.environ.get("VOICE_PROVIDER"))
            print(f"✅ {r['path']}" + ("（新建）" if r["created"] else "（已存在，未覆盖）"))
        elif a.castcmd == "add":
            provider = a.provider
            if a.engine == "clone" and not provider:
                provider = (os.environ.get("VOICE_PROVIDER") or "").strip() or None
            e = cast_add(cf, {"name": a.name, "role": a.role, "engine": a.engine,
                              "voice": a.voice or None, "rate": a.rate, "pitch": a.pitch,
                              "volume": a.volume, "provider": provider,
                              "voice_id": a.voice_id, "archetype": a.archetype,
                              "ref": a.ref, "note": a.note})
            print(f"✅ {e['name']} → {e.get('voice') or e.get('voice_id')}（{e['engine']}"
                  + (f"·{provider}" if provider else "") + "）")
        elif a.castcmd == "list":
            for c in cast_load(cf).get("cast", []):
                tag = c.get("voice") if c.get("engine") == "edge" else f"clone:{c.get('voice_id')}"
                print(f"  {c.get('name')} [{c.get('role','')}] {tag} rate={c.get('rate')} pitch={c.get('pitch')}"
                      f" 形象={c.get('archetype','?')} — {c.get('note','')}")
        elif a.castcmd == "check":
            data = cast_load(cf)
            probs = cast_check(data, closed_source_configured=_closed_source_configured())
            if probs:
                print(f"⚠️ 选角有 {len(probs)} 个问题：")
                for p in probs:
                    print(f"  - {p}")
                return 1
            print("✅ 选角校验通过")
            for tip in cast_advisories(data):
                print(f"  💡 {tip}")
        return 0
    if a.cmd == "dub":
        r = dub(Path(a.cast).expanduser(), Path(a.lines).expanduser(),
                Path(a.output).expanduser(),
                Path(a.srt).expanduser() if a.srt else None, a.gap, a.proxy,
                allow_edge=a.allow_edge)
        print(f"✅ 配音完成：{r['voice']}（{r['lines']} 行，{r['duration']}s，"
              f"{len(r['voices'])} 种声线）\n   字幕：{r['srt']}\n   声线：{'、'.join(r['voices'])}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
