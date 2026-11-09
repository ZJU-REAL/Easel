#!/usr/bin/env python3
"""toutiao_publish.py — 把图文内容发布到今日头条（头条号后台 mp.toutiao.com）。

用法（CWD=项目根）：
  # 离线自检（不启浏览器）：
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py --selftest

  # 首次登录：打开头条号后台登录页，扫码后 profile 持久化
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py --login

  # 预览（dry-run，不真正发布）：
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --tags "AI,效率"

  # 存草稿 / 真正发布：
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --draft
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" --cover outputs/主题名/cover.png --exec

  # 带正文插图（--images 逗号分隔；正文里独占一行的 ![](路径) 决定插图位置）：
  python skills/builtin/skill-toutiao-publisher/scripts/toutiao_publish.py \
      --input outputs/主题名/article.md --title "文章标题" \
      --images outputs/主题名/fig1.png,outputs/主题名/fig2.png --exec

依赖：playwright + chromium（`pip install playwright && playwright install chromium`）。
登录态持久化在 ~/.easel-browser-profiles/ToutiaoProfile（与其它平台 publisher 同款方案）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# PROJECT_ROOT：优先 EASEL_ROOT env（gateway/CLI/web 注入），否则按 __file__ 上溯。
# ⚠️ 本脚本会被 openclaw/sync.sh 拍平复制到 workspace，那里相对层级会变——故 env 兜底不可省
# （与 zhihu_answer.py / manifest.py 同款）。
PROJECT_ROOT = Path(os.environ.get("EASEL_ROOT") or Path(__file__).resolve().parents[4])
_SHARED_SCRIPTS = PROJECT_ROOT / "skills" / "shared" / "scripts"
if str(_SHARED_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SHARED_SCRIPTS))

import content_guard  # noqa: E402  出站内容安全闸门
import output_paths  # noqa: E402  产物路径规约

PROFILE_DIR = Path.home() / ".easel-browser-profiles" / "ToutiaoProfile"

LOGIN_URL = "https://mp.toutiao.com/auth/page/login"
PUBLISH_URL = "https://mp.toutiao.com/profile_v4/graphic/publish"
HOME_URL = "https://mp.toutiao.com/profile_v4/index"

# 标题上限：头条图文标题 30 字（超限后台会截断/报错），正文无硬限。
TITLE_LIMIT = 30
TAG_LIMIT = 5

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]

# 选择器按"从新到旧"排列，逐个尝试——头条号后台改版频繁，多策略比单点选择器耐改。
TITLE_SELECTORS = [
    "textarea[placeholder*='标题']",
    "input[placeholder*='标题']",
    ".article-title textarea",
    ".title-input textarea",
    "textarea.byte-input__textarea",
]
BODY_SELECTORS = [
    ".ProseMirror",
    "div[contenteditable='true'][data-placeholder]",
    "div.editor-content[contenteditable='true']",
    "#ueditor_0",
]
BODY_IFRAME_SELECTORS = ["iframe[id*='ueditor']", "iframe[class*='editor']"]
SUBMIT_SELECTORS = [
    "button:has-text('预览并发布')",
    "text=预览并发布",
    "button:has-text('发布')",
    "div.publish-btn",
]
# 头条号没有「存草稿」按钮——草稿是自动保存的（真机 2026-10 校准）。

# 正文输入后必须出现的确认态（发布成功页特征），用于判定是否真的发出去了。
SUCCESS_HINTS = ("发布成功", "已发布", "内容管理", "草稿箱")

# 正文里的图片占位符：独占一行的 ![说明](路径)。命中 --images 里的图 → 在该位置插图。
IMAGE_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")

# 编辑器里已插入的图片（用于判断一次上传是否真的落进去了）
EDITOR_IMG_SELECTOR = ".ProseMirror img, div[contenteditable='true'] img, .editor-content img"

# 正文编辑器的「插入图片」入口——头条号是字节 syl-* 组件，工具栏工具的类名带版本前缀，
# 多策略逐个试（和标题/正文选择器同款思路：改版频繁，多路比单点耐改）。
# 第一条是真机校准过的（2026-10）：字节系工具栏的图片工具 class 就是 "image"。
IMAGE_BUTTON_SELECTORS = [
    ".syl-toolbar-tool.image",
    "button:has-text('图片')",
    "[aria-label*='图片']",
    "[title*='图片']",
    "[data-tooltip*='图片']",
    "[class*='toolbar'] [class*='image']",
    "[class*='toolbar'] [class*='pic']",
    "[class*='editor'] [class*='image']",
]
# 图片面板里的「确定」——上传完必须点它，图才会进编辑器（真机踩过：漏这一步图只进素材区）
IMAGE_CONFIRM_SELECTORS = [
    "button:has-text('确定')",
    ".byte-btn:has-text('确定')",
    "text=确定",
]
# 面板里已上传的图片缩略图（用来判断上传是否完成）
UPLOADED_THUMB_SELECTORS = "ul.image-list img, .pic-select-image-item img"
# 封面设置区里的 file input（页面上往往有多个 file input，挑错就传错位置）
COVER_INPUT_SELECTORS = [
    "[class*='cover'] input[type='file']",
    "[class*='Cover'] input[type='file']",
    "[class*='poster'] input[type='file']",
    "[class*='封面'] input[type='file']",
]

# 登录页二维码元素：头条登录走字节 SSO，二维码可能在 <img> / <canvas> / 内嵌组件里，
# 且后台改版频繁——多选择器逐个试，全不中退回整页截图（宁可给大图，也别给空图）。
QR_SELECTORS = [
    "img[src*='qrcode']",
    "img[src*='qr_code']",
    "[class*='qrcode'] img",
    "[class*='qr-code'] img",
    "canvas[class*='qr']",
    "img[src^='data:image']",
]
# URL 命中这些片段 = 还在登录/SSO 流程里（未登录）。
_LOGIN_URL_HINTS = ("login", "signin", "passport", "sso", "auth/page")


def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _resolve(path_str: str) -> Path:
    """相对路径一律挂到 PROJECT_ROOT 下（CLI 从仓库根或别处跑都一致）。"""
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - 环境依赖，selftest 不触发
        die(f"未安装 playwright：{exc}\n→ pip install playwright && playwright install chromium")
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _first_match(page, selectors: list[str], timeout_ms: int = 5000):
    """按顺序尝试选择器，返回第一个可见元素；全不中返回 None。"""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for sel in selectors:
            try:
                locator = page.locator(sel).first
                if locator.count() and locator.is_visible():
                    return locator
            except Exception:
                continue
        page.wait_for_timeout(300)
    return None


def _fill_title(page, title: str, timeout_ms: int) -> bool:
    el = _first_match(page, TITLE_SELECTORS, timeout_ms)
    if not el:
        return False
    el.click()
    el.fill("")
    el.type(title, delay=20)
    return True


def _editor_img_count(page) -> int:
    """编辑器里已插入的图片数（用来判断一次上传是否真的落进正文）。"""
    try:
        return page.locator(EDITOR_IMG_SELECTOR).count()
    except Exception:
        return 0


def _try_set_file_input(page, scope_sel: str, path: Path, timeout_ms: int,
                        before_count: int) -> bool:
    """在 scope_sel 范围内找 file input 塞图，等编辑器里图片数增加。

    set_input_files 对隐藏 input 也能生效（不要求可见），所以弹层里的隐藏 input 照样能用。
    """
    try:
        inputs = page.locator(scope_sel)
        if not inputs.count():
            return False
        inputs.first.set_input_files(str(path))
    except Exception:
        return False
    deadline = time.time() + max(timeout_ms, 8000) / 1000
    while time.time() < deadline:
        if _editor_img_count(page) > before_count:
            page.wait_for_timeout(500)   # 等平台把图传完并插入
            return True
        page.wait_for_timeout(400)
    return False


def _upload_via_panel(page, path: Path, timeout_ms: int, before_count: int) -> bool:
    """图片面板流程（真机 2026-10 校准的头条号图文编辑器）：

      面板已打开 → 给面板里**可见的** file input 塞图 → 平台传自己 CDN，面板出现缩略图
      → 点面板底部「确定」→ 图片才插进编辑器当前光标处。

    漏掉「确定」这一步，图只会停在面板的素材区，编辑器里不会有图——这是真机踩过的坑。
    """
    try:
        inputs = page.locator("input[type=file]:visible")
        if not inputs.count():
            return False
        inputs.first.set_input_files(str(path))
    except Exception:
        return False

    # 等平台把图传完并渲染出缩略图
    deadline = time.time() + max(timeout_ms, 20000) / 1000
    uploaded = False
    while time.time() < deadline:
        try:
            if page.locator(UPLOADED_THUMB_SELECTORS).count() > 0:
                uploaded = True
                break
        except Exception:
            pass
        page.wait_for_timeout(500)
    if not uploaded:
        return False

    confirm = _first_match(page, IMAGE_CONFIRM_SELECTORS, 4000)
    if confirm is None:
        return False
    try:
        confirm.click()
    except Exception:
        return False

    deadline = time.time() + 15
    while time.time() < deadline:
        if _editor_img_count(page) > before_count:
            page.wait_for_timeout(500)   # 等平台把图写进文档
            return True
        page.wait_for_timeout(400)
    return False


def _upload_inline_image(page, path: Path, timeout_ms: int) -> bool:
    """在编辑器当前光标处插入一张图，返回是否成功。

    头条号正文是 ProseMirror 富文本：给 <img src="本地路径"> 会被编辑器清掉，
    必须走编辑器的图片上传控件，让平台自己把图传上 CDN 再写进文档。
    策略从稳到险逐个试，全不中返回 False（调用方据此阻断发布，不静默发成纯文字）。
    """
    before = _editor_img_count(page)

    # 策略 1：编辑器容器里直接挂着 file input 的版本（部分实现如此，不用点工具栏）
    direct = "div[contenteditable='true'] input[type='file']"
    if page.locator(direct).count():
        return _try_set_file_input(page, direct, path, timeout_ms, before)

    # 策略 2：点工具栏「图片」→ 面板上传 → 点「确定」插入
    for btn_sel in IMAGE_BUTTON_SELECTORS:
        btn = _first_match(page, [btn_sel], 1500)
        if btn is None:
            continue
        try:
            btn.click()
        except Exception:
            return False
        page.wait_for_timeout(800)
        return _upload_via_panel(page, path, timeout_ms, before)
    return False


def _fill_body(page, body: str, images: list[Path], timeout_ms: int) -> tuple[bool, list[str]]:
    """正文填入编辑器。

    images 里的图按正文中的 ![]() 占位符原位插入；正文没引用到的，追加到末尾。
    返回 (是否填成功, 插入失败的图路径列表)——有图插失败必须让调用方知道，
    否则会以「以为有图、其实纯文字」的形式发出去。
    """
    pending = {str(p.resolve()): p for p in images}
    failed: list[str] = []

    el = _first_match(page, BODY_SELECTORS, timeout_ms)
    if el is None:
        # 回退：正文编辑器在 iframe 里（老版 ueditor）——只能纯文字，插不了图
        for frame_sel in BODY_IFRAME_SELECTORS:
            try:
                frame_el = page.locator(frame_sel).first
                if not frame_el.count():
                    continue
                frame = frame_el.content_frame
                if frame:
                    frame.locator("body").click()
                    frame.locator("body").type(body, delay=5)
                    return True, [str(p) for p in images]
            except Exception:
                continue
        return False, [str(p) for p in images]

    el.click()
    used: set[str] = set()
    # 富文本编辑器用 insert_text 逐段写入，避免 type() 在长文下过慢。
    for para in [p for p in body.split("\n") if p.strip()]:
        m = IMAGE_LINE_RE.match(para.strip())
        if m:
            key = str(_resolve(m.group(2)).resolve())
            path = pending.get(key)
            if path is not None:
                # 无论成功与否都算「正文引用过」——否则末尾追加会把它再插一遍
                used.add(key)
                if not _upload_inline_image(page, path, timeout_ms):
                    failed.append(str(path))
                page.keyboard.press("Enter")
                continue
        page.keyboard.insert_text(para)
        page.keyboard.press("Enter")

    # 正文没引用到的图：追加到末尾（头条会自动取正文首图作封面）
    for key, path in pending.items():
        if key in used:
            continue
        if not _upload_inline_image(page, path, timeout_ms):
            failed.append(str(path))
        page.keyboard.press("Enter")

    return True, failed


def _pick_cover_input(page):
    """挑封面用的 file input。

    页面上往往有多个 file input（正文插图一个、封面一个），用 inputs.first 会挑错。
    优先封面区域内的；没有就挑编辑器容器之外的那个。
    """
    for sel in COVER_INPUT_SELECTORS:
        try:
            loc = page.locator(sel)
            if loc.count():
                return loc.first
        except Exception:
            continue
    try:
        loc = page.locator("input[type='file']")
        n = loc.count()
        for i in range(n):
            el = loc.nth(i)
            try:
                inside = el.evaluate(
                    "e => !!e.closest(\"div[contenteditable='true'], .ProseMirror, .editor-content\")")
            except Exception:
                inside = False
            if not inside:
                return el
        return loc.first if n else None
    except Exception:
        return None


def _upload_cover(page, cover: Path) -> bool:
    """封面走页面里的 file input（头条号封面弹窗内），失败只告警不阻断。"""
    if not cover.is_file():
        return False
    try:
        el = _pick_cover_input(page)
        if el is None:
            return False
        el.set_input_files(str(cover))
        page.wait_for_timeout(1500)
        return True
    except Exception:
        return False


def _wait_autosave(page, timeout_ms: int) -> bool:
    """等头条号的草稿自动保存提示出现（页面底部「草稿保存中...」）。

    真机 2026-10 校准：头条号不显示「已保存」，只有「草稿保存中...」这一个指示器
    （偶发短暂出现「保存失败」后又重试成功）。所以这里只能确认「平台在存草稿」，
    无法在页面层确认落库结果——真要确认得去草稿箱看。
    """
    deadline = time.time() + max(timeout_ms, 20000) / 1000
    while time.time() < deadline:
        try:
            txt = page.inner_text("body")
        except Exception:
            txt = ""
        if "草稿已保存" in txt:
            page.wait_for_timeout(3000)   # 让这一轮保存落库
            return True
        page.wait_for_timeout(500)
    return False


def _click_submit(page) -> bool:
    """点「预览并发布」并处理二次确认弹窗。"""
    btn = _first_match(page, SUBMIT_SELECTORS, 8000)
    if not btn:
        return False
    btn.click()
    page.wait_for_timeout(2500)
    # 发布确认弹窗（"确认发布"二次确认）
    for label in ("确认发布", "确定", "确认"):
        try:
            confirm = page.locator(f"button:has-text('{label}')").first
            if confirm.count() and confirm.is_visible():
                confirm.click()
                page.wait_for_timeout(2500)
                break
        except Exception:
            raise  # A confirmation click may have reached the server; never retry it.
    return True


def _write_receipt(url: str, status: int, payload: object) -> dict | None:
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme != 'https' or parsed.hostname != 'mp.toutiao.com' or '/article/' not in parsed.path:
        return None
    operation = parsed.path.rstrip('/').split('/')[-1]
    if operation in {'publish', 'submit', 'publish_article', 'publish_article_post'}:
        mode = 'publish'
    elif operation in {'save', 'save_article', 'save_draft', 'edit_article_post'}:
        mode = 'draft'
    else:
        return None
    if not 200 <= status < 300 or not isinstance(payload, dict):
        return {'mode': mode, 'outcome': 'unknown'}
    codes = [payload[k] for k in ('code', 'err_no', 'errno', 'errcode') if k in payload]
    if codes and any(type(code) is not int or code != 0 for code in codes):
        return {'mode': mode, 'outcome': 'rejected'}
    if not codes and payload.get('message') != 'success' and payload.get('success') is not True:
        return {'mode': mode, 'outcome': 'unknown'}
    data = payload.get('data', {})
    if not isinstance(data, dict):
        return {'mode': mode, 'outcome': 'unknown'}
    identifier = next((data[k] for k in ('article_id', 'pgc_id', 'draft_id', 'id') if data.get(k)), None)
    if type(identifier) not in (str, int) or not re.fullmatch(r'[0-9]{1,32}', str(identifier)) or int(identifier) <= 0:
        return {'mode': mode, 'outcome': 'unknown'}
    return {'mode': mode, 'outcome': 'accepted', 'id': str(identifier)}


def _observe_receipts(page, mode: str) -> dict:
    receipt = {'mode': mode, 'active': False, 'outcome': 'unknown'}
    def receive(response):
        if not receipt['active'] or receipt['outcome'] == 'accepted':
            return
        try:
            if response.request.method != 'POST':
                return
            started = response.request.timing.get('startTime', -1)
            if started < receipt.get('after', 0):
                return
            result = _write_receipt(response.url, response.status, response.json())
            if result is not None and result['mode'] == mode:
                receipt.update(result)
        except Exception:
            pass
    page.on('response', receive)
    return receipt


def _wait_receipt(page, receipt: dict, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while receipt['outcome'] == 'unknown' and time.monotonic() < deadline:
        page.wait_for_timeout(250)
    return receipt['outcome'] == 'accepted'


def _open_browser(pw, headed: bool):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=not headed, args=LAUNCH_ARGS,
        viewport={"width": 1440, "height": 900},
    )
    return ctx, ctx.pages[0] if ctx.pages else ctx.new_page()


def login(wait_seconds: int, headed: bool = True) -> int:
    """打开登录页等扫码，登录态写入 PROFILE_DIR。"""
    sync_playwright = _require_playwright()
    with sync_playwright() as pw:
        ctx, page = _open_browser(pw, headed)
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        print(f"请在弹出的浏览器里扫码登录头条号（{wait_seconds}s 内）…", file=sys.stderr)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if _backend_authenticated(page):
                ctx.close()
                print(f"登录成功，profile 已保存到 {PROFILE_DIR}", file=sys.stderr)
                return 0
            page.wait_for_timeout(2000)
        ctx.close()
    die("登录超时：未检测到登录态，请重跑 --login")


# ---- Web 工作台驱动用的两个子命令（login / whoami） ----
# 与 xhs_publish.py / douyin_publish.py 同款约定：Web 后端不直接管浏览器，
# 只读 login_state 协议文件（轮询进度）和 stdout 的单行 JSON（校验结果）。

def _login_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="toutiao_publish.py login",
                                description="扫码登录头条号（Web 端驱动，可见窗口完成手机绑定）")
    p.add_argument("--qr-out", help="二维码截图落盘路径（默认 outputs/_login/toutiao.png）")
    p.add_argument("--status-file", help="登录状态 JSON（默认 outputs/_login/toutiao.json）")
    p.add_argument("--timeout", type=int, default=180, help="等待扫码秒数")
    p.add_argument("--headed", action="store_true", help="有头浏览器（本机调试）")
    return p


def _whoami_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="toutiao_publish.py whoami",
                                description="校验头条号登录态，stdout 输出一行 JSON")
    p.add_argument("--headed", action="store_true", help="有头浏览器（本机调试）")
    return p


def _is_logged_in(page) -> bool:
    """确认已离开登录流程，且没有停在手机号绑定页。

    优先用 URL 而不是元素选择器：未登录时头条号后台会重定向到登录页，
    但扫码后的手机号绑定页也可能位于头条域名，不能把它算作已登录。
    """
    try:
        parsed = urlparse(page.url or "")
    except ValueError:
        return False
    return (parsed.scheme == "https" and parsed.hostname == "mp.toutiao.com"
            and not any(h in parsed.path.lower() for h in _LOGIN_URL_HINTS)
            and not _needs_phone_binding(page))


def _needs_phone_binding(page) -> bool:
    """识别扫码后的平台手机号绑定页；不读取或保存手机号/验证码。"""
    for frame in [page, *getattr(page, "frames", [])]:
        try:
            title = frame.get_by_text("手机绑定", exact=True).first
            phone = frame.locator("input[placeholder*='手机']").first
            if title.is_visible() and phone.is_visible():
                return True
        except Exception:
            continue
    return False


def _backend_authenticated(page) -> bool:
    """离开扫码页后重进创作者后台，避免中途跳转被误判为登录成功。"""
    if not _is_logged_in(page):
        return False
    try:
        response = page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        if response is None or not 200 <= response.status < 300:
            return False
        page.wait_for_timeout(2500)
    except Exception:
        return False
    return (_is_logged_in(page)
            and urlparse(page.url).path.rstrip('/') == urlparse(HOME_URL).path.rstrip('/'))


def _capture_qr(page, qr_out: Path) -> bool:
    """把登录二维码截到 qr_out。多选择器逐个试（最多 15s），全不中退回整页截图。"""
    deadline = time.time() + 15
    while time.time() < deadline:
        if _needs_phone_binding(page):
            return False
        for sel in QR_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.count() and el.is_visible():
                    el.screenshot(path=str(qr_out))
                    if qr_out.is_file() and qr_out.stat().st_size > 500:
                        return True
            except Exception:
                continue
        page.wait_for_timeout(500)
    try:
        if _needs_phone_binding(page):
            return False
        page.screenshot(path=str(qr_out))
        return qr_out.is_file()
    except Exception:
        return False


def _qr_login(profile: Path, qr_out: Path, status_file: Path, timeout_s: int,
              headed: bool = False) -> int:
    """扫码登录：二维码落盘；可见窗口支持手机绑定，状态供 Web 轮询。"""
    import login_state

    try:
        sync_playwright = _require_playwright()
    except SystemExit:
        login_state.write_status(str(status_file), "error", "未安装 playwright")
        raise

    profile.mkdir(parents=True, exist_ok=True)
    qr_out.parent.mkdir(parents=True, exist_ok=True)
    login_state.write_status(str(status_file), "starting", "启动浏览器…")
    with sync_playwright() as pw:
        ctx = None
        try:
            ctx = pw.chromium.launch_persistent_context(
                str(profile), headless=not headed, locale="zh-CN", args=LAUNCH_ARGS,
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if _backend_authenticated(page):
                ctx.close()
                ctx = None
                login_state.write_status(str(status_file), "success", "已登录")
                print("✅ 今日头条 已登录（登录态在持久化目录）")
                return 0
            binding = _needs_phone_binding(page)
            captured = False if binding else _capture_qr(page, qr_out)
            binding = binding or _needs_phone_binding(page)
            if binding:
                qr_out.unlink(missing_ok=True)
                if not headed:
                    login_state.write_status(str(status_file), "error",
                                             "头条号要求绑定手机号；请用有头浏览器重新登录")
                    return 1
                login_state.write_status(str(status_file), "window_login",
                                         "请在弹出的今日头条窗口绑定手机号并输入短信验证码")
            else:
                if not captured:
                    login_state.write_status(str(status_file), "error",
                                             "未找到登录二维码（头条号后台可能已改版）")
                    return 1
                login_state.write_status(str(status_file), "qr_ready",
                                         "二维码已就绪，请扫码；后续验证请在浏览器窗口完成",
                                         qr=str(qr_out))
                print(f"📱 二维码已保存：{qr_out}")
            deadline = time.time() + max(timeout_s, 30)
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                if _needs_phone_binding(page):
                    if not headed:
                        qr_out.unlink(missing_ok=True)
                        login_state.write_status(str(status_file), "error",
                                                 "头条号要求绑定手机号；请用有头浏览器重新登录")
                        return 1
                    if not binding:
                        binding = True
                        try:
                            qr_out.unlink()
                        except OSError:
                            pass
                        login_state.write_status(str(status_file), "window_login",
                                                 "扫码已确认；请在弹出的今日头条窗口绑定手机号并输入短信验证码")
                    continue
                if _backend_authenticated(page):
                    ctx.close()
                    ctx = None
                    login_state.write_status(str(status_file), "success", "登录成功")
                    try:
                        qr_out.unlink()  # 成功后清掉二维码图，避免误扫过期码
                    except OSError:
                        pass
                    print("✅ 登录成功")
                    return 0
            login_state.write_status(str(status_file), "expired",
                                     "手机绑定未完成，请重新登录" if binding else "二维码超时未扫")
            return 1
        except Exception as exc:
            # 浏览器起不来（内核没装 / profile 被占用）也必须把状态写成 error：
            # 真机踩到过——launch 抛异常时状态文件卡在 starting，前端只能等进程退出才兜出失败。
            login_state.write_status(str(status_file), "error", f"登录失败：{exc}")
            return 1
        finally:
            if ctx is not None:
                ctx.close()


def _probe_identity(headed: bool = False) -> dict:
    """打开头条号后台判定登录态。返回 {loggedIn, name, avatar}；失败附 error 字段。

    error 字段是给 Web 端判定的：有它 = 校验本身没跑成（不是可信的「未登录」），
    web/app.py 据此不写缓存、不把卡片翻成未登录。
    """
    out: dict = {"loggedIn": False, "name": "", "avatar": ""}
    try:
        sync_playwright = _require_playwright()
    except SystemExit:
        out["error"] = "未安装 playwright"
        return out
    try:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), headless=not headed, locale="zh-CN", args=LAUNCH_ARGS,
                viewport={"width": 1440, "height": 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                response = page.goto(HOME_URL, wait_until="domcontentloaded", timeout=45000)
                if response is None or not 200 <= response.status < 300:
                    raise RuntimeError("头条号后台加载失败，未确认登录状态")
                page.wait_for_timeout(2500)
                out["loggedIn"] = _is_logged_in(page)
                if out["loggedIn"]:
                    out["name"] = _read_display_name(page)
            finally:
                ctx.close()
    except Exception as exc:
        out["error"] = f"校验失败：{exc}"
    return out


def _read_display_name(page) -> str:
    """尽力读头条号昵称；读不到返回空串（不阻断 whoami）。"""
    for sel in ("[class*='user-name']", "[class*='userName']", "[class*='nickname']",
                "[class*='user-info'] span", "[class*='avatar'] + *"):
        try:
            el = page.locator(sel).first
            if el.count() and el.is_visible():
                text = (el.inner_text() or "").strip()
                if text:
                    return text[:40]
        except Exception:
            continue
    return ""


def cmd_login(argv: list[str]) -> int:
    args = _login_parser().parse_args(argv)
    root = PROJECT_ROOT / "outputs" / "_login"
    qr_out = _resolve(args.qr_out) if args.qr_out else (root / "toutiao.png")
    status_file = (Path(args.status_file).expanduser() if args.status_file
                   else (root / "toutiao.json"))
    return _qr_login(PROFILE_DIR, qr_out, status_file, args.timeout, headed=args.headed)


def cmd_whoami(argv: list[str]) -> int:
    args = _whoami_parser().parse_args(argv)
    print(json.dumps(_probe_identity(headed=args.headed), ensure_ascii=False))
    return 0


def publish_article(content: str, title: str, tags: list[str], cover: Path | None,
                    images: list[Path], dry_run: bool, headed: bool, as_draft: bool,
                    timeout_ms: int) -> dict:
    """把图文发到头条号。dry_run=True 时只返回离线计划，不打开浏览器或创建远程草稿。"""
    result: dict = {"platform": "toutiao", "dry_run": dry_run, "draft": as_draft,
                    "title": title, "tags": tags,
                    "cover": str(cover) if cover else "",
                    "images": [str(p) for p in images], "steps": {}}
    result['published'] = False
    if dry_run:
        result['note'] = 'dry-run：仅预览计划，不打开浏览器，不创建远程草稿。'
        return result
    sync_playwright = _require_playwright()
    with sync_playwright() as pw:
        ctx, page = _open_browser(pw, headed)
        try:
            receipt = _observe_receipts(page, 'draft' if as_draft else 'publish')
            page.goto(PUBLISH_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            if "login" in page.url or "auth" in page.url:
                result["error"] = "未登录头条号：先跑 --login 扫码"
                return result

            result["steps"]["title"] = _fill_title(page, title, timeout_ms)
            body_ok, failed_images = _fill_body(page, content, images, timeout_ms)
            result["steps"]["body"] = body_ok
            # 话题先于封面：封面上传会抢走焦点，话题要在编辑器里打
            if tags:
                result["steps"]["tags"] = _fill_tags(page, tags, timeout_ms)
            if cover:
                result["steps"]["cover"] = _upload_cover(page, cover)

            if not result["steps"]["title"] or not result["steps"]["body"]:
                result["error"] = "编辑器定位失败（标题或正文），头条号后台可能已改版——见 references/publish-flow.md"
                return result

            # 插图失败要拦住：否则会以「以为有图、其实纯文字」的形式发出去
            if failed_images:
                result["error"] = ("以下图片未能插入编辑器（头条号后台可能已改版，"
                                   "或图片格式不被接受）：\n  " + "\n  ".join(failed_images))
                return result
            result["steps"]["images"] = True

            receipt['after'] = time.time() * 1000
            receipt['active'] = True

            if as_draft:
                # 头条号没有「存草稿」按钮——草稿是自动保存的（真机 2026-10 校准：
                # 页面上只有 预览 / 定时发布 / 预览并发布，草稿提示是「草稿将自动保存」）。
                # 所以「存草稿」= 填完内容就停，等平台自动保存，绝不点「预览并发布」。
                saved = _wait_receipt(page, receipt, timeout_ms)
                result["steps"]["draft"] = saved
                result['draft_saved'] = saved
                result["published"] = False
                result["url"] = page.url
                if not saved:
                    result["error"] = "草稿保存结果未核实，请到草稿箱核对，先别重复创建。"
                else:
                    result["note"] = "已核实平台接受草稿保存，未公开发布。"
                return result

            try:
                submitted = _click_submit(page)
            except Exception:
                result['error'] = '提交结果未知，请到平台后台核对，先别重发。'
                return result
            if not submitted:
                result["error"] = "未找到「预览并发布」按钮"
                return result
            result["published"] = _wait_receipt(page, receipt, timeout_ms)
            if not result['published']:
                result['error'] = '发布结果未核实，请到平台后台核对，先别重发。'
            else:
                result['article_id'] = receipt['id']
            result["url"] = page.url
        finally:
            ctx.close()
    return result


def _insert_topic(page, tag: str, timeout_ms: int) -> bool:
    """在编辑器里插入一个话题节点。

    头条图文编辑器没有独立的话题输入框——话题是在正文里打「#话题名」，然后从联想列表里
    选一下才会变成真话题节点（<a class="tteditor-forum">）。真机 2026-10 校准：
    联想项的类名是 .forum-list-item-text，文本与话题名完全一致时才点。
    联想没出现（平台上没有这个话题）就把刚打进去的「#话题」撤掉，别在正文留半截井号。
    """
    before = page.locator(".ProseMirror a.tteditor-forum").count()
    # 真机 2026-10 校准：必须先打「#」等联想面板出来，再打话题名——一次性插「#话题」
    # 不会唤起联想（真机实测：一次性插 → 无联想项；分步插 → 有）。
    page.keyboard.insert_text("#")
    page.wait_for_timeout(1200)
    page.keyboard.insert_text(tag)
    deadline = time.time() + max(timeout_ms, 8000) / 1000
    while time.time() < deadline:
        hit = page.evaluate(
            """(tag) => {
                const els = Array.from(document.querySelectorAll('.forum-list-item-text'))
                    .filter(e => (e.innerText || '').trim() === tag && (e.offsetWidth || e.offsetHeight));
                if (!els.length) return false;
                els[0].click();
                return true;
            }""", tag)
        if hit:
            page.wait_for_timeout(500)
            if page.locator(".ProseMirror a.tteditor-forum").count() > before:
                return True
        page.wait_for_timeout(300)
    for _ in range(len(tag) + 2):   # 撤掉没匹配上的「#话题」
        page.keyboard.press("Backspace")
    return False


def _fill_tags(page, tags: list[str], timeout_ms: int) -> bool:
    """话题绑定。

    先找话题/标签输入框（部分版本有）；头条图文没有独立输入框（真机 2026-10 校准），
    退回编辑器内「#话题 → 联想 → 点选」。找不到/匹配不上就跳过，不阻断发布。
    """
    el = _first_match(page, ["input[placeholder*='话题']", "input[placeholder*='标签']"], 2000)
    if el is not None:
        el.click()
        for tag in tags[:TAG_LIMIT]:
            el.type(tag, delay=30)
            page.wait_for_timeout(600)
            page.keyboard.press("Enter")
        return True

    # 编辑器内 # 联想——光标得在正文里（封面上传会抢焦点，故话题先于封面处理）
    try:
        page.locator(".ProseMirror").first.click()
        page.keyboard.press("Control+End")
    except Exception:
        pass
    ok = 0
    for tag in tags[:TAG_LIMIT]:
        if not _insert_topic(page, tag, timeout_ms):
            break
        ok += 1
    return ok > 0


def _write_record(result: dict) -> Path:
    """发布留痕写 outputs/_publish/（系统目录，需 allow_system）。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = output_paths.validate_output_path(
        f"outputs/_publish/toutiao_{stamp}.json", allow_system=True, create_parent=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def _selftest() -> int:
    """轻量自测（不启浏览器）：校验选择器常量、标题上限与路径解析。"""
    assert TITLE_LIMIT == 30, "头条图文标题上限应为 30 字"
    assert TITLE_SELECTORS and BODY_SELECTORS and SUBMIT_SELECTORS, "选择器表不应为空"
    assert "--disable-blink-features=AutomationControlled" in LAUNCH_ARGS, "反检测参数缺失"
    assert PUBLISH_URL.startswith("https://mp.toutiao.com/"), "发布地址应为头条号后台"
    # 插图相关：图片按钮选择器 + 正文占位符解析
    assert IMAGE_BUTTON_SELECTORS and IMAGE_CONFIRM_SELECTORS, "插图选择器表不应为空"
    assert IMAGE_LINE_RE.match("![](outputs/x/a.png)"), "图片占位符正则应能匹配 ![]()"
    assert not IMAGE_LINE_RE.match("普通段落"), "图片占位符正则不该匹配普通文字"
    # 相对路径必须挂到 PROJECT_ROOT，且产物只能落 outputs/<主题> 或注册系统目录
    assert _resolve("outputs/x/a.md") == PROJECT_ROOT / "outputs/x/a.md"
    assert _resolve(str(Path.home())).is_absolute()
    try:
        output_paths.validate_output_path("outputs/toutiao-app-upgrade/note.md")
        ok = True
    except output_paths.OutputPathError:
        ok = False
    assert ok, "outputs/<主题>/ 下的产物路径应被接受"
    try:
        output_paths.validate_output_path("outputs/_publish/toutiao.json", allow_system=True)
        ok = True
    except output_paths.OutputPathError:
        ok = False
    assert ok, "outputs/_publish/ 应被接受为注册系统目录"
    # 出站闸门在 dry-run 下不拦、只告警
    content_guard.guard_or_die(["正常正文，无敏感信息"], exec_mode=False, label="自检")
    try:
        import playwright  # noqa: F401
        pw_state = "yes"
    except Exception:
        pw_state = "MISSING（需 pip install playwright && playwright install chromium）"
    print(f"toutiao_publish.py selftest: OK (playwright={pw_state})")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Web 工作台驱动用的子命令。这里手动分发而不是用 argparse 的 subparsers，
    # 是为了让原有 flag 用法（SKILL.md / DEVELOPMENT.md / 单测都在用）一字不变。
    if args_list and args_list[0] == "login":
        return cmd_login(args_list[1:])
    if args_list and args_list[0] == "whoami":
        return cmd_whoami(args_list[1:])

    if "--selftest" in args_list:
        return _selftest()

    parser = argparse.ArgumentParser(description="今日头条（头条号）图文发布工具")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    parser.add_argument("--login", action="store_true", help="打开登录页等扫码，持久化登录态")
    parser.add_argument("--login-wait", type=int, default=180, help="扫码等待秒数（默认 180）")
    parser.add_argument("--input", help="正文 Markdown/文本文件路径")
    parser.add_argument("--content", help="正文文本（Web 端直传，与 --input 二选一）")
    parser.add_argument("--title", help="文章标题（≤30 字）")
    parser.add_argument("--cover", help="封面图路径（可选，头条可自动选正文首图）")
    parser.add_argument("--images", default="",
                        help="正文插图路径，逗号分隔。正文里写成独占一行的 ![](路径) 则原位插入，"
                             "没写占位的追加到正文末尾")
    parser.add_argument("--tags", default="", help="话题标签，逗号分隔（≤5 个）")
    parser.add_argument("--draft", action="store_true", help="存草稿而不是直接发布")
    parser.add_argument("--exec", action="store_true", dest="execute",
                        help="真正发布（默认 dry-run，只填编辑器）")
    parser.add_argument("--allow-unsafe", action="store_true",
                        help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    parser.add_argument("--headed", action="store_true", help="有头浏览器模式（调试用）")
    parser.add_argument("--timeout", type=int, default=15000, help="编辑器元素等待毫秒数")
    args = parser.parse_args(args_list)

    if args.login:
        return login(args.login_wait, headed=True)

    if args.input and args.content:
        parser.error("--input 与 --content 只能给一个")
    if not args.title or not (args.input or args.content):
        parser.error("发布需要 --title 加 --input 或 --content"
                     "（或用 login / whoami / --login / --selftest）")

    if args.content:
        content = args.content.strip()
        source = "--content"
    else:
        src = _resolve(args.input)
        if not src.is_file():
            die(f"内容文件不存在：{src}")
        content = src.read_text(encoding="utf-8").strip()
        source = str(src)
    if not content:
        die("内容为空")

    title = args.title.strip()
    if len(title) > TITLE_LIMIT:
        die(f"标题 {len(title)} 字超过头条图文上限 {TITLE_LIMIT} 字，请精简后再发")
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    cover = _resolve(args.cover) if args.cover else None
    if cover and not cover.is_file():
        die(f"封面图不存在：{cover}")
    images: list[Path] = []
    for raw in args.images.split(","):
        raw = raw.strip()
        if not raw:
            continue
        p = _resolve(raw)
        if not p.is_file():
            die(f"插图不存在：{p}")
        images.append(p)

    if args.draft and args.execute:
        parser.error('--draft 与 --exec 不能同时使用')
    if len(tags) > TAG_LIMIT:
        die(f'话题不能超过 {TAG_LIMIT} 个')
    dry_run = not (args.execute or args.draft)
    # 出站内容安全闸门：真发前扫描标题/正文/话题，检出内部设置泄露即阻止发布（dry-run 只告警）。
    content_guard.guard_or_die([title, content, *tags], exec_mode=not dry_run,
                               allow_unsafe=args.allow_unsafe, label="今日头条图文")

    print(f"[{'DRY-RUN' if dry_run else 'EXEC'}] 今日头条图文发布", file=sys.stderr)
    print(f"  标题: {title}（{len(title)} 字）", file=sys.stderr)
    print(f"  正文: {source}（{len(content)} 字）· 话题 {len(tags)} 个"
          f"{' · 插图 ' + str(len(images)) + ' 张' if images else ''}"
          f"{' · 存草稿' if args.draft else ''}", file=sys.stderr)

    result = publish_article(content, title, tags, cover, images, dry_run,
                             args.headed, args.draft, args.timeout)
    if result.get("error"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        die(result["error"])
    if not dry_run and not (result.get('draft_saved') is True if args.draft else result.get('published') is True):
        die('操作结果未核实，请到平台后台核对，先别重试。', 5)
    record = _write_record(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"留痕: {record}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
