#!/usr/bin/env python3
"""mindmap.py — Markdown 大纲 → 思维导图（markmap 自包含 HTML + 可选 PNG）。

把 Markdown 大纲（标题层级 + 列表）渲染成可交互思维导图 HTML（基于 markmap，自包含，
浏览器打开即用），可选用 Chromium 渲染成 PNG 图片。

与 chart-visualization/infographic 的区别：那些做数据图表/信息图；本 SKILL 专做**层级大纲**
的思维导图（知识结构、SWOT、内容框架）。

依赖：HTML 生成纯标准库；PNG 渲染需 playwright + chromium + 外网（markmap JS 走 CDN）。

子命令：
    make       Markdown 大纲 → 思维导图 HTML（--png 追加渲染 PNG）
    selftest   自检（HTML 生成 + 可选 PNG）

用法举例：
    mindmap.py make -i outline.md -o outputs/mindmap/mm.html
    mindmap.py make -i outline.md -o outputs/mindmap/mm.html --png
    echo "# 主题\\n## 分支A\\n- 点1" | mindmap.py make -i - -o mm.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  html,body{{margin:0;padding:0;background:{bg};}}
  svg.markmap{{width:100vw;height:100vh;}}
</style>
</head><body>
<div class="markmap" data-color-freeze-level="2">
<script type="text/template">
{markdown}
</script>
</div>
<script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@0.18"></script>
</body></html>
"""


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _prep_out(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def build_html(markdown: str, title: str = "思维导图", bg: str = "#ffffff") -> str:
    """纯函数：Markdown → markmap HTML（供测试）。"""
    md = (markdown or "").strip()
    if not md:
        _die("Markdown 大纲为空")
    # 防止 </script> 破坏模板
    md = md.replace("</script>", "<\\/script>")
    return _TEMPLATE.format(title=title, bg=bg, markdown=md)


def _render_png(html_path: Path, png_path: Path) -> bool:
    """用 chromium 把 markmap HTML 渲染成 PNG。需 playwright+内核+外网。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"  (未装 playwright，跳过 PNG：{e})", file=sys.stderr)
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page(viewport={"width": 1600, "height": 1000},
                              device_scale_factor=2)
            page.goto(html_path.as_uri(), wait_until="networkidle", timeout=30000)
            page.wait_for_selector("svg.markmap g", timeout=15000)
            page.wait_for_timeout(1200)  # 等布局动画
            page.screenshot(path=str(png_path), full_page=True)
            b.close()
        return png_path.is_file()
    except Exception as e:
        print(f"  (PNG 渲染失败，可能无外网加载 markmap CDN：{e})", file=sys.stderr)
        return False


def cmd_make(a) -> int:
    if a.input == "-":
        md = sys.stdin.read()
    else:
        p = Path(a.input).expanduser()
        if not p.is_file():
            _die(f"输入不存在：{p}")
        md = p.read_text(encoding="utf-8")
    title = a.title or (md.strip().splitlines()[0].lstrip("# ").strip() if md.strip() else "思维导图")
    html = build_html(md, title=title, bg=a.bg)
    out = _prep_out(a.output)
    if out.suffix.lower() != ".html":
        out = out.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    kb = out.stat().st_size / 1024
    print(f"✅ {out} ({kb:.0f} KB) 思维导图 HTML（浏览器打开可交互）")
    if a.png:
        png = out.with_suffix(".png")
        if _render_png(out, png):
            print(f"✅ {png} ({png.stat().st_size/1024:.0f} KB) PNG")
        else:
            print("  PNG 未生成（HTML 可用）。如需 PNG：确保 playwright+chromium+外网。",
                  file=sys.stderr)
    return 0


def cmd_selftest(a) -> int:
    print("mindmap 自检 ...", file=sys.stderr)
    import tempfile
    sample = ("# 内容策略\n## 选题\n- 热点\n- 痛点\n## 形式\n- 图文\n- 视频\n"
              "## 渠道\n- 小红书\n- 抖音\n")
    # HTML 生成
    html = build_html(sample, title="测试")
    assert "markmap-autoloader" in html, "缺 markmap 脚本"
    assert "内容策略" in html and "小红书" in html, "Markdown 未嵌入"
    assert "<title>测试</title>" in html
    # 嵌入内容里的 </script> 被转义（模板自身的 script 标签不受影响）
    assert "<\\/script>" in build_html("# a\n- </script>攻击"), "未转义嵌入的 </script>"

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "o.md"; src.write_text(sample, encoding="utf-8")
        out = Path(td) / "mm.html"
        cmd_make(argparse.Namespace(input=str(src), output=str(out), title=None,
                                    bg="#ffffff", png=a.png_in_selftest))
        assert out.is_file() and "markmap" in out.read_text(encoding="utf-8")
        if a.png_in_selftest:
            png = out.with_suffix(".png")
            print(f"  PNG 存在：{png.is_file()}", file=sys.stderr)
    print("✅ selftest 通过（HTML 生成 + Markdown 嵌入 + 标题 + </script> 转义）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Markdown 大纲 → 思维导图（markmap HTML + 可选 PNG）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("make", help="生成思维导图")
    p.add_argument("-i", "--input", required=True, help="Markdown 大纲文件（- 为 stdin）")
    p.add_argument("-o", "--output", required=True, help="输出 HTML 路径")
    p.add_argument("--title", help="页面标题（默认取首行标题）")
    p.add_argument("--bg", default="#ffffff", help="背景色（默认白）")
    p.add_argument("--png", action="store_true", help="额外渲染 PNG（需 playwright+chromium+外网）")
    p.set_defaults(func=cmd_make)

    ps = sub.add_parser("selftest", help="自检")
    ps.add_argument("--png-in-selftest", action="store_true", help="自检也测 PNG 渲染")
    ps.set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
