#!/usr/bin/env python3
"""xhs_publish.py — 小红书发布（Playwright，headless 可用）.

替代旧的 CDP-to-真实Chrome 死栈（那套需桌面 Chrome，本 Linux 环境跑不了）。
本脚本用 Playwright + 持久化登录态，headless 即可发布，流程与选择器移植自
xpzouying/xiaohongshu-mcp（Go/go-rod，成熟稳定）。确定性 IO 固化在脚本，
文案/策略仍由上层 LLM 决定。

移植的关键健壮技巧（源见各处 REF 注释）：
  - 切「上传图文/视频」tab：重试 + 遮挡检测 + 移除弹层
  - 逐图上传并等预览出现（≤60s）；视频等发布按钮可点击（≤10min = 处理完成）
  - 话题：输 # + 联想下拉点选，真绑话题
  - 发布按钮：新版 <xhs-publish-btn> + 旧版 .bg-red 双兼容
  - 发布成功校验：URL 离开 /publish/publish 才算成功（消除假成功）
  - 反检测：--disable-blink-features=AutomationControlled + 逐字符输入 + zh-CN

子命令:
  check          验 playwright + chromium 内核
  login          有头扫码登录并持久化 cookie
  plan           离线打印发布步骤与选择器（不启浏览器）
  publish        图文发布（--images 逗号分隔）
  publish-video  视频发布（--video）
  selftest       离线自检（选择器字典 / 参数解析 / 标题长度算法）

真实发布需：playwright + chromium 内核 + 已扫码登录 + 外网可达（默认走项目代理）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import login_state  # noqa: E402
import content_guard  # noqa: E402  出站内容安全闸门

# --------------------------------------------------------------------------- #
# 选择器集中维护（小红书改版时单点更新）。REF = xiaohongshu-mcp 对应源。
# --------------------------------------------------------------------------- #
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"
EXPLORE_URL = "https://www.xiaohongshu.com/explore"
TITLE_MAX = 20  # 小红书标题上限（全角计法，见 calc_title_length）

SELECTORS = {
    # 登录（REF login.go）
    "login_ok": ".main-container .user .link-wrapper .channel",
    "qrcode": ".login-container .qrcode-img",
    # 进页/切 tab（REF publish.go mustClickPublishTab）
    "upload_content": "div.upload-content",
    "creator_tab": "div.creator-tab",
    "pop_cover": "div.d-popover",
    # 上传（REF publish.go uploadImages / publish_video.go uploadVideo）
    "upload_input_first": ".upload-input",
    "upload_input_more": "input[type=file]",
    "img_preview": ".img-preview-area .pr",
    # 标题/正文（REF publish.go submitPublish / getContentElement）
    "title_input": "div.d-input input, input[placeholder*='标题']",
    "content_quill": "div.ql-editor",
    "content_editable": "div.editor-container [contenteditable='true'], [contenteditable='true']",
    "content_placeholder": "p[data-placeholder*='输入正文描述']",
    "title_overflow": "div.title-container div.max_suffix",
    "content_overflow": "div.edit-container div.length-error",
    # 话题（REF publish.go inputTag）
    "topic_container": "#creator-editor-topic-container",
    "topic_item": "#creator-editor-topic-container .item",
    # 发布按钮（REF publish.go findPublishButton）
    "publish_btn_new": "xhs-publish-btn",
    "publish_btn_old": ".publish-page-publish-btn button.bg-red",
}

PROFILE_NAME = "XiaohongshuProfile"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QR_OUT = PROJECT_ROOT / "outputs" / "_login" / "xhs-login-qrcode.png"

# Chromium 启动性能参数（提速冷启动；勿禁用图片——二维码是图片）
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--disable-features=TranslateUI,BackForwardCache",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]


# --------------------------------------------------------------------------- #
# 纯函数（可离线自测）
# --------------------------------------------------------------------------- #
def calc_title_length(s: str) -> int:
    """小红书标题长度：UTF-16 码元非 ASCII 计 2、ASCII 计 1，再 (n+1)//2 上取整。
    REF pkg/xhsutil/title.go CalcTitleLength。20 全角字 → 20。"""
    utf16 = s.encode("utf-16-le")
    byte_len = 0
    for i in range(0, len(utf16), 2):
        code = utf16[i] | (utf16[i + 1] << 8)
        byte_len += 2 if code > 127 else 1
    return (byte_len + 1) // 2


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _abspaths(csv: str | None) -> list[str]:
    """逗号分隔路径 → 绝对路径列表，校验存在。"""
    if not csv:
        return []
    out = []
    for raw in csv.split(","):
        raw = raw.strip()
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            _die(f"文件不存在：{p}")
        out.append(str(p))
    return out


def _profile_dir(base: str | None) -> Path:
    root = Path(base).expanduser() if base else Path.home() / ".easel-browser-profiles"
    return root / PROFILE_NAME


def _proxy(explicit: str | None, disable: bool) -> str | None:
    """外网代理：--no-proxy 关；--proxy 显式；否则取 env（小红书是外网，默认需代理）。"""
    if disable:
        return None
    if explicit:
        return explicit
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") \
        or os.environ.get("EASEL_PROXY")


# --------------------------------------------------------------------------- #
# 浏览器动作（移植自 xiaohongshu-mcp，需 playwright）
# --------------------------------------------------------------------------- #
def _human_type(page, locator, text: str) -> None:
    """逐字符输入 + 随机间隔（反检测，REF humanize/input.go Type）。"""
    locator.click()
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(30, 110))


def _click_publish_tab(page, tabname: str) -> None:
    """点「上传图文/上传视频」tab：重试 15s + 遮挡检测 + 移弹层。REF mustClickPublishTab。"""
    page.wait_for_selector(SELECTORS["upload_content"], timeout=15000)
    deadline = time.time() + 15
    while time.time() < deadline:
        tabs = page.query_selector_all(SELECTORS["creator_tab"])
        for tab in tabs:
            try:
                if not tab.is_visible():
                    continue
                if (tab.inner_text() or "").strip() != tabname:
                    continue
            except Exception:
                continue
            # 遮挡检测（REF isElementBlocked：elementFromPoint 命中的是不是自己）
            blocked = tab.evaluate(
                """(el) => { const r = el.getBoundingClientRect();
                    if (!r.width || !r.height) return true;
                    const t = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
                    return !(t === el || el.contains(t)); }""")
            if blocked:
                cover = page.query_selector(SELECTORS["pop_cover"])
                if cover:
                    cover.evaluate("el => el.remove()")
                page.wait_for_timeout(200)
                continue
            tab.click()
            return
        page.wait_for_timeout(200)
    _die(f"未找到发布 TAB：{tabname}（页面结构可能已变，检查 SELECTORS.creator_tab）")


def _upload_images(page, paths: list[str]) -> None:
    """逐张上传并等预览出现（≤60s/张）。REF uploadImages/waitForUploadComplete。"""
    for i, path in enumerate(paths):
        sel = SELECTORS["upload_input_first"] if i == 0 else SELECTORS["upload_input_more"]
        page.set_input_files(sel, path)
        print(f"  上传图片 {i+1}/{len(paths)}: {path}", file=sys.stderr)
        deadline = time.time() + 60
        while time.time() < deadline:
            if len(page.query_selector_all(SELECTORS["img_preview"])) >= i + 1:
                break
            page.wait_for_timeout(500)
        else:
            _die(f"第 {i+1} 张图片上传超时（60s）")
        page.wait_for_timeout(1000)


def _upload_video(page, path: str) -> None:
    """上传视频，等发布按钮可点击（≤10min = 处理完成）。REF publish_video.go uploadVideo。"""
    sel = SELECTORS["upload_input_first"]
    if not page.query_selector(sel):
        sel = SELECTORS["upload_input_more"]
    page.set_input_files(sel, path)
    print(f"  上传视频：{path}（等待处理，最长 10min）", file=sys.stderr)
    _wait_publish_clickable(page, timeout_s=600)


def _content_element(page):
    """正文输入框：先 ql-editor（旧版），再 contenteditable（新版），最后退回 placeholder 定位。
    REF getContentElement。小红书已把正文编辑器从 Quill 换成 contenteditable。"""
    el = page.query_selector(SELECTORS["content_quill"])
    if el:
        return el
    el = page.query_selector(SELECTORS["content_editable"])
    if el:
        return el
    ph = page.query_selector(SELECTORS["content_placeholder"])
    if ph:
        cur = ph
        for _ in range(5):
            parent = cur.evaluate_handle("el => el.parentElement").as_element()
            if not parent:
                break
            role = parent.get_attribute("role") or ""
            if role == "textbox" or parent.get_attribute("contenteditable") == "true":
                return parent
            cur = parent
    return None


def _check_overflow(page) -> None:
    """标题/正文超限：读平台自身的溢出提示元素。REF checkTitleMaxLength/checkContentMaxLength。"""
    for key, name in (("title_overflow", "标题"), ("content_overflow", "正文")):
        el = page.query_selector(SELECTORS[key])
        if el and el.is_visible():
            _die(f"{name}超出平台长度限制：{(el.inner_text() or '').strip()}")


def _input_tags(page, content_el, tags: list[str]) -> None:
    """话题：正文末尾输 # + 联想下拉点第一项，真绑话题。REF inputTag。

    注意：必须把 # 与话题名**连续输入**、中途不能再 click 正文——否则光标会被挪走，
    # 和话题名被拆开，小红书识别不到连续的 #话题 token，联想不出、绑不上话题。
    """
    if not tags:
        return
    content_el.click()
    page.keyboard.press("Control+End")   # 光标移到正文末尾，避免 # 插到正文中间
    page.wait_for_timeout(400)
    for tag in tags:
        tag = tag.lstrip("#").strip()
        if not tag:
            continue
        page.keyboard.type(" ")          # 与正文/上一话题分隔，确保 # 起一个新 token
        page.keyboard.type("#")
        page.wait_for_timeout(300)
        for ch in tag:                   # 逐字输入话题名——不再 click（避免移光标拆开 #话题）
            page.keyboard.type(ch)
            page.wait_for_timeout(random.randint(30, 110))
        page.wait_for_timeout(1000)
        item = page.query_selector(SELECTORS["topic_item"])
        if item:
            item.click()                 # 点联想第一项 = 真正绑定话题
        else:
            page.keyboard.type(" ")      # 无联想则退化为空格分隔（至少保留 #文字）
        page.wait_for_timeout(500)


def _wait_publish_clickable(page, timeout_s: int = 15):
    """等发布按钮可点击（新旧兼容）。REF findPublishButton/waitForPublishButtonClickable。"""
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        for w in page.query_selector_all(SELECTORS["publish_btn_new"]):
            if not w.is_visible():
                continue
            if (w.get_attribute("is-publish") or "") == "false":
                continue
            if (w.get_attribute("submit-disabled") or "") == "true":
                last = "新版发布按钮不可点击"
                continue
            return ("new", w)
        for b in page.query_selector_all(SELECTORS["publish_btn_old"]):
            if not b.is_visible():
                continue
            if b.get_attribute("disabled") is not None:
                last = "旧版发布按钮 disabled"
                continue
            if (b.get_attribute("aria-disabled") or "") == "true":
                last = "旧版发布按钮 aria-disabled"
                continue
            return ("old", b)
        page.wait_for_timeout(1000)
    _die(f"等待发布按钮可点击超时{('：' + last) if last else ''}")


def _diag_after_publish(page) -> str:
    """点发布后失败时，抓屏幕上可见的弹框/报错/toast 文案，供排错。
    截图默认不存（正常使用不截图）；排错时设 EASEL_PUBLISH_DEBUG=1 才会存失败截图。"""
    bits = []
    for sel in (".d-modal", "[role=dialog]", "[class*=modal]", "[class*=dialog]",
                ".d-message", ".d-toast", "[class*=toast]", "[class*=error]", "[class*=tip]"):
        try:
            for el in page.query_selector_all(sel):
                if el.is_visible():
                    t = (el.inner_text() or "").strip().replace("\n", " / ")
                    if t and t not in " ".join(bits):
                        bits.append(f"[{sel}] {t[:120]}")
        except Exception:
            pass
    shot = ""
    if os.environ.get("EASEL_PUBLISH_DEBUG"):
        try:
            out = PROJECT_ROOT / "outputs" / "_login" / "xhs-publish-fail.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out))
            shot = f"（调试截图见 {out}）"
        except Exception:
            pass
    return ("屏幕可见元素：" + " | ".join(bits[:6]) if bits else "屏幕无可识别弹框/报错") + shot


def _confirm_publish_dialog(page) -> None:
    """点发布后若弹二次确认框，点其确认按钮（保守：仅当可见且文案匹配）。"""
    deadline = time.time() + 5
    while time.time() < deadline:
        for b in page.query_selector_all("button, .d-button, [role=button]"):
            try:
                if not b.is_visible():
                    continue
                tx = (b.inner_text() or "").strip()
                if tx in ("确认发布", "确定发布", "继续发布", "立即发布", "确认", "确定"):
                    b.click()
                    page.wait_for_timeout(1000)
                    return
            except Exception:
                pass
        page.wait_for_timeout(500)


def _wait_publish_success(page, timeout_s: int = 40) -> None:
    """发布成功校验：小红书发布成功后**原地清空表单回到上传页**（不换 URL）。
    成功信号任一：跳离 /publish/publish、出现「成功」toast、或编辑表单已重置（标题框+图片预览消失）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if "/publish/publish" not in page.url:
            print(f"✅ 发布成功，已跳转：{page.url}")
            return
        for sel in (".d-message", ".d-toast", "[class*=toast]", "[class*=message]"):
            try:
                el = page.query_selector(sel)
                if el and el.is_visible() and "成功" in (el.inner_text() or ""):
                    print("✅ 发布成功（检测到成功提示）")
                    return
            except Exception:
                pass
        # 表单已重置：填过的标题框 + 上传的图片预览都消失 = 已提交回到空上传页
        try:
            if (not page.query_selector(SELECTORS["title_input"])
                    and not page.query_selector(SELECTORS["img_preview"])):
                print("✅ 发布成功（编辑表单已清空复位）")
                return
        except Exception:
            pass
        page.wait_for_timeout(500)
    _die("发布未确认成功：点击发布后未跳离发布页/未见成功提示。" + _diag_after_publish(page))


def _normalize_content(text: str) -> str:
    """小红书编辑器「不支持连续空行输入」——把 2+ 连续空行压成单个空行，行尾空白清掉。"""
    if not text:
        return text
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)      # 行尾空白
    text = re.sub(r"\n{3,}", "\n\n", text)       # 连续空行（3+ 换行）→ 一个空行
    return text.strip("\n")


def _fill_and_submit(page, title, content, tags):
    """标题→正文→话题→长度校验→发布→成功校验。"""
    content = _normalize_content(content)         # 修连续空行导致的发布失败
    title_el = page.query_selector(SELECTORS["title_input"])
    if not title_el:
        _die("未找到标题输入框（检查 SELECTORS.title_input）")
    _human_type(page, title_el, title)
    page.wait_for_timeout(400)

    content_el = _content_element(page)
    if not content_el:
        _die("未找到正文输入框（检查 SELECTORS.content_*）")
    _human_type(page, content_el, content)
    page.wait_for_timeout(500)
    title_el.click()  # REF waitAndClickTitleInput：回点标题增强稳定性
    _input_tags(page, content_el, tags)

    _check_overflow(page)

    kind, btn = _wait_publish_clickable(page, 15)
    btn.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    box = btn.bounding_box()
    if kind == "new" and box:
        # xhs-publish-btn 是宽横条(闭合 Shadow DOM)，内含[暂存离开][发布]两个按钮；
        # 点 host 中心会落在两按钮间隙→无效。发布按钮在右侧约 62% 处（实测像素为品牌红），按坐标点它。
        page.mouse.click(box["x"] + box["width"] * 0.62, box["y"] + box["height"] / 2)
    else:
        try:
            btn.click(force=True)
        except Exception:
            btn.click()
    page.wait_for_timeout(1000)
    _confirm_publish_dialog(page)   # 若弹二次确认框，点确认
    _wait_publish_success(page, 40)


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def _launch(p, headed: bool, base: str | None, proxy: str | None):
    profile = _profile_dir(base)
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(headless=not headed,
                  locale="zh-CN",
                  args=LAUNCH_ARGS)
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    return p.chromium.launch_persistent_context(str(profile), **kwargs)


def cmd_check(_a) -> int:
    ok = True
    try:
        from playwright.sync_api import sync_playwright
        print("✅ playwright 已安装")
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                print(f"✅ chromium 内核：{path}")
            else:
                print("❌ 未安装浏览器内核（playwright install chromium）"); ok = False
    except Exception as e:
        print(f"❌ playwright/内核不可用：{e}"); ok = False
    print(f"登录态目录：{_profile_dir(None)}")
    return 0 if ok else 3


def cmd_login(a) -> int:
    """headless 友好登录：把二维码抠成 PNG 供扫码，轮询登录成功后持久化 cookie。
    REF login.go FetchQrcodeImage/WaitForLogin。远程无桌面环境靠图片扫码，非有头窗口。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)

    qr_out = Path(a.qr_out).expanduser() if a.qr_out else DEFAULT_QR_OUT
    timeout_s = a.timeout or 180
    sf = getattr(a, "status_file", None)
    login_state.write_status(sf, "starting")

    with sync_playwright() as p:
        ctx = _launch(p, headed=a.headed, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(EXPLORE_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(800)

            # 已登录直接返回
            if page.query_selector(SELECTORS["login_ok"]):
                print("✅ 已登录（cookie 已在持久化目录），无需扫码")
                login_state.write_status(sf, "success", "已登录")
                return 0

            # 风险 IP 拦截检测：机房/代理出口常被小红书判为风险，直接拦在登录页之前
            if "website-login/error" in page.url or "安全限制" in (page.title() or ""):
                login_state.write_status(sf, "error", "IP 存在风险，需干净网络/代理")
                _die("小红书判定当前网络为风险 IP（安全限制 300012「IP存在风险，请切换可靠网络环境」）——"
                     "二维码在此环境无法弹出。解决：①用干净/家宽 IP 的代理 `--proxy socks5://...`；"
                     "②在正常网络的机器上 login 拿到登录态，再把持久化目录 "
                     f"{_profile_dir(a.profile_base)} 整个拷到本机复用。", 4)

            # 抠二维码存 PNG（元素截图，不依赖 src 格式，最稳）
            try:
                qr = page.wait_for_selector(SELECTORS["qrcode"], timeout=15000)
            except Exception:
                login_state.write_status(sf, "error", "未找到登录二维码")
                _die("未找到登录二维码（页面结构可能已变，检查 SELECTORS.qrcode），"
                     "或已弹别的登录方式——可加 --headed 观察")
            qr_out.parent.mkdir(parents=True, exist_ok=True)
            qr.screenshot(path=str(qr_out))
            login_state.write_status(sf, "qr_ready", "二维码已就绪，请扫码", qr=str(qr_out))
            print(f"📱 二维码已保存：{qr_out}")
            print(f"   用小红书 App 扫码登录。若走 Easel Web UI，可在 outputs 里查看这张图。")
            print(f"   （二维码有时效，约几分钟；过期请重跑 login）")
            print(f"⏳ 等待扫码确认（最长 {timeout_s}s）...", file=sys.stderr)

            # 轮询登录成功
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                if page.query_selector(SELECTORS["login_ok"]):
                    print("✅ 登录成功，cookie 已持久化，下次免登")
                    login_state.write_status(sf, "success", "登录成功")
                    try:
                        qr_out.unlink()  # 登录成功清掉二维码图，避免误扫过期码
                    except OSError:
                        pass
                    return 0
                page.wait_for_timeout(2000)
            login_state.write_status(sf, "expired", "二维码超时未扫")
            print(f"⏱️ {timeout_s}s 内未检测到登录成功（二维码可能已过期）。请重跑 login 再扫。",
                  file=sys.stderr)
            return 1
        finally:
            ctx.close()


def _plan_lines(kind: str, title: str, content: str, media: list[str], tags: list[str]) -> list[str]:
    tab = "上传图文" if kind == "image" else "上传视频"
    tl = calc_title_length(title) if title else 0
    lines = [
        f"发布类型：{kind}    发布页：{PUBLISH_URL}",
        f"标题：{title}（长度 {tl}/{TITLE_MAX}{'  ⚠️超限' if tl > TITLE_MAX else ''}）",
        f"正文：{content[:40]}{'...' if len(content) > 40 else ''}",
        f"媒体：{media}",
        f"话题：{tags}",
        "步骤：",
        f"  1. goto {PUBLISH_URL} → WaitLoad+DOMStable",
        f"  2. 点 tab「{tab}」（重试+遮挡检测）",
        f"  3. {'逐图上传等预览(≤60s/张)' if kind == 'image' else '上传视频等处理(≤10min)'}",
        "  4. 输标题/正文（逐字符）+ 话题联想点选",
        "  5. 平台 DOM 长度校验",
        "  6. 等发布按钮可点击（新版<xhs-publish-btn>/旧版.bg-red）→ 点击",
        "  7. 成功校验：URL 离开 /publish/publish",
    ]
    return lines


def cmd_plan(a) -> int:
    kind = "video" if a.video else "image"
    media = [str(Path(a.video).expanduser())] if a.video else (
        [s.strip() for s in (a.images or "").split(",") if s.strip()])
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    for ln in _plan_lines(kind, a.title or "<title>", a.content or "<content>", media, tags):
        print(ln)
    return 0


def _publish(a, kind: str) -> int:
    if not a.title:
        _die("--title 必填")
    if calc_title_length(a.title) > TITLE_MAX:
        _die(f"标题过长（{calc_title_length(a.title)}/{TITLE_MAX}），请精简")
    if kind == "image":
        media = _abspaths(a.images)
        if not media:
            _die("--images 至少一张图片")
    else:
        if not a.video:
            _die("--video 必填")
        media = [_abspaths(a.video)[0]]
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]

    # 出站内容安全闸门：真发前扫描标题/正文/话题，检出 API key/内部 URL/代理 IP/模型名/
    # "由 AI 生成" 等内部设置泄露即阻止发布（dry-run 只告警）。--allow-unsafe 手动放行。
    content_guard.guard_or_die([a.title, a.content, " ".join(tags)],
                               exec_mode=bool(a.exec),
                               allow_unsafe=getattr(a, "allow_unsafe", False),
                               label="小红书发布内容")

    if not a.exec:
        print("dry-run（加 --exec 真正发布）：\n")
        for ln in _plan_lines(kind, a.title, a.content or "", media, tags):
            print(ln)
        return 0

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    with sync_playwright() as p:
        ctx = _launch(p, headed=a.headed, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(300000)
        try:
            page.goto(PUBLISH_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if not page.query_selector(SELECTORS["login_ok"]) and "login" in page.url.lower():
                _die("未登录，请先 `login` 扫码")
            if kind == "image":
                _click_publish_tab(page, "上传图文")
                page.wait_for_timeout(1000)
                _upload_images(page, media)
            else:
                _click_publish_tab(page, "上传视频")
                page.wait_for_timeout(1000)
                _upload_video(page, media[0])
            _fill_and_submit(page, a.title, a.content or "", tags)
        except PWTimeout as e:
            _die(f"步骤超时（选择器可能已失效，检查 SELECTORS）：{e}")
        finally:
            if not a.keep_open:
                ctx.close()
    # 发布成功 → 落统一内容日历（对话页自动记录；发布页由 web 设 AUTORECORD=0 跳过防重复）
    try:
        import calendar_ops
        calendar_ops.record_publish("xiaohongshu", a.title,
                                    ptype="视频" if kind == "video" else "图文",
                                    tags=(a.tags or ""), note=(a.content or ""), source="chat")
    except Exception:
        pass
    return 0


def cmd_publish(a) -> int:
    return _publish(a, "image")


def cmd_publish_video(a) -> int:
    return _publish(a, "video")


def cmd_whoami(a) -> int:
    """真校验登录态 + 读账号昵称/头像，输出单行 JSON（供 Web 后端解析）。
    xhs 须直连（--no-proxy），走代理会被判风险。抽不到昵称时 name 空但 loggedIn 仍准。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(json.dumps({"loggedIn": False, "name": "", "avatar": "", "error": f"playwright:{e}"}))
        return 0
    result = {"loggedIn": False, "name": "", "avatar": ""}
    try:
        with sync_playwright() as p:
            ctx = _launch(p, headed=False, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(EXPLORE_URL, wait_until="domcontentloaded")
                try:  # 等登录态元素出现（已登录会很快命中；未登录则短等后判定）
                    page.wait_for_selector(SELECTORS["login_ok"], timeout=4000)
                except Exception:
                    pass
                logged = bool(page.query_selector(SELECTORS["login_ok"]))
                result["loggedIn"] = logged
                if logged:
                    img = page.query_selector('.main-container .user img.reds-img')
                    if img:
                        result["avatar"] = img.get_attribute("src") or ""
                    a_el = page.query_selector('.main-container .user a[href^="/user/profile/"]')
                    href = a_el.get_attribute("href") if a_el else None
                    if href:  # 昵称在个人主页，explore 页只有头像
                        try:
                            page.goto("https://www.xiaohongshu.com" + href,
                                      wait_until="domcontentloaded")
                            try:
                                page.wait_for_selector(".user-name", timeout=4000)
                            except Exception:
                                pass
                            for sel in (".user-name", ".user-nickname",
                                        'div[class*="nickname"]', ".info .name"):
                                el = page.query_selector(sel)
                                if el:
                                    t = (el.inner_text() or "").strip()
                                    if t:
                                        result["name"] = t.splitlines()[0][:40]
                                        break
                        except Exception:
                            pass
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001 — whoami 永远输出 JSON，异常视作未登录
        result["error"] = str(e)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_selftest(_a) -> int:
    print("xhs_publish 自检（离线）...", file=sys.stderr)
    # 标题长度算法（REF title.go）
    assert calc_title_length("") == 0
    assert calc_title_length("abcd") == 2, "4 ASCII → (4+1)//2 = 2"
    assert calc_title_length("你好") == 2, "2 全角 → 4 字节 → 2"
    assert calc_title_length("你" * 20) == 20, "20 全角 → 20（上限）"
    assert calc_title_length("a") == 1
    # 选择器字典完整
    need = ["login_ok", "qrcode", "creator_tab", "upload_input_first", "img_preview",
            "title_input", "content_quill", "topic_item", "publish_btn_new", "publish_btn_old"]
    for k in need:
        assert k in SELECTORS and SELECTORS[k], f"缺选择器 {k}"
    # 路径解析
    try:
        _abspaths("/no/such/file_xyz.jpg")
        raise AssertionError("不存在文件未报错")
    except SystemExit:
        pass
    # profile 目录路由
    assert _profile_dir(None).name == PROFILE_NAME
    # 代理逻辑
    assert _proxy(None, True) is None, "--no-proxy 应禁用"
    assert _proxy("http://x:1", False) == "http://x:1", "显式代理优先"
    # plan 渲染
    lines = _plan_lines("image", "标题", "正文", ["/a.jpg"], ["#tag"])
    assert any("上传图文" in ln for ln in lines) and any("成功校验" in ln for ln in lines)
    lines_v = _plan_lines("video", "t", "c", ["/a.mp4"], [])
    assert any("上传视频" in ln for ln in lines_v)
    print("✅ selftest 通过（标题算法 + 选择器字典 + 路径/代理/路由 + plan 渲染）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="小红书发布（Playwright，headless 可用；流程移植自 xiaohongshu-mcp）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--profile-base", help="登录态根目录（默认 ~/.easel-browser-profiles）")
        p.add_argument("--proxy", help="外网代理（默认取 env，小红书是外网需代理）")
        p.add_argument("--no-proxy", action="store_true", help="禁用代理")

    def add_content(p):
        p.add_argument("--title", help="标题（≤20 全角）")
        p.add_argument("--content", help="正文")
        p.add_argument("--images", help="图片路径，逗号分隔（图文发布）")
        p.add_argument("--video", help="视频路径（视频发布）")
        p.add_argument("--tags", help="话题，逗号分隔（如 'AI,教程'）")
        p.add_argument("--exec", action="store_true", help="真正发布（默认 dry-run）")
        p.add_argument("--allow-unsafe", action="store_true",
                       help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
        p.add_argument("--headed", action="store_true", help="有头模式（首次校验选择器用）")
        p.add_argument("--keep-open", action="store_true", help="发布后不关浏览器")

    sub.add_parser("check", help="检查 playwright/内核").set_defaults(func=cmd_check)

    p = sub.add_parser("login", help="扫码登录并持久化（headless：抠二维码成图片）")
    add_common(p)
    p.add_argument("--qr-out", help=f"二维码图片输出路径（默认 {DEFAULT_QR_OUT}）")
    p.add_argument("--status-file", help="登录状态 JSON 输出路径（供 Web 后端轮询）")
    p.add_argument("--timeout", type=int, help="等待扫码超时秒数（默认 180）")
    p.add_argument("--headed", action="store_true", help="有头模式（本地有桌面时可窗口内扫）")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("plan", help="发布步骤预览（离线）")
    add_content(p)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("publish", help="图文发布")
    add_common(p); add_content(p)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("publish-video", help="视频发布")
    add_common(p); add_content(p)
    p.set_defaults(func=cmd_publish_video)

    p = sub.add_parser("whoami", help="真校验登录态 + 读昵称/头像（输出 JSON）")
    add_common(p)
    p.set_defaults(func=cmd_whoami)

    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
