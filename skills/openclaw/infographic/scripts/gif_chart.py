#!/usr/bin/env python3
"""gif_chart.py — 动画 GIF 图表/信息图的确定性封装（matplotlib + Pillow + 标准库）。

infographic SKILL「动画 GIF 模式」的运行时脚本。把社媒爆款的几类动画图表固化为
确定性子命令，避免 LLM 现场手写动画代码导致不稳定。产物是可直接发社媒的 GIF。

依赖：matplotlib（Agg 后端）、Pillow、numpy（标准科学栈，已装）。

argparse 顶层 + 子命令，每个子命令都能 `-h`：
    bar-race    条形竞赛动画（多时间点的排名变化，数据可视化爆款形式）
    count-up    数字滚动增长动画（KPI 从 0 涨到目标值，ease-out）
    progress    进度动画（环形 ring / 条形 bar，0 → 目标百分比）
    line-grow   折线逐步生长动画（曲线沿 x 轴渐次画出）

通用参数：
    --output x.gif        输出路径（默认 outputs/ 下按子命令命名）
    --data f.json         数据 JSON（省略时各子命令有内置示例；'-' 读 stdin）
    --width 900           宽度像素（高度按子命令宽高比推导，或用 --height 覆盖）
    --fps 20              帧率
    --duration 4          总时长秒
    --title "..."         标题（覆盖数据里的 title）

自检：
    gif_chart.py --selftest      # 各子命令用内置示例生成小 GIF，断言存在且 >0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError:
    print("ERROR: 未安装 numpy。请运行：pip install numpy", file=sys.stderr)
    sys.exit(3)

try:
    import matplotlib
    matplotlib.use("Agg")  # 无显示环境，必须在 pyplot 前设置
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    from matplotlib.patches import Wedge
except ImportError:
    print("ERROR: 未安装 matplotlib。请运行：pip install matplotlib", file=sys.stderr)
    sys.exit(3)

try:
    from PIL import Image
except ImportError:
    print("ERROR: 未安装 Pillow。请运行：pip install Pillow", file=sys.stderr)
    sys.exit(3)


# ── 中文字体 ─────────────────────────────────────────────────────────────────

_CN_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def _setup_font() -> None:
    """注册系统中文字体到 matplotlib，避免中文乱码。找不到则告警降级。"""
    names: list[str] = []
    for fp in _CN_FONT_CANDIDATES:
        if Path(fp).is_file():
            try:
                font_manager.fontManager.addfont(fp)
                names.append(font_manager.FontProperties(fname=fp).get_name())
            except Exception:  # noqa: BLE001
                continue
    names.append("DejaVu Sans")  # 拉丁兜底
    plt.rcParams["font.sans-serif"] = names
    plt.rcParams["axes.unicode_minus"] = False
    if len(names) == 1:
        print("WARN: 未找到系统中文字体，中文可能显示为方块。", file=sys.stderr)


# 调色板（莫兰迪 + 高饱和混搭，社媒友好）
_PALETTE = [
    "#5B8FF9", "#61DDAA", "#F6BD16", "#F08BB4", "#7262FD",
    "#78D3F8", "#9661BC", "#F6903D", "#008685", "#F08BB4",
    "#5D7092", "#E86452", "#6DC8EC", "#945FB9", "#FF9845",
]


# ── 通用工具 ─────────────────────────────────────────────────────────────────

def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _load_data(spec: str | None, default: dict) -> dict:
    """读取数据 JSON：None→内置示例；'-'→stdin；否则文件路径。"""
    if spec is None:
        return default
    try:
        raw = sys.stdin.read() if spec == "-" else Path(spec).read_text("utf-8")
    except FileNotFoundError:
        _die(f"数据文件不存在: {spec}")
    except Exception as e:  # noqa: BLE001
        _die(f"读取数据失败: {e}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"数据不是合法 JSON: {e}")
    if not isinstance(data, dict):
        _die("数据 JSON 顶层必须是对象 {}")
    return data


def _figsize(width: int, height: int | None, ratio: float) -> tuple:
    """返回 (figsize, dpi)。dpi 固定 100，figsize 由像素推导。ratio = 宽/高。"""
    dpi = 100
    w = max(200, int(width))
    h = int(height) if height else int(round(w / ratio))
    return (w / dpi, h / dpi), dpi


def _fig_to_pil(fig) -> "Image.Image":
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    buf = fig.canvas.buffer_rgba()
    return Image.frombytes("RGBA", (w, h), bytes(buf)).convert("RGB")


def _save_gif(frames: list, output: str, fps: int, *, hold_last: int = 0) -> None:
    """把 PIL 帧列表存成 GIF：自适应调色板 + optimize 控体积，循环播放。"""
    if not frames:
        _die("没有生成任何帧")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    if hold_last > 0:
        frames = frames + [frames[-1]] * hold_last
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    duration_ms = max(20, int(round(1000 / max(1, fps))))
    pal[0].save(
        output, save_all=True, append_images=pal[1:],
        duration=duration_ms, loop=0, optimize=True, disposal=2,
    )
    kb = Path(output).stat().st_size / 1024
    w, h = frames[0].size
    print(f"✅ {output} ({w}x{h}, {len(pal)} 帧 @ {fps}fps, {kb:.0f} KB)")


def _ease_out(t: float) -> float:
    """缓出插值 [0,1]，动画收尾更自然。"""
    return 1 - (1 - t) ** 3


def _n_frames(fps: int, duration: float) -> int:
    return max(2, int(round(fps * max(0.2, duration))))


def _default_out(args, name: str) -> str:
    return args.output or f"outputs/{name}.gif"


# ── bar-race ─────────────────────────────────────────────────────────────────

_DEMO_BAR_RACE = {
    "title": "各城市用户数增长",
    "times": ["2021", "2022", "2023", "2024"],
    "series": {
        "北京": [120, 180, 240, 300], "上海": [100, 170, 260, 320],
        "深圳": [80, 160, 230, 340], "广州": [90, 130, 180, 250],
        "杭州": [60, 120, 200, 280], "成都": [50, 100, 170, 240],
    },
}


def cmd_bar_race(args) -> int:
    d = _load_data(args.data, _DEMO_BAR_RACE)
    title = args.title or d.get("title", "")
    times = d.get("times")
    series = d.get("series")
    if not times or not isinstance(series, dict) or not series:
        _die("bar-race 需要 {times:[...], series:{名称:[数值,...]}}")
    n_t = len(times)
    for name, vals in series.items():
        if not isinstance(vals, list) or len(vals) != n_t:
            _die(f"series['{name}'] 长度须等于 times 长度 {n_t}")
    names = list(series.keys())
    color_of = {nm: _PALETTE[i % len(_PALETTE)] for i, nm in enumerate(names)}
    top_n = min(args.top_n, len(names))

    total = _n_frames(args.fps, args.duration)
    n_trans = max(1, n_t - 1)
    (figsize, dpi) = _figsize(args.width, args.height, 16 / 9)

    frames = []
    for fi in range(total):
        g = fi / (total - 1) * n_trans  # [0, n_trans]
        seg = min(int(g), n_trans - 1)
        local = _ease_out(g - seg)
        cur = {nm: series[nm][seg] + (series[nm][seg + 1] - series[nm][seg]) * local
               for nm in names}
        label_idx = min(seg + (1 if local > 0.5 else 0), n_t - 1)

        ranked = sorted(names, key=lambda nm: cur[nm], reverse=True)[:top_n]
        ranked = ranked[::-1]  # 由下往上画，最大在顶
        vmax = max(cur.values()) or 1.0

        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_axes([0.02, 0.06, 0.96, 0.82])
        ypos = range(len(ranked))
        vals = [cur[nm] for nm in ranked]
        ax.barh(list(ypos), vals, color=[color_of[nm] for nm in ranked],
                height=0.78, edgecolor="none")
        for y, nm, v in zip(ypos, ranked, vals):
            ax.text(v + vmax * 0.01, y, f" {nm}  {v:,.0f}",
                    va="center", ha="left", fontsize=13, color="#333")
        ax.set_xlim(0, vmax * 1.18)
        ax.set_ylim(-0.6, len(ranked) - 0.4)
        ax.set_yticks([])
        ax.set_xticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        if title:
            fig.text(0.03, 0.94, title, fontsize=20, fontweight="bold", color="#222")
        fig.text(0.95, 0.90, str(times[label_idx]), fontsize=34,
                 fontweight="bold", color="#bbb", ha="right", va="top")
        frames.append(_fig_to_pil(fig))
        plt.close(fig)

    _save_gif(frames, _default_out(args, "bar-race"), args.fps,
              hold_last=int(args.fps * 0.8))
    return 0


# ── count-up ─────────────────────────────────────────────────────────────────

_DEMO_COUNT_UP = {
    "title": "核心数据",
    "items": [
        {"label": "累计用户", "value": 1280000, "suffix": ""},
        {"label": "日活跃", "value": 356000, "suffix": ""},
        {"label": "好评率", "value": 98, "suffix": "%"},
    ],
}


def cmd_count_up(args) -> int:
    d = _load_data(args.data, _DEMO_COUNT_UP)
    title = args.title or d.get("title", "")
    if "items" in d:
        items = d["items"]
    else:  # 单个数字的便捷形态
        items = [{"label": d.get("label", ""), "value": d.get("value", 0),
                  "prefix": d.get("prefix", ""), "suffix": d.get("suffix", "")}]
    if not isinstance(items, list) or not items:
        _die("count-up 需要 {items:[{label,value,suffix?}]} 或 {label,value}")
    for it in items:
        try:
            float(it.get("value"))
        except (TypeError, ValueError):
            _die(f"item 缺少数值 value: {it}")

    total = _n_frames(args.fps, args.duration)
    (figsize, dpi) = _figsize(args.width, args.height, 16 / 9)
    n = len(items)

    frames = []
    for fi in range(total):
        p = _ease_out(fi / (total - 1))
        fig = plt.figure(figsize=figsize, dpi=dpi)
        fig.patch.set_facecolor("#0f1420")
        if title:
            fig.text(0.5, 0.90, title, fontsize=22, color="#8a94a6",
                     ha="center", va="top")
        for i, it in enumerate(items):
            y = 0.66 - i * (0.66 / max(1, n)) if n > 1 else 0.52
            target = float(it["value"])
            cur = target * p
            digits = 0 if float(target).is_integer() else 1
            txt = f"{it.get('prefix','')}{cur:,.{digits}f}{it.get('suffix','')}"
            col = _PALETTE[i % len(_PALETTE)]
            fig.text(0.5, y, txt, fontsize=52, fontweight="bold", color=col,
                     ha="center", va="center")
            fig.text(0.5, y - 0.10, str(it.get("label", "")), fontsize=16,
                     color="#c8cfdb", ha="center", va="center")
        frames.append(_fig_to_pil(fig))
        plt.close(fig)

    _save_gif(frames, _default_out(args, "count-up"), args.fps,
              hold_last=int(args.fps * 1.0))
    return 0


# ── progress ─────────────────────────────────────────────────────────────────

_DEMO_PROGRESS = {"label": "项目完成度", "value": 76, "max": 100}


def cmd_progress(args) -> int:
    d = _load_data(args.data, _DEMO_PROGRESS)
    label = args.title or d.get("label", "")
    try:
        value = float(d.get("value", 0))
        vmax = float(d.get("max", 100))
    except (TypeError, ValueError):
        _die("progress 需要数值 value / max")
    if vmax <= 0:
        _die("max 必须 > 0")
    frac_target = max(0.0, min(1.0, value / vmax))
    color = d.get("color") or _PALETTE[0]

    total = _n_frames(args.fps, args.duration)
    ring = args.style == "ring"
    (figsize, dpi) = _figsize(args.width, args.height, 1.0 if ring else 16 / 5)

    frames = []
    for fi in range(total):
        p = _ease_out(fi / (total - 1))
        frac = frac_target * p
        fig = plt.figure(figsize=figsize, dpi=dpi)
        if ring:
            ax = fig.add_axes([0.05, 0.05, 0.9, 0.9])
            ax.set_xlim(-1.3, 1.3)
            ax.set_ylim(-1.3, 1.3)
            ax.set_aspect("equal")
            ax.axis("off")
            ax.add_patch(Wedge((0, 0), 1.0, 0, 360, width=0.28, facecolor="#e9edf2"))
            ang = 90 - 360 * frac
            ax.add_patch(Wedge((0, 0), 1.0, ang, 90, width=0.28, facecolor=color))
            ax.text(0, 0.08, f"{frac*100:.0f}%", fontsize=40, fontweight="bold",
                    color="#222", ha="center", va="center")
            if label:
                ax.text(0, -0.28, label, fontsize=15, color="#666",
                        ha="center", va="center")
        else:
            ax = fig.add_axes([0.06, 0.30, 0.88, 0.40])
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            ax.add_patch(plt.Rectangle((0, 0.25), 1, 0.5, facecolor="#e9edf2"))
            ax.add_patch(plt.Rectangle((0, 0.25), frac, 0.5, facecolor=color))
            if label:
                fig.text(0.06, 0.80, label, fontsize=18, color="#333", va="bottom")
            fig.text(0.94, 0.80, f"{frac*100:.0f}%", fontsize=22,
                     fontweight="bold", color=color, ha="right", va="bottom")
        frames.append(_fig_to_pil(fig))
        plt.close(fig)

    _save_gif(frames, _default_out(args, "progress"), args.fps,
              hold_last=int(args.fps * 1.0))
    return 0


# ── line-grow ────────────────────────────────────────────────────────────────

_DEMO_LINE_GROW = {
    "title": "月度增长趋势",
    "x": ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月"],
    "series": {
        "营收": [20, 35, 30, 50, 65, 60, 80, 95],
        "成本": [15, 20, 22, 28, 30, 35, 38, 42],
    },
}


def cmd_line_grow(args) -> int:
    d = _load_data(args.data, _DEMO_LINE_GROW)
    title = args.title or d.get("title", "")
    xs = d.get("x")
    series = d.get("series")
    if not xs or not isinstance(series, dict) or not series:
        _die("line-grow 需要 {x:[...], series:{名称:[数值,...]}}")
    npt = len(xs)
    for name, vals in series.items():
        if not isinstance(vals, list) or len(vals) != npt:
            _die(f"series['{name}'] 长度须等于 x 长度 {npt}")
    names = list(series.keys())
    xi = np.arange(npt)
    ymax = max(max(v) for v in series.values()) or 1.0
    ymin = min(min(v) for v in series.values())
    ymin = min(0, ymin)

    total = _n_frames(args.fps, args.duration)
    (figsize, dpi) = _figsize(args.width, args.height, 16 / 9)

    frames = []
    for fi in range(total):
        prog = (fi / (total - 1)) * (npt - 1)  # 已画到的 x 位置（浮点）
        k = int(prog)
        frac = prog - k
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_axes([0.09, 0.12, 0.86, 0.76])
        for i, nm in enumerate(names):
            ys = series[nm]
            col = _PALETTE[i % len(_PALETTE)]
            px = list(xi[: k + 1])
            py = list(ys[: k + 1])
            if k < npt - 1 and frac > 0:
                px.append(k + frac)
                py.append(ys[k] + (ys[k + 1] - ys[k]) * frac)
            ax.plot(px, py, color=col, linewidth=2.6, label=nm)
            if len(px) > 1:
                ax.scatter([px[-1]], [py[-1]], color=col, s=36, zorder=5)
        ax.set_xlim(-0.3, npt - 0.7)
        ax.set_ylim(ymin, ymax * 1.12)
        ax.set_xticks(list(xi))
        ax.set_xticklabels([str(x) for x in xs], fontsize=11)
        ax.tick_params(axis="y", labelsize=11)
        ax.grid(True, axis="y", linestyle="--", alpha=0.35)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        if len(names) > 1:
            ax.legend(loc="upper left", fontsize=12, frameon=False)
        if title:
            fig.text(0.09, 0.93, title, fontsize=19, fontweight="bold", color="#222")
        frames.append(_fig_to_pil(fig))
        plt.close(fig)

    _save_gif(frames, _default_out(args, "line-grow"), args.fps,
              hold_last=int(args.fps * 0.8))
    return 0


# ── selftest ─────────────────────────────────────────────────────────────────

def _selftest() -> int:
    import tempfile
    ok = True
    NS = argparse.Namespace
    with tempfile.TemporaryDirectory() as dd:
        d = Path(dd)

        def _run(name, fn, ns):
            nonlocal ok
            out = ns.output
            try:
                fn(ns)
                if Path(out).is_file() and Path(out).stat().st_size > 0:
                    with Image.open(out) as im:
                        is_gif = im.format == "GIF"
                    print(f"[PASS] {name} → {Path(out).name} "
                          f"({Path(out).stat().st_size/1024:.0f} KB, gif={is_gif})")
                    if not is_gif:
                        ok = False
                else:
                    print(f"[FAIL] {name}: 输出不存在或为空", file=sys.stderr)
                    ok = False
            except SystemExit as e:
                print(f"[FAIL] {name}: 退出码 {e.code}", file=sys.stderr)
                ok = False
            except Exception as e:  # noqa: BLE001
                print(f"[FAIL] {name}: {e}", file=sys.stderr)
                ok = False

        base = dict(data=None, title=None, width=480, height=None,
                    fps=10, duration=1.2)
        _run("bar-race", cmd_bar_race,
             NS(output=str(d / "bar-race.gif"), top_n=10, **base))
        _run("count-up", cmd_count_up,
             NS(output=str(d / "count-up.gif"), **base))
        _run("progress", cmd_progress,
             NS(output=str(d / "progress.gif"), style="ring", **base))
        _run("progress-bar", cmd_progress,
             NS(output=str(d / "progress-bar.gif"), style="bar", **base))
        _run("line-grow", cmd_line_grow,
             NS(output=str(d / "line-grow.gif"), **base))

    print("=" * 44)
    if ok:
        print("[PASS] gif_chart 全部子命令自检通过（真出 GIF）")
        return 0
    print("[FAIL] 存在失败的子命令", file=sys.stderr)
    return 1


# ── argparse 顶层 ────────────────────────────────────────────────────────────

def _common(p) -> None:
    p.add_argument("-o", "--output", help="输出 GIF 路径（默认 outputs/<子命令>.gif）")
    p.add_argument("--data", help="数据 JSON 路径（'-' 读 stdin；省略用内置示例）")
    p.add_argument("--title", help="标题（覆盖数据里的 title）")
    p.add_argument("--width", type=int, default=900, help="宽度像素（默认 900）")
    p.add_argument("--height", type=int, help="高度像素（默认按子命令宽高比推导）")
    p.add_argument("--fps", type=int, default=20, help="帧率（默认 20）")
    p.add_argument("--duration", type=float, default=4.0, help="总时长秒（默认 4）")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="动画 GIF 图表：bar-race / count-up / progress / line-grow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--selftest", action="store_true",
                    help="各子命令用内置示例生成小 GIF 并断言")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("bar-race", help="条形竞赛动画（排名随时间变化）")
    _common(p)
    p.add_argument("--top-n", type=int, default=10, help="每帧显示前 N 名（默认 10）")
    p.set_defaults(func=cmd_bar_race)

    p = sub.add_parser("count-up", help="数字滚动增长动画（KPI 0→目标）")
    _common(p)
    p.set_defaults(func=cmd_count_up)

    p = sub.add_parser("progress", help="进度动画（环形 ring / 条形 bar）")
    _common(p)
    p.add_argument("--style", choices=["ring", "bar"], default="ring",
                   help="进度样式（默认 ring 环形）")
    p.set_defaults(func=cmd_progress)

    p = sub.add_parser("line-grow", help="折线逐步生长动画")
    _common(p)
    p.set_defaults(func=cmd_line_grow)

    return ap


def main() -> int:
    _setup_font()
    ap = build_parser()
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
