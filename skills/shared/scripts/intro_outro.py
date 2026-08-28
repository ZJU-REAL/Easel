#!/usr/bin/env python3
"""intro_outro.py — 片头 / 片尾卡片生成 + 拼接到主视频的确定性封装。

"片头片尾"类 SKILL（video-intro-outro）共用此脚本。用 ffmpeg 生成带标题/副标题/
logo/关注引导的卡片片段，再把片头 + 主视频 + 片尾归一化后拼接（硬切或淡入淡出转场）。
避免手拼 drawtext/xfade 时算错时间偏移、音画参数不一致导致拼接失败。

依赖：ffmpeg + ffprobe。

子命令（每个都能 `-h`）：
    card    生成单张卡片片段（纯色/渐变/图片背景 + 标题/副标题/logo/CTA）
    attach  片头 + 主视频 + 片尾 → 成片（--transition none 硬切 / fade 淡入淡出）
    selftest 自检（造卡片 + 造主视频 → 拼接 → 校验）

用法举例：
    intro_outro.py card --title "本期主题" --subtitle "3 分钟讲清楚" -o intro.mp4 \
        --duration 2.5 --gradient --color 0x1a2a6c --color2 0xb21f1f
    intro_outro.py card --title "感谢观看" --cta "点赞 + 关注 不迷路" -o outro.mp4 --preset outro
    intro_outro.py attach --main talk.mp4 --intro intro.mp4 --outro outro.mp4 \
        -o final.mp4 --transition fade
    intro_outro.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# 中文字体候选（drawtext 需显式字体路径）
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_TRANSITIONS = ("none", "fade", "fadeblack", "fadewhite", "wipeleft", "slideup", "circleopen")


# ── 基础工具 ──────────────────────────────────────────────────────────
def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _check_ffmpeg() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if shutil.which(t) is None:
            _die(f"未找到 {t}，请先安装 ffmpeg（含 ffprobe）。", 3)


def _require_input(path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_file():
        _die(f"输入文件不存在: {p}", 2)
    return p


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-18:])
        _die(f"ffmpeg 执行失败（exit {proc.returncode}）:\n{tail}", proc.returncode or 1)


def _find_font(explicit: str | None = None) -> str:
    if explicit:
        if not Path(explicit).is_file():
            _die(f"指定字体文件不存在: {explicit}", 2)
        return explicit
    for f in _FONT_CANDIDATES:
        if Path(f).is_file():
            return f
    _die("未找到可用字体，请用 --font 指定 .ttf/.ttc 路径。", 2)
    return ""


def _esc(text: str) -> str:
    """drawtext text 转义。"""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%"))


def _probe_dur(path: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _probe_wh(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        w, h = (proc.stdout or "").strip().split("x")
        return int(w), int(h)
    except ValueError:
        _die(f"无法读取分辨率：{path}", 2)
        return 0, 0


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


# ── card：生成卡片片段 ────────────────────────────────────────────────
def _bg_source(a, w: int, h: int, dur: float) -> tuple[list[str], str]:
    """返回 (ffmpeg 输入参数, 背景视频滤镜标签前的处理)。产出统一命名 [bg]。"""
    if a.bg_image:
        img = _require_input(a.bg_image)
        inputs = ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(img)]
        vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
              f"crop={w}:{h},setsar=1,fps=30[bg]")
        return inputs, vf
    if a.gradient:
        # 静态双色渐变（speed=0 避免动画闪烁）
        c0 = a.color.replace("0x", "0x")
        c1 = a.color2.replace("0x", "0x")
        # speed 需 ≥1e-05；取极小值以近似静态渐变（2-3s 内位移不可见）
        src = (f"gradients=s={w}x{h}:c0={c0}:c1={c1}:x0=0:y0=0:x1={w}:y1={h}"
               f":d={dur:.3f}:speed=0.00001:type=linear")
        inputs = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", src]
        vf = f"[0:v]setsar=1,fps=30[bg]"
        return inputs, vf
    # 纯色
    src = f"color=c={a.color}:s={w}x{h}:d={dur:.3f}"
    inputs = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", src]
    vf = f"[0:v]setsar=1,fps=30[bg]"
    return inputs, vf


def cmd_card(a) -> int:
    _check_ffmpeg()
    try:
        w, h = (int(x) for x in a.size.lower().split("x"))
    except ValueError:
        _die(f"size 格式错误：{a.size}（应如 1080x1920）", 2)
    dur = max(0.5, float(a.duration))
    font = _find_font(a.font)
    out = _prep_out(a.output)

    inputs, bg_vf = _bg_source(a, w, h, dur)

    # 文本层：标题（大，居中偏上）/ 副标题（中，标题下）/ CTA（底部）
    fs_title = a.title_size or max(28, h // 14)
    fs_sub = max(20, h // 30)
    fs_cta = max(18, h // 32)
    chain = [bg_vf]
    cur = "[bg]"

    if a.logo:
        logo = _require_input(a.logo)
        inputs += ["-i", str(logo)]
        lw = a.logo_width or w // 5
        # logo 缩放后叠加在标题上方
        chain.append(f"[{1 + (1 if a.bg_image else 0)}:v]scale={lw}:-1[logo]")
        chain.append(f"{cur}[logo]overlay=(W-w)/2:{int(h*0.22)}[v_logo]")
        cur = "[v_logo]"

    n = 0
    if a.title:
        y = f"(h-text_h)/2-{int(h*0.05)}"
        chain.append(
            f"{cur}drawtext=fontfile='{font}':text='{_esc(a.title)}':"
            f"fontcolor={a.title_color}:fontsize={fs_title}:x=(w-text_w)/2:y={y}:"
            f"borderw=3:bordercolor=black@0.55:shadowx=2:shadowy=2[v{n}]")
        cur = f"[v{n}]"; n += 1
    if a.subtitle:
        y = f"(h-text_h)/2+{int(h*0.06)}"
        chain.append(
            f"{cur}drawtext=fontfile='{font}':text='{_esc(a.subtitle)}':"
            f"fontcolor={a.subtitle_color}:fontsize={fs_sub}:x=(w-text_w)/2:y={y}:"
            f"borderw=2:bordercolor=black@0.5[v{n}]")
        cur = f"[v{n}]"; n += 1
    if a.cta:
        y = f"h-text_h-{int(h*0.12)}"
        chain.append(
            f"{cur}drawtext=fontfile='{font}':text='{_esc(a.cta)}':"
            f"fontcolor={a.cta_color}:fontsize={fs_cta}:x=(w-text_w)/2:y={y}:"
            f"borderw=2:bordercolor=black@0.5[v{n}]")
        cur = f"[v{n}]"; n += 1

    # 淡入淡出
    fade = min(0.6, dur / 3)
    chain.append(f"{cur}fade=t=in:st=0:d={fade:.3f},"
                 f"fade=t=out:st={dur - fade:.3f}:d={fade:.3f}[vout]")

    filter_complex = ";".join(chain)
    # 静音音轨，方便下游拼接
    cmd = ["ffmpeg", "-y", *inputs,
           "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
           "-filter_complex", filter_complex, "-map", "[vout]", "-map", f"{_audio_idx(a)}:a",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
           "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out)]
    _run(cmd)
    _done(out, f"({dur:.1f}s {w}x{h} {a.preset}卡片)")
    return 0


def _audio_idx(a) -> int:
    """anullsrc 是最后一个输入，其序号 = 之前输入数。"""
    idx = 1  # 背景恒占 1 个输入
    if a.logo:
        idx += 1
    return idx


# ── attach：拼接片头/主/片尾 ──────────────────────────────────────────
def _normalize(src: Path, w: int, h: int, workdir: Path, tag: str) -> Path:
    """把片段归一化到 w×h / 30fps / yuv420p / aac stereo 44100，补静音轨（若无音频）。"""
    out = workdir / f"norm_{tag}.mp4"
    has_audio = _has_audio(src)
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30")
    if has_audio:
        _run(["ffmpeg", "-y", "-i", str(src), "-vf", vf,
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
              "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out)])
    else:
        _run(["ffmpeg", "-y", "-i", str(src),
              "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
              "-vf", vf, "-map", "0:v", "-map", "1:a",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
              "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out)])
    return out


def _has_audio(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return bool((proc.stdout or "").strip())


def _concat_hard(clips: list[Path], out: Path, workdir: Path) -> None:
    lst = workdir / "list.txt"
    lst.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])


def _concat_xfade(clips: list[Path], out: Path, td: float, transition: str) -> None:
    """用 xfade + acrossfade 链式转场拼接。clips 已归一化到相同参数。"""
    durs = [_probe_dur(c) for c in clips]
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    vchain, achain = [], []
    vcur, acur = "[0:v]", "[0:a]"
    offset = 0.0
    for i in range(1, len(clips)):
        offset += durs[i - 1] - td
        vlabel = f"[vx{i}]"
        alabel = f"[ax{i}]"
        vchain.append(
            f"{vcur}[{i}:v]xfade=transition={transition}:duration={td:.3f}:"
            f"offset={offset:.3f}{vlabel}")
        achain.append(f"{acur}[{i}:a]acrossfade=d={td:.3f}{alabel}")
        vcur, acur = vlabel, alabel
    fc = ";".join(vchain + achain)
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", fc,
          "-map", vcur, "-map", acur,
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])


def cmd_attach(a) -> int:
    _check_ffmpeg()
    main = _require_input(a.main)
    if not a.intro and not a.outro:
        _die("至少要给 --intro 或 --outro 之一。", 2)
    if a.size:
        try:
            w, h = (int(x) for x in a.size.lower().split("x"))
        except ValueError:
            _die(f"size 格式错误：{a.size}", 2)
    else:
        w, h = _probe_wh(main)  # 默认对齐主视频画幅
    out = _prep_out(a.output)

    with tempfile.TemporaryDirectory() as td_:
        workdir = Path(td_)
        order: list[Path] = []
        if a.intro:
            order.append(_normalize(_require_input(a.intro), w, h, workdir, "intro"))
        order.append(_normalize(main, w, h, workdir, "main"))
        if a.outro:
            order.append(_normalize(_require_input(a.outro), w, h, workdir, "outro"))

        if a.transition == "none":
            _concat_hard(order, out, workdir)
            extra = "(硬切拼接)"
        else:
            td = max(0.2, float(a.trans_duration))
            # 转场时长不能超过任一相邻片段
            min_dur = min(_probe_dur(c) for c in order)
            if td >= min_dur:
                td = max(0.2, min_dur / 2)
            _concat_xfade(order, out, td, a.transition)
            extra = f"({a.transition} 转场 {td:.1f}s)"
    _done(out, f"{w}x{h} {extra}")
    return 0


# ── selftest ──────────────────────────────────────────────────────────
def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("intro_outro 自检 ...", file=sys.stderr)
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 片头卡片（渐变 + 标题 + 副标题）
        intro = d / "intro.mp4"
        ns_i = argparse.Namespace(
            title="测试片头", subtitle="Sub Title", cta=None, logo=None, logo_width=None,
            size="640x360", duration=1.5, gradient=True, bg_image=None,
            color="0x1a2a6c", color2="0xb21f1f", font=None, preset="intro",
            title_size=None, title_color="white", subtitle_color="0xFFD700",
            cta_color="white", output=str(intro))
        cmd_card(ns_i)
        assert intro.is_file() and intro.stat().st_size > 0, "片头卡片未生成"
        assert _has_audio(intro), "片头缺静音轨"

        # 片尾卡片（纯色 + CTA）
        outro = d / "outro.mp4"
        ns_o = argparse.Namespace(
            title="感谢观看", subtitle=None, cta="点赞关注不迷路", logo=None, logo_width=None,
            size="640x360", duration=1.5, gradient=False, bg_image=None,
            color="black", color2="0xb21f1f", font=None, preset="outro",
            title_size=None, title_color="white", subtitle_color="0xFFD700",
            cta_color="0xFFD700", output=str(outro))
        cmd_card(ns_o)
        assert outro.is_file(), "片尾卡片未生成"

        # 主视频
        main = d / "main.mp4"
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=640x360:d=2",
              "-f", "lavfi", "-i", "sine=frequency=440:d=2",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-shortest", str(main)])

        # 硬切拼接
        f1 = d / "hard.mp4"
        cmd_attach(argparse.Namespace(main=str(main), intro=str(intro), outro=str(outro),
                                      size=None, transition="none", trans_duration=0.5,
                                      output=str(f1)))
        d1 = _probe_dur(f1)
        assert d1 > 4.5, f"硬切成片时长异常：{d1:.2f}s（应≈5s）"

        # 淡入淡出转场拼接
        f2 = d / "fade.mp4"
        cmd_attach(argparse.Namespace(main=str(main), intro=str(intro), outro=str(outro),
                                      size="640x360", transition="fade", trans_duration=0.5,
                                      output=str(f2)))
        d2 = _probe_dur(f2)
        assert 3.5 < d2 < 5.0, f"转场成片时长异常：{d2:.2f}s（应≈4s，两次 0.5s 交叠）"

    print("✅ selftest 全部通过（card 渐变/纯色 + attach 硬切/转场）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="片头/片尾卡片生成 + 拼接（确定性 ffmpeg 封装）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("card", help="生成单张卡片片段")
    p.add_argument("--title", help="主标题")
    p.add_argument("--subtitle", help="副标题")
    p.add_argument("--cta", help="行动引导文案（如 点赞关注），常用于片尾")
    p.add_argument("--logo", help="logo 图片路径（叠加在标题上方）")
    p.add_argument("--logo-width", type=int, help="logo 宽度像素（默认画幅 1/5）")
    p.add_argument("--size", default="1080x1920", help="画幅 WxH（默认 1080x1920 竖版）")
    p.add_argument("--duration", type=float, default=2.5, help="时长秒（默认 2.5）")
    p.add_argument("--gradient", action="store_true", help="双色渐变背景（用 --color/--color2）")
    p.add_argument("--bg-image", help="用图片作背景（覆盖颜色/渐变）")
    p.add_argument("--color", default="0x1a1a2e", help="背景色 / 渐变起色（默认深蓝）")
    p.add_argument("--color2", default="0x16213e", help="渐变终色")
    p.add_argument("--title-size", type=int, help="标题字号（默认按画幅高度自适应）")
    p.add_argument("--title-color", default="white")
    p.add_argument("--subtitle-color", default="0xFFD700")
    p.add_argument("--cta-color", default="0xFFD700")
    p.add_argument("--font", help="字体文件路径（默认自动探测 CJK 字体）")
    p.add_argument("--preset", default="intro", choices=["intro", "outro"],
                   help="仅用于日志标注")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_card)

    p = sub.add_parser("attach", help="片头+主视频+片尾拼接")
    p.add_argument("--main", required=True, help="主视频")
    p.add_argument("--intro", help="片头片段")
    p.add_argument("--outro", help="片尾片段")
    p.add_argument("--size", help="强制画幅 WxH（默认对齐主视频）")
    p.add_argument("--transition", default="none", choices=list(_TRANSITIONS),
                   help="none 硬切（默认）/ fade 等 xfade 转场")
    p.add_argument("--trans-duration", type=float, default=0.5, help="转场时长秒（默认 0.5）")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_attach)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
