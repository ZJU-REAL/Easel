#!/usr/bin/env python3
"""Easel 素材管理 — outputs/ 产物的确定性索引 / 检索 / 归档 / 标签。

把有副作用、需状态一致的文件操作从 LLM 手动 find/grep/mv/改 JSON 固化为代码。

子命令:
  scan      扫描 outputs/ 生成或更新索引（路径/日期/平台/类型/大小/标签）
  search    按 日期范围 / 平台 / 类型 / 关键词 / 标签 检索
  archive   按 日期/平台/类型 归档产物（默认 dry-run，--apply 才移动；幂等）
  tag       给产物打 / 删标签，维护 tags.json
  list      输出素材清单
  report    输出统计报告（按类型 / 平台 / 日期分布）

状态文件（均在 outputs/ 根，原子写入：临时文件 + os.replace）:
  INDEX.json   文件索引
  tags.json    路径 -> 标签列表

设计约束:
  - 删除 / 移动类操作默认 dry-run，仅打印将影响的文件；加 --apply 才真正执行
  - 移动幂等：目标已存在（且内容一致）则跳过；source==target 跳过
  - 缺目录 / 文件时友好处理不崩
纯 stdlib，python3.11。
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta

# ---- 平台 / 类型识别规则 ----------------------------------------------------
PLATFORMS = ["xiaohongshu", "weibo", "douyin", "zhihu", "wechat", "x"]
PLATFORM_ALIASES = {
    "小红书": "xiaohongshu", "xhs": "xiaohongshu",
    "微博": "weibo", "wb": "weibo",
    "抖音": "douyin", "dy": "douyin",
    "知乎": "zhihu",
    "公众号": "wechat", "weixin": "wechat", "微信": "wechat",
    "twitter": "x", "推特": "x",
}
EXT_TYPE = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "image", ".svg": "image",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio",
    ".md": "text", ".txt": "text", ".json": "text", ".csv": "text",
    ".html": "text", ".pdf": "text",
}
# 文件名 / 路径关键词细化类型
TYPE_HINTS = [
    ("card", "card"), ("卡片", "card"),
    ("poster", "poster"), ("海报", "poster"),
    ("script", "script"), ("脚本", "script"),
    ("note", "note"), ("笔记", "note"),
]
DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


def eprint(*a):
    print(*a, file=sys.stderr)


def atomic_write_json(path, data):
    """临时文件 + os.replace 原子写入。"""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        eprint(f"[warn] 读取 {path} 失败（{e}），使用空默认值")
        return default


def detect_platform(relpath):
    low = relpath.lower()
    # CJK 别名用子串匹配（无分隔符）
    for alias, canon in PLATFORM_ALIASES.items():
        if not re.search(r"[a-z]", alias) and alias in relpath:
            return canon
    # 拉丁平台名 / 别名按 token 精确匹配（避免 "x" 命中 "xhs" 等子串误判）
    tokens = set(re.split(r"[^a-z0-9]+", low))
    for alias, canon in PLATFORM_ALIASES.items():
        if re.search(r"[a-z]", alias) and alias.lower() in tokens:
            return canon
    for p in PLATFORMS:
        if p in tokens:
            return p
    # 长名（>=4 字符）再退回子串匹配
    for p in PLATFORMS:
        if len(p) >= 4 and p in low:
            return p
    return "unknown"


def detect_type(relpath):
    low = relpath.lower()
    for hint, t in TYPE_HINTS:
        if hint in low:
            return t
    ext = os.path.splitext(relpath)[1].lower()
    return EXT_TYPE.get(ext, "other")


def detect_date(relpath, mtime):
    m = DATE_RE.search(os.path.basename(relpath)) or DATE_RE.search(relpath)
    if m:
        y, mo, d = m.groups()
        try:
            datetime(int(y), int(mo), int(d))
            return f"{y}-{mo}-{d}"
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def index_path(root):
    return os.path.join(root, "INDEX.json")


def tags_path(root):
    return os.path.join(root, "tags.json")


# 索引 / 归档时忽略的状态文件与隐藏项
IGNORE_NAMES = {"INDEX.json", "tags.json", ".gitkeep"}


def iter_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过隐藏目录（如 .drafts 仍保留？此处保留 .drafts 但跳过 .git 之类）
        dirnames[:] = [d for d in dirnames if not d.startswith(".git")]
        for fn in filenames:
            if fn in IGNORE_NAMES:
                continue
            yield os.path.join(dirpath, fn)


def build_entry(root, full, tags_map):
    rel = os.path.relpath(full, root)
    try:
        st = os.stat(full)
    except OSError:
        return None
    return {
        "path": rel,
        "topic": rel.split(os.sep)[0] if os.sep in rel else "",
        "date": detect_date(rel, st.st_mtime),
        "platform": detect_platform(rel),
        "type": detect_type(rel),
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "tags": sorted(tags_map.get(rel, [])),
    }


# ---- scan -------------------------------------------------------------------
def cmd_scan(args):
    root = args.root
    if not os.path.isdir(root):
        eprint(f"[error] 目录不存在: {root}")
        return 1
    tags_map = load_json(tags_path(root), {})
    entries = []
    for full in iter_files(root):
        e = build_entry(root, full, tags_map)
        if e:
            entries.append(e)
    entries.sort(key=lambda x: (x["date"], x["path"]), reverse=True)
    idx = {
        "version": 1,
        "updated": datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "count": len(entries),
        "files": entries,
    }
    atomic_write_json(index_path(root), idx)
    total = sum(e["size"] for e in entries)
    print(f"已索引 {len(entries)} 个文件，共 {total / 1024 / 1024:.2f} MB -> {index_path(root)}")
    return 0


def load_index(root, auto=True):
    idx = load_json(index_path(root), None)
    if idx is None:
        if auto:
            eprint("[info] 索引不存在，自动执行 scan …")
            tags_map = load_json(tags_path(root), {})
            entries = [e for e in (build_entry(root, f, tags_map)
                                   for f in iter_files(root)) if e]
            return {"files": entries}
        return {"files": []}
    return idx


# ---- search / list ----------------------------------------------------------
def _date_bounds(spec):
    """把 today/this-week/this-month/YYYY-MM/YYYY-MM-DD 转成 (lo, hi) 闭区间字符串。"""
    today = datetime.now().date()
    if spec == "today":
        s = today.isoformat()
        return s, s
    if spec == "this-week":
        lo = today - timedelta(days=today.weekday())
        return lo.isoformat(), today.isoformat()
    if spec == "this-month":
        return today.replace(day=1).isoformat(), today.isoformat()
    if re.fullmatch(r"20\d{2}-\d{2}", spec):
        return spec + "-01", spec + "-31"
    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", spec):
        return spec, spec
    return None, None


def filter_entries(entries, args):
    out = entries
    if getattr(args, "platform", None):
        out = [e for e in out if e["platform"] == args.platform]
    if getattr(args, "type", None):
        out = [e for e in out if e["type"] == args.type]
    if getattr(args, "date", None):
        lo, hi = _date_bounds(args.date)
        if lo:
            out = [e for e in out if lo <= e["date"] <= hi]
    if getattr(args, "since", None):
        out = [e for e in out if e["date"] >= args.since]
    if getattr(args, "until", None):
        out = [e for e in out if e["date"] <= args.until]
    if getattr(args, "tag", None):
        want = [t.strip() for t in args.tag.split(",") if t.strip()]
        out = [e for e in out if all(t in e["tags"] for t in want)]
    if getattr(args, "query", None):
        q = args.query.lower()
        scored = []
        for e in out:
            score = 0
            if q in os.path.basename(e["path"]).lower():
                score += 3
            elif q in e["path"].lower():
                score += 2
            if any(q in t.lower() for t in e["tags"]):
                score += 1
            # 文本文件内容匹配
            if e["type"] in ("text", "script", "note"):
                full = os.path.join(args.root, e["path"])
                try:
                    with open(full, encoding="utf-8", errors="ignore") as f:
                        if q in f.read().lower():
                            score += 2
                except OSError:
                    pass
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1]["path"]))
        return [e for _, e in scored]
    return out


def _print_table(entries):
    if not entries:
        print("（无匹配项）")
        return
    print(f"{'日期':<11} {'平台':<12} {'类型':<7} {'大小':>8}  路径")
    for e in entries:
        kb = f"{e['size'] / 1024:.0f}K"
        tags = " ".join("#" + t for t in e["tags"])
        line = f"{e['date']:<11} {e['platform']:<12} {e['type']:<7} {kb:>8}  {e['path']}"
        if tags:
            line += f"  {tags}"
        print(line)


def cmd_search(args):
    idx = load_index(args.root)
    res = filter_entries(idx["files"], args)
    print(f"找到 {len(res)} 个匹配项：")
    _print_table(res)
    return 0


def cmd_list(args):
    idx = load_index(args.root)
    res = filter_entries(idx["files"], args)
    total = sum(e["size"] for e in res)
    print(f"素材清单（{args.root}）：{len(res)} 个文件，{total / 1024 / 1024:.2f} MB")
    _print_table(res)
    return 0


# ---- report -----------------------------------------------------------------
def cmd_report(args):
    idx = load_index(args.root)
    entries = idx["files"]
    if not entries:
        print("（无素材）")
        return 0

    def group(key):
        d = {}
        for e in entries:
            d.setdefault(e[key], []).append(e)
        return d

    total = len(entries)
    print(f"# 素材统计（{args.root}）— 共 {total} 个文件\n")
    print("## 按类型")
    for t, es in sorted(group("type").items(), key=lambda x: -len(x[1])):
        print(f"  {t:<8} {len(es):>4}  ({len(es) * 100 // total}%)")
    print("\n## 按平台")
    for p, es in sorted(group("platform").items(), key=lambda x: -len(x[1])):
        latest = max(e["date"] for e in es)
        print(f"  {p:<12} {len(es):>4}  最近 {latest}")
    print("\n## 按日期（近 14 天有产出的）")
    bydate = group("date")
    for d in sorted(bydate, reverse=True)[:14]:
        print(f"  {d}  {len(bydate[d]):>3}")
    return 0


# ---- tag --------------------------------------------------------------------
def cmd_tag(args):
    root = args.root
    tp = tags_path(root)
    tags_map = load_json(tp, {})
    rel = os.path.relpath(args.path, root) if os.path.isabs(args.path) else args.path
    full = os.path.join(root, rel)
    if not os.path.exists(full):
        eprint(f"[error] 文件不存在: {full}")
        return 1
    cur = set(tags_map.get(rel, []))
    add = [t.strip() for t in (args.add or "").split(",") if t.strip()]
    rm = [t.strip() for t in (args.remove or "").split(",") if t.strip()]
    cur |= set(add)
    cur -= set(rm)
    if cur:
        tags_map[rel] = sorted(cur)
    else:
        tags_map.pop(rel, None)
    atomic_write_json(tp, tags_map)
    print(f"{rel} 标签: {' '.join('#' + t for t in sorted(cur)) or '（无）'}")
    # 同步进索引（若存在）
    idx = load_json(index_path(root), None)
    if idx:
        for e in idx["files"]:
            if e["path"] == rel:
                e["tags"] = sorted(cur)
        atomic_write_json(index_path(root), idx)
    return 0


# ---- archive ----------------------------------------------------------------
def _same_file(a, b):
    try:
        if os.path.samefile(a, b):
            return True
    except OSError:
        pass
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def cmd_archive(args):
    root = args.root
    if not os.path.isdir(root):
        eprint(f"[error] 目录不存在: {root}")
        return 1
    tags_map = load_json(tags_path(root), {})
    # 收集待归档文件
    if args.path:
        src_full = args.path if os.path.isabs(args.path) else os.path.join(root, args.path)
        if not os.path.exists(src_full):
            eprint(f"[error] 路径不存在: {src_full}")
            return 1
        if os.path.isdir(src_full):
            candidates = list(iter_files(src_full))
        else:
            candidates = [src_full]
    else:
        candidates = list(iter_files(root))

    plans = []  # (src, dst, status)
    for src in candidates:
        rel = os.path.relpath(src, root)
        # 已经在 日期/平台/类型 结构里的跳过（首段是日期）
        first = rel.split(os.sep)[0]
        if DATE_RE.fullmatch(first.replace("-", "")):
            continue
        e = build_entry(root, src, tags_map)
        if not e:
            continue
        dst = os.path.join(root, e["date"], e["platform"], e["type"], os.path.basename(src))
        if os.path.abspath(src) == os.path.abspath(dst):
            plans.append((src, dst, "skip-same-path"))
        elif os.path.exists(dst):
            if _same_file(src, dst):
                plans.append((src, dst, "skip-exists-identical"))
            else:
                plans.append((src, dst, "conflict-exists-differ"))
        else:
            plans.append((src, dst, "move"))

    moves = [p for p in plans if p[2] == "move"]
    conflicts = [p for p in plans if p[2] == "conflict-exists-differ"]
    skips = [p for p in plans if p[2].startswith("skip")]

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 归档计划：{len(moves)} 移动，{len(conflicts)} 冲突，{len(skips)} 跳过")
    for src, dst, _ in moves:
        print(f"  MOVE  {os.path.relpath(src, root)}  ->  {os.path.relpath(dst, root)}")
    for src, dst, _ in conflicts:
        print(f"  CONFLICT  {os.path.relpath(src, root)}  目标已存在且内容不同，跳过")

    if not args.apply:
        if moves:
            print("\n以上为预览。确认后加 --apply 执行。")
        return 0

    done = 0
    for src, dst, _ in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # 同步标签映射的 key
        old_rel = os.path.relpath(src, root)
        new_rel = os.path.relpath(dst, root)
        os.replace(src, dst)
        if old_rel in tags_map:
            tags_map[new_rel] = tags_map.pop(old_rel)
        done += 1
    if moves:
        atomic_write_json(tags_path(root), tags_map)
    print(f"已移动 {done} 个文件。重新扫描索引 …")
    cmd_scan(argparse.Namespace(root=root))
    return 0


# ---- CLI --------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="assets.py",
        description="Easel 素材管理：scan/search/archive/tag/list/report。",
    )
    p.add_argument("--root", default="outputs", help="产物根目录（默认 outputs）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan", help="扫描并生成 / 更新索引")

    def add_filters(sp):
        sp.add_argument("--platform", choices=PLATFORMS, help="按平台筛选")
        sp.add_argument("--type", help="按类型筛选 image/video/text/card/poster/script/note")
        sp.add_argument("--date", help="日期：today/this-week/this-month/YYYY-MM/YYYY-MM-DD")
        sp.add_argument("--since", help="起始日期 YYYY-MM-DD（含）")
        sp.add_argument("--until", help="结束日期 YYYY-MM-DD（含）")
        sp.add_argument("--tag", help="按标签筛选，逗号分隔（需全部命中）")

    sp = sub.add_parser("search", help="按条件检索")
    sp.add_argument("query", nargs="?", help="关键词（文件名 / 内容 / 标签）")
    add_filters(sp)

    sp = sub.add_parser("list", help="输出素材清单")
    add_filters(sp)

    sub.add_parser("report", help="输出统计报告")

    sp = sub.add_parser("tag", help="给产物打 / 删标签")
    sp.add_argument("path", help="目标文件（相对 root 或绝对路径）")
    sp.add_argument("--add", help="要添加的标签，逗号分隔")
    sp.add_argument("--remove", help="要删除的标签，逗号分隔")

    sp = sub.add_parser("archive", help="按 日期/平台/类型 归档（默认 dry-run）")
    sp.add_argument("path", nargs="?", help="指定文件 / 目录，缺省归档整个 root")
    sp.add_argument("--apply", action="store_true", help="真正执行移动（缺省仅预览）")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    dispatch = {
        "scan": cmd_scan, "search": cmd_search, "list": cmd_list,
        "report": cmd_report, "tag": cmd_tag, "archive": cmd_archive,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
