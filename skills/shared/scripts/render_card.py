#!/usr/bin/env python3
"""render_card.py — HTML → 图片 的确定性渲染（playwright + chromium）。

所有"HTML 单图 → 截图"类 SKILL（card-quote / card-xiaohongshu / poster-hero /
comparison-card 等）共用此脚本，避免每次现场即兴起 headless 浏览器导致慢/卡/超时。

依赖：playwright（`pip install playwright` + `playwright install chromium`）。

用法：
    # 截取单个元素
    render_card.py --html card.html --out card.png --selector ".card"

    # 整页截图（竖版海报常用）
    render_card.py --html poster.html --out poster.png --full-page --width 1080 --height 1920

    # 一个 HTML 里多张卡片，批量导出（selector 命中多个元素，逐个存 <out前缀>_1.png ...）
    render_card.py --html cards.html --out-dir ./out --all ".card" --prefix card

    # 自检（不需要 HTML，验证浏览器可用）
    render_card.py --selftest
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--font-render-hinting=none",
    "--disable-dev-shm-usage",
]


def _env_proxy() -> str | None:
    """从环境变量取外网代理（CDN/Google Fonts 需要）。"""
    for k in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY"):
        v = os.environ.get(k)
        if v:
            return v
    return None


async def _render(args) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: 未安装 playwright。请运行：pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 3

    html_path = Path(args.html).resolve()
    if not html_path.is_file():
        print(f"ERROR: HTML 文件不存在: {html_path}", file=sys.stderr)
        return 2

    fmt = args.format
    proxy = args.proxy or _env_proxy()
    launch_kwargs: dict = {"args": _LAUNCH_ARGS}
    if proxy:
        launch_kwargs["proxy"] = {"server": proxy}
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(**launch_kwargs)
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: 无法启动 chromium（可能未 `playwright install chromium`）: {e}", file=sys.stderr)
            return 3
        page = await browser.new_page(
            viewport={"width": args.width, "height": args.height},
            device_scale_factor=args.scale,
        )
        # 不用 networkidle：外部 CDN/字体可能永不 idle 导致挂起。
        # 用 "load" + 有界超时，超时也继续（页面通常已可视），再靠 --wait 等字体。
        try:
            await page.goto(f"file://{html_path}", wait_until="load",
                            timeout=args.nav_timeout)
        except Exception as e:  # noqa: BLE001
            print(f"WARN: 页面加载未在 {args.nav_timeout}ms 内完成（外部资源慢），继续渲染: {e}",
                  file=sys.stderr)
        # 等 web 字体 / 布局稳定
        try:
            await page.evaluate("document.fonts && document.fonts.ready")
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(args.wait)

        saved: list[str] = []

        def _shot_kwargs(path: str) -> dict:
            kw: dict = {"path": path, "type": fmt}
            if fmt == "jpeg":
                kw["quality"] = args.quality
            return kw

        if args.all:
            out_dir = Path(args.out_dir or ".").resolve()
            out_dir.mkdir(parents=True, exist_ok=True)
            els = await page.query_selector_all(args.all)
            if not els:
                print(f"ERROR: selector 未命中任何元素: {args.all}", file=sys.stderr)
                await browser.close()
                return 2
            for i, el in enumerate(els, 1):
                out_path = out_dir / f"{args.prefix}_{i}.{fmt}"
                await el.screenshot(**_shot_kwargs(str(out_path)))
                saved.append(str(out_path))
        else:
            if not args.out:
                print("ERROR: 需要 --out（或用 --all + --out-dir 批量）", file=sys.stderr)
                await browser.close()
                return 2
            out_path = Path(args.out).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if args.full_page:
                await page.screenshot(**_shot_kwargs(str(out_path)), full_page=True)
            elif args.selector:
                el = await page.query_selector(args.selector)
                if el is None:
                    print(f"ERROR: selector 未命中: {args.selector}", file=sys.stderr)
                    await browser.close()
                    return 2
                await el.screenshot(**_shot_kwargs(str(out_path)))
            else:
                # 无 selector 无 full-page：截 viewport 区域
                await page.screenshot(**_shot_kwargs(str(out_path)))
            saved.append(str(out_path))

        await browser.close()

    for s in saved:
        kb = Path(s).stat().st_size / 1024
        print(f"✅ {s} ({kb:.0f} KB)")
    print(f"共渲染 {len(saved)} 张")
    return 0


async def _selftest() -> int:
    """渲染一张最小卡片验证浏览器链路可用。"""
    import tempfile

    html = (
        "<html><head><meta charset='utf-8'><style>"
        ".card{width:400px;height:225px;display:flex;align-items:center;"
        "justify-content:center;background:#1a1a2e;color:#fff;"
        "font:600 28px sans-serif;}</style></head>"
        "<body><div class='card'>Easel 渲染自检 OK</div></body></html>"
    )
    with tempfile.TemporaryDirectory() as d:
        hp = Path(d) / "t.html"
        hp.write_text(html, encoding="utf-8")
        op = Path(d) / "t.png"
        ns = argparse.Namespace(
            html=str(hp), out=str(op), out_dir=None, selector=".card", all=None,
            prefix="card", full_page=False, width=400, height=225, scale=2,
            format="png", quality=90, wait=300, nav_timeout=20000, proxy=None,
        )
        rc = await _render(ns)
        if rc == 0 and op.is_file() and op.stat().st_size > 0:
            print("[PASS] 渲染链路正常")
            return 0
        print("[FAIL] 渲染自检失败", file=sys.stderr)
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="HTML → 图片 确定性渲染（playwright）")
    ap.add_argument("--html", help="输入 HTML 文件路径")
    ap.add_argument("--out", help="输出图片路径（单图模式）")
    ap.add_argument("--out-dir", help="输出目录（--all 批量模式）")
    ap.add_argument("--selector", help="要截取的元素 CSS selector（单图）")
    ap.add_argument("--all", help="批量截取命中该 selector 的所有元素")
    ap.add_argument("--prefix", default="card", help="批量模式文件名前缀（默认 card）")
    ap.add_argument("--full-page", action="store_true", help="整页截图")
    ap.add_argument("--width", type=int, default=1080, help="视口宽（默认 1080）")
    ap.add_argument("--height", type=int, default=1440, help="视口高（默认 1440）")
    ap.add_argument("--scale", type=int, default=2, help="设备像素比，越高越清晰（默认 2）")
    ap.add_argument("--format", choices=["png", "jpeg"], default="png", help="输出格式")
    ap.add_argument("--quality", type=int, default=90, help="jpeg 质量 1-100（默认 90）")
    ap.add_argument("--wait", type=int, default=1200, help="渲染等待毫秒（默认 1200，等字体）")
    ap.add_argument("--nav-timeout", type=int, default=20000, help="页面加载超时毫秒（默认 20000，超时也继续）")
    ap.add_argument("--proxy", help="外网代理（默认读 https_proxy/http_proxy 环境变量，供 CDN/字体加载）")
    ap.add_argument("--selftest", action="store_true", help="运行渲染自检")
    args = ap.parse_args()

    if args.selftest:
        return asyncio.run(_selftest())
    if not args.html:
        ap.error("需要 --html（或 --selftest）")
    return asyncio.run(_render(args))


if __name__ == "__main__":
    sys.exit(main())
