#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel_ops.py — 网文连载的确定性状态管理（纯标准库）。

小说连载的**创意**（世界观/大纲/正文）交给 LLM；本脚本只负责**确定性 IO**：
搭书籍目录骨架、维护连载进度、机械扫 AI 味/重复措辞。核心思想是「文件即真相 +
按需加载」——AI 不靠上下文记忆，每写一章只加载相关切片，状态落文件、可 diff。

子命令：
    scaffold   为一本书搭出 bible/outline/state/chapters 目录 + 模板文件（不覆盖已存在）
    record     登记/更新某章进度（写 state/progress.json，重生成 state/progress.md 表）
    show       打印连载进度表
    slopcheck  机械扫描一段正文的 AI 味词 / 过度连接词 / 重复措辞（advisory）
    selftest   自检

用法举例：
    novel_ops.py scaffold --book "我的书名"
    novel_ops.py scaffold --book "我的书名" --root outputs
    novel_ops.py record --book "我的书名" --chapter 1 --title "重生" --words 4200 --status done
    novel_ops.py show --book "我的书名"
    novel_ops.py slopcheck -f outputs/我的书名/chapters/001.md
    echo "文本" | novel_ops.py slopcheck
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_ROOT = "outputs"

# ── 目录树模板（scaffold 时按需 seed，已存在不覆盖，保护未提交/已写内容）──
_TEMPLATES: dict[str, str] = {
    "bible/world.md": "# 世界观设定（硬事实）\n\n> 时代/地域/力量体系/规则。这里写的都是全书不可违背的硬约束。\n",
    "bible/characters.md": "# 人物档案\n\n> 每个角色：身份 / 外貌 / 性格 / 目标 / 与他人关系。跨章一致的依据。\n\n## 主角\n\n",
    "bible/voice.md": "# 文风指纹 + 禁用清单\n\n## 文风指纹\n\n> 视角(第一/第三)、时态、句式节奏、用词偏好、叙事腔调。\n\n## 禁用词/AI 痕迹清单\n\n> 本书要避免的口头禅、陈词、句式（slopcheck 会机械扫这些）。\n",
    "bible/canon.md": "# Canon（跨章硬事实库）\n\n> 已发生的关键事件、时间线、伏笔状态（埋下/回收）。写新章前必读，写完 sync 时更新。\n\n## 时间线\n\n## 伏笔登记\n\n| 伏笔 | 埋于章 | 状态 | 计划回收 |\n|---|---|---|---|\n",
    "outline/overview.md": "# 全书梗概\n\n> 一句话卖点 + 核心冲突 + 主线走向 + 结局方向。\n",
    "outline/volumes.md": "# 分卷 Arc\n\n> 每卷：目标/转折/卷末高潮。\n\n## 第一卷\n",
    "outline/chapters.md": "# 章节目录\n\n| 章 | 标题 | 一句话钩子 | 涉及伏笔 |\n|---|---|---|---|\n",
    "state/summary.md": "# 滚动前情提要\n\n> 由 text-condenser 压缩已发生剧情生成，写下一章时加载它而非全文。\n",
    "state/character-state.md": "# 角色当前状态\n\n> 各角色此刻的位置/处境/关系/持有物，随剧情推进更新。\n",
    "state/plot-arcs.md": "# 情节线追踪\n\n> 各条明线/暗线的当前进度。\n",
}

_PROGRESS_JSON = "state/progress.json"
_PROGRESS_MD = "state/progress.md"

# ── slopcheck 词表（网文语境的 AI 味信号，advisory）──
_SLOP_MARKERS = [
    "值得注意的是", "总而言之", "综上所述", "不难看出", "众所周知",
    "在这个", "在这样一个", "首先", "其次", "最后", "此外", "然而，",
    "无疑", "无疑是", "可以说", "某种程度上", "在某种意义上",
    "空气仿佛凝固", "嘴角勾起一抹", "眼中闪过一丝", "心中五味杂陈",
    "不由得", "缓缓地", "深吸一口气", "微微一笑",
]
_OVERUSED_CONNECTORS = ["于是", "然后", "接着", "随后", "紧接着"]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _book_dir(root: str, book: str) -> Path:
    return (Path(root).expanduser() / book).resolve()


# ── scaffold ──────────────────────────────────────────────────────────
def scaffold(root: str, book: str) -> dict:
    """搭书籍目录骨架，seed 模板文件（已存在不覆盖）。返回统计。"""
    if not book.strip():
        _die("--book 书名不能为空")
    base = _book_dir(root, book)
    created, skipped = [], []
    for sub in ("bible", "outline", "state", "chapters"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    for rel, content in _TEMPLATES.items():
        p = base / rel
        if p.exists():
            skipped.append(rel)
        else:
            p.write_text(content, encoding="utf-8")
            created.append(rel)
    # 初始化空 progress
    pj = base / _PROGRESS_JSON
    if not pj.exists():
        pj.write_text(json.dumps({"book": book, "chapters": []},
                                 ensure_ascii=False, indent=2), encoding="utf-8")
        _render_progress_md(base, {"book": book, "chapters": []})
        created.append(_PROGRESS_JSON)
    return {"base": str(base), "created": created, "skipped": skipped}


# ── progress ──────────────────────────────────────────────────────────
def _load_progress(base: Path) -> dict:
    pj = base / _PROGRESS_JSON
    if not pj.exists():
        return {"book": base.name, "chapters": []}
    return json.loads(pj.read_text(encoding="utf-8"))


def _render_progress_md(base: Path, data: dict) -> None:
    rows = ["# 连载进度", "",
            "| 章 | 标题 | 字数 | 状态 | 更新 |",
            "|---|---|---|---|---|"]
    total = 0
    for c in sorted(data.get("chapters", []), key=lambda x: x["chapter"]):
        total += int(c.get("words", 0) or 0)
        rows.append(f"| {c['chapter']} | {c.get('title','')} | "
                    f"{c.get('words',0)} | {c.get('status','')} | {c.get('updated','')} |")
    done = sum(1 for c in data.get("chapters", []) if c.get("status") == "done")
    rows += ["", f"**合计**：{len(data.get('chapters', []))} 章 / "
             f"已定稿 {done} 章 / 累计 {total} 字"]
    (base / _PROGRESS_MD).write_text("\n".join(rows) + "\n", encoding="utf-8")


def record(root: str, book: str, chapter: int, title: str | None,
           words: int | None, status: str, when: str | None) -> dict:
    """登记/更新一章进度（幂等 upsert，按 chapter 号）。"""
    base = _book_dir(root, book)
    if not base.exists():
        _die(f"书籍目录不存在，请先 scaffold：{base}")
    data = _load_progress(base)
    chs = data.setdefault("chapters", [])
    hit = next((c for c in chs if c["chapter"] == chapter), None)
    if hit is None:
        hit = {"chapter": chapter}
        chs.append(hit)
    if title is not None:
        hit["title"] = title
    if words is not None:
        hit["words"] = words
    hit["status"] = status
    hit["updated"] = when or ""  # 时间戳由调用方传入（脚本内不取 Date，保持确定性）
    (base / _PROGRESS_JSON).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _render_progress_md(base, data)
    return {"chapter": chapter, "status": status, "total_chapters": len(chs)}


def show(root: str, book: str) -> str:
    base = _book_dir(root, book)
    md = base / _PROGRESS_MD
    if md.exists():
        return md.read_text(encoding="utf-8")
    data = _load_progress(base)
    return json.dumps(data, ensure_ascii=False, indent=2)


# ── slopcheck ─────────────────────────────────────────────────────────
def slopcheck(text: str) -> dict:
    """机械扫 AI 味词 / 过度连接词 / 重复句首。返回命中清单（advisory）。"""
    hits: list[dict] = []
    for w in _SLOP_MARKERS:
        n = text.count(w)
        if n:
            hits.append({"type": "ai-marker", "term": w, "count": n})
    for w in _OVERUSED_CONNECTORS:
        n = text.count(w)
        if n >= 3:  # 连接词高频才算问题
            hits.append({"type": "overused", "term": w, "count": n})
    # 重复句首（同一开头连续/多次出现）
    starts: dict[str, int] = {}
    for line in text.splitlines():
        s = line.strip()[:4]
        if len(s) >= 2:
            starts[s] = starts.get(s, 0) + 1
    for s, n in starts.items():
        if n >= 4:
            hits.append({"type": "repeated-start", "term": s, "count": n})
    hits.sort(key=lambda h: -h["count"])
    return {"total_hits": sum(h["count"] for h in hits),
            "distinct": len(hits), "hits": hits}


def _read_input(path: str | None) -> str:
    if path and path != "-":
        return Path(path).expanduser().read_text(encoding="utf-8")
    data = sys.stdin.read()
    if not data:
        _die("没有输入。用 -f 指定文件，或 stdin 传入。")
    return data


# ── selftest ──────────────────────────────────────────────────────────
def _selftest() -> int:
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        r = scaffold(td, "测试书")
        base = Path(r["base"])
        chk("scaffold 建目录", (base / "bible/world.md").is_file()
            and (base / "chapters").is_dir())
        chk("scaffold 建 progress", (base / _PROGRESS_JSON).is_file())
        # 二次 scaffold 不覆盖
        (base / "bible/world.md").write_text("我的内容", encoding="utf-8")
        scaffold(td, "测试书")
        chk("scaffold 不覆盖已有", (base / "bible/world.md").read_text(
            encoding="utf-8") == "我的内容")
        # record upsert
        record(td, "测试书", 1, "第一章", 4200, "done", "2026-08-04")
        record(td, "测试书", 2, "第二章", 3800, "draft", "2026-08-04")
        record(td, "测试书", 1, None, 4500, "done", "2026-08-05")  # 更新第1章
        data = _load_progress(base)
        c1 = next(c for c in data["chapters"] if c["chapter"] == 1)
        chk("record upsert 幂等", len(data["chapters"]) == 2 and c1["words"] == 4500)
        chk("progress.md 生成", "累计" in (base / _PROGRESS_MD).read_text(
            encoding="utf-8"))

    s = slopcheck("值得注意的是，他缓缓地深吸一口气。于是他走了。于是又停下。于是再走。")
    terms = {h["term"] for h in s["hits"]}
    chk("slopcheck 抓 ai-marker", "值得注意的是" in terms and "缓缓地" in terms)
    chk("slopcheck 抓过度连接词", "于是" in terms)
    chk("slopcheck 干净文本无命中", slopcheck("他推开门，风灌了进来。")["distinct"] == 0)

    print("✅ selftest 通过" if ok else "❌ selftest 失败")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="网文连载确定性状态管理（scaffold/record/show/slopcheck）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scaffold", help="搭书籍目录骨架")
    ps.add_argument("--book", required=True)
    ps.add_argument("--root", default=DEFAULT_ROOT)

    pr = sub.add_parser("record", help="登记/更新章节进度")
    pr.add_argument("--book", required=True)
    pr.add_argument("--root", default=DEFAULT_ROOT)
    pr.add_argument("--chapter", type=int, required=True)
    pr.add_argument("--title")
    pr.add_argument("--words", type=int)
    pr.add_argument("--status", default="draft",
                    choices=["draft", "done", "revised", "planned"])
    pr.add_argument("--when", help="更新时间戳（调用方传入，如 2026-08-04）")

    psh = sub.add_parser("show", help="打印进度表")
    psh.add_argument("--book", required=True)
    psh.add_argument("--root", default=DEFAULT_ROOT)

    pc = sub.add_parser("slopcheck", help="机械扫 AI 味/重复（advisory）")
    pc.add_argument("-f", "--file", help="正文文件（默认 stdin）")
    pc.add_argument("--json", action="store_true")

    sub.add_parser("selftest", help="自检")

    a = ap.parse_args()
    if a.cmd == "selftest":
        return _selftest()
    if a.cmd == "scaffold":
        r = scaffold(a.root, a.book)
        print(f"✅ {r['base']}")
        print(f"   新建 {len(r['created'])} 个文件，跳过已存在 {len(r['skipped'])} 个")
        return 0
    if a.cmd == "record":
        r = record(a.root, a.book, a.chapter, a.title, a.words, a.status, a.when)
        print(f"✅ 第 {r['chapter']} 章 [{r['status']}]，共 {r['total_chapters']} 章")
        return 0
    if a.cmd == "show":
        print(show(a.root, a.book))
        return 0
    if a.cmd == "slopcheck":
        r = slopcheck(_read_input(a.file))
        if a.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            if not r["hits"]:
                print("✅ 未命中 AI 味词/重复（advisory 通过）")
            else:
                print(f"⚠️ 命中 {r['distinct']} 类 / 共 {r['total_hits']} 处：")
                for h in r["hits"]:
                    print(f"  [{h['type']}] {h['term']} ×{h['count']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
