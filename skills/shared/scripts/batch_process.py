#!/usr/bin/env python3
"""batch_process.py — 批量处理目录（图片/视频/音频）。

对一个目录里的一批文件，统一套用同一个处理操作（压缩/加水印/转格式/缩放/转比例/归一化…），
逐个委派给对应的确定性脚本 image_ops.py / video_ops.py / audio_ops.py 执行，输出到指定目录。

与单文件处理的区别：image-editing/video-editing/audio-editing 处理单个文件，本 SKILL 批量套用。

依赖：ffmpeg（视频/音频）；Pillow（图片）——即 ops 脚本各自的依赖。

子命令：
    run        批量执行某个操作（op 及其参数透传给对应 ops 脚本）
    list       预览将处理哪些文件（dry-run）
    selftest   自检

用法举例：
    # 批量压缩图片到 500KB
    batch_process.py run --dir imgs --type image --op compress --out-dir out -- --max-kb 500
    # 批量给图片加水印
    batch_process.py run --dir imgs --type image --op watermark --out-dir out -- --text @我的账号 --position bottom-right
    # 批量视频转竖版
    batch_process.py run --dir clips --type video --op aspect --out-dir out -- --ratio 9:16 --mode pad
    # 批量音频转 mp3
    batch_process.py run --dir raw --type audio --op convert --out-dir out --ext .mp3 -- --bitrate 192k
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_SELF = Path(__file__).resolve().parent
_TYPES = {
    "image": {"script": _SELF / "image_ops.py", "in_flag": "-i",
              "ext": {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".gif"}},
    "video": {"script": _SELF / "video_ops.py", "in_flag": "-i",
              "ext": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".m4v"}},
    "audio": {"script": _SELF / "audio_ops.py", "in_flag": None,  # audio_ops 用位置参数
              "ext": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}},
}


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _collect(a) -> list[Path]:
    d = Path(a.dir).expanduser()
    if not d.is_dir():
        _die(f"目录不存在：{d}")
    exts = _TYPES[a.type]["ext"]
    it = d.rglob("*") if a.recursive else d.iterdir()
    files = sorted(p for p in it if p.is_file() and p.suffix.lower() in exts)
    if not files:
        _die(f"目录中无 {a.type} 文件：{d}")
    return files


def _out_path(f: Path, out_dir: Path, ext: str | None) -> Path:
    name = f.stem + (ext if ext else f.suffix)
    return out_dir / name


def cmd_list(a) -> int:
    files = _collect(a)
    print(f"将处理 {len(files)} 个 {a.type} 文件（{a.dir}）：")
    for f in files:
        print(f"  {f.name}")
    return 0


def cmd_run(a) -> int:
    files = _collect(a)
    cfg = _TYPES[a.type]
    script = cfg["script"]
    if not script.is_file():
        _die(f"缺少 ops 脚本：{script}")
    out_dir = Path(a.out_dir).expanduser() if a.out_dir else Path(a.dir).expanduser() / "batch_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    op_args = a.op_args or []

    ok, failed = 0, []
    for i, f in enumerate(files, 1):
        out = _out_path(f, out_dir, a.ext)
        in_part = [cfg["in_flag"], str(f)] if cfg["in_flag"] else [str(f)]
        cmd = [sys.executable, str(script), a.op, *in_part, "-o", str(out), *op_args]
        print(f"  [{i}/{len(files)}] {a.op} {f.name} → {out.name}", file=sys.stderr)
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0 and out.is_file():
            ok += 1
        else:
            tail = (r.stderr or "").strip().splitlines()[-2:]
            failed.append((f.name, " ".join(tail)))
            print(f"     ⚠️ 失败：{' '.join(tail)}", file=sys.stderr)
    print(f"\n✅ 批量完成：成功 {ok}/{len(files)} → {out_dir}")
    if failed:
        print(f"❌ 失败 {len(failed)}：" + ", ".join(n for n, _ in failed))
        return 1
    return 0


def cmd_selftest(_a) -> int:
    print("batch_process 自检 ...", file=sys.stderr)
    import tempfile
    from PIL import Image
    with tempfile.TemporaryDirectory() as td_:
        d = Path(td_)
        # 图片批处理：造 3 张图 → 批量缩放
        img_dir = d / "imgs"; img_dir.mkdir()
        for i in range(3):
            Image.new("RGB", (800, 600), (i * 60, 100, 200)).save(img_dir / f"p{i}.jpg")
        out = d / "img_out"
        rc = cmd_run(argparse.Namespace(dir=str(img_dir), type="image", op="resize",
                                        out_dir=str(out), ext=None, recursive=False,
                                        op_args=["--width", "400"]))
        outs = sorted(out.glob("*.jpg"))
        assert rc == 0 and len(outs) == 3, f"图片批处理应出 3 张，实得 {len(outs)}"
        assert Image.open(outs[0]).size[0] == 400, "缩放未生效"

        # 音频批处理（位置参数路径）：造 2 个 wav → 批量转 mp3
        import shutil
        if shutil.which("ffmpeg"):
            aud_dir = d / "aud"; aud_dir.mkdir()
            for i in range(2):
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i",
                                f"sine=frequency={300+i*100}:d=1", str(aud_dir / f"a{i}.wav")],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            aout = d / "aud_out"
            rc2 = cmd_run(argparse.Namespace(dir=str(aud_dir), type="audio", op="convert",
                                             out_dir=str(aout), ext=".mp3", recursive=False,
                                             op_args=["--bitrate", "128k"]))
            mp3s = sorted(aout.glob("*.mp3"))
            assert rc2 == 0 and len(mp3s) == 2, f"音频批转应出 2 个 mp3，实得 {len(mp3s)}"
        else:
            print("  (无 ffmpeg，跳过音频批处理)", file=sys.stderr)

        # list 预览
        cmd_list(argparse.Namespace(dir=str(img_dir), type="image", recursive=False))
    print("✅ selftest 通过（图片批缩放 + 音频批转格式[位置参数] + list 预览）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="批量处理目录（图片/视频/音频，委派 *_ops.py）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="op 及其参数写在 `--` 之后，原样透传给对应 ops 脚本。")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("run", help="批量执行操作")
    p.add_argument("--dir", required=True, help="输入目录")
    p.add_argument("--type", required=True, choices=list(_TYPES))
    p.add_argument("--op", required=True, help="ops 脚本的子命令（如 resize/compress/aspect/convert）")
    p.add_argument("--out-dir", help="输出目录（默认 <dir>/batch_out）")
    p.add_argument("--ext", help="输出扩展名（如 .mp3/.png；默认沿用原扩展）")
    p.add_argument("--recursive", action="store_true", help="递归子目录")
    p.add_argument("op_args", nargs=argparse.REMAINDER,
                   help="`--` 之后透传给 ops 脚本的参数")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="预览将处理的文件")
    p.add_argument("--dir", required=True)
    p.add_argument("--type", required=True, choices=list(_TYPES))
    p.add_argument("--recursive", action="store_true")
    p.set_defaults(func=cmd_list)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    # 去掉 REMAINDER 里前导的 "--"
    if getattr(a, "op_args", None) and a.op_args and a.op_args[0] == "--":
        a.op_args = a.op_args[1:]
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
