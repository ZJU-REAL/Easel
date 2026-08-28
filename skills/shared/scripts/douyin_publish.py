#!/usr/bin/env python3
"""douyin_publish.py — 抖音发布（Playwright，headless 可用）.

替代旧的 CDP/puppeteer/MCP Node 死栈（那套需真实 Chrome + MCP，本 Linux 环境跑不了）。
用 Playwright + 持久化登录态，headless 即可发布；创作者平台流程与选择器移植自
WJZ-P/douyin-upload-mcp-skill（src/douyin-ops.js）。确定性 IO 在脚本，文案/策略交给上层。

移植的关键流程（REF = douyin-ops.js）：
  - 首页点「高清发布」→ 等 URL 进 content/upload
  - 切 tab（发布视频/发布图文）→ 隐藏 file input 塞文件
  - 视频等 uploading-container 消失（≤5min）→ 等 AI 封面（≤60s）选推荐封面
  - 标题 input[placeholder*=作品标题]；简介 slate contenteditable（Ctrl+A 清空再输）
  - 发布按钮在 card-container-creator-layout 内文本「发布」→ toast 校验「发布成功」
  - 登录：img[aria-label=二维码] 抠图轮询；命中短信验证给提示

子命令: check / login / plan / publish / publish-video / selftest
真实发布需：playwright + chromium + 已扫码登录 + 外网可达（默认走项目代理）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import login_state  # noqa: E402
import content_guard  # noqa: E402  出站内容安全闸门

HOME_URL = "https://creator.douyin.com/"
TITLE_MAX = 30  # 抖音作品标题上限（字符）

# 选择器集中维护（抖音改版单点更新）。REF = _ref-douyin/src/douyin-ops.js SELECTORS。
SELECTORS = {
    "hd_publish": 'button[class*="douyin-creator-master-button"], #douyin-creator-master-side-upload-wrap button',
    "qrcode": 'img[class*="qr"], [class*="qrcode"] img, [class*="qrcode"] canvas, img[aria-label="二维码"]',
    "qr_box": '[class*="qrcode"]',
    "qr_loaded": '[class*="qrcode"] img[src^="data:image"], [class*="qrcode"] img[src*="qr"], img[class*="qr"], img[aria-label="二维码"]',
    "qr_tab": '扫码登录',
    "sms_verify": 'div[class*="uc_verification_component"]',
    # 短信验证码墙（扫码后风控触发）。真实 DOM 未知，用多候选防御式选择器；
    # 首次命中会 dump 真实 DOM 到 outputs/_login/douyin_sms_dom.html 供后续校准。
    "sms_send": ('button:has-text("获取验证码"), button:has-text("发送验证码"), '
                 'button:has-text("重新发送"), a:has-text("获取验证码"), '
                 'span:has-text("获取验证码"), div[class*="uc_verification_component"] button'),
    "sms_input": ('div[class*="uc_verification_component"] input, '
                  'input[placeholder*="验证码"], input[maxlength="6"][type="tel"], '
                  'input[maxlength="6"], input[type="tel"]'),
    "sms_submit": ('div[class*="uc_verification_component"] button:has-text("登录"), '
                   'div[class*="uc_verification_component"] button:has-text("确定"), '
                   'div[class*="uc_verification_component"] button:has-text("验证"), '
                   'div[class*="uc_verification_component"] button:has-text("提交"), '
                   'button:has-text("验证并登录")'),
    "sms_phone": 'div[class*="uc_verification_component"]',
    "avatar": '[class*="avatar"]',
    "tab_video": 'div[class*="tab-item"]:has-text("发布视频")',
    "tab_imagetext": 'div[class*="tab-item"]:has-text("发布图文")',
    "file_input": 'div[class*="drag-upload"] input[type="file"]',
    "file_input_fallback": 'input[type="file"]',
    "uploading": '[class*="uploading-container"]',
    "cover_title": 'span[class*="recommendTitle"]',
    "cover_first": 'div[class*="recommendCoverContainer"] > div:first-child',
    "cover_confirm": 'div.semi-modal-footer button.semi-button-primary',
    "title_input": 'input[placeholder*="作品标题"]',
    "desc_input": 'div[data-placeholder*="作品简介"][contenteditable="true"], div.editor-kit-container[contenteditable="true"]',
    "publish_container": 'div[class*="card-container-creator-layout"]',
    "toast": 'span[class*="semi-toast-content-text"]',
}
PROFILE_NAME = "DouyinProfile"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QR_OUT = PROJECT_ROOT / "outputs" / "_login" / "douyin.png"

# 短信验证墙的多步流程选择器（跨引擎，逐个 query_selector 尝试；真机首次跑后据 dump 校准）。
# 扫码后先出「验证方式选择屏」→ 选「接收短信验证码」进发码屏 → 点「获取验证码」下发短信。
SMS_RECEIVE_OPTS = ("text=接收短信验证码", "div:has-text('接收短信验证码')",
                    "text=短信验证码", "span:has-text('接收短信')")
SMS_SEND_OPTS = ("button:has-text('获取验证码')", "text=获取验证码",
                 "button:has-text('发送验证码')", "text=重新发送验证码", "text=重新发送")
# 提交后判「码错/过期」的文案（命中即回退到 sms_required 让用户重输，而非直接失败退出）。
SMS_ERROR_TEXTS = ("验证码错误", "验证码填写错误", "验证码输入错误", "验证码不正确",
                   "验证码已过期", "验证码过期", "请重新获取", "请重新发送",
                   "验证失败", "输入错误", "已失效")
# 短信验证弹窗容器（semi 设计体系）——关键：页面上背景登录表单也有「请输入验证码」框，
# 必须把找输入框/按钮/手机号/错误文案都**限定在这个弹窗内**，否则 query_selector 会取到
# DOM 顺序在前的背景框，导致码打进没用的框、弹窗框空着（真机实测的坑，见截图）。
SMS_MODAL_SELS = ("[class*='semi-modal-content']", "[class*='semi-modal']",
                  "div[role='dialog']", "[class*='modal-content']", "[class*='dialog']")
# 判「真正出现了身份验证/短信墙」的文案——**只认弹窗里的这些词**，不认背景『验证码登录』表单
# （它也有验证码框但不是风控墙）。没命中=不需要短信验证，别硬跳短信流程（实事求是）。
WALL_KEYWORDS = ("身份验证", "接收短信", "短信验证", "验证方式", "短信已发送",
                 "验证码已发送", "获取验证码", "验证并登录", "手机刷脸")

# Chromium 启动性能参数（提速冷启动；勿禁用图片——二维码是图片）
# 注意：**不加** --disable-dev-shm-usage——本机 /dev/shm 有 360G，禁用会让 Chromium 把共享内存
# 写到 overlay /tmp，发布页这类重页面下会触发渲染进程崩溃（"Page crashed"，真机实测）。
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-gpu", "--disable-software-rasterizer",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--disable-features=TranslateUI,BackForwardCache",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _abspaths(csv: str | None) -> list[str]:
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
    if disable:
        return None
    if explicit:
        return explicit
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") \
        or os.environ.get("EASEL_PROXY")


def _launch(p, headed: bool, base: str | None, proxy: str | None):
    profile = _profile_dir(base)
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(headless=not headed, locale="zh-CN", args=LAUNCH_ARGS)
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    return p.chromium.launch_persistent_context(str(profile), **kwargs)


def _logged_in(page) -> bool:
    """已登录：无二维码 且 首页有「高清发布」按钮。REF checkLogin phase=logged_in。
    对**导航中**的 "execution context was destroyed" 等瞬时错误容错重试——登录成功那刻页面
    正跳转，裸 query 会抛异常导致 runner 崩溃、状态卡在 verifying（真机实测的坑）。"""
    for _ in range(3):
        try:
            if page.query_selector(SELECTORS["qrcode"]):
                return False
            return bool(page.query_selector(SELECTORS["hd_publish"]))
        except Exception:
            try:
                page.wait_for_timeout(500)
            except Exception:
                return False
    return False


def _find_qr(page):
    """定位登录二维码，返回可截图的元素句柄。抖音登录页多版本：
    ①老式 = 随机 class 的方形 base64 PNG `<img>`（≈178px）；
    ②新版（2026-08 实测）= 方形 `<canvas>`（≈180×180，中心叠一个 svg logo）——旧的只认 img
    的逻辑会漏掉，导致「未找到二维码」。两种都按「可见的方形、120~320px」定位，不靠 class。"""
    # ① data:image 方形 img
    for img in page.query_selector_all("img"):
        try:
            src = img.get_attribute("src") or ""
            if not src.startswith("data:image"):
                continue
            box = img.bounding_box()
            if box and 100 <= box["width"] <= 320 and abs(box["width"] - box["height"]) < 40:
                return img
        except Exception:
            continue
    # ② 「扫码登录」标签下方的方形元素（svg/canvas/div 二维码，2026-08 实测当前版本是 SVG）
    try:
        vh = page.viewport_size["height"] if page.viewport_size else 900
    except Exception:
        vh = 900
    lab = page.query_selector("text=扫码登录")
    try:
        lb = lab.bounding_box() if lab else None
    except Exception:
        lb = None
    best = None
    for el in page.query_selector_all("div, svg, canvas"):
        try:
            box = el.bounding_box()
            if not box:
                continue
            w, h = box["width"], box["height"]
            if not (120 <= w <= 320 and abs(w - h) < 30):
                continue
            if box["y"] < 0 or box["y"] + h > vh - 5:        # 完整在屏内（排除 y=900 的屏外 canvas）
                continue
            if lb is not None:                                # 在「扫码登录」下方、水平接近
                if not (box["y"] >= lb["y"] and abs((box["x"] + w / 2) - (lb["x"] + lb["width"] / 2)) < 160):
                    continue
            elif box["x"] + w / 2 < 600:                       # 无标签时退而取右侧登录面板
                continue
            if best is None or box["y"] < best[1]:            # 取最靠上的（最外层二维码容器）
                best = (el, box["y"])
        except Exception:
            continue
    return best[0] if best else None


def _shot_qr(page, qr, qr_out: Path) -> None:
    """截二维码。canvas 二维码直接 element.screenshot 常得空白（headless），改用**页面级截图 +
    clip 到二维码区域**（抓屏幕合成后的真实像素），失败再退回元素截图。"""
    try:
        box = qr.bounding_box()
        if box and box["width"] > 20:
            pad = 6
            page.screenshot(path=str(qr_out), clip={
                "x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
                "width": box["width"] + pad * 2, "height": box["height"] + pad * 2})
            return
    except Exception:
        pass
    qr.screenshot(path=str(qr_out))


# --------------------------------------------------------------------------- #
# 浏览器动作
# --------------------------------------------------------------------------- #
def _refresh_qr_if_expired(page) -> bool:
    """二维码过期后抖音会显示「已失效/点击刷新」并把码褪成只剩 logo——点一下刷新出新码。"""
    for t in ("点击刷新", "二维码已失效", "刷新二维码", "已失效", "点击刷新二维码"):
        try:
            el = page.query_selector(f"text={t}")
            if el and el.is_visible():
                el.click()
                page.wait_for_timeout(1800)
                return True
        except Exception:
            continue
    return False


def _human_type(page, el, text: str) -> None:
    """聚焦→Ctrl+A 清空→逐字输入（REF fillTitle/fillDescription）。"""
    el.click()
    page.wait_for_timeout(200)
    page.keyboard.press("Control+a")
    page.keyboard.press("Delete")
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(15)


def _go_upload(page):
    """首页点「高清发布」→ 等进 content/upload。REF goUploadPage。"""
    if "content/upload" in page.url:
        return
    btn = page.query_selector(SELECTORS["hd_publish"])
    if not btn:
        _die("未找到「高清发布」按钮（检查 SELECTORS.hd_publish，或未登录）")
    btn.click()
    deadline = time.time() + 15
    while time.time() < deadline:
        if "content/upload" in page.url:
            page.wait_for_timeout(800)
            return
        page.wait_for_timeout(500)
    _die("点击高清发布后未进入上传页（content/upload）")


def _switch_tab(page, kind: str):
    """切「发布视频/发布图文」tab。REF switchPublishType。"""
    sel = SELECTORS["tab_video"] if kind == "video" else SELECTORS["tab_imagetext"]
    try:
        page.wait_for_selector(sel, timeout=10000)
    except Exception:
        _die(f"未找到发布 tab（{kind}），检查 SELECTORS.tab_*")
    page.click(sel)
    page.wait_for_timeout(400)


def _upload_files(page, paths: list[str]):
    """隐藏 file input 塞文件（比拦截 filechooser 稳）。REF _clickAndChooseFile。"""
    fi = page.query_selector(SELECTORS["file_input"]) or page.query_selector(SELECTORS["file_input_fallback"])
    if not fi:
        _die("未找到上传 file input（检查 SELECTORS.file_input）")
    fi.set_input_files(paths)
    page.wait_for_timeout(1000)


def _wait_video_processed(page, timeout_s: int = 300):
    """等上传/转码完成 + 编辑器就绪。小文件秒传时 uploading-container 可能还没出现就返回=假就绪
    （真机实测：标题框还没渲染就去填→找不到）。改为**正向等标题输入框出现**（编辑页
    content/post/video 渲染完成的标志），再等上传条彻底消失。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.query_selector(SELECTORS["title_input"]) and not page.query_selector(SELECTORS["uploading"]):
            page.wait_for_timeout(1200)   # 编辑器完全可交互
            return
        page.wait_for_timeout(1500)
    _die(f"视频上传/转码超时或编辑器未就绪（{timeout_s}s）")


def _select_ai_cover(page):
    """等 AI 封面就绪（标题不含'生成中'）→ 选推荐封面 → 确认。best-effort：抖音通常自动取首帧
    做封面，不选也能发；仅当推荐封面 UI 存在时才点，缺失就跳过（不空等）。"""
    deadline = time.time() + 20
    while time.time() < deadline:
        t = page.query_selector(SELECTORS["cover_title"])
        if not t:                       # 无推荐封面 UI → 用自动封面，直接跳过
            return
        if "生成中" not in (t.inner_text() or ""):
            break
        page.wait_for_timeout(1000)
    cover = page.query_selector(SELECTORS["cover_first"])
    if cover:
        cover.click()
        page.wait_for_timeout(300)
        confirm = page.query_selector(SELECTORS["cover_confirm"])
        if confirm:
            confirm.click()
            page.wait_for_timeout(300)


def _fill_title_desc(page, title: str, desc: str, tags: list[str]):
    ti = page.query_selector(SELECTORS["title_input"])
    if not ti:
        _die("未找到标题输入框（检查 SELECTORS.title_input）")
    _human_type(page, ti, title)
    page.wait_for_timeout(300)
    # 抖音话题写进简介正文（# 自动联想成话题）
    body = desc or ""
    if tags:
        body = (body + " " + " ".join("#" + t.lstrip("#") for t in tags)).strip()
    di = page.query_selector(SELECTORS["desc_input"])
    if di and body:
        _human_type(page, di, body)
        page.wait_for_timeout(300)


def _click_publish(page):
    """在 card-container-creator-layout 内点文本为「发布」的按钮。REF publishVideo step8。"""
    container = page.query_selector(SELECTORS["publish_container"])
    scope = container or page
    btn = None
    for b in scope.query_selector_all("button"):
        try:
            if (b.inner_text() or "").strip() == "发布" and b.is_visible():
                btn = b
                break
        except Exception:
            continue
    if not btn:
        _die("未找到发布按钮（card-container 内文本『发布』）")
    btn.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    btn.click()


def _dump_publish_fail(page, tag: str = "publish-fail") -> None:
    """发布失败/超时时落盘编辑页 DOM + 截图，供选择器校准。"""
    d = DEFAULT_QR_OUT.parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"douyin-{tag}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(d / f"douyin-{tag}.png"))
    except Exception:
        pass


def _wait_toast(page, timeout_s: int = 20) -> None:
    """判发布结果：①URL 跳内容管理页(content/manage) = 成功；②toast 含「成功」= 成功；
    ③toast 含失败/错误类词 = 失败(dump)；超时未确认 → dump 后按未确认处理（不误报成功）。"""
    start_url = page.url
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            url = page.url
            if "content/manage" in url or ("post/video" not in url and "creator-micro" in url
                                           and url != start_url):
                print(f"✅ 发布成功（已跳转：{url[:70]}）")
                return
            t = page.query_selector(SELECTORS["toast"])
            if t:
                txt = (t.inner_text() or "").strip()
                if "成功" in txt:
                    print(f"✅ 发布成功（toast：{txt}）")
                    return
                if any(k in txt for k in ("失败", "错误", "不能", "不支持", "请先", "请选择", "请上传")):
                    _dump_publish_fail(page)
                    _die(f"发布失败（toast：{txt}）")
        except Exception:
            pass
        page.wait_for_timeout(1000)
    _dump_publish_fail(page)
    _die("发布结果未确认（未跳转、无成功 toast；DOM 已 dump 到 outputs/_login/douyin-publish-fail.*）", 5)


def _handle_publish_sms(page, code_file: Path, sf=None, wait_s: int = 300) -> bool:
    """发布点「发布」后触发的**短信验证墙**（与登录同款风控弹窗）：点「获取验证码」下发短信 →
    等前端/CLI 回填验证码文件 → 填码提交（复用登录的弹窗定位/提交）→ 墙消失/跳转即通过。
    复用 _find_verify_input/_sms_click_submit/_sms_fill_and_submit。返回是否通过。"""
    page.set_default_timeout(8000)   # 短信交互期用短超时，避免 _publish 的 300s 默认让查询挂死（真机实测）
    try:
        return _handle_publish_sms_inner(page, code_file, sf, wait_s)
    finally:
        page.set_default_timeout(300000)


def _publish_verified(page) -> bool:
    """短信验证是否已放行：验证墙消失，或已跳离编辑页（发布提交后跳内容管理）。"""
    try:
        url = page.url
        if "content/manage" in url or ("post/video" not in url and "post/image" not in url
                                       and "creator-micro" in url):
            return True
        return not _verify_wall(page)
    except Exception:
        return False


def _handle_publish_sms_inner(page, code_file: Path, sf, wait_s: int) -> bool:
    _dump_sms_dom(page, DEFAULT_QR_OUT, tag="publish")
    login_state.write_status(sf, "sms_required", "发布需短信验证，正在发送验证码…")
    login_state.read_sms_code(str(code_file))                 # 清旧码
    _sms_click_first(page, SMS_SEND_OPTS)                     # 点「获取验证码」下发
    phone = _sms_phone(page)
    msg = "发布短信验证：请输入手机收到的验证码" + (f"（{phone}）" if phone else "")
    login_state.write_status(sf, "sms_required", msg)
    print(f"📩 {msg}——等待回填 {code_file}（≤{wait_s}s，可多次重输）", file=sys.stderr)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if _publish_verified(page):                          # 墙没了/已跳转 = 验证已过（或平台直接放行）
            return True
        code = login_state.read_sms_code(str(code_file))
        if not code:
            page.wait_for_timeout(1500)
            continue
        login_state.write_status(sf, "verifying", "正在验证验证码…")
        _sms_fill_and_submit(page, code)
        # 轮询等验证放行（墙消失或已跳转）——服务端校验有往返，单次检查太短会误判「未通过」
        ok, err = False, ""
        for _ in range(12):
            page.wait_for_timeout(1500)
            if _publish_verified(page):
                ok = True
                break
            err = _sms_error_text(page)
            if err:
                break
        if ok:
            print("✅ 发布短信验证通过", file=sys.stderr)
            return True
        note = f"{err or '验证未通过'}，请重新输入验证码"
        login_state.read_sms_code(str(code_file))
        login_state.write_status(sf, "sms_required", note)
        print(f"⚠️ {note}", file=sys.stderr)
    login_state.write_status(sf, "error", "发布短信验证超时未完成")
    return False


def _sms_modal(page):
    """定位短信验证**弹窗**（含输入框/验证按钮/手机号的那层），排除背景登录表单。
    先按 semi class 找；class 实测不可靠（dump 只抓到标题壳）时，退到按弹窗**独有文案**
    （背景『验证码登录』表单绝不含）定位含 input 的最内层容器。找不到返回 None。"""
    best = None
    for sel in SMS_MODAL_SELS:
        for el in page.query_selector_all(sel):
            try:
                if not el.is_visible():
                    continue
                txt = el.inner_text() or ""
                if "验证码" not in txt and "验证" not in txt:
                    continue
                # 越靠内（文本越短）越可能是真正的弹窗内容层，优先
                if best is None or len(txt) < best[0]:
                    best = (len(txt), el)
            except Exception:
                continue
    if best:
        return best[1]
    # class 兜底失败 → 按独有文案找含 input 的最小容器
    for kw in ("短信已发送", "接收短信验证码", "无法验证通过"):
        for el in page.query_selector_all(f"div:has-text('{kw}'), section:has-text('{kw}')"):
            try:
                if el.is_visible() and el.query_selector("input"):
                    if best is None or len((el.inner_text() or "")) < best[0]:
                        best = (len(el.inner_text() or ""), el)
            except Exception:
                continue
        if best:
            return best[1]
    return None


def _verify_wall(page) -> bool:
    """是否**真的**出现了身份验证/短信墙。基于文案（WALL_KEYWORDS）判定，只认验证弹窗，
    不认背景『验证码登录』表单——**不需要短信验证时就不会误判**，避免硬跳短信流程。"""
    for getter in (_sms_modal, lambda p: p.query_selector(SELECTORS["sms_verify"])):
        try:
            el = getter(page)
            if not el or not el.is_visible():
                continue
            t = el.inner_text() or ""
            if any(k in t for k in WALL_KEYWORDS):
                return True
        except Exception:
            continue
    return False


def _dump_sms_dom(page, qr_out: Path, tag: str = "") -> str:
    """把短信验证的真实 DOM + 截图 + **全页 HTML + 输入框清单**落盘，供彻底校准。
    弹窗 class 不可靠时（实测），全页 dump + 输入框坐标/属性清单是定位真实框的唯一可靠依据。
    tag 非空时文件名带后缀（如 tag='after' → douyin_sms_after.*），用于区分提交前/后状态。"""
    d = qr_out.parent
    sfx = f"_{tag}" if tag else ""
    dom_path = d / f"douyin_sms{sfx}_dom.html"
    try:
        el = _sms_modal(page) or page.query_selector(SELECTORS["sms_verify"])
        dom_path.write_text(el.inner_html() if el else page.content(), encoding="utf-8")
    except Exception:
        pass
    try:  # 全页 HTML —— 弹窗定位失败时据此看真实结构
        (d / f"douyin_sms{sfx}_page.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:  # 所有输入框的属性/可见/坐标/**当前值** 清单 —— 一眼看出码进没进弹窗框
        inv = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('input')).map((i, n) => {
                const r = i.getBoundingClientRect();
                return n + ': ph=' + (i.placeholder || '') + ' type=' + i.type
                    + ' ml=' + i.maxLength + ' vis=' + (r.width > 4 && r.height > 4)
                    + ' val=' + (i.value || '')
                    + ' box=' + Math.round(r.x) + ',' + Math.round(r.y)
                    + ' cls=' + (i.className || '').slice(0, 50);
            }).join('\n')""")
        (d / f"douyin_sms{sfx}_inputs.txt").write_text(inv or "(no inputs)", encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(d / f"douyin_sms{sfx}.png"))
    except Exception:
        pass
    return str(dom_path)


def _sms_click_first(page, selectors) -> bool:
    """逐个尝试点击（跨引擎选择器），命中第一个可见的即点并返回 True。"""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                return True
        except Exception:
            continue
    return False


def _sms_phone(page) -> str:
    """抠脱敏手机号（best-effort，仅用于提示）。全页搜——正则够特异，不会误命中。"""
    import re
    try:
        m = re.search(r"1\d{2}[\*\s]{2,}\d{2,4}", page.inner_text("body") or "")
        if m:
            return m.group(0)
    except Exception:
        pass
    return ""


def _sms_error_text(page) -> str:
    """提交后若出现「码错/过期」文案，返回命中的关键词；否则空串。全页搜（关键词够特异）。"""
    try:
        text = page.inner_text("body") or ""
    except Exception:
        return ""
    for kw in SMS_ERROR_TEXTS:
        if kw in text:
            return kw
    return ""


def _find_verify_input(page):
    """精确定位短信验证**弹窗**里的验证码输入框，避开背景『验证码登录』表单的同名框。

    真机实测（outputs/_login/douyin_sms_inputs.txt）：页面上有 4 个 input——背景『验证码登录』
    表单占 idx 0/1/2（+86/手机号/验证码，靠右 x≈1149），居中弹窗的验证码框是 idx 3（x≈472）。
    背景表单 DOM 顺序在弹窗**之前**，且**也有「获取验证码」按钮**——所以旧版用「获取验证码」当
    锚点会先命中背景表单、把码打进错框（弹窗框空着→「验证」按钮不激活→登不上，就是这个坑）。
    改用：①弹窗**独有文案**（背景表单绝不含）定位容器取其 input；②兜底取水平**最居中**的验证码
    框（弹窗永远居中、背景表单靠右）。两条路都指向弹窗那个框。返回 ElementHandle 或 None。"""
    try:
        idx = page.evaluate(
            r"""() => {
                const inputs = Array.from(document.querySelectorAll('input'));
                const vis = el => { const r = el.getBoundingClientRect();
                    return r.width > 4 && r.height > 4; };
                // 弹窗独有文案——背景『验证码登录』表单没有这些词（不含歧义的「获取验证码」）
                const anchors = ['短信已发送', '接收短信验证码', '无法验证通过', '后重新发送'];
                const nodes = Array.from(document.querySelectorAll('div,section,form'));
                for (const el of nodes) {
                    const t = el.textContent || '';
                    if (!anchors.some(a => t.includes(a))) continue;
                    if (el.querySelectorAll('*').length > 60) continue;   // 收窄到弹窗内容层
                    const inp = el.querySelector('input');   // 弹窗子树内只有弹窗自己的框
                    if (inp && vis(inp)) return inputs.indexOf(inp);
                }
                // 兜底：可见的「验证码/6 位」输入框里，取水平最居中的（弹窗居中、背景表单靠右）
                const vw = window.innerWidth || 1280;
                const cx = i => { const r = i.getBoundingClientRect(); return r.x + r.width / 2; };
                const cand = inputs.filter(i => vis(i) &&
                    ((i.placeholder || '').includes('验证码') || i.maxLength === 6));
                if (cand.length) {
                    cand.sort((a, b) => Math.abs(cx(a) - vw / 2) - Math.abs(cx(b) - vw / 2));
                    return inputs.indexOf(cand[0]);
                }
                return -1;
            }""")
    except Exception:
        idx = -1
    if idx is not None and idx >= 0:
        els = page.query_selector_all("input")
        if idx < len(els):
            return els[idx]
    return None


def _sms_find_input(scope):
    """在给定范围内找可编辑验证码输入框（作为 _find_verify_input 的兜底）。
    多个候选时取水平**最居中**的（弹窗居中、背景『验证码登录』表单靠右），避免取到背景框。"""
    cands = []
    for sel in ("input[placeholder*='验证码']", "input[maxlength='6']",
                "input[type='tel']", "input[type='text']", "input"):
        for el in scope.query_selector_all(sel):
            try:
                if el.is_visible() and el.is_editable():
                    cands.append(el)
            except Exception:
                continue
        if cands:
            break
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    try:  # 取中心 x 最接近视口中线的（弹窗居中）
        vw = scope.evaluate("() => window.innerWidth || 1280")

        def _dist(el):
            b = el.bounding_box() or {"x": 1e9, "width": 0}
            return abs(b["x"] + b["width"] / 2 - vw / 2)

        return min(cands, key=_dist)
    except Exception:
        return cands[-1]  # 退而取最后一个（弹窗通常挂 body 末尾，DOM 顺序在背景表单之后）


def _sms_click_submit(page) -> bool:
    """点弹窗「验证」按钮提交。**抖音的按钮是纯 `<div>`**（class 形如
    `uc_verification_component_btn... primary-Npo6wt`，含 `btn` **不含** `button`、也无
    `role=button`）——旧的 `button,[class*=button]` 选择器匹配不到（真机实测：码填对、按钮已
    激活，却因点不到而从不提交 →「验证未完成」）。改为找**文本恰为提交词的最内层可见元素**，
    不靠 tag/class。「验证」为弹窗独有（背景『验证码登录』表单的按钮是「登录」），优先点。"""
    for label in ("验证", "验证并登录", "确定", "提交", "登录"):
        for el in page.query_selector_all(f":text-is('{label}')"):
            try:
                if not el.is_visible():
                    continue
                # 只点最内层（其子孙不再含同一提交词），避免点到包着两个按钮的 wrapper
                if any((k.inner_text() or "").strip() == label
                       for k in el.query_selector_all("*")):
                    continue
                el.click(timeout=3000)
                return True
            except Exception:
                continue
    return False


def _sms_fill_and_submit(page, code: str) -> bool:
    """定位弹窗验证码框 → 逐字键入 → **校验值真进了 React 受控 state**（没进用原生 setter +
    input/change 事件强制触发，否则「验证」按钮不激活）→ 点弹窗「验证」提交。找不到框返回 False。"""
    inp = _find_verify_input(page) or _sms_find_input(_sms_modal(page) or page)
    if not inp:
        return False
    try:
        inp.scroll_into_view_if_needed()
        inp.click()
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        for ch in code:
            page.keyboard.type(ch)
            page.wait_for_timeout(40)      # 逐字慢打，确保 React 逐位受控更新
    except Exception:
        pass
    # 校验值是否真进了输入框；没进（React 没收到）→ 原生 value setter + 派发 input/change 触发受控更新
    try:
        got = inp.input_value()
    except Exception:
        got = ""
    if got != code:
        try:
            inp.evaluate(
                """(el, code) => {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    setter.call(el, code);
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                }""", code)
            page.wait_for_timeout(300)
        except Exception:
            pass
    print(f"   验证码已填入（框内值={inp.input_value() if _safe(inp) else '?'}）", file=sys.stderr)
    page.wait_for_timeout(700)             # 等「验证」按钮由填满激活
    # 提交：点弹窗内「验证」（Playwright 原生 click 可信），回车兜底。
    # ⚠️ 不再用 `if _logged_in(page): return` 短路——发布页顶部恒有「高清发布」按钮，
    #    _logged_in 会永远 True 导致填了码却不点「验证」（真机实测：发布短信验证卡死的根因）。
    if not _sms_click_submit(page):
        try:
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
        except Exception:
            pass
    try:  # 提交后大概率跳转登录，等页面稳定再让上层轮询，减少撞「导航中上下文销毁」
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    return True


def _safe(inp) -> bool:
    try:
        inp.input_value()
        return True
    except Exception:
        return False


def _await_sms_result(page, deadline: float) -> str:
    """判定一次提交的终态：'success' / 'error'(码错·过期) / 'timeout'(未定)。
    整个轮询体对导航中的瞬时异常容错（登录成功会触发跳转，裸 query 会抛错）。"""
    saw_gone = False
    while time.time() < deadline:
        try:
            if _logged_in(page):
                return "success"
            if _sms_error_text(page):
                return "error"
            # 验证墙消失且无二维码 = 大概率正在跳登录态，给一次宽限等「高清发布」出现
            wall_gone = not page.query_selector(SELECTORS["sms_verify"]) and _find_qr(page) is None
        except Exception:
            page.wait_for_timeout(1000)
            continue
        if wall_gone and not saw_gone:
            saw_gone = True
            try:
                page.wait_for_selector(SELECTORS["hd_publish"], timeout=5000)
            except Exception:
                pass
            if _logged_in(page):
                return "success"
        page.wait_for_timeout(1200)
    return "timeout"


def _handle_sms(page, sf, qr_out: Path, code_file: Path, wait_s: int = 240) -> bool:
    """扫码后遇短信验证墙：选发码方式 → 触发发码 → 等前端回填 → 填码提交 → **判终态**。

    终态三分：成功→True；码错/过期→回退 sms_required 让用户在剩余窗口内**重输**（不再一次
    失败就退出重扫码）；整体超时→写 error 返回 False。选择器为防御式多候选，据 DOM dump 校准。
    """
    _dump_sms_dom(page, qr_out)
    login_state.write_status(sf, "scanned", "扫码成功，正在准备短信验证…")
    print("⚠️ 抖音要求身份验证；处理中…", file=sys.stderr)
    login_state.read_sms_code(str(code_file))  # 清理上一轮陈旧验证码

    # 第1步：验证方式选择屏——点「接收短信验证码」进到发码屏（缺这步验证码从不下发）
    if _sms_click_first(page, SMS_RECEIVE_OPTS):
        page.wait_for_timeout(1800)
    _dump_sms_dom(page, qr_out)  # dump 发码屏，供校准发码按钮/输入框
    # 第2步：点「获取验证码」触发下发短信（有的进屏自动发）
    _sms_click_first(page, SMS_SEND_OPTS)

    phone = _sms_phone(page)
    msg = "验证码已发送，请输入手机收到的验证码" + (f"（{phone}）" if phone else "")
    login_state.write_status(sf, "sms_required", msg)
    print(f"📩 {msg}——等待前端回填（≤{wait_s}s，可多次重输）", file=sys.stderr)

    overall_deadline = time.time() + wait_s
    input_missing = False
    while time.time() < overall_deadline:
        if _logged_in(page):        # 点发送后平台有时直接放行
            return True
        code = login_state.read_sms_code(str(code_file))
        if not code:
            page.wait_for_timeout(1500)
            continue
        login_state.write_status(sf, "verifying", "正在验证验证码…")  # 前端转圈
        if not _sms_fill_and_submit(page, code):
            if not input_missing:   # 只提示一次，仍留在循环等（避免选择器一时未就绪就退出）
                input_missing = True
                login_state.write_status(
                    sf, "sms_required",
                    "未找到验证码输入框（DOM 已 dump，需校准选择器），可稍后重试")
            page.wait_for_timeout(1500)
            continue
        input_missing = False
        verdict = _await_sms_result(page, deadline=min(overall_deadline, time.time() + 30))
        if verdict == "success":
            return True
        # 码错/过期/未定 → 回退 sms_required 让用户重输（触发重新获取），继续等新码
        _dump_sms_dom(page, qr_out, tag="after")  # dump 提交后状态（报错框/按钮/值），供定位
        errtxt = _sms_error_text(page)
        note = (f"{errtxt}，请重新输入验证码（或稍后点重新获取）" if errtxt
                else "验证未完成，请确认验证码后重新输入")
        login_state.read_sms_code(str(code_file))  # 清掉可能的残留
        login_state.write_status(sf, "sms_required", note)
        print(f"⚠️ {note}", file=sys.stderr)

    login_state.write_status(sf, "error", "短信验证超时未完成（码未输入 / 多次错误 / 已过期），请重试")
    return False


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
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
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    qr_out = Path(a.qr_out).expanduser() if a.qr_out else DEFAULT_QR_OUT
    timeout_s = a.timeout or 180
    sf = getattr(a, "status_file", None)
    code_file = (Path(a.sms_code_file).expanduser() if getattr(a, "sms_code_file", None)
                 else qr_out.parent / "douyin.code")
    login_state.read_sms_code(str(code_file))  # 清理陈旧验证码文件
    login_state.write_status(sf, "starting")

    with sync_playwright() as p:
        ctx = _launch(p, headed=a.headed, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            if _logged_in(page):
                login_state.write_status(sf, "success", "已登录")
                print("✅ 抖音已登录（登录态在持久化目录）")
                return 0
            # 抖音登录默认可能是「验证码登录」tab，二维码在「扫码登录」tab 下——先切过去
            try:
                tab = page.query_selector(f"text={SELECTORS['qr_tab']}")
                if tab and tab.is_visible():
                    tab.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass
            # 二维码是随机 class 的方形 base64 图（≈178px），异步渲染——按尺寸轮询定位，不靠 class
            qr = None
            qr_deadline = time.time() + 22
            while time.time() < qr_deadline:
                qr = _find_qr(page)
                if qr or _verify_wall(page):
                    break
                page.wait_for_timeout(1000)
            if not qr:
                # 无二维码：可能未出码前就直接走了短信验证（风控）
                if _verify_wall(page):
                    if _handle_sms(page, sf, qr_out, code_file):
                        login_state.write_status(sf, "success", "登录成功（含短信验证）")
                        print("✅ 抖音登录成功（含短信验证），登录态已持久化")
                        try:
                            qr_out.unlink()
                        except OSError:
                            pass
                        return 0
                    return 4
                login_state.write_status(sf, "error", "未找到二维码")
                _die("未找到登录二维码（登录页可能改版；可加 --headed 观察）", 1)
            qr_out.parent.mkdir(parents=True, exist_ok=True)
            _shot_qr(page, qr, qr_out)
            login_state.write_status(sf, "qr_ready", "扫码登录抖音", qr=str(qr_out))
            print(f"📱 二维码已保存：{qr_out}（抖音 App 扫码）", file=sys.stderr)
            print(f"⏳ 等待扫码（最长 {timeout_s}s）...", file=sys.stderr)

            deadline = time.time() + timeout_s
            scanned = False
            last_shot = time.time()
            while time.time() < deadline:
                if _logged_in(page):
                    login_state.write_status(sf, "success", "登录成功")
                    print("✅ 抖音登录成功，登录态已持久化")
                    try:
                        qr_out.unlink()
                    except OSError:
                        pass
                    return 0
                if _verify_wall(page):
                    if _handle_sms(page, sf, qr_out, code_file):
                        login_state.write_status(sf, "success", "登录成功（含短信验证）")
                        print("✅ 抖音登录成功（含短信验证），登录态已持久化")
                        try:
                            qr_out.unlink()
                        except OSError:
                            pass
                        return 0
                    return 4
                if not scanned and _find_qr(page) is None:
                    # 二维码消失=已扫码，尚未到验证屏——立即给用户反馈，避免"没动静"
                    login_state.write_status(sf, "scanned", "扫码成功，正在跳转验证…")
                    print("📲 已扫码，正在跳转验证…", file=sys.stderr)
                    scanned = True
                if not scanned and time.time() - last_shot > 10:
                    # ⭐ 每 ~10s 重截二维码，保持 douyin.png 是**当前有效码**——抖音码 1~2min 过期，
                    #    只截一次会让用户扫到已过期的旧快照（真机实测的「二维码不对」根因）。
                    _refresh_qr_if_expired(page)     # 若已失效先点刷新出新码
                    q = _find_qr(page)
                    if q:
                        _shot_qr(page, q, qr_out)
                        login_state.write_status(sf, "qr_ready", "扫码登录抖音（已刷新）", qr=str(qr_out))
                    last_shot = time.time()
                page.wait_for_timeout(1500)
            login_state.write_status(sf, "expired", "二维码超时未扫")
            print(f"⏱️ {timeout_s}s 内未登录成功（二维码可能过期），请重跑 login", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001 — 兜底：任何异常都必须落终态
            # 登录成功那刻会跳转，个别裸 query 可能抛「上下文销毁」——先复查登录态再决定终态，
            # 绝不把前端晾在 verifying/中途态上无限转圈（真机实测的坑）。
            try:
                if _logged_in(page):
                    login_state.write_status(sf, "success", "登录成功")
                    print("✅ 抖音登录成功（异常后复查确认），登录态已持久化")
                    try:
                        qr_out.unlink()
                    except OSError:
                        pass
                    return 0
            except Exception:
                pass
            login_state.write_status(sf, "error", f"登录中断：{type(e).__name__}")
            print(f"❌ 登录流程异常：{e}", file=sys.stderr)
            return 4
        finally:
            ctx.close()


def _plan_lines(kind, title, desc, media, tags):
    tab = "发布视频" if kind == "video" else "发布图文"
    over = "  ⚠️超限" if len(title) > TITLE_MAX else ""
    return [
        f"发布类型：{kind}    平台：抖音 creator.douyin.com",
        f"标题：{title}（{len(title)}/{TITLE_MAX}{over}）",
        f"简介：{desc[:40]}{'...' if len(desc) > 40 else ''}",
        f"媒体：{media}", f"话题（写入简介）：{tags}",
        "步骤：",
        "  1. 首页点「高清发布」→ 进 content/upload",
        f"  2. 切 tab「{tab}」",
        f"  3. {'上传视频等转码(≤5min)+选AI封面' if kind == 'video' else '上传图片'}",
        "  4. 填标题/简介（Ctrl+A 清空再逐字输入）+ # 话题",
        "  5. 点「发布」→ toast 校验「发布成功」",
    ]


def cmd_plan(a) -> int:
    kind = "video" if a.video else "imagetext"
    media = [str(Path(a.video).expanduser())] if a.video else (
        [s.strip() for s in (a.images or "").split(",") if s.strip()])
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]
    for ln in _plan_lines(kind, a.title or "<title>", a.content or "", media, tags):
        print(ln)
    return 0


def _verify_published(p, a, title: str) -> bool:
    """重开一个干净 context 查内容管理页，确认标题对应作品是否已发布/审核中（权威判定）。
    发布收尾偶发渲染进程崩溃（"Page crashed"）但作品其实已提交成功——崩溃后用它核验，避免误报失败。"""
    key = (title or "").strip()[:12]
    if not key:
        return False
    try:
        ctx = _launch(p, headed=False, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.set_default_timeout(30000)
            page.goto("https://creator.douyin.com/creator-micro/content/manage",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(6000)     # 作品列表异步渲染
            body = page.inner_text("body") or ""
            found = key in body
            print(f"{'✅ 核验：内容管理页已见该作品' if found else '❌ 核验：内容管理页未见该作品'}（key={key}）",
                  file=sys.stderr)
            return found
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 重开核验失败：{e}", file=sys.stderr)
        return False


def _publish(a, kind: str) -> int:
    if not a.title:
        _die("--title 必填")
    if len(a.title) > TITLE_MAX:
        _die(f"标题过长（{len(a.title)}/{TITLE_MAX}），请精简")
    if kind == "video":
        if not a.video:
            _die("--video 必填")
        media = [_abspaths(a.video)[0]]
    else:
        media = _abspaths(a.images)
        if not media:
            _die("--images 至少一张图片")
    tags = [t.strip() for t in (a.tags or "").split(",") if t.strip()]

    # 出站内容安全闸门：真发前扫描标题/简介/话题，检出内部设置泄露即阻止（dry-run 只告警）。
    content_guard.guard_or_die([a.title, a.content, " ".join(tags)],
                               exec_mode=bool(a.exec),
                               allow_unsafe=getattr(a, "allow_unsafe", False),
                               label="抖音发布内容")

    if not a.exec:
        print("dry-run（加 --exec 真正发布）：\n")
        for ln in _plan_lines(kind, a.title, a.content or "", media, tags):
            print(ln)
        return 0

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    sf = getattr(a, "status_file", None)
    login_state.write_status(sf, "starting", "发布中…")
    published = None   # None=未确认（崩溃/超时→重开核验）；True/False=已判定
    with sync_playwright() as p:
        ctx = _launch(p, headed=a.headed, base=a.profile_base, proxy=_proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(300000)
        try:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            if not _logged_in(page):
                _die("未登录，请先 `login` 扫码")
            _go_upload(page)
            _switch_tab(page, "video" if kind == "video" else "imagetext")
            _upload_files(page, media)
            if kind == "video":
                _wait_video_processed(page)
                _select_ai_cover(page)
            _fill_title_desc(page, a.title, a.content or "", tags)
            _click_publish(page)
            page.wait_for_timeout(2500)
            # 发布也可能触发风控短信验证墙（真机实测：点发布后弹「接收短信验证码」）
            if _verify_wall(page):
                code_file = (Path(a.sms_code_file).expanduser()
                             if getattr(a, "sms_code_file", None)
                             else DEFAULT_QR_OUT.parent / "douyin.code")
                if not _handle_publish_sms(page, code_file, sf):
                    _dump_publish_fail(page, "publish-sms-fail")
                    published = False
            # 收尾（验证通过后抖音自动提交，此阶段偶发渲染进程崩溃/上下文销毁）——抗错，
            # 崩了不判失败，交给下面「重开干净浏览器查内容管理页」权威核验。
            if published is None:
                try:
                    page.wait_for_timeout(1500)
                    if "post/video" in page.url or "post/image" in page.url:
                        try:
                            _click_publish(page)
                        except SystemExit:
                            pass
                    _wait_toast(page, timeout_s=40)
                    published = True
                except (PWTimeout, PWError, SystemExit) as e:
                    print(f"⚠️ 收尾阶段异常（{type(e).__name__}）——将重开浏览器核验是否已发布", file=sys.stderr)
                    published = None
        except PWTimeout:
            _dump_publish_fail(page, "publish-timeout")
            published = None
        except PWError as e:
            print(f"⚠️ 发布过程渲染异常（{e}）——将重开浏览器核验", file=sys.stderr)
            published = None
        finally:
            try:
                if not a.keep_open:
                    ctx.close()
            except Exception:
                pass
        # 未确认（崩溃/超时）→ 重开一个干净 context 查内容管理页，确认到底发出去没有
        if published is None:
            published = _verify_published(p, a, a.title)
    if published:
        login_state.write_status(sf, "success", "发布成功")
        print("✅ 抖音发布成功")
        # 落统一内容日历（对话页自动；发布页由 web 设 AUTORECORD=0 跳过防重复）
        try:
            import calendar_ops
            calendar_ops.record_publish("douyin", a.title,
                                        ptype="视频" if kind == "video" else "图文",
                                        tags=(a.tags or ""), note=(a.content or ""), source="chat")
        except Exception:
            pass
        return 0
    login_state.write_status(sf, "error", "发布未确认成功（见 outputs/_login/douyin-publish-fail.* 或内容管理页）")
    _die("发布未确认成功（内容管理页未见该作品；见截图/日志）", 5)


def cmd_publish(a) -> int:
    return _publish(a, "imagetext")


def cmd_publish_video(a) -> int:
    return _publish(a, "video")


def cmd_whoami(a) -> int:
    """真校验登录态 + 读昵称/头像，输出单行 JSON（供 Web 后端解析）。
    复用 _logged_in（无二维码 + 有「高清发布」）。昵称/头像选择器 best-effort，登录后需校验。"""
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
                page.goto(HOME_URL, wait_until="domcontentloaded")
                try:
                    page.wait_for_selector(SELECTORS["hd_publish"], timeout=4000)
                except Exception:
                    pass
                logged = _logged_in(page)
                result["loggedIn"] = logged
                if logged:
                    # 昵称/头像用**稳定锚点**取，不靠随机 class（真机校准 2026-08）：
                    # 头像 src 路径含 aweme-avatar 稳定；昵称是「抖音号：」上一行的非数字文本。
                    try:
                        page.wait_for_timeout(1500)  # 主页头像/昵称异步渲染
                        na = page.evaluate(
                            r"""() => {
                                const av = document.querySelector('img[src*="aweme-avatar"]')
                                       || document.querySelector('img[src*="douyinpic.com/aweme"]');
                                let name = '', avatar = av ? av.src : '';
                                const all = [...document.querySelectorAll('*')].filter(
                                    e => e.children.length === 0 && (e.textContent || '').trim());
                                const ai = all.findIndex(e => /抖音号[:：]/.test(e.textContent));
                                if (ai > 0) for (let j = ai - 1; j >= 0 && j >= ai - 4; j--) {
                                    const t = (all[j].textContent || '').trim();
                                    if (t && !/^[\d,]+$/.test(t) && t.length <= 40) { name = t; break; }
                                }
                                return {name, avatar};
                            }""")
                        result["name"] = (na.get("name") or "")[:40]
                        result["avatar"] = na.get("avatar") or ""
                    except Exception:
                        pass
            finally:
                ctx.close()
    except Exception as e:  # noqa: BLE001 — whoami 永远输出 JSON
        result["error"] = str(e)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_selftest(_a) -> int:
    print("douyin_publish 自检（离线）...", file=sys.stderr)
    need = ["hd_publish", "qrcode", "tab_video", "tab_imagetext", "file_input",
            "uploading", "title_input", "desc_input", "publish_container", "toast",
            "sms_verify", "sms_send", "sms_input", "sms_submit"]
    for k in need:
        assert k in SELECTORS and SELECTORS[k], f"缺选择器 {k}"
    try:
        _abspaths("/no/such/file_xyz.jpg")
        raise AssertionError("不存在文件未报错")
    except SystemExit:
        pass
    assert _profile_dir(None).name == PROFILE_NAME
    assert _proxy(None, True) is None
    assert _proxy("http://x:1", False) == "http://x:1"
    lv = _plan_lines("video", "标题", "简介", ["/a.mp4"], ["热点"])
    assert any("发布视频" in x for x in lv) and any("发布成功" in x for x in lv)
    li = _plan_lines("imagetext", "t", "c", ["/a.jpg"], [])
    assert any("发布图文" in x for x in li)
    # 验证码文件协议：写入→读取消费一次→再读为空
    import tempfile as _tf
    tmpd = Path(_tf.mkdtemp())
    cf = tmpd / "douyin.code"
    cf.write_text("123456")
    assert login_state.read_sms_code(str(cf)) == "123456"
    assert not cf.exists(), "验证码文件未被消费删除"
    assert login_state.read_sms_code(str(cf)) == ""
    assert "sms_required" in login_state.STATES and "scanned" in login_state.STATES
    assert "verifying" in login_state.STATES
    # 短信多步流程常量齐备（选发码方式 / 触发发码 / 码错文案 / 弹窗定位 / 墙判定词）
    assert SMS_RECEIVE_OPTS and SMS_SEND_OPTS and SMS_ERROR_TEXTS and SMS_MODAL_SELS and WALL_KEYWORDS
    assert any("接收短信" in s for s in SMS_RECEIVE_OPTS)
    assert any("获取验证码" in s for s in SMS_SEND_OPTS)
    assert "验证码错误" in SMS_ERROR_TEXTS and "验证码已过期" in SMS_ERROR_TEXTS
    assert any("modal" in s for s in SMS_MODAL_SELS)
    assert "接收短信" in WALL_KEYWORDS and "身份验证" in WALL_KEYWORDS
    print("✅ selftest 通过（短信选择器 + 弹窗定位 + 墙判定 + 路径/代理/路由 + plan + 验证码文件协议）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="抖音发布（Playwright，headless 可用；流程移植自 douyin-upload-mcp-skill）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--profile-base", help="登录态根目录（默认 ~/.easel-browser-profiles）")
        p.add_argument("--proxy", help="外网代理（默认取 env）")
        p.add_argument("--no-proxy", action="store_true", help="禁用代理")

    def add_content(p):
        p.add_argument("--title", help="标题（≤30 字）")
        p.add_argument("--content", help="作品简介")
        p.add_argument("--images", help="图片路径，逗号分隔（图文）")
        p.add_argument("--video", help="视频路径（视频）")
        p.add_argument("--tags", help="话题，逗号分隔（写入简介 # 话题）")
        p.add_argument("--exec", action="store_true", help="真正发布（默认 dry-run）")
        p.add_argument("--allow-unsafe", action="store_true",
                       help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
        p.add_argument("--headed", action="store_true", help="有头模式（首次校验选择器）")
        p.add_argument("--keep-open", action="store_true", help="发布后不关浏览器")
        p.add_argument("--sms-code-file", help="发布触发短信验证时的验证码回填文件（默认 <_login>/douyin.code）")
        p.add_argument("--status-file", help="登录/验证状态 JSON 输出路径（供 Web 后端轮询短信墙）")

    sub.add_parser("check", help="检查 playwright/内核").set_defaults(func=cmd_check)

    p = sub.add_parser("login", help="扫码登录并持久化（headless 抠二维码）")
    add_common(p)
    p.add_argument("--qr-out", help=f"二维码图片输出路径（默认 {DEFAULT_QR_OUT}）")
    p.add_argument("--status-file", help="登录状态 JSON 输出路径（供 Web 后端轮询）")
    p.add_argument("--sms-code-file", help="短信验证码回填文件（默认 <qr目录>/douyin.code）")
    p.add_argument("--timeout", type=int, help="等待扫码超时秒数（默认 180）")
    p.add_argument("--headed", action="store_true", help="有头模式")
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
