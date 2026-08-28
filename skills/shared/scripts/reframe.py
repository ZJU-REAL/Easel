#!/usr/bin/env python3
"""reframe.py — 视频画幅智能转换（竖横互转）的确定性封装。

"竖版横版互转"类 SKILL（video-reframe）共用此脚本。把视频转到目标宽高比，三种策略：
    blur   模糊背景填充（原画完整居中 + 放大模糊的自身作背景，无黑边，最常用）
    crop   焦点裁切（按焦点位置裁到目标比例，无黑边但会裁掉边缘）
    smart  人脸感知裁切（cv2 检测人脸 → 以人脸中位位置为焦点裁切，无脸退化为居中）

与 video_ops.py aspect 的区别：aspect 只做黑边 pad 或居中 crop；本脚本提供模糊背景填充
与人脸感知裁切。与 clipify 的区别：clipify 是逐段动态人脸 pan 的特化流程；本脚本做整段
静态焦点裁切（更稳、更快），需要逐镜头动态追踪时用 clipify。

依赖：ffmpeg + ffprobe；smart 模式需 opencv-python（无则自动退化为居中裁切）。

子命令：
    reframe   转换画幅（--ratio 必填；--mode blur/crop/smart）
    selftest  自检

用法举例：
    reframe.py reframe -i in.mp4 -o out.mp4 --ratio 9:16 --mode blur
    reframe.py reframe -i in.mp4 -o out.mp4 --ratio 9:16 --mode crop --focus-x 0.6
    reframe.py reframe -i in.mp4 -o out.mp4 --ratio 9:16 --mode smart
    reframe.py selftest
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_RATIOS = {"9:16", "16:9", "1:1", "4:5", "3:4", "4:3", "21:9"}


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


def _probe_wh(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        w, h = (proc.stdout or "").strip().split("x")[:2]
        return int(w), int(h)
    except ValueError:
        _die(f"无法读取分辨率：{path}", 2)
        return 0, 0


def _has_audio(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return bool((proc.stdout or "").strip())


def _done(out: Path, extra: str = "") -> None:
    kb = out.stat().st_size / 1024 if out.is_file() else 0
    print(f"✅ {out} ({kb:.0f} KB){(' ' + extra) if extra else ''}")


def _even(n: float) -> int:
    return int(round(n / 2)) * 2


def _out_size(ratio: str, sw: int, sh: int, size: str | None) -> tuple[int, int]:
    if size:
        try:
            w, h = (int(x) for x in size.lower().split("x"))
            return _even(w), _even(h)
        except ValueError:
            _die(f"size 格式错误：{size}", 2)
    rw, rh = (int(x) for x in ratio.split(":"))
    long = max(sw, sh)
    if rw < rh:  # 竖版目标
        oh, ow = long, long * rw / rh
    else:        # 横版/方形目标
        ow, oh = long, long * rh / rw
    return _even(ow), _even(oh)


# ── 人脸焦点（cv2） ───────────────────────────────────────────────────
def _face_focus_x(path: Path, samples: int = 24) -> float | None:
    """采样若干帧检测人脸，返回人脸中心 x 的中位比例（0-1）；无脸/无 cv2 返回 None。"""
    try:
        import cv2  # noqa
    except Exception:
        print("  (未装 opencv-python，smart 退化为居中)", file=sys.stderr)
        return None
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs: list[float] = []
    idxs = ([int(total * i / samples) for i in range(samples)] if total > 0
            else list(range(samples)))
    for fi in idxs:
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
        h, w = gray.shape[:2]
        if len(faces):
            # 取最大脸
            x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
            xs.append((x + fw / 2) / w)
    cap.release()
    if not xs:
        return None
    xs.sort()
    return xs[len(xs) // 2]


# ── 滤镜构建 ──────────────────────────────────────────────────────────
def _vf_blur(ow: int, oh: int, sigma: int) -> str:
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={ow}:{oh}:force_original_aspect_ratio=increase,"
        f"crop={ow}:{oh},gblur=sigma={sigma}[bgb];"
        f"[fg]scale={ow}:{oh}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def _vf_crop(ow: int, oh: int, sw: int, sh: int, fx: float, fy: float) -> str:
    """先按目标比例裁切源，再缩放到 ow×oh。焦点 fx/fy 为 0-1 比例。"""
    target_ar = ow / oh
    src_ar = sw / sh
    if src_ar > target_ar:  # 源更宽 → 裁宽
        cw, ch = sh * target_ar, sh
    else:                   # 源更高 → 裁高
        cw, ch = sw, sw / target_ar
    cw, ch = _even(cw), _even(ch)
    # 焦点 → 裁切左上角，限制在边界内
    x_expr = f"min(max(0\\,{fx}*iw-{cw}/2)\\,iw-{cw})"
    y_expr = f"min(max(0\\,{fy}*ih-{ch}/2)\\,ih-{ch})"
    return f"crop={cw}:{ch}:{x_expr}:{y_expr},scale={ow}:{oh},setsar=1"


def cmd_reframe(a) -> int:
    _check_ffmpeg()
    src = _require_input(a.input)
    if a.ratio not in _RATIOS:
        _die(f"--ratio 需为 {sorted(_RATIOS)} 之一，收到 {a.ratio}", 2)
    sw, sh = _probe_wh(src)
    ow, oh = _out_size(a.ratio, sw, sh, a.size)
    out = _prep_out(a.output)

    if a.mode == "blur":
        vf = _vf_blur(ow, oh, a.blur_sigma)
        info = "模糊背景填充"
    else:
        fx, fy = a.focus_x, a.focus_y
        if a.mode == "smart":
            found = _face_focus_x(src)
            fx = found if found is not None else 0.5
            info = f"人脸焦点裁切(fx={fx:.2f})" if found is not None else "居中裁切(未检出人脸)"
        else:
            info = f"焦点裁切(fx={fx:.2f})"
        vf = _vf_crop(ow, oh, sw, sh, fx, fy)

    cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium"]
    cmd += (["-c:a", "copy"] if _has_audio(src) else ["-an"])
    cmd += [str(out)]
    _run(cmd)
    _done(out, f"({sw}x{sh}→{ow}x{oh} {a.ratio} · {info})")
    return 0


def cmd_selftest(_a) -> int:
    _check_ffmpeg()
    print("reframe 自检 ...", file=sys.stderr)
    import tempfile
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        src = d / "src.mp4"
        # 16:9 横版测试源（带音轨）
        _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=1280x720:d=2",
              "-f", "lavfi", "-i", "sine=frequency=440:d=2",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
              "-shortest", str(src)])

        for mode in ("blur", "crop", "smart"):
            out = d / f"{mode}.mp4"
            ns = argparse.Namespace(input=str(src), output=str(out), ratio="9:16",
                                    mode=mode, size=None, focus_x=0.5, focus_y=0.5,
                                    blur_sigma=25)
            cmd_reframe(ns)
            w, h = _probe_wh(out)
            assert (w, h) == (720, 1280), f"{mode} 输出尺寸应 720x1280，实得 {w}x{h}"
            assert _has_audio(out), f"{mode} 丢失音轨"

        # 显式 size + 焦点偏右
        out = d / "sized.mp4"
        ns = argparse.Namespace(input=str(src), output=str(out), ratio="1:1",
                                mode="crop", size="480x480", focus_x=0.7, focus_y=0.5,
                                blur_sigma=25)
        cmd_reframe(ns)
        assert _probe_wh(out) == (480, 480), "显式 size 未生效"

    print("✅ selftest 全部通过（blur / crop / smart / 显式 size）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="视频画幅智能转换（竖横互转：模糊填充 / 焦点裁切 / 人脸感知）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("reframe", help="转换画幅")
    p.add_argument("-i", "--input", required=True)
    p.add_argument("-o", "--output", required=True)
    p.add_argument("--ratio", required=True, help="目标比例 9:16/16:9/1:1/4:5/3:4/4:3/21:9")
    p.add_argument("--mode", default="blur", choices=["blur", "crop", "smart"],
                   help="blur 模糊背景填充(默认) / crop 焦点裁切 / smart 人脸感知裁切")
    p.add_argument("--size", help="强制输出 WxH（默认按 ratio 与源分辨率推算）")
    p.add_argument("--focus-x", type=float, default=0.5, help="crop 焦点横向比例 0-1（默认 0.5）")
    p.add_argument("--focus-y", type=float, default=0.5, help="crop 焦点纵向比例 0-1（默认 0.5）")
    p.add_argument("--blur-sigma", type=int, default=25, help="blur 背景模糊强度（默认 25）")
    p.set_defaults(func=cmd_reframe)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
