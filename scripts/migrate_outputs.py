#!/usr/bin/env python3
"""migrate_outputs.py — 把存量 outputs/ 收敛到统一目录规约（安全、可预览）.

背景：早期各 SKILL / agent 各写各的，outputs/ 下产物目录结构不一、缺元数据、
中间件与成品混放。本脚本把每个项目目录**增量回填** `.easel.json` 展示头
（供前端「内容库」富展示），可选把公认中间件挪进 `assets/`。

目录规约（详见 docs/SKILL-SPEC.md / manifest.py）：
  outputs/<主题>/
    .easel.json   唯一元数据（展示头 + 编排 steps，隐藏）
    <成品>           用户要发/读的最终文件放项目根
    assets/          中间件：frames/clips/构建脚本/原始素材/草稿/重复文件

安全原则：
  - 默认 --dry-run：只打印计划、不改动。
  - --apply：只**增量回填** .easel.json 展示头（纯新增字段，不覆盖已有值、不动文件）。
  - --apply --reorganize：额外把公认中间件 mv 进 assets/（保守清单，逐条打印）。
  - **本脚本绝不 rm 任何文件**（删测试残渣走 scripts/cleanup_outputs.sh，由用户手动跑）。

用法：
  python scripts/migrate_outputs.py                 # dry-run 预览全部项目
  python scripts/migrate_outputs.py --topic 房东清单 # 只看一个
  python scripts/migrate_outputs.py --apply          # 回填展示头
  python scripts/migrate_outputs.py --apply --reorganize  # 并归整中间件
  python scripts/migrate_outputs.py selftest
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[1])
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
MANIFEST_NAME = ".easel.json"
CST = timezone(timedelta(hours=8))
# 非 _ 前缀的历史系统目录（归因层数据），不是内容项目 → 迁移跳过（与 web/app.py 对齐）
SYSTEM_TOPLEVEL_DIRS = {"analytics"}

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DOC_EXTS = {".md", ".pdf", ".html", ".htm", ".txt"}
DELIVERABLE_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | {".md", ".pdf", ".html", ".htm"}

# 归整（--reorganize）时挪进 assets/ 的公认中间件
INTERMEDIATE_DIRS = {"frames", "clips", "tmp", "temp", "draft", "drafts", "raw", "reference", "_work"}
INTERMEDIATE_EXTS = {".py", ".js", ".ipynb", ".sh"}   # 构建/导出脚本
# 永不移动、永不当成品的文件
PROTECTED_NAMES = {MANIFEST_NAME, "meta.json", "README.md", "readme.md", "brief.md"}


def _now_iso() -> str:
    return datetime.now(CST).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# 推断
# --------------------------------------------------------------------------- #
def _root_files(proj: Path) -> list[Path]:
    """项目根直属文件（不含子目录、不含隐藏/受保护元数据）。"""
    return [f for f in sorted(proj.iterdir())
            if f.is_file() and not f.name.startswith(".") and f.name not in PROTECTED_NAMES]


def _load_meta_json(proj: Path) -> dict:
    mj = proj / "meta.json"
    if mj.is_file():
        try:
            return json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def infer_kind(proj: Path, platform: str = "") -> str:
    """按项目根/子目录文件推断产物体裁。"""
    all_files = [f for f in proj.rglob("*") if f.is_file()]
    exts = {f.suffix.lower() for f in all_files}
    names = [f.name.lower() for f in all_files]
    if exts & VIDEO_EXTS:
        return "video"
    if any(n.startswith("card") or n.startswith("card_") for n in names) or \
       any(f.suffix.lower() == ".html" and "card" in f.name.lower() for f in all_files):
        return "cards"
    if any("poster" in n for n in names):
        return "poster"
    if (exts & IMAGE_EXTS) and not (exts & {".md"}):
        return "cards"          # 纯图产物按卡片归类
    if exts & AUDIO_EXTS:
        return "audio"
    if exts & {".md", ".txt", ".pdf", ".html"}:
        return "xhs-note" if "小红书" in platform else "article"
    return "other"


def infer_deliverables(proj: Path) -> list[str]:
    """项目根直属的成品文件名（去掉同名 png 时的重复 jpg）。"""
    files = _root_files(proj)
    stems_png = {f.stem for f in files if f.suffix.lower() == ".png"}
    out = []
    for f in files:
        if f.suffix.lower() not in DELIVERABLE_EXTS:
            continue
        if f.suffix.lower() in (".jpg", ".jpeg") and f.stem in stems_png:
            continue            # 有同名 png → jpg 视作重复中间件
        out.append(f.name)
    return out


def _first_media(proj: Path, prefer: list[str]) -> str:
    """封面兜底：优先 deliverables 里的媒体，其次全目录首张图/视频（返回相对项目根路径）。"""
    for name in prefer:
        if Path(name).suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS):
            return name
    for f in sorted(proj.rglob("*")):
        if f.is_file() and f.suffix.lower() in (IMAGE_EXTS | VIDEO_EXTS):
            return str(f.relative_to(proj))
    return ""


def build_header(proj: Path, existing: dict) -> dict:
    """构造要回填的展示头（只填缺失字段，不覆盖已有值）。返回本次实际新增的字段。"""
    mj = _load_meta_json(proj)
    header: dict = {}

    def fill(key, value):
        if key not in existing and value not in (None, "", []):
            header[key] = value

    platform = existing.get("platform") or mj.get("platform") or ""
    fill("title", mj.get("title") or proj.name)
    fill("summary", mj.get("summary") or "")
    fill("platform", platform)
    fill("tags", mj.get("tags") or [])
    fill("kind", infer_kind(proj, platform or mj.get("platform", "")))
    fill("status", "draft")
    deliverables = infer_deliverables(proj)
    fill("deliverables", deliverables)
    cover = mj.get("cover_image") or _first_media(proj, deliverables)
    fill("cover", cover)
    return header


def plan_reorg(proj: Path) -> list[tuple[Path, Path]]:
    """归整计划：(源, 目标) 对，把公认中间件挪进 assets/。已在 assets/ 内的跳过。"""
    assets = proj / "assets"
    moves: list[tuple[Path, Path]] = []
    stems_png = {f.stem for f in proj.iterdir() if f.is_file() and f.suffix.lower() == ".png"}
    for c in sorted(proj.iterdir()):
        if c.name in ("assets",) or c.name.startswith("."):
            continue
        if c.is_dir() and c.name in INTERMEDIATE_DIRS:
            moves.append((c, assets / c.name))
        elif c.is_file() and c.name not in PROTECTED_NAMES:
            is_script = c.suffix.lower() in INTERMEDIATE_EXTS
            is_dup_jpg = c.suffix.lower() in (".jpg", ".jpeg") and c.stem in stems_png
            if is_script or is_dup_jpg:
                moves.append((c, assets / c.name))
    return moves


# --------------------------------------------------------------------------- #
# 执行
# --------------------------------------------------------------------------- #
def process_project(proj: Path, apply: bool, reorganize: bool) -> dict:
    mpath = proj / MANIFEST_NAME
    existing = {}
    if mpath.is_file():
        try:
            existing = json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    header = build_header(proj, existing)
    reorg = plan_reorg(proj) if reorganize else []

    if apply:
        if header:
            data = existing or {
                "topic": proj.name, "profile": "",
                "created": _now_iso(), "steps": [],
            }
            data.update(header)
            data["updated"] = _now_iso()
            tmp = mpath.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, mpath)
        for src, dst in reorg:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    return {"project": proj.name, "backfill": header,
            "reorg": [(str(s.relative_to(proj)), str(d.relative_to(proj))) for s, d in reorg]}


def iter_projects(topic: str | None):
    if not OUTPUTS_DIR.is_dir():
        return
    for e in sorted(OUTPUTS_DIR.iterdir()):
        if e.name.startswith("_") or e.name.startswith("."):
            continue
        if not e.is_dir():
            continue          # 根目录散文件交给 cleanup_outputs.sh
        if e.name in SYSTEM_TOPLEVEL_DIRS:
            continue          # 归因层系统目录，非内容项目
        if topic and e.name != topic:
            continue
        yield e


def cmd_run(args) -> None:
    apply = args.apply
    results = [process_project(p, apply, args.reorganize) for p in iter_projects(args.topic)]
    mode = "APPLY" + ("+REORG" if args.reorganize else "") if apply else "DRY-RUN"
    print(f"=== migrate_outputs [{mode}] · {len(results)} 个项目 ===\n")
    touched = 0
    for r in results:
        if not r["backfill"] and not r["reorg"]:
            continue
        touched += 1
        print(f"● {r['project']}")
        if r["backfill"]:
            print(f"    回填展示头: {json.dumps(r['backfill'], ensure_ascii=False)}")
        for s, d in r["reorg"]:
            print(f"    归整: {s}  →  {d}")
        print()
    if touched == 0:
        print("（无需改动：所有项目展示头已齐全）")
    elif not apply:
        print(f"以上为计划。加 --apply 执行回填" +
              ("（--reorganize 已列归整计划）" if args.reorganize else "，加 --reorganize 一并归整中间件") + "。")


# --------------------------------------------------------------------------- #
# selftest
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "测试项目"
        (proj).mkdir()
        (proj / "note.md").write_text("正文", encoding="utf-8")
        (proj / "cover.png").write_bytes(b"\x89PNG")
        (proj / "card_1.png").write_bytes(b"\x89PNG")
        (proj / "card_1.jpg").write_bytes(b"jpg")       # 重复 jpg
        (proj / "export_cards.py").write_text("build", encoding="utf-8")
        (proj / "frames").mkdir()
        (proj / "frames" / "f001.png").write_bytes(b"\x89PNG")
        (proj / "meta.json").write_text(json.dumps(
            {"title": "真标题", "platform": "小红书", "tags": ["A", "B"]}, ensure_ascii=False),
            encoding="utf-8")

        # 推断
        header = build_header(proj, {})
        assert header["title"] == "真标题", "应取 meta.json 标题"
        assert header["platform"] == "小红书"
        assert header["kind"] == "cards", f"有 card_*.png 应判 cards，实为 {header['kind']}"
        assert header["tags"] == ["A", "B"]
        assert "card_1.jpg" not in header["deliverables"], "同名 png 存在时 jpg 应排除出成品"
        assert "note.md" in header["deliverables"] and "card_1.png" in header["deliverables"]
        assert "export_cards.py" not in header["deliverables"], "脚本不算成品"
        assert header["cover"] in ("cover.png", "card_1.png"), "封面应是根媒体"

        # 已有字段不覆盖
        header2 = build_header(proj, {"title": "用户改过的", "kind": "video"})
        assert "title" not in header2 and "kind" not in header2, "已有字段不应回填"

        # reorg 计划
        moves = {s.name for s, _ in plan_reorg(proj)}
        assert "frames" in moves and "export_cards.py" in moves and "card_1.jpg" in moves
        assert "note.md" not in moves and "cover.png" not in moves and "card_1.png" not in moves
        assert "meta.json" not in moves, "meta.json 受保护不移动"

        # apply：回填 + 归整
        process_project(proj, apply=True, reorganize=True)
        data = json.loads((proj / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert data["title"] == "真标题" and data["kind"] == "cards"
        assert (proj / "assets" / "frames" / "f001.png").is_file(), "frames 应移入 assets/"
        assert (proj / "assets" / "export_cards.py").is_file()
        assert (proj / "assets" / "card_1.jpg").is_file()
        assert (proj / "note.md").is_file() and (proj / "card_1.png").is_file()

        # 幂等：二次 apply 无新回填
        r2 = process_project(proj, apply=True, reorganize=True)
        assert not r2["backfill"], "二次 apply 展示头应已齐全、无新增"

    print("migrate_outputs.py selftest: OK")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="把存量 outputs/ 收敛到统一目录规约")
    p.add_argument("cmd", nargs="?", default="run",
                   help="run（默认，扫描/回填）| selftest")
    p.add_argument("--topic", help="只处理某个项目目录")
    p.add_argument("--apply", action="store_true", help="真正回填 .easel.json 展示头（否则 dry-run）")
    p.add_argument("--reorganize", action="store_true", help="额外把中间件挪进 assets/（与 --apply 连用）")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "selftest":
        sys.exit(_selftest())
    cmd_run(args)


if __name__ == "__main__":
    main()
