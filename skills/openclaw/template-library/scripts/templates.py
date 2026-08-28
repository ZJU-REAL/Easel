#!/usr/bin/env python3
"""Easel 模板库 — 内容模板的确定性 CRUD + 变量提取 / 替换。

把模板文件读写、INDEX.json 维护、usage_count 自增、{{var}} 提取替换
从 LLM 手动操作固化为代码。LLM 只做意图路由与内容分析。

子命令:
  save    保存模板（--file / --text 提供内容，含 {{var}} 占位符）
  list    列出模板（可按 --category 筛选）
  get     打印模板内容与元信息
  edit    修改模板内容 / 分类 / 描述（重新提取变量）
  delete  删除模板（默认 dry-run，--apply 才真正删）
  use     套用模板：替换 {{var}} 并将 usage_count 自增

存储:
  templates/{category}/{name}.md   模板文件（带 frontmatter）
  templates/INDEX.json             索引（原子写入：临时文件 + os.replace）

变量占位符统一用 {{var_name}}。纯 stdlib，python3.11。
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_一-鿿]+)\s*\}\}")
CATEGORIES = ["xiaohongshu", "weibo", "douyin", "zhihu", "wechat", "x", "general"]


def eprint(*a):
    print(*a, file=sys.stderr)


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def atomic_write_json(path, data):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2))


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        eprint(f"[warn] 读取 {path} 失败（{e}），使用默认值")
        return default


def index_path(root):
    return os.path.join(root, "INDEX.json")


def load_index(root):
    return load_json(index_path(root), {"version": 1, "templates": []})


def save_index(root, idx):
    idx["updated"] = datetime.now().isoformat(timespec="seconds")
    idx["count"] = len(idx["templates"])
    atomic_write_json(index_path(root), idx)


def extract_vars(body):
    seen = []
    for m in VAR_RE.finditer(body):
        v = m.group(1)
        if v not in seen:
            seen.append(v)
    return seen


def render_frontmatter(meta):
    lines = ["---"]
    for k in ("name", "category", "description", "profile", "created", "usage_count"):
        if k in meta and meta[k] is not None:
            v = meta[k]
            lines.append(f"{k}: {v}")
    lines.append("variables: [" + ", ".join(meta.get("variables", [])) + "]")
    lines.append("---")
    return "\n".join(lines)


def template_file(root, category, name):
    return os.path.join(root, category, f"{name}.md")


def find_entry(idx, name):
    for e in idx["templates"]:
        if e["name"] == name:
            return e
    return None


def read_body(path):
    """读取模板文件，剥掉 frontmatter，返回正文。"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


# ---- save -------------------------------------------------------------------
def _get_content(args):
    if args.file:
        if not os.path.exists(args.file):
            eprint(f"[error] 源文件不存在: {args.file}")
            return None
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    if args.text is not None:
        return args.text
    eprint("[error] 需提供 --file 或 --text")
    return None


def cmd_save(args):
    root = args.root
    body = _get_content(args)
    if body is None:
        return 1
    idx = load_index(root)
    if find_entry(idx, args.name) and not args.force:
        eprint(f"[error] 模板已存在: {args.name}（用 edit 修改，或 save --force 覆盖）")
        return 1
    variables = extract_vars(body)
    meta = {
        "name": args.name,
        "category": args.category,
        "description": args.description or "",
        "profile": args.profile or "shared",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "usage_count": 0,
        "variables": variables,
    }
    path = template_file(root, args.category, args.name)
    atomic_write(path, render_frontmatter(meta) + "\n\n" + body.strip() + "\n")
    entry = {
        "name": args.name, "category": args.category,
        "description": meta["description"], "profile": meta["profile"],
        "created": meta["created"], "usage_count": 0,
        "variables": variables,
        "path": os.path.relpath(path, root),
    }
    old = find_entry(idx, args.name)
    if old:
        idx["templates"].remove(old)
    idx["templates"].append(entry)
    save_index(root, idx)
    print(f"已保存模板 '{args.name}' -> {os.path.relpath(path, root)}")
    print(f"分类: {args.category}  变量({len(variables)}): "
          + (", ".join(variables) or "（无）"))
    return 0


# ---- list -------------------------------------------------------------------
def cmd_list(args):
    idx = load_index(args.root)
    ts = idx["templates"]
    if args.category:
        ts = [t for t in ts if t["category"] == args.category]
    if not ts:
        print("（无模板）")
        return 0
    print(f"模板库（{args.root}）：{len(ts)} 个")
    bycat = {}
    for t in ts:
        bycat.setdefault(t["category"], []).append(t)
    for cat in sorted(bycat):
        rows = sorted(bycat[cat], key=lambda x: -x.get("usage_count", 0))
        print(f"\n## {cat} ({len(rows)})")
        for t in rows:
            print(f"  {t['name']:<20} 变量{len(t.get('variables', [])):>2} "
                  f"用{t.get('usage_count', 0):>3}次  {t.get('description', '')}")
    return 0


# ---- get --------------------------------------------------------------------
def cmd_get(args):
    idx = load_index(args.root)
    e = find_entry(idx, args.name)
    if not e:
        eprint(f"[error] 模板不存在: {args.name}")
        return 1
    path = os.path.join(args.root, e["path"])
    if not os.path.exists(path):
        eprint(f"[error] 模板文件丢失: {path}（索引存在但文件缺失）")
        return 1
    print(f"# 模板: {e['name']}  [{e['category']}]  用{e.get('usage_count', 0)}次")
    print(f"变量({len(e.get('variables', []))}): "
          + (", ".join(e.get("variables", [])) or "（无）"))
    print(f"描述: {e.get('description', '')}\n---")
    print(read_body(path))
    return 0


# ---- edit -------------------------------------------------------------------
def cmd_edit(args):
    root = args.root
    idx = load_index(root)
    e = find_entry(idx, args.name)
    if not e:
        eprint(f"[error] 模板不存在: {args.name}")
        return 1
    old_path = os.path.join(root, e["path"])
    body = read_body(old_path) if os.path.exists(old_path) else ""
    if args.file or args.text is not None:
        new = _get_content(args)
        if new is None:
            return 1
        body = new
    if args.description is not None:
        e["description"] = args.description
    new_cat = args.category or e["category"]
    variables = extract_vars(body)
    e["category"] = new_cat
    e["variables"] = variables
    meta = {
        "name": e["name"], "category": new_cat,
        "description": e.get("description", ""), "profile": e.get("profile", "shared"),
        "created": e.get("created", datetime.now().strftime("%Y-%m-%d")),
        "usage_count": e.get("usage_count", 0), "variables": variables,
    }
    new_path = template_file(root, new_cat, e["name"])
    atomic_write(new_path, render_frontmatter(meta) + "\n\n" + body.strip() + "\n")
    if os.path.abspath(new_path) != os.path.abspath(old_path) and os.path.exists(old_path):
        os.remove(old_path)
    e["path"] = os.path.relpath(new_path, root)
    save_index(root, idx)
    print(f"已更新模板 '{e['name']}'  分类={new_cat}  变量({len(variables)}): "
          + (", ".join(variables) or "（无）"))
    return 0


# ---- delete -----------------------------------------------------------------
def cmd_delete(args):
    root = args.root
    idx = load_index(root)
    e = find_entry(idx, args.name)
    if not e:
        eprint(f"[error] 模板不存在: {args.name}")
        return 1
    path = os.path.join(root, e["path"])
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] 将删除模板 '{args.name}' -> {e['path']}")
    if not args.apply:
        print("确认后加 --apply 执行。")
        return 0
    if os.path.exists(path):
        os.remove(path)
    idx["templates"].remove(e)
    save_index(root, idx)
    print(f"已删除模板 '{args.name}'")
    return 0


# ---- use --------------------------------------------------------------------
def _collect_values(args):
    values = {}
    if args.vars:
        try:
            values.update(json.loads(args.vars))
        except json.JSONDecodeError as ex:
            eprint(f"[error] --vars 不是合法 JSON: {ex}")
            return None
    for kv in args.var or []:
        if "=" not in kv:
            eprint(f"[error] --var 需 name=value 格式: {kv}")
            return None
        k, v = kv.split("=", 1)
        values[k.strip()] = v
    return values


def cmd_use(args):
    root = args.root
    idx = load_index(root)
    e = find_entry(idx, args.name)
    if not e:
        eprint(f"[error] 模板不存在: {args.name}")
        return 1
    path = os.path.join(root, e["path"])
    if not os.path.exists(path):
        eprint(f"[error] 模板文件丢失: {path}")
        return 1
    values = _collect_values(args)
    if values is None:
        return 1
    body = read_body(path)

    missing = []

    def repl(m):
        name = m.group(1)
        if name in values:
            return str(values[name])
        missing.append(name)
        return m.group(0)

    filled = VAR_RE.sub(repl, body)
    missing = sorted(set(missing))

    # usage_count 自增（原子写回索引）
    e["usage_count"] = e.get("usage_count", 0) + 1
    save_index(root, idx)

    print(f"# 套用模板: {e['name']}  (第 {e['usage_count']} 次使用)")
    if missing:
        eprint(f"[warn] 未填变量（保留占位符）: {', '.join(missing)}")
    print("---")
    print(filled.rstrip())
    return 0


# ---- CLI --------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="templates.py",
        description="Easel 模板库：save/list/get/edit/delete/use。",
    )
    p.add_argument("--root", default="templates", help="模板根目录（默认 templates）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("save", help="保存模板")
    sp.add_argument("name", help="模板名")
    sp.add_argument("--category", default="general", choices=CATEGORIES)
    src = sp.add_mutually_exclusive_group()
    src.add_argument("--file", help="源文件路径")
    src.add_argument("--text", help="源文本（含 {{var}} 占位符）")
    sp.add_argument("--description", help="一句话描述")
    sp.add_argument("--profile", help="绑定画像名（缺省 shared）")
    sp.add_argument("--force", action="store_true", help="同名则覆盖")

    sp = sub.add_parser("list", help="列出模板")
    sp.add_argument("--category", choices=CATEGORIES, help="按分类筛选")

    sp = sub.add_parser("get", help="打印模板内容")
    sp.add_argument("name")

    sp = sub.add_parser("edit", help="修改模板")
    sp.add_argument("name")
    sp.add_argument("--category", choices=CATEGORIES, help="改分类（会移动文件）")
    src = sp.add_mutually_exclusive_group()
    src.add_argument("--file", help="用文件替换正文")
    src.add_argument("--text", help="用文本替换正文")
    sp.add_argument("--description", help="改描述")

    sp = sub.add_parser("delete", help="删除模板（默认 dry-run）")
    sp.add_argument("name")
    sp.add_argument("--apply", action="store_true", help="真正删除")

    sp = sub.add_parser("use", help="套用模板并 usage_count 自增")
    sp.add_argument("name")
    sp.add_argument("--var", action="append", help="变量赋值 name=value（可重复）")
    sp.add_argument("--vars", help="变量赋值 JSON，如 '{\"a\":\"b\"}'")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    dispatch = {
        "save": cmd_save, "list": cmd_list, "get": cmd_get,
        "edit": cmd_edit, "delete": cmd_delete, "use": cmd_use,
    }
    return dispatch[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
