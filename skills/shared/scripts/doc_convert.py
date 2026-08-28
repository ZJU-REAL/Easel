#!/usr/bin/env python3
"""doc_convert.py — Markdown → HTML / PDF / 长图 PNG（排版转换）。

把 Markdown 文稿排版成干净的 HTML、可打印 PDF、或适合社媒/存档的长图 PNG。
用 python-markdown 排版 + Chromium 打印/截图，无需 pandoc。

范围：MD → HTML / PDF / PNG（长图）。DOCX/PPT 等需 pandoc，不在此范围。

依赖：markdown（`pip install markdown`）；PDF/PNG 需 playwright + chromium。

子命令：
    convert    Markdown → HTML/PDF/PNG（按输出后缀）
    selftest   自检

用法举例：
    doc_convert.py convert -i article.md -o out.html
    doc_convert.py convert -i article.md -o out.pdf
    doc_convert.py convert -i article.md -o out.png --width 800
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_CSS = """
:root{--fg:#24292f;--muted:#57606a;--border:#d0d7de;--code-bg:#f6f8fa;--accent:#0969da;}
*{box-sizing:border-box;}
body{margin:0;background:#fff;color:var(--fg);
  font-family:-apple-system,'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',
  'Helvetica Neue',Arial,sans-serif;line-height:1.75;font-size:17px;}
.page{max-width:{maxw}px;margin:0 auto;padding:48px 40px;}
h1,h2,h3,h4{line-height:1.35;margin:1.6em 0 .6em;font-weight:700;}
h1{font-size:1.9em;border-bottom:2px solid var(--border);padding-bottom:.3em;}
h2{font-size:1.5em;border-bottom:1px solid var(--border);padding-bottom:.25em;}
h3{font-size:1.25em;} p{margin:.8em 0;}
a{color:var(--accent);text-decoration:none;}
code{background:var(--code-bg);padding:.15em .4em;border-radius:5px;font-size:.9em;
  font-family:'SF Mono',Consolas,monospace;}
pre{background:var(--code-bg);padding:16px;border-radius:8px;overflow:auto;}
pre code{background:none;padding:0;}
blockquote{margin:.8em 0;padding:.2em 1em;color:var(--muted);
  border-left:4px solid var(--border);}
table{border-collapse:collapse;margin:1em 0;width:100%;}
th,td{border:1px solid var(--border);padding:8px 12px;text-align:left;}
th{background:var(--code-bg);} img{max-width:100%;height:auto;border-radius:8px;}
ul,ol{padding-left:1.6em;} li{margin:.3em 0;} hr{border:none;border-top:1px solid var(--border);}
"""

_HTML = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body><div class="page">{body}</div></body></html>"""


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def md_to_html(md_text: str, title: str, maxw: int) -> str:
    """Markdown → 完整 HTML（纯函数，供测试）。"""
    try:
        import markdown
    except Exception as e:
        _die(f"需要 markdown 库：{e}（pip install markdown）", 3)
    body = markdown.markdown(
        md_text, extensions=["extra", "tables", "fenced_code", "toc",
                             "sane_lists", "nl2br", "admonition"])
    return _HTML.format(title=title, css=_CSS.replace("{maxw}", str(maxw)), body=body)


def _render(html_path: Path, out: Path, kind: str, width: int) -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"{kind} 需要 playwright：{e}（pip install playwright && playwright install chromium）", 3)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": width, "height": 1200}, device_scale_factor=2)
        page.goto(html_path.as_uri(), wait_until="networkidle", timeout=30000)
        if kind == "pdf":
            page.pdf(path=str(out), format="A4",
                     margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
                     print_background=True)
        else:  # png 长图
            page.screenshot(path=str(out), full_page=True)
        b.close()
    return out.is_file()


def cmd_convert(a) -> int:
    src = Path(a.input).expanduser()
    if not src.is_file():
        _die(f"输入不存在：{src}")
    md_text = src.read_text(encoding="utf-8")
    title = a.title or (md_text.strip().splitlines()[0].lstrip("# ").strip()
                        if md_text.strip() else src.stem)
    out = _prep_out(a.output)
    fmt = a.format or out.suffix.lower().lstrip(".")
    if fmt not in ("html", "pdf", "png"):
        _die(f"不支持的输出格式：{fmt}（支持 html/pdf/png）")

    html = md_to_html(md_text, title, a.width if fmt == "png" else a.page_width)

    if fmt == "html":
        out.write_text(html, encoding="utf-8")
        print(f"✅ {out} ({out.stat().st_size/1024:.0f} KB) HTML")
        return 0
    # pdf/png 需先落 HTML 临时文件
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "doc.html"
        tmp.write_text(html, encoding="utf-8")
        ok = _render(tmp, out, fmt, a.width)
    if ok:
        print(f"✅ {out} ({out.stat().st_size/1024:.0f} KB) {fmt.upper()}")
        return 0
    _die(f"{fmt} 渲染失败")
    return 1


def cmd_selftest(_a) -> int:
    print("doc_convert 自检 ...", file=sys.stderr)
    import tempfile
    sample = ("# 标题\n\n正文段落，含**加粗**与`代码`。\n\n"
              "## 小节\n- 列表项 1\n- 列表项 2\n\n"
              "| 平台 | 字数 |\n|---|---|\n| 小红书 | 1000 |\n| 微博 | 2000 |\n\n"
              "```python\nprint('hi')\n```\n")
    # MD → HTML
    html = md_to_html(sample, "测试", 800)
    assert "<h1" in html and "<table>" in html, "MD 未正确转 HTML（缺标题/表格）"
    assert "<strong>" in html and "<code>" in html, "加粗/代码未渲染"
    assert "PingFang" in html, "CJK 字体样式缺失"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "a.md"; src.write_text(sample, encoding="utf-8")
        # HTML
        h = Path(td) / "o.html"
        cmd_convert(argparse.Namespace(input=str(src), output=str(h), format=None,
                                       title=None, width=800, page_width=760))
        assert h.is_file()
        # PDF
        pdf = Path(td) / "o.pdf"
        cmd_convert(argparse.Namespace(input=str(src), output=str(pdf), format=None,
                                       title=None, width=800, page_width=760))
        assert pdf.is_file() and pdf.stat().st_size > 1000, "PDF 未生成"
        # PNG 长图
        png = Path(td) / "o.png"
        cmd_convert(argparse.Namespace(input=str(src), output=str(png), format=None,
                                       title=None, width=800, page_width=760))
        assert png.is_file() and png.stat().st_size > 1000, "PNG 未生成"
    print("✅ selftest 通过（MD→HTML/PDF/PNG，表格/代码/加粗/CJK）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Markdown → HTML/PDF/长图 PNG（python-markdown + Chromium）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("convert", help="转换 Markdown")
    p.add_argument("-i", "--input", required=True, help="Markdown 文件")
    p.add_argument("-o", "--output", required=True, help="输出（.html/.pdf/.png）")
    p.add_argument("--format", choices=["html", "pdf", "png"], help="默认按输出后缀")
    p.add_argument("--title", help="文档标题（默认取首行）")
    p.add_argument("--width", type=int, default=800, help="PNG 长图宽度像素（默认 800）")
    p.add_argument("--page-width", type=int, default=760, help="HTML/PDF 正文最大宽度（默认 760）")
    p.set_defaults(func=cmd_convert)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
