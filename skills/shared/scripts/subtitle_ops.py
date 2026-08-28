#!/usr/bin/env python3
"""subtitle_ops.py — 字幕解析 / 双语合并 / 烧录的确定性封装。

"字幕翻译 / 双语字幕"类 SKILL（subtitle-translate 等）共用此脚本。翻译本身由
LLM 完成（agent 读原文行 → 逐行翻译 → 回填），本脚本只负责**确定性**的部分：
解析多格式字幕、按行提取待译文本、把译文与原文合并成双语字幕、格式互转、
以及软挂载 / 硬烧录进视频。这样翻译质量交给 LLM，时间轴/格式/烧录不出错。

与 asr.py 的边界：asr.py 是"语音 → 字幕"（ASR）；本脚本是"已有字幕 → 翻译/双语/烧录"，
不做语音识别。与 video_ops.py 的边界：video_ops 做通用剪辑，本脚本专管字幕。

依赖：ffmpeg + ffprobe（仅 burn/convert-from-video 用）。解析/合并纯 Python，无依赖。

子命令（每个都能 `-h`）：
    parse     解析 srt/vtt/ass → JSON（cues: idx/start/end/text）
    extract   按行提取待译文本（编号，供 LLM 翻译）
    merge     原文字幕 + 译文行 → 双语字幕（srt/ass）
    build     从 JSON（含 text + 可选 trans）构建单语/双语字幕
    convert   字幕格式互转（srt ↔ vtt ↔ ass）
    burn      把字幕烧录（硬字幕）或挂载（软字幕）进视频
    selftest  自检（造样例 → 解析 → 双语 → 校验）

用法举例：
    subtitle_ops.py extract -i in.srt -o lines.txt          # 提取待译行
    #  → LLM 逐行翻译 lines.txt 得 trans.txt（行数一致）
    subtitle_ops.py merge -i in.srt --trans trans.txt -o bi.srt --order orig-top
    subtitle_ops.py merge -i in.srt --trans trans.txt -o bi.ass --format ass
    subtitle_ops.py burn -i video.mp4 --sub bi.ass -o out.mp4          # 硬烧录
    subtitle_ops.py burn -i video.mp4 --sub bi.srt -o out.mp4 --soft   # 软挂载
    subtitle_ops.py selftest
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 中文友好断行用标点
_ZH_PUNCT = "，。！？；：、,.!?;:）】》"


# ── 基础工具 ──────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _require_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


# ── 时间戳 ────────────────────────────────────────────────────────────
def _parse_ts(ts: str) -> float:
    """解析 SRT(00:00:01,000) / VTT(00:00:01.000 或 00:01.000) / ASS(0:00:01.00) 时间戳 → 秒。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
        elif len(parts) == 2:
            h, m, s = "0", parts[0], parts[1]
        else:
            return 0.0
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


def _fmt_srt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _fmt_vtt_ts(sec: float) -> str:
    return _fmt_srt_ts(sec).replace(",", ".")


def _fmt_ass_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


# ── 解析各格式 → 统一 cue 列表 ────────────────────────────────────────
# cue = {"idx": int, "start": float, "end": float, "text": str}
#   text 内部换行统一用 "\n"

_TS_RANGE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)


def _parse_srt_vtt(raw: str) -> list[dict]:
    cues: list[dict] = []
    # 归一化换行，去 BOM 与 VTT 头
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks = re.split(r"\n\s*\n", raw.strip())
    idx = 0
    for blk in blocks:
        lines = [l for l in blk.split("\n") if l.strip() != ""]
        if not lines:
            continue
        if lines[0].strip().upper().startswith("WEBVTT"):
            lines = lines[1:]
            if not lines:
                continue
        # 跳过纯序号行
        if lines and re.fullmatch(r"\d+", lines[0].strip()):
            lines = lines[1:]
        if not lines:
            continue
        m = _TS_RANGE.search(lines[0])
        if not m:
            continue
        start, end = _parse_ts(m.group(1)), _parse_ts(m.group(2))
        text = "\n".join(lines[1:]).strip()
        if not text:
            continue
        idx += 1
        cues.append({"idx": idx, "start": start, "end": end, "text": text})
    return cues


def _parse_ass(raw: str) -> list[dict]:
    cues: list[dict] = []
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    fmt_fields: list[str] = []
    idx = 0
    for line in raw.split("\n"):
        s = line.strip()
        if s.startswith("Format:") and not fmt_fields:
            fmt_fields = [f.strip().lower() for f in s[len("Format:"):].split(",")]
        elif s.startswith("Dialogue:"):
            body = s[len("Dialogue:"):]
            # Text 是最后一个字段，前面按逗号切固定数量
            n = len(fmt_fields) if fmt_fields else 10
            parts = body.split(",", n - 1)
            if len(parts) < n:
                continue
            try:
                si = fmt_fields.index("start") if fmt_fields else 1
                ei = fmt_fields.index("end") if fmt_fields else 2
            except ValueError:
                si, ei = 1, 2
            start, end = _parse_ts(parts[si]), _parse_ts(parts[ei])
            text = parts[-1]
            # 去 ASS 覆盖标签 {...}，\N/\n → 换行
            text = re.sub(r"\{[^}]*\}", "", text)
            text = text.replace("\\N", "\n").replace("\\n", "\n").strip()
            if not text:
                continue
            idx += 1
            cues.append({"idx": idx, "start": start, "end": end, "text": text})
    return cues


def parse_file(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    suf = path.suffix.lower()
    if suf == ".ass" or suf == ".ssa" or "[Events]" in raw[:2000]:
        cues = _parse_ass(raw)
    else:
        cues = _parse_srt_vtt(raw)
    if not cues:
        _die(f"未从 {path.name} 解析出任何字幕条目（格式不支持或文件为空）。", 2)
    return cues


# ── 渲染各格式 ────────────────────────────────────────────────────────
def _render_srt(cues: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{_fmt_srt_ts(c['start'])} --> {_fmt_srt_ts(c['end'])}\n{c['text']}")
    return "\n\n".join(blocks) + "\n"


def _render_vtt(cues: list[dict]) -> str:
    blocks = ["WEBVTT\n"]
    for c in cues:
        blocks.append(f"{_fmt_vtt_ts(c['start'])} --> {_fmt_vtt_ts(c['end'])}\n{c['text']}")
    return "\n\n".join(blocks) + "\n"


# 双语 ASS：原文（白，较大）+ 译文（黄，略小，位置更靠下），两条 Dialogue 分别用两种 Style
_ASS_BI_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Orig,{font},{fs_orig},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{mv_orig},1
Style: Trans,{font},{fs_trans},&H0000FFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,{mv_trans},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# 单语 ASS
_ASS_MONO_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _render_ass_bilingual(cues: list[dict], order: str, font: str) -> str:
    """双语 ASS：两条 Dialogue（Orig/Trans），译文在下、原文在上。
    order=orig-top → 原文在上方（MarginV 大）译文在下方（MarginV 小）。"""
    if order == "trans-top":
        mv_orig, mv_trans = 40, 105
    else:  # orig-top（默认）
        mv_orig, mv_trans = 105, 40
    header = _ASS_BI_HEADER.format(
        font=font, fs_orig=58, fs_trans=48, mv_orig=mv_orig, mv_trans=mv_trans)
    lines = [header]
    for c in cues:
        s, e = _fmt_ass_ts(c["start"]), _fmt_ass_ts(c["end"])
        orig = c["text"].replace("\n", "\\N")
        trans = (c.get("trans") or "").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{s},{e},Orig,,0,0,0,,{orig}")
        if trans:
            lines.append(f"Dialogue: 0,{s},{e},Trans,,0,0,0,,{trans}")
    return "\n".join(lines) + "\n"


def _render_ass_mono(cues: list[dict], font: str) -> str:
    header = _ASS_MONO_HEADER.format(font=font, fs=60)
    lines = [header]
    for c in cues:
        s, e = _fmt_ass_ts(c["start"]), _fmt_ass_ts(c["end"])
        body = c["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{body}")
    return "\n".join(lines) + "\n"


def _bilingual_srt(cues: list[dict], order: str) -> list[dict]:
    """把 cue 的 text/trans 堆叠成 SRT 双语正文（原文\\n译文）。"""
    out = []
    for c in cues:
        orig, trans = c["text"], (c.get("trans") or "")
        if trans:
            body = f"{trans}\n{orig}" if order == "trans-top" else f"{orig}\n{trans}"
        else:
            body = orig
        out.append({**c, "text": body})
    return out


def _write_subtitle(cues: list[dict], out: Path, fmt: str, *,
                    bilingual: bool, order: str, font: str) -> None:
    if fmt == "ass":
        content = (_render_ass_bilingual(cues, order, font)
                   if bilingual else _render_ass_mono(cues, font))
    elif fmt == "vtt":
        content = _render_vtt(_bilingual_srt(cues, order) if bilingual else cues)
    else:  # srt
        content = _render_srt(_bilingual_srt(cues, order) if bilingual else cues)
    out.write_text(content, encoding="utf-8")


def _fmt_from_out(out: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    suf = Path(out).suffix.lower().lstrip(".")
    return suf if suf in ("srt", "vtt", "ass") else "srt"


# ── 子命令 ────────────────────────────────────────────────────────────
def cmd_parse(a) -> int:
    cues = parse_file(_require_input(a.input))
    payload = json.dumps({"count": len(cues), "cues": cues}, ensure_ascii=False, indent=2)
    if a.output:
        out = _prep_out(a.output)
        out.write_text(payload, encoding="utf-8")
        _done(out, f"({len(cues)} 条)")
    else:
        print(payload)
    return 0


def cmd_extract(a) -> int:
    """按行输出待译文本，每 cue 一行（内部换行用空格连接），供 LLM 逐行翻译。
    行号与 cue 顺序一致；LLM 翻译后须保持行数与顺序不变。"""
    cues = parse_file(_require_input(a.input))
    lines = [c["text"].replace("\n", " ").strip() for c in cues]
    body = "\n".join(lines) + "\n"
    if a.output:
        out = _prep_out(a.output)
        out.write_text(body, encoding="utf-8")
        _done(out, f"({len(lines)} 行待译)")
        print(f"提示：逐行翻译为等行数文件，再 `merge -i {a.input} --trans <译文> -o <双语>`",
              file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


def cmd_merge(a) -> int:
    """原文字幕 + 译文行文件 → 双语（或纯译文）字幕。译文行数须与 cue 数一致。"""
    cues = parse_file(_require_input(a.input))
    trans_raw = _require_input(a.trans).read_text(encoding="utf-8", errors="replace")
    trans_lines = [l.rstrip() for l in trans_raw.replace("\r\n", "\n").split("\n")]
    # 去掉尾部空行
    while trans_lines and trans_lines[-1].strip() == "":
        trans_lines.pop()
    if len(trans_lines) != len(cues):
        _die(f"译文行数（{len(trans_lines)}）与字幕条数（{len(cues)}）不一致。"
             f"请保持逐行一一对应、不增删空行。", 2)
    for c, t in zip(cues, trans_lines):
        c["trans"] = t.strip()
    fmt = _fmt_from_out(a.output, a.format)
    bilingual = not a.trans_only
    if a.trans_only:  # 只输出译文（用译文替换原文）
        for c in cues:
            c["text"] = c.get("trans") or c["text"]
    out = _prep_out(a.output)
    _write_subtitle(cues, out, fmt, bilingual=bilingual, order=a.order, font=a.font)
    _done(out, f"({len(cues)} 条 {'双语' if bilingual else '纯译文'} {fmt})")
    return 0


def cmd_build(a) -> int:
    """从 JSON 构建字幕。JSON 为 parse 的输出格式，cue 可含 text 与可选 trans。"""
    raw = sys.stdin.read() if a.json == "-" else _require_input(a.json).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"JSON 解析失败：{e}", 2)
    cues = data.get("cues") if isinstance(data, dict) else data
    if not cues:
        _die("JSON 中没有 cues。", 2)
    has_trans = any((c.get("trans") or "").strip() for c in cues)
    bilingual = has_trans and not a.trans_only
    if a.trans_only:
        for c in cues:
            c["text"] = c.get("trans") or c["text"]
    fmt = _fmt_from_out(a.output, a.format)
    out = _prep_out(a.output)
    _write_subtitle(cues, out, fmt, bilingual=bilingual, order=a.order, font=a.font)
    _done(out, f"({len(cues)} 条 {fmt})")
    return 0


def cmd_convert(a) -> int:
    cues = parse_file(_require_input(a.input))
    fmt = _fmt_from_out(a.output, a.format)
    out = _prep_out(a.output)
    _write_subtitle(cues, out, fmt, bilingual=False, order="orig-top", font=a.font)
    _done(out, f"→ {fmt}")
    return 0


def _check_ffmpeg() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            _die(f"未找到 {t}，burn 需要 ffmpeg。", 3)


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        _die(f"ffmpeg 执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)


def _ff_escape(path: str) -> str:
    """subtitles/ass 滤镜文件名转义（: \\ ' 需转义）。"""
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def cmd_burn(a) -> int:
    _check_ffmpeg()
    video = _require_input(a.input)
    sub = _require_input(a.sub)
    out = _prep_out(a.output)
    if a.soft:
        # 软字幕：挂载为可开关字幕轨。mp4 → mov_text；mkv → srt。
        codec = "srt" if out.suffix.lower() == ".mkv" else "mov_text"
        _run(["ffmpeg", "-y", "-i", str(video), "-i", str(sub),
              "-map", "0", "-map", "1", "-c", "copy", "-c:s", codec,
              "-metadata:s:s:0", f"language={a.lang}", str(out)])
        _done(out, "(软字幕轨)")
    else:
        # 硬字幕：烧进画面。ass 用 ass 滤镜（保留样式），srt/vtt 用 subtitles 滤镜。
        sp = _ff_escape(str(sub))
        if sub.suffix.lower() in (".ass", ".ssa"):
            vf = f"ass='{sp}'"
        else:
            style = a.force_style or "Fontsize=22,Outline=1,Shadow=0"
            vf = f"subtitles='{sp}':force_style='{style}'"
            if a.font_dir:
                vf += f":fontsdir='{_ff_escape(a.font_dir)}'"
        _run(["ffmpeg", "-y", "-i", str(video), "-vf", vf,
              "-c:v", "libx264", "-crf", "20", "-preset", "medium",
              "-c:a", "copy", str(out)])
        _done(out, "(硬字幕)")
    return 0


def cmd_selftest(_a) -> int:
    print("subtitle_ops 自检 ...", file=sys.stderr)
    sample = (
        "1\n00:00:01,000 --> 00:00:03,500\nHello world\n\n"
        "2\n00:00:03,500 --> 00:00:06,000\nThis is a test\nsecond line\n\n"
        "3\n00:00:06,000 --> 00:00:08,000\nGoodbye\n"
    )
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        srt = d / "in.srt"
        srt.write_text(sample, encoding="utf-8")

        # 1) parse
        cues = parse_file(srt)
        assert len(cues) == 3, f"parse 应得 3 条，实得 {len(cues)}"
        assert abs(cues[1]["start"] - 3.5) < 1e-6, "时间戳解析错误"
        assert "\n" in cues[1]["text"], "多行文本未保留换行"

        # 2) extract
        lines = [c["text"].replace("\n", " ") for c in cues]
        assert len(lines) == 3 and lines[1] == "This is a test second line"

        # 3) merge → 双语 srt
        trans = d / "trans.txt"
        trans.write_text("你好世界\n这是一个测试\n再见\n", encoding="utf-8")
        bi_srt = d / "bi.srt"
        ns = argparse.Namespace(input=str(srt), trans=str(trans), output=str(bi_srt),
                                format=None, order="orig-top", font="Noto Sans CJK SC",
                                trans_only=False)
        cmd_merge(ns)
        body = bi_srt.read_text(encoding="utf-8")
        assert "Hello world" in body and "你好世界" in body, "双语 SRT 缺原文或译文"
        re_cues = parse_file(bi_srt)
        assert len(re_cues) == 3, "双语 SRT 回解析条数不对"

        # 4) merge → 双语 ass（两 Style）
        bi_ass = d / "bi.ass"
        ns2 = argparse.Namespace(input=str(srt), trans=str(trans), output=str(bi_ass),
                                 format="ass", order="orig-top", font="Noto Sans CJK SC",
                                 trans_only=False)
        cmd_merge(ns2)
        atext = bi_ass.read_text(encoding="utf-8")
        assert "Style: Orig" in atext and "Style: Trans" in atext, "双语 ASS 缺样式"
        assert atext.count("Dialogue:") == 6, "双语 ASS 应有 6 条 Dialogue（3×2）"

        # 5) convert srt → vtt
        vtt = d / "out.vtt"
        ns3 = argparse.Namespace(input=str(srt), output=str(vtt), format=None,
                                 font="Noto Sans CJK SC")
        cmd_convert(ns3)
        assert vtt.read_text(encoding="utf-8").startswith("WEBVTT"), "VTT 头缺失"

        # 6) 行数不一致应报错
        bad = d / "bad.txt"
        bad.write_text("只有一行\n", encoding="utf-8")
        import subprocess as _sp
        r = _sp.run([sys.executable, __file__, "merge", "-i", str(srt),
                     "--trans", str(bad), "-o", str(d / "x.srt")],
                    capture_output=True, text=True)
        assert r.returncode != 0, "行数不一致时应报错"

    print("✅ selftest 全部通过（parse/extract/merge-srt/merge-ass/convert/校验）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="字幕解析 / 双语合并 / 烧录（确定性；翻译由 LLM 完成）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("parse", help="解析 srt/vtt/ass → JSON")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", help="输出 JSON 路径（省略则打印 stdout）")
    p.set_defaults(func=cmd_parse)

    p = sub.add_parser("extract", help="按行提取待译文本（供 LLM 翻译）")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", help="输出 txt 路径（省略则打印 stdout）")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("merge", help="原文字幕 + 译文行 → 双语字幕")
    p.add_argument("-i", "--input", required=True, help="原文字幕 srt/vtt/ass")
    p.add_argument("--trans", required=True, help="译文行文件（行数=字幕条数）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--format", choices=["srt", "vtt", "ass"], help="默认按输出后缀")
    p.add_argument("--order", choices=["orig-top", "trans-top"], default="orig-top",
                   help="原文在上 / 译文在上（默认原文在上）")
    p.add_argument("--trans-only", action="store_true", help="只输出译文（不保留原文）")
    p.add_argument("--font", default="Noto Sans CJK SC", help="ASS 字体名")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("build", help="从 JSON（text+可选 trans）构建字幕")
    p.add_argument("--json", required=True, help="JSON 文件路径（- 表示 stdin）")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--format", choices=["srt", "vtt", "ass"], help="默认按输出后缀")
    p.add_argument("--order", choices=["orig-top", "trans-top"], default="orig-top")
    p.add_argument("--trans-only", action="store_true")
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("convert", help="字幕格式互转 srt/vtt/ass")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--format", choices=["srt", "vtt", "ass"], help="默认按输出后缀")
    p.add_argument("--font", default="Noto Sans CJK SC")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("burn", help="字幕烧录（硬）/挂载（软）进视频")
    p.add_argument("-i", "--input", required=True, help="视频文件")
    p.add_argument("--sub", required=True, help="字幕文件 srt/vtt/ass")
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--soft", action="store_true", help="软字幕（可开关），默认硬烧录")
    p.add_argument("--lang", default="chi", help="软字幕语言标记（默认 chi）")
    p.add_argument("--force-style", help="srt 硬烧录样式，如 Fontsize=24,PrimaryColour=&H00FFFFFF")
    p.add_argument("--font-dir", help="srt 硬烧录字体目录（含 CJK 字体时指定）")
    p.set_defaults(func=cmd_burn)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
