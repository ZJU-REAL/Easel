#!/usr/bin/env python3
"""web_publisher.py — 通用浏览器发布框架（Playwright + 登录态持久化，配置驱动）。

为"无开放 API、只能靠网页操作"的平台（快手 / 视频号 / 知乎 等）提供统一发布引擎：
每个平台是一份「步骤配置」（登录页 / 发布页 / 选择器步骤），共用同一套 Playwright 引擎。
登录态用持久化 user-data-dir 保存，扫码/登录一次后复用。

⚠️ 环境依赖（真实发布需具备，缺则不可用——同 skill-xhs-publisher 定位）：
    - playwright（`pip install playwright`）+ 浏览器内核（`playwright install chromium`）
    - 目标平台已登录（首次 `login` 打开有头浏览器扫码/登录，持久化到 profile 目录）
    - 有图形/远程显示或平台支持无头（登录一般需有头）
  无头/无内核环境仍可用 `platforms` / `plan`（dry-run 步骤预览）/ `check`。

⚠️ 选择器时效性：各平台网页改版频繁，内置选择器为**最佳努力**，**首次使用需人工校验/更新**
   （见各平台 config 的 selector_caveat 与 SKILL 文档）。发布前务必先 `plan` 预览、`login` 目视确认。

子命令：
    platforms  列出支持平台
    plan       解析并打印某平台的发布步骤（dry-run，不开浏览器）
    check      检查 playwright / 浏览器内核
    login      打开有头浏览器登录并持久化登录态
    publish    执行网页发布（按步骤自动化）
    selftest   自检（配置完整性 + 步骤解析，离线）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import login_state  # noqa: E402
import content_guard  # noqa: E402  出站内容安全闸门

# ── 平台配置注册表 ────────────────────────────────────────────────────
# 每个步骤：{"action": goto|upload|fill|click|wait|press|waitfor, "selector"?, "value"?}
# value 支持占位符：{media} {title} {desc} {tags} {cover}
# 注：小红书**不在此**——其发布流程复杂（切 tab/逐图等上传/话题联想/成功校验），
#     用独立脚本 skills/shared/scripts/xhs_publish.py（移植自 xiaohongshu-mcp）。
PLATFORMS: dict[str, dict] = {
    "kuaishou": {
        "name": "快手",
        "login_url": "https://cp.kuaishou.com",
        "publish_url": "https://cp.kuaishou.com/article/publish/video",
        "profile": "KuaishouProfile",
        "media_kind": "video",  # 快手走视频发布流程（publish/video），只收视频；图片会晦涩超时
        # 已登录标志（2026-07 实测：快手创作者中心改版，旧 .cp-header .user-name 已失效）
        "login_check": ".user-info-avatar, .user-line, .vertical-menu, .setting-container",
        # 严格判定：未登录会重定向到同域营销落地页（URL≠首页但其实未登录）→ 必须命中上面强选择器才算登录
        "login_strict": True,
        # 发布子系统鉴权探针：快手创作者中心「外壳」token（api_st/api_ph，+14d）比发布上传用的
        # onvideo token（+0d，常在数小时内过期）活得久 → 外壳 DOM 仍显示已登录、昵称头像都在，
        # 但真去发布时上传子系统 401 失败（用户实测「外壳正常但发不出去」）。DOM 外壳判定看不到这层，
        # 故登录判定后再探一次发布/作品模块自己的 current/user（同源、无签名可直接 fetch）：
        # result==1 表示发布鉴权正常；仅在「明确失效」信号（跳登录/401·403/未登录 result·文案）时才判未登录，
        # 瞬时错误（如 result:500002「请稍后重试」/网络错误）保持外壳判定，避免把有效会话误翻成未登录。
        "login_probe": {
            "url": "https://cp.kuaishou.com/rest/cp/works/v2/common/pc/current/user",
            "method": "POST",
            "ok_result": [1],
        },
        # 收紧：去掉泛 [class*=login]（会误命中营销页/已登录页的 login 相关元素 → 假未登录）；
        # 快手真扫码在 passport 域（URL 已判），cp 站已登录靠 login_check
        "logged_out_selector": ".login-container, [class*=qrcode] img[src^='data:image']",
        # 快手登录页是营销落地页，需点『立即登录』跳 passport 再切『扫码登录』才出二维码
        "login_prep": [{"click": "text=立即登录"}, {"wait": 3000},
                       {"click": "text=扫码登录"}, {"wait": 2500}],
        # 二维码本体优先（passport 扫码码多为 base64 img / canvas，异步渲染）
        "login_qr_selector": "[class*=qrcode] img[src^='data:image'], [class*=qrcode] canvas, "
                             "[class*=qrcode] img, [class*=qr-login] img, [class*=qrcode]",
        # 截图前等这个真正渲染出来（固定 wait 不够——快手 passport 二维码异步画）
        "qr_loaded": "[class*=qrcode] img[src^='data:image'], [class*=qrcode] canvas, "
                     "[class*=qrcode] img[src], canvas",
        "me_name_selector": ".user-info-name, .user-line .name, .username, .user-name",
        "me_avatar_selector": ".user-info-avatar img[src], .user-line img[src^='http']",
        "publish_success": {"url_not_contains": "publish/video"},
        "steps": [
            # 先导航到管理页再回来，彻底清理草稿/页面状态
            {"action": "goto", "value": "https://cp.kuaishou.com/article/manage/video"},
            {"action": "wait", "value": "2000"},
            {"action": "goto", "value": "https://cp.kuaishou.com/article/publish/video"},
            # 等 SPA 渲染上传区（goto 后立即操作太早，input[type=file] 未就绪 → set_input_files 塞了不触发上传）
            {"action": "wait", "value": "4000"},
            # 上次未发布的草稿会弹「继续编辑/放弃」横条挡住上传——先点『放弃』清理（没有则跳过）
            {"action": "click", "selector": "text=放弃, button:has-text('放弃'), [class*=abandon]", "optional": True},
            {"action": "wait", "value": "2000"},
            {"action": "upload", "selector": "input[type=file]", "value": "{media}"},
            # 快手上传后需转码才出编辑表单（可能 1-3min），等久点；描述框标签未定死，放宽多候选
            {"action": "waitfor",
             "selector": "textarea, [contenteditable=true], input[placeholder*=描述], "
                         "[placeholder*=描述], [placeholder*=作品], [class*=editor][contenteditable]",
             "value": "180000"},
            # 快手新手引导（react-joyride）有时会挡住描述框，headless 下无法手动关闭；
            # 只移除引导浮层，不触碰业务表单内容。
            {"action": "js_eval",
             "value": """() => {
                 for (const sel of ['#react-joyride-portal','.react-joyride__overlay','.react-joyride__spotlight']) {
                     document.querySelectorAll(sel).forEach(el => el.remove());
                 }
                 document.querySelectorAll('[style*=pointer-events]').forEach(el => {
                     const cls = (el.className || '').toString();
                     if (cls.includes('joyride')) el.remove();
                 });
             }"""},
            {"action": "fill",
             "selector": "textarea, [contenteditable=true], input[placeholder*=描述], [placeholder*=描述]",
             "value": "{title}\n{desc}\n{tags}"},
            {"action": "wait", "value": "3000"},
            # 截图：记录表单填写后状态
            {"action": "screenshot", "value": "outputs/_login/ks-prefill.png"},
            # 等发布按钮就绪（转码完成后才可点）
            {"action": "waitfor", "selector": "[class*=_edit-section-btns]", "value": "60000"},
            # 等封面缩略图加载完毕（_recommend-cover-item loading 消失后才能发布，否则点击无效）
            {"action": "wait", "value": "25000"},
            # 真发布按钮：表单底部『发布』，class 含 _button-primary_<hash>，在 _edit-section-btns_ 容器内。
            # 用 js_click（scrollIntoView + JS dispatchEvent）触发——标准 click() 与 :has-text 对该按钮不可靠；
            # 选择器多候选逐一尝试：优先容器内 button-primary，回退到非导航栏（非 publish-button 容器）的 button-primary。
            # 勿点右上角『发布作品』（class=publish-button，是下拉菜单不是提交按钮）。
            # 另：快手话题标签最多 4 个，超限报错 '话题标签数量超过上限：4'。
            {"action": "js_click",
             "selector": "[class*=_edit-section-btns] [class*=button-primary], [class*=button-primary]:not([class*=publish-button] *)"},
            {"action": "wait", "value": "8000"},
            # 点发布后可能弹二次确认弹窗——optional
            {"action": "click",
             "selector": "[class*=dialog] [class*=button-primary], [class*=dialog] button:has-text('确认'), "
                         "[class*=dialog] button:has-text('确定'), text=确认发布, text=确定发布",
             "optional": True},
            {"action": "wait", "value": "4000"},
        ],
        # 图文发布流程（media 是图片时走这套）：切「上传图文」tab + filechooser 上传图片
        # （图文的图片 input 用 set_input_files 不触发上传，必须点『上传图片』走 filechooser——真机 dump 确认）
        "steps_image": [
            {"action": "goto", "value": "https://cp.kuaishou.com/article/publish/video"},
            {"action": "wait", "value": "4000"},
            {"action": "click", "selector": "text=放弃, button:has-text('放弃'), [class*=abandon]", "optional": True},
            {"action": "wait", "value": "1500"},
            # 切「上传图文」tab
            {"action": "click", "selector": ".ant-tabs-tab-btn:has-text('上传图文'), text=上传图文"},
            {"action": "wait", "value": "3000"},
            # filechooser 上传图片（点『上传图片』按钮拦截文件选择器）
            {"action": "filechooser_upload",
             "selector": "text=上传图片, [class*=upload] button:has-text('上传图片'), button:has-text('上传图片')",
             "value": "{media}"},
            # 等图片上传完成（CDN 预览就绪）——否则点发布会弹「请在图片上传完成后再点击发布」
            {"action": "waitfor", "selector": "[class*=preview-cover], img[src*='ssrcdn']", "value": "90000"},
            {"action": "wait", "value": "2500"},
            # 图文编辑表单：描述框 div[class*=_description]（占位『添加合适的话题和描述…』）
            {"action": "waitfor",
             "selector": "[class*=_description], [placeholder*=描述], [contenteditable=true]", "value": "60000"},
            {"action": "fill",
             "selector": "[class*=_description], [placeholder*=描述], [contenteditable=true]",
             "value": "{title}\n{desc}\n{tags}"},
            {"action": "wait", "value": "1500"},
            {"action": "click",
             "selector": "[class*=button-primary]:has-text('发布'), "
                         "div[class*=_button]:has-text('发布'):not(:has-text('作品'))"},
            {"action": "wait", "value": "2500"},
            {"action": "click",
             "selector": "[class*=dialog] [class*=button-primary], [class*=dialog] button:has-text('确认'), "
                         "[class*=dialog] button:has-text('确定'), text=确认发布, text=确定发布",
             "optional": True},
            {"action": "wait", "value": "4000"},
        ],
        # 发布成功校验：成功后离开发布页 / 出现成功 toast（避免"点了发布=成功"的假阳性）
        "publish_success": {"url_not_contains": "publish/video", "selector": "text=发布成功"},
        "selector_caveat": "快手创作者中心发布页；上传后转码才出编辑表单（描述框 DIV，占位『作品描述…』）；"
                           "真发布按钮在表单底部：div[class*=button-primary]『发布』（品牌红，非 <button>；"
                           "注意别点左侧导航的『发布作品』菜单）。点发布后可能弹二次确认（已加 optional）。"
                           "若仍未成功，看 outputs/_publish.log dump 的可点元素更新选择器。",
    },
    "weixin-channels": {
        "name": "微信视频号",
        "login_url": "https://channels.weixin.qq.com",
        "publish_url": "https://channels.weixin.qq.com/platform/post/create",
        "profile": "ChannelsProfile",
        "media_kind": "video",  # 视频号也走视频发布流程
        # 登录判定靠 URL：未登录一律重定向到 channels.weixin.qq.com/login.html（含 login 标记 → _is_logged_in 判未登录）；
        # login_check 为已登录主页的正向兜底（真机 2026-08 校准：登录后主页才有 finder-nickname/唯一ID/桌面导航）
        "login_check": ".finder-nickname, .finder-uniq-id, .finder-ui-desktop-menu",
        # ⚠️ 二维码在跨域 iframe 内（open.weixin.qq.com 的微信标准扫码组件 connect/qrconnect），
        # 主页面 query_selector 根本找不到——必须截 <iframe> 元素本体（真机 2026-08 验证：得 208×208 清晰码；
        # iframe 内 img.js_qrcode_img 的 src 是相对 URL /connect/qrcode/<ticket>，非 base64，故打分裁剪那套不适用）
        "login_qr_iframe": "iframe[src*='open.weixin.qq.com/connect/qrconnect']",
        # 登录页出现该扫码 iframe = 未登录的可靠信号
        "logged_out_selector": "iframe[src*='open.weixin.qq.com/connect/qrconnect'], .login-mask",
        "me_name_selector": ".finder-nickname, .name",
        "me_avatar_selector": "img.avatar[src], .finder-info img[src]",
        "steps": [
            {"action": "goto", "value": "https://channels.weixin.qq.com/platform/post/create"},
            {"action": "upload", "selector": "input[type=file]", "value": "{media}"},
            {"action": "waitfor", "selector": "textarea,.input-editor", "value": "60000"},
            {"action": "fill", "selector": ".input-editor,textarea", "value": "{title}"},
            {"action": "wait", "value": "3000"},
            {"action": "click", "selector": "button:has-text('发表')"},
        ],
        # 发布成功校验：成功后离开创作页（/platform/post/create → 作品列表）——避免"点了发表=成功"假阳性
        "publish_success": {"url_not_contains": "post/create", "selector": "text=发表成功"},
        "selector_caveat": "视频号需微信扫码登录，二维码在跨域 iframe（open.weixin.qq.com/connect/qrconnect）内，"
                           "已配 login_qr_iframe 直接截 iframe 元素本体（真机 2026-08 验证有效）。"
                           "登录判定/whoami 已真机校准（login_check=finder-nickname/唯一ID/桌面导航；昵称 .finder-nickname、头像 img.avatar）。"
                           "发布走专用函数 _publish_weixin_channels（真机 2026-08 打通）：goto /platform/post/list 点『发表视频』进创作页"
                           "（直接 goto create 会重定向回首页）→ 上传 → 等转码出创作器（在 OOPIF iframe /micro/content/post/create 内，"
                           "Playwright locator 解析不到、合成点击不被信任）→ evaluate 填描述(div.input-editor,execCommand) + 聚焦发表按钮 "
                           "→ page.keyboard 按 Enter 可信提交，URL 跳 /post/list 即成功。下方 steps 已弃用（占位）。",
    },
    "zhihu": {
        "name": "知乎",
        "login_url": "https://www.zhihu.com/signin",
        "publish_url": "https://zhuanlan.zhihu.com/write",
        "profile": "ZhihuProfile",
        "login_check": ".AppHeader-profile, .AppHeader-userInfo",
        "logged_out_selector": ".SignContainer, .Login-content, button:has-text('登录')",
        "me_name_selector": ".AppHeader-profile .name, .ProfileHeader-name, .AppHeader-userInfo .name",
        "me_avatar_selector": ".AppHeader-profile img[src], .Avatar[src]",
        "steps": [
            {"action": "goto", "value": "https://zhuanlan.zhihu.com/write"},
            {"action": "waitfor", "selector": "textarea,.WriteIndex-titleInput,input", "value": "30000"},
            {"action": "fill", "selector": ".WriteIndex-titleInput textarea,textarea[placeholder*='标题']", "value": "{title}"},
            {"action": "type", "selector": ".public-DraftEditor-content,[contenteditable=true]", "value": "{desc}"},
            {"action": "wait", "value": "2000"},
            {"action": "click", "selector": "button:text-is('发布')"},
        ],
        # 发布成功校验：知乎发成功后跳到文章页 zhuanlan.zhihu.com/p/<id>（草稿是 /p/<id>/edit，需排除）
        "publish_success": {"url_contains": "/p/", "url_not_contains": "/edit"},
        "selector_caveat": "知乎专栏写文章页；正文为 Draft.js contenteditable。『发布』按钮须精确匹配"
                           "（避免误点『发布设置』）。首次需核对标题输入框与发布流程。",
    },
}

_ACTIONS = {"goto", "upload", "filechooser_upload", "fill", "type", "click", "js_click", "js_eval", "wait", "press", "waitfor", "screenshot"}

# Chromium 启动性能参数（提速冷启动；勿禁用图片——二维码是图片）
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--disable-extensions", "--disable-background-networking",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    "--disable-features=TranslateUI,BackForwardCache",
    "--mute-audio", "--no-first-run", "--no-default-browser-check",
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _resolve_steps(platform: str, ctx: dict, steps_key: str = "steps") -> list[dict]:
    cfg = PLATFORMS.get(platform)
    if not cfg:
        _die(f"未知平台：{platform}（支持：{', '.join(PLATFORMS)}）")
    src = cfg.get(steps_key) or cfg["steps"]
    steps = []
    for st in src:
        s = dict(st)
        if "value" in s and isinstance(s["value"], str):
            for k, v in ctx.items():
                s["value"] = s["value"].replace("{" + k + "}", str(v))
        if s["action"] not in _ACTIONS:
            _die(f"配置错误：未知 action {s['action']}")
        steps.append(s)
    return steps


def _steps_key_for(cfg: dict, media: str | None) -> str:
    """按媒体类型选步骤集：图片且平台有图文流程 → steps_image；否则默认 steps。"""
    ext = Path(media).suffix.lower() if media else ""
    if ext and ext not in VIDEO_EXTS and cfg.get("steps_image"):
        return "steps_image"
    return "steps"


def _profile_dir(platform: str, base: str | None) -> Path:
    root = Path(base).expanduser() if base else Path.home() / ".easel-browser-profiles"
    return root / PLATFORMS[platform]["profile"]


def cmd_platforms(_a) -> int:
    print(f"支持 {len(PLATFORMS)} 个网页发布平台：\n")
    for k, c in PLATFORMS.items():
        print(f"  {k:18s} {c['name']}  → 发布页 {c['publish_url']}")
    print("\n真实发布需 playwright + 浏览器内核 + 已登录（见 check / login）。")
    return 0


def cmd_plan(a) -> int:
    ctx = {"media": a.media or "<media>", "title": a.title or "<title>",
           "desc": a.desc or "<desc>", "tags": a.tags or "", "cover": a.cover or ""}
    steps = _resolve_steps(a.platform, ctx, _steps_key_for(PLATFORMS.get(a.platform, {}), a.media))
    cfg = PLATFORMS[a.platform]
    print(f"平台：{cfg['name']}（{a.platform}）")
    print(f"登录页：{cfg['login_url']}")
    print(f"⚠️ 选择器提示：{cfg['selector_caveat']}\n")
    print("发布步骤（dry-run）：")
    for i, s in enumerate(steps, 1):
        detail = s.get("selector", "")
        val = s.get("value", "")
        print(f"  {i}. {s['action']:8s} {detail}  {('= ' + val) if val else ''}")
    return 0


def cmd_check(_a) -> int:
    ok = True
    try:
        import playwright  # noqa
        from playwright.sync_api import sync_playwright  # noqa
        print("✅ playwright 已安装")
    except Exception as e:
        print(f"❌ playwright 未安装：{e}（pip install playwright）"); ok = False
    # 浏览器内核
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                print(f"✅ chromium 内核：{path}")
            else:
                print("❌ 未安装浏览器内核（playwright install chromium）"); ok = False
    except Exception as e:
        print(f"❌ 无法检查内核：{e}（playwright install chromium）"); ok = False
    print("登录态目录：~/.easel-browser-profiles/<平台>Profile")
    return 0 if ok else 3


def _split_sels(sel: str) -> list[str]:
    """逗号分隔的多候选选择器 → 列表（去空）。修掉旧代码 sel.split(',')[0] 丢兜底的坑。"""
    return [s.strip() for s in (sel or "").split(",") if s.strip()]


def _first_visible_el(page, sel: str):
    """多候选里挑第一个可见元素；都不可见则退回第一个存在的。"""
    for want_visible in (True, False):
        for s in _split_sels(sel):
            try:
                el = page.query_selector(s)
                if el and (el.is_visible() if want_visible else True):
                    return el
            except Exception:
                pass
    return None


def _fill_first_visible(page, sel: str, val: str) -> None:
    """填写多候选目标，自动兼容 contenteditable（富文本用键入，input/textarea 用 fill）。"""
    el = _first_visible_el(page, sel)
    if el is None:
        raise RuntimeError(f"填写目标未找到：{sel}")
    editable = False
    try:
        editable = bool(el.evaluate("e => e.isContentEditable"))
    except Exception:
        pass
    if editable:
        el.click()
        page.keyboard.type(val)
    else:
        el.fill(val)


def _publish_weixin_channels(page, ctx: dict) -> None:
    """视频号发布专用流程（与通用 steps 不同，真机 2026-08 校准）：
    - 直接 goto /platform/post/create 会被重定向回首页 → 必须 SPA 导航（首页→内容管理→发表视频）。
    - 创作器在同源 iframe /micro/content/post/create：描述框 div.input-editor、发表按钮
      button.weui-desktop-btn_primary 都在该 frame 内，主页面选择器够不到。"""
    media = ctx.get("media")
    if not media:
        raise RuntimeError("视频号发布需要视频文件（--media）")
    cfg = PLATFORMS["weixin-channels"]
    # 1) 进创作页：goto 列表页（会回跳首页但 SPA 会渲染「发表视频」入口）→ 点它进 create
    page.goto("https://channels.weixin.qq.com/platform/post/list", wait_until="domcontentloaded")
    _settle_login(page, cfg)
    if not _is_logged_in(page, cfg):
        raise RuntimeError("视频号未登录，请先在账号页扫码登录")
    page.wait_for_timeout(3000)
    page.wait_for_selector("text=发表视频", timeout=15000)
    # 点第一个「可见」的发表视频（避开同名但不可见的帮助文字 <p>，那会导致点击超时）
    loc = page.locator("text=发表视频")
    clicked = False
    for i in range(min(loc.count(), 8)):
        try:
            el = loc.nth(i)
            if el.is_visible():
                el.click()
                clicked = True
                break
        except Exception:
            pass
    if not clicked:
        raise RuntimeError("找不到可点的『发表视频』按钮")
    page.wait_for_url("**/post/create", timeout=15000)
    # 2) 上传视频：先等上传 input 就绪再塞（否则塞到未就绪的 input，转码不触发 → 创作器不出现）
    print("  视频号：上传视频…", file=sys.stderr)
    page.wait_for_timeout(5000)
    page.wait_for_selector("input[type=file]", state="attached", timeout=30000)
    page.set_input_files("input[type=file]", media, timeout=30000)
    # 3-5) 等创作器就绪并发表。真机踩坑：转码完成时 composer iframe（/micro/content/post/create，
    #      嵌套在另一 iframe 内 → frame_locator 的 iframe[src] 解析不到）会重载，持有的 frame 句柄立即失效
    #      （evaluate 刚确认元素存在、下一步 locator 就报找不到）。故每轮从 page.frames 重取最新 frame，
    #      同一轮内立即填描述+发表；若中途 frame 重载报错，等一下换新 frame 重试。填描述先 Ctrl+A 清空保证幂等。
    print("  视频号：等转码 + 创作表单…", file=sys.stderr)
    desc = "\n".join(x for x in (ctx.get("title"), ctx.get("desc"), ctx.get("tags")) if x)
    deadline = time.time() + 300
    published = False
    last_err = None
    while time.time() < deadline and not published:
        fr = next((f for f in page.frames if "micro/content/post/create" in (f.url or "")), None)
        if fr is None:
            page.wait_for_timeout(3000)
            continue
        try:
            ready = fr.evaluate("() => !!document.querySelector('div.input-editor') && "
                                "[...document.querySelectorAll('button')].some(b => (b.innerText||'').trim() === '发表')")
        except Exception:
            page.wait_for_timeout(3000)   # frame 正在重载
            continue
        if not ready:
            page.wait_for_timeout(3000)
            continue
        try:
            if desc:
                fr.evaluate("""(t) => {
                    const ed = document.querySelector('div.input-editor');
                    if (ed) {
                        ed.focus();
                        document.execCommand('selectAll', false, null);
                        document.execCommand('insertText', false, t);
                    }
                }""", desc)
                page.wait_for_timeout(1200)
            # 真机 2026-08 验证的可靠提交法：该 composer 是 OOPIF——Playwright locator 解析不到、
            # evaluate 合成点击不被视频号信任（校验 isTrusted）。故 evaluate 聚焦发表按钮 →
            # page.keyboard 按 Enter（CDP 系统级注入的可信键盘事件，路由到聚焦元素触发真实提交）。
            # 成功标志：约 6s 后 URL 从 /post/create 跳到 /post/list。切勿在 Enter 后再点其它「确认」按钮（会打断提交）。
            print("  视频号：聚焦发表并按 Enter…", file=sys.stderr)
            status = fr.evaluate("""() => {
                const b = [...document.querySelectorAll('button')].find(x => (x.innerText||'').trim() === '发表');
                if (!b) return 'no-btn';
                if (b.disabled || b.getAttribute('disabled') !== null) return 'disabled';
                b.scrollIntoView({block: 'center'});
                b.focus();
                return document.activeElement === b ? 'focused' : 'not-focused';
            }""")
            print(f"  视频号：发表按钮状态={status}", file=sys.stderr)
            if status == 'disabled':
                last_err = "发表按钮 disabled（视频可能还在处理）"
                page.wait_for_timeout(5000)
                continue
            if status == 'no-btn':
                last_err = "未找到发表按钮"
                page.wait_for_timeout(3000)
                continue
            page.keyboard.press("Enter")   # 可信提交
            # 等 URL 离开创作页 = 提交成功（真机 ~6s 跳 /post/list）
            for _ in range(12):
                page.wait_for_timeout(2000)
                if "post/create" not in (page.url or "").lower():
                    published = True
                    break
            if not published:
                last_err = "发表后未跳转（可能未提交），换新 frame 重试"
        except Exception as e:
            last_err = e
            page.wait_for_timeout(3000)   # 多半是 frame 刚重载，换新 frame 重试
    if not published:
        raise RuntimeError(f"视频号发表未成功（创作器反复重载或选择器失效）：{last_err}")
    page.wait_for_timeout(3000)


def _run_browser(a, headed: bool, do_publish: bool) -> int:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except Exception as e:
        _die(f"需要 playwright：{e}（pip install playwright && playwright install chromium）", 3)
    profile = _profile_dir(a.platform, a.profile_base)
    profile.mkdir(parents=True, exist_ok=True)
    cfg = PLATFORMS[a.platform]
    ctx = {"media": a.media or "", "title": a.title or "", "desc": a.desc or "",
           "tags": a.tags or "", "cover": a.cover or ""}
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(profile), headless=not headed, args=LAUNCH_ARGS,
            viewport={"width": 1440, "height": 900})
        page = browser.pages[0] if browser.pages else browser.new_page()
        if not do_publish:
            page.goto(cfg["login_url"])
            print(f"已打开 {cfg['name']} 登录页，请在浏览器完成登录（扫码等），登录态保存在 {profile}。",
                  file=sys.stderr)
            print("登录完成后按 Enter 关闭 ...", file=sys.stderr)
            try:
                input()
            except EOFError:
                pass
            browser.close()
            return 0
        # publish：按媒体类型选步骤——图片且平台有图文流程走 steps_image，否则默认 steps
        steps = _resolve_steps(a.platform, ctx, _steps_key_for(cfg, a.media))
        # 发布前登录预检：未登录时发布页会被重定向到落地页，后续 upload 找不到 input 会晦涩超时——提前明确报错
        try:
            page.goto(cfg["publish_url"], wait_until="domcontentloaded")
            _settle_login(page, cfg)  # 等客户端跳转落定，避免 SPA 未跳转期误判已登录（否则后续 upload 撞登录页超时）
        except Exception:
            pass
        if not _is_logged_in(page, cfg):
            _die(f"{cfg['name']}未登录：发布页被重定向到登录/落地页。请先在账号页扫码登录后重试。", 6)
        # 外壳已登录但发布子系统鉴权可能已失效（快手 onvideo token 短命）→ 提前明确报错，
        # 避免后续 upload 因发布态失效而晦涩超时。仅明确失效才拦，瞬时错误放行。
        if cfg.get("login_probe") and _probe_publish_auth(page, cfg) == "expired":
            _die(f"{cfg['name']}登录态已失效（发布子系统未授权）：外壳虽显示已登录，但发布上传鉴权已过期。请在账号页重新扫码登录后重试。", 6)
        try:
            if a.platform == "weixin-channels":
                # 视频号走专用流程（SPA 导航 + iframe 创作器），通用 steps 不适用 → 跳过
                _publish_weixin_channels(page, ctx)
                steps = []
            for i, s in enumerate(steps, 1):
                act = s["action"]
                sel = s.get("selector", "")
                val = s.get("value", "")
                opt = s.get("optional", False)  # 可选步骤失败不中断（如清理旧草稿弹窗）
                print(f"  步骤 {i}/{len(steps)}: {act} {sel}", file=sys.stderr)
                try:
                    if act == "goto":
                        page.goto(val)
                    elif act == "upload":
                        page.set_input_files(sel, val)
                    elif act == "filechooser_upload":
                        # 点上传按钮拦截文件选择器再塞文件（快手图文的图片 input 直接 set 不触发上传）
                        with page.expect_file_chooser(timeout=15000) as fc:
                            el = _first_visible_el(page, sel)
                            if el is None:
                                raise RuntimeError(f"上传按钮未找到：{sel}")
                            el.click()
                        fc.value.set_files(val)
                    elif act == "fill":
                        _fill_first_visible(page, sel, val)
                    elif act == "type":
                        # 富文本编辑器（如知乎 Draft.js）：page.fill 不生效，须点聚焦后真实键入
                        # 长文用剪贴板粘贴，避免逐字 type 超时
                        el = _first_visible_el(page, sel)
                        if el:
                            el.click()
                            try:
                                page.evaluate("""(text) => {
                                    const dt = new DataTransfer();
                                    dt.setData('text/plain', text);
                                    document.activeElement.dispatchEvent(
                                        new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})
                                    );
                                }""", val)
                                page.wait_for_timeout(1000)
                                # 验证内容是否注入成功（Draft.js 可能拒绝）
                                inner = el.inner_text()
                                if not inner or len(inner.strip()) < 10:
                                    raise RuntimeError("clipboard inject failed")
                            except Exception:
                                # 降级：键盘逐字输入（慢但兼容）
                                page.keyboard.type(val)
                    elif act == "js_click":
                        # JS dispatchEvent 点击（快手等框架按钮 Playwright click() 无效）
                        el = _first_visible_el(page, sel)
                        if el is None:
                            raise RuntimeError(f"点击目标未找到：{sel}")
                        try:
                            el_info = page.evaluate("el => ({tag:el.tagName,cls:el.className,txt:(el.innerText||'').trim().slice(0,30)})", el)
                            print(f"  [js_click debug] 找到元素: {el_info}")
                        except Exception:
                            pass
                        try:
                            el.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        # 先尝试 Playwright 原生 force click（React/Vue 合成事件能感知）
                        try:
                            el.click(force=True, timeout=5000)
                        except Exception:
                            # 回退：完整指针事件链（pointerdown→mousedown→mouseup→click）
                            page.evaluate("""
                                el => {
                                    ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(type => {
                                        el.dispatchEvent(new MouseEvent(type, {bubbles:true,cancelable:true,view:window}));
                                    });
                                }
                            """, el)
                    elif act == "screenshot":
                        # 截图到指定路径（相对工作目录）
                        import pathlib as _pl
                        _cwd = _pl.Path.cwd()
                        _sp = _cwd / val if val else _cwd / "outputs/_login/debug-screenshot.png"
                        _sp.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(_sp))
                    elif act == "js_eval":
                        # 直接执行 JS 代码（用于快手等框架按钮，CSS选择器/has-text 匹配不稳定）
                        page.evaluate(val)
                    elif act == "click":
                        # 多候选（快手『发布作品』是 div.publish-button 非 <button>）+ 滚动到可点
                        el = _first_visible_el(page, sel)
                        if el is None:
                            raise RuntimeError(f"点击目标未找到：{sel}")
                        try:
                            el.scroll_into_view_if_needed()
                        except Exception:
                            pass
                        el.click()
                    elif act == "wait":
                        page.wait_for_timeout(int(val or 1000))
                    elif act == "press":
                        page.keyboard.press(val)
                    elif act == "waitfor":
                        page.wait_for_selector(sel, timeout=int(val or 30000))  # 逗号=CSS group
                except Exception as e:
                    if opt:
                        print(f"    (可选步骤跳过：{e})", file=sys.stderr)
                        continue
                    raise
            # 发布结果校验（配置了 publish_success 才验；未配的平台沿用"跑完即报"）
            chk = cfg.get("publish_success")
            if chk:
                ok = False
                deadline = time.time() + 30
                while time.time() < deadline:
                    url = (page.url or "").lower()
                    uc, unc = chk.get("url_contains"), chk.get("url_not_contains")
                    if uc or unc:  # 支持纯 url_not_contains（发布成功后离开发布页）
                        if (uc in url if uc else True) and (unc not in url if unc else True):
                            ok = True
                            break
                    if chk.get("selector") and page.query_selector(chk["selector"]):
                        ok = True
                        break
                    page.wait_for_timeout(500)
                if not ok:
                    try:  # 仅失败时截图，供排错（正常成功不截）
                        fp = Path(__file__).resolve().parents[3] / "outputs" / "_login" / f"{a.platform}-publish-fail.png"
                        fp.parent.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(fp))
                    except Exception:
                        pass
                    # 识别常见"账号级验证墙"（需短信/绑手机），给精准提示
                    body_txt = ""
                    try:
                        body_txt = page.inner_text("body") or ""
                    except Exception:
                        pass
                    if any(k in body_txt for k in ("设置手机号", "绑定手机号", "短信验证", "验证码登录")):
                        _die(f"{cfg['name']}账号需先绑定手机号/短信验证才能发布，headless 无法完成——"
                             f"请在普通浏览器给该账号绑定手机号后重试。", 4)
                    # dump 点发布后出现的弹窗/可点按钮（供补二次确认步骤）
                    try:
                        dlg = page.evaluate("""() => {
                            const out = [];
                            const kws = ['确认','确定','发布','提交','继续','同意'];
                            for (const el of document.querySelectorAll(
                                    '[class*=dialog] button,[class*=dialog] [class*=btn],'
                                    +'[class*=modal] button,[role=dialog] button,[class*=confirm] button,'
                                    +'[class*=popup] button,[class*=publish-button]')) {
                                if (el.offsetParent === null) continue;
                                const t = (el.innerText||'').trim();
                                if (!t || t.length > 10) continue;
                                if (!kws.some(k => t.includes(k))) continue;
                                out.push(el.tagName+' "'+t+'" class='+(el.className||'').toString().slice(0,45));
                            }
                            return [...new Set(out)].slice(0,15).join('\\n');
                        }""")
                        print("    点发布后出现的弹窗/按钮（供补二次确认选择器）：\n"
                              + (dlg or "(无弹窗按钮——可能没触发发布或已直接提交)"), file=sys.stderr)
                    except Exception:
                        pass
                    _die(f"发布未确认成功：步骤跑完但未跳到成功状态（当前 URL={page.url}）。"
                         f"可能『发布』按钮未生效或有二次确认弹窗——需核对选择器。", 5)
                print(f"✅ 发布成功（已确认跳转：{page.url}）")
            else:
                print("✅ 发布步骤执行完毕，请在浏览器/平台后台确认发布结果。")
        except PWTimeout as e:
            # 超时（常见：选择器失效 / 上传转码慢）——截图 + dump 当前可见输入控件，便于精修选择器
            try:
                fp = Path(__file__).resolve().parents[3] / "outputs" / "_login" / f"{a.platform}-publish-fail.png"
                fp.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(fp))
                print(f"    失败截图：{fp}", file=sys.stderr)
            except Exception:
                pass
            try:
                dump = page.evaluate("""() => {
                    const out = [];
                    const q = 'textarea,[contenteditable=true],input[type=text],[placeholder],[data-placeholder]';
                    for (const el of document.querySelectorAll(q)) {
                        if (el.offsetParent === null) continue;
                        const ph = el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '';
                        out.push(el.tagName + ' class=' + (el.className||'').toString().slice(0,45) + ' ph=' + ph.slice(0,30));
                    }
                    return out.slice(0, 20).join('\\n');
                }""")
                print("    当前可见输入控件（供更新 SELECTORS）：\n" + (dump or "(无)"), file=sys.stderr)
            except Exception:
                pass
            _die(f"步骤超时（选择器可能已失效，需更新）：{e}")
        finally:
            if not a.keep_open:
                browser.close()
    return 0


def cmd_login(a) -> int:
    return _run_browser(a, headed=True, do_publish=False)


_LOGIN_MARKERS = ("login", "signin", "passport", "/account/")

# 视频文件扩展名（视频流程平台的媒体类型校验用）
VIDEO_EXTS = {".mp4", ".mov", ".flv", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".ts", ".mpeg", ".mpg"}

# 登录轮询：间隔 1s（原 2s，成功检测延迟减半）；每 N 轮用辅助页深探一次
_LOGIN_POLL_MS = 1000
_LOGIN_PROBE_EVERY = 3


def _is_logged_in(page, cfg: dict) -> bool:
    """判断是否已登录，可靠性顺序：URL 落在登录页 → 登出浮层可见 → 强选择器命中 → URL 启发式兜底。
    强选择器优先于 URL 启发式（快手实测：未登录会重定向到同域落地页，URL≠首页但其实未登录，
    靠 URL 启发式会假阳性；配 login_strict 的平台不命中强选择器即判未登录）。"""
    try:
        url = (page.url or "").lower().rstrip("/")
    except Exception:
        url = ""
    # 1. URL 明确在登录/验证页（视频号→login.html、知乎→signin，实测）
    if any(m in url for m in _LOGIN_MARKERS):
        return False
    # 2. 登出浮层/二维码可见 → 未登录（快手停在发布页但弹登录浮层，实测）
    out_sel = cfg.get("logged_out_selector")
    if out_sel:
        for s in (x.strip() for x in out_sel.split(",")):
            try:
                el = page.query_selector(s) if s else None
                if el and el.is_visible():
                    return False
            except Exception:
                pass
    # 3. 强选择器（login_check）命中 → 已登录（最可靠，优先于 URL 启发式）
    #    必须「可见」才算：快手等 SPA 登出后重定向到同域营销落地页，复用同一份前端 bundle，
    #    创作者中心的 .user-line/.vertical-menu 等外壳节点可能仍存在于 DOM 但被隐藏 →
    #    只用 query_selector（存在性）会假阳性判「已登录」。与上面 logged_out 的 is_visible 判定保持一致。
    sel = cfg.get("login_check")
    if sel:
        for s in (x.strip() for x in sel.split(",")):
            try:
                el = page.query_selector(s) if s else None
                if el and el.is_visible():
                    return True
            except Exception:
                pass
        # 配了 login_check 却都不命中：严格平台（快手：同域落地页 URL 区分不了）直接判未登录
        if cfg.get("login_strict"):
            return False
    # 4. URL 启发式兜底（非严格平台）：已离开登录入口页且无登录标记 → 已登录
    login_url = cfg["login_url"].lower().rstrip("/")
    if url and url != login_url:
        return True
    return False


# 发布子系统鉴权探针的「明确未登录」文案（外壳判定之外的第二道校验，见各平台 cfg["login_probe"]）
_PROBE_LOGOUT_HINTS = ("未登录", "登录态", "请登录", "重新登录", "not login", "not logged", "unauthorized", "登录已过期")
# 快手 REST 常见「登录态失效」result 码（外壳 token 活着但发布 token 已死时该模块会返回它们）
_PROBE_LOGOUT_RESULTS = {109, 100110000}


def _probe_publish_auth(page, cfg: dict) -> str:
    """探发布/上传子系统自己的鉴权，返回 'ok' | 'expired' | 'unknown'。
    背景：某些平台（快手）创作者中心「外壳」token 比「发布上传」token 活得久，
    外壳 DOM 判定会在发布态早已失效后仍报已登录。故在外壳判定为已登录后，用页面上下文
    （带 cookie、同源）再打一次发布模块自己的接口。
    fail-safe：只有明确失效信号（跳登录页 / 401·403 / 未登录 result·文案）才返回 'expired'；
    瞬时错误、网络失败、未知 result 一律 'unknown'，让调用方保留外壳判定，绝不把有效会话翻成未登录。"""
    probe = cfg.get("login_probe")
    if not probe:
        return "unknown"
    try:
        r = page.evaluate(
            """async ({u,m}) => {
                try {
                  const resp = await fetch(u, {method:m||'GET', credentials:'include',
                                               headers:{'accept':'application/json'}});
                  const t = await resp.text();
                  return {status: resp.status, redirected: resp.redirected, finalUrl: resp.url, body: (t||'').slice(0,600)};
                } catch(e) { return {error: String(e)}; }
            }""",
            {"u": probe["url"], "m": probe.get("method", "GET")},
        )
    except Exception:
        return "unknown"
    if not isinstance(r, dict) or r.get("error"):
        return "unknown"
    final = (r.get("finalUrl") or "").lower()
    if r.get("redirected") and any(m in final for m in _LOGIN_MARKERS):
        return "expired"
    if r.get("status") in (401, 403):
        return "expired"
    body = r.get("body") or ""
    ok_results = probe.get("ok_result") or []
    try:
        d = json.loads(body)
    except Exception:
        d = None
    if isinstance(d, dict):
        res = d.get("result", d.get("code"))
        if res in ok_results:
            return "ok"
        if res in _PROBE_LOGOUT_RESULTS:
            return "expired"
        msg = str(d.get("message") or d.get("msg") or "")
        if any(h in msg.lower() if h.isascii() else h in msg for h in _PROBE_LOGOUT_HINTS):
            return "expired"
        return "unknown"  # 未知 result（如快手 500002「请稍后重试」瞬时）→ 不翻转
    if any((h in body.lower() if h.isascii() else h in body) for h in _PROBE_LOGOUT_HINTS):
        return "expired"
    return "unknown"


def _settle_login(page, cfg: dict, max_ms: int = 7000) -> None:
    """判登录态前先等客户端跳转/渲染尘埃落定，再交给 _is_logged_in。
    视频号等 SPA：死会话打开发布页后 URL 要 3-4s 才客户端跳回 login.html，
    过早判定会命中 _is_logged_in 的 URL 启发式（URL≠入口且无 login 标记）→ 误报已登录。
    轮询到任一明确信号即停：URL 出现登录标记（未登录）/ login_check 命中（已登录）/ 超时。
    负向信号（跳回 login.html）可靠，不依赖 login_check 选择器是否准确。"""
    deadline = time.time() + max_ms / 1000
    checks = [x.strip() for x in (cfg.get("login_check") or "").split(",") if x.strip()]
    while time.time() < deadline:
        try:
            u = (page.url or "").lower()
        except Exception:
            u = ""
        if any(m in u for m in _LOGIN_MARKERS):
            return  # 已跳到登录/验证页 → 明确未登录
        for s in checks:
            try:
                el = page.query_selector(s)
                if el and el.is_visible():
                    return  # 命中可见的登录后元素 → 明确已登录（隐藏的外壳骨架不算，见 _is_logged_in 注释）
            except Exception:
                pass
        page.wait_for_timeout(400)


_QR_SELECTORS = (".login-qr", "[class*=login-qr]", "[class*=qrcode]", "[class*=qr-code]",
                 "[class*=qrCode]", "[class*=scan-code]", "canvas", "img[src*=qr]", "img[src*=QR]")

# 截二维码前先等它真正渲染（异步 base64/canvas 二维码，固定 wait 不够会截到空框/别的图）。
# 平台可用 cfg["qr_loaded"] override；否则用这个通用默认。
_QR_LOADED_DEFAULT = ("img[src^='data:image'], canvas, [class*=qrcode] img, "
                      "[class*=qrcode] canvas, .login-qr img, img[src*=qr]")


def _score_qr_el(el) -> float | None:
    """给候选元素打「像不像二维码」的分：可见 + 接近正方形 + 尺寸合适才入选；
    base64 img / canvas 本体加权（二维码几乎都是它们）。不合格返回 None。"""
    try:
        if not el.is_visible():
            return None
        b = el.bounding_box()
    except Exception:
        return None
    if not b:
        return None
    w, h = b["width"], b["height"]
    # 尺寸：收紧到 140~600（原 120~520 太松，logo/广告/头像会误命中）
    if w < 140 or h < 140 or w > 600 or h > 600:
        return None
    ratio = w / h if h else 0
    if not (0.75 <= ratio <= 1.34):   # 二维码接近正方形，排除横幅/文字条
        return None
    score = float(min(w, h))
    try:
        tag = (el.evaluate("e => e.tagName") or "").lower()
        src = el.get_attribute("src") or ""
        if tag == "img" and src.startswith("data:image"):
            score += 10000        # base64 img = 二维码本体，最优先
        elif tag == "canvas":
            score += 5000
        elif tag == "img" and ("qr" in src.lower()):
            score += 2000
    except Exception:
        pass
    return score


def _crop_qr(page, qr_out, cfg) -> None:
    """把登录二维码裁出来单独存图（而非整页）。遍历平台配置 + 常见选择器的所有候选，
    用 _score_qr_el 挑「最像二维码」的那个（base64/canvas 本体 + 接近正方形 + 尺寸合适），
    而不是遇到第一个宽松方形就用；都不中才退回整页。
    ⚠️ 调用前应先等二维码渲染（见 cmd_login_qr 的 qr_loaded 等待），否则可能截到空框。"""
    cands: list[str] = []
    if cfg.get("login_qr_selector"):  # 拆逗号逐个试，保证具体选择器优先于容器
        cands += [s.strip() for s in cfg["login_qr_selector"].split(",") if s.strip()]
    cands += list(_QR_SELECTORS)
    best = None  # (score, el)
    for sel in cands:
        try:
            els = page.query_selector_all(sel)
        except Exception:
            continue
        for el in els:
            sc = _score_qr_el(el)
            if sc is None:
                continue
            if best is None or sc > best[0]:
                best = (sc, el)
    if best is not None:
        try:
            best[1].screenshot(path=str(qr_out))
            return
        except Exception:
            pass
    page.screenshot(path=str(qr_out))   # 兜底：整页


def _capture_qr(page, qr_out, cfg) -> None:
    """截登录二维码到 qr_out，按平台形态分两条路：
    - 码在跨域 iframe（视频号：open.weixin.qq.com 的微信标准扫码组件）→ 主页面 query_selector 找不到，
      直接截 <iframe> 元素本体（真机验证得清晰码；iframe 内 img 是相对 URL 非 base64，打分裁剪那套不适用）。
    - 码在主页面 → 先等它渲染（qr_loaded），再用 _crop_qr 按打分裁剪最像二维码的元素。"""
    ifr = cfg.get("login_qr_iframe")
    if ifr:
        try:
            page.wait_for_selector(ifr, timeout=15000, state="visible")
            # 等 iframe 内二维码 img attach（跨域 frame 里 img 的 visible 判定不稳，用 attached 兜底）
            for fr in page.frames:
                if fr != page.main_frame and "qrconnect" in (fr.url or ""):
                    try:
                        fr.wait_for_selector(
                            "img.js_qrcode_img, img.web_qrcode_img, img[src*='/connect/qrcode/']",
                            timeout=10000, state="attached")
                    except Exception:
                        pass
                    break
            page.wait_for_timeout(800)  # 让二维码画完再截
            el = page.query_selector(ifr)
            if el:
                el.screenshot(path=str(qr_out))
                return
        except Exception:
            pass  # iframe 路径任何异常都退回主页面裁剪
    # 主页面二维码：先等渲染（异步 base64/canvas，固定 wait 不够会截到空框），再打分裁剪
    try:
        page.wait_for_selector(cfg.get("qr_loaded") or _QR_LOADED_DEFAULT,
                               timeout=15000, state="visible")
    except Exception:
        pass
    _crop_qr(page, qr_out, cfg)


def _probe_logged_in(browser, cfg: dict) -> bool:
    """用辅助页 goto 发布页探测登录态——针对扫码成功后停在 passport/login 域、
    不自动跳回创作者中心的平台（快手实测：点『立即登录』跳 passport，扫码后停在 passport
    不自跳，主扫码页 URL 恒含 passport → _is_logged_in 恒 False → 一直超时）。
    持久化 context 内 cookie 共享：已登录则辅助页能直接进发布页。不动主扫码页（保留二维码）。"""
    probe = None
    try:
        probe = browser.new_page()
        probe.goto(cfg.get("publish_url") or cfg["login_url"],
                   wait_until="domcontentloaded", timeout=20000)
        _settle_login(probe, cfg)  # 等客户端跳转落定（视频号死会话 3-4s 才跳回 login.html）
        return _is_logged_in(probe, cfg)
    except Exception:
        return False
    finally:
        if probe:
            try:
                probe.close()
            except Exception:
                pass


def cmd_login_qr(a) -> int:
    """headless 抠二维码登录（供 Web 前端）：截登录页二维码 → 轮询登录成功 → 持久化。
    状态写 login_state JSON 供后端轮询。同 xhs_publish.py login 的机制。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    cfg = PLATFORMS.get(a.platform)
    if not cfg:
        _die(f"未知平台：{a.platform}（支持：{', '.join(PLATFORMS)}）")
    profile = _profile_dir(a.platform, a.profile_base)
    profile.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[3] / "outputs" / "_login"
    qr_out = Path(a.qr_out).expanduser() if a.qr_out else root / f"{a.platform}.png"
    sf = a.status_file or str(root / f"{a.platform}.json")
    timeout_s = a.timeout or 180

    login_state.write_status(sf, "starting")
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            str(profile), headless=True, locale="zh-CN",
            args=LAUNCH_ARGS)
        page = browser.pages[0] if browser.pages else browser.new_page()
        try:
            page.goto(cfg["login_url"], wait_until="domcontentloaded")
            # 给客户端 redirect + 登录态渲染时间：已登录常从入口页跳到 /profile 等，
            # 固定 1.2s 经常不够（快手实测 → 误判未登录去截整页）。等 login_check 出现最多 6s。
            try:
                page.wait_for_selector(cfg["login_check"], timeout=6000)
            except Exception:
                page.wait_for_timeout(1200)
            if _is_logged_in(page, cfg):
                login_state.write_status(sf, "success", "已登录")
                print(f"✅ {cfg['name']} 已登录（登录态在持久化目录）")
                return 0

            # 登录预备步骤（如快手：点『立即登录』跳 passport 再切『扫码登录』才出二维码）
            for step in cfg.get("login_prep", []):
                try:
                    if "click" in step:
                        el = page.query_selector(step["click"])
                        if el:
                            el.click()
                    if "wait" in step:
                        page.wait_for_timeout(step["wait"])
                except Exception:
                    pass

            # 截二维码为 PNG。视频号等把码放在跨域 iframe 里（主页面找不到）→ 截 iframe 元素本体；
            # 其余平台在主页面异步渲染（base64/canvas）→ 先等渲染再按打分裁剪。统一走 _capture_qr。
            qr_out.parent.mkdir(parents=True, exist_ok=True)
            _capture_qr(page, qr_out, cfg)
            login_state.write_status(sf, "qr_ready", f"扫码登录 {cfg['name']}", qr=str(qr_out))
            print(f"📱 {cfg['name']} 登录页/二维码已保存：{qr_out}", file=sys.stderr)
            print(f"⏳ 等待扫码（最长 {timeout_s}s）...", file=sys.stderr)

            confirmed = False
            tick = 0
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                tick += 1
                if _is_logged_in(page, cfg):
                    confirmed = True
                    break
                # 扫码页仍停在 passport/login 域时深探：用辅助页 goto 发布页判登录态
                # （快手扫码成功不自跳创作者中心，主扫码页 URL 恒含 passport）
                try:
                    cur = (page.url or "").lower()
                except Exception:
                    cur = ""
                if tick % _LOGIN_PROBE_EVERY == 0 and any(m in cur for m in _LOGIN_MARKERS):
                    if _probe_logged_in(browser, cfg):
                        confirmed = True
                        break
                page.wait_for_timeout(_LOGIN_POLL_MS)
            if confirmed:
                login_state.write_status(sf, "success", "登录成功")
                print(f"✅ {cfg['name']} 登录成功，登录态已持久化")
                try:
                    qr_out.unlink()
                except OSError:
                    pass
                return 0
            login_state.write_status(sf, "expired", "二维码超时未扫")
            print(f"⏱️ {timeout_s}s 内未检测到登录成功（二维码可能过期）", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001 — 任何异常都写 error 终态，否则前端轮询会卡在 starting/qr_ready
            login_state.write_status(sf, "error", f"登录异常：{e}")
            print(f"❌ {cfg['name']} 登录异常：{e}", file=sys.stderr)
            return 1
        finally:
            browser.close()


def cmd_publish(a) -> int:
    if not a.media and a.platform != "zhihu":
        _die("--media 媒体文件必填")
    if a.media and not Path(a.media).expanduser().is_file():
        _die(f"媒体文件不存在：{a.media}")
    # 媒体类型校验：视频流程平台给图片会晦涩超时；但若平台有图文流程（steps_image）则放行走图文
    cfg = PLATFORMS.get(a.platform, {})
    if cfg.get("media_kind") == "video" and a.media and not cfg.get("steps_image"):
        ext = Path(a.media).suffix.lower()
        if ext not in VIDEO_EXTS:
            _die(f"{cfg.get('name', a.platform)}走视频发布流程，需视频文件（{', '.join(sorted(VIDEO_EXTS))}），"
                 f"当前选的是 {ext or '无扩展名'} 文件（{Path(a.media).name}）。"
                 f"请改选视频文件；图文（发图片）发布暂未支持。", 7)
    if not a.exec:
        print("dry-run（加 --exec 真正发布）：")
        content_guard.guard_or_die([a.title, a.desc, a.tags], exec_mode=False,
                                   allow_unsafe=getattr(a, "allow_unsafe", False),
                                   label=f"{cfg.get('name', a.platform)}发布内容")
        return cmd_plan(a)
    # 出站内容安全闸门：真发前扫描标题/正文/话题，检出内部设置泄露即阻止发布。
    content_guard.guard_or_die([a.title, a.desc, a.tags], exec_mode=True,
                               allow_unsafe=getattr(a, "allow_unsafe", False),
                               label=f"{cfg.get('name', a.platform)}发布内容")
    rc = _run_browser(a, headed=a.headed, do_publish=True)
    if rc == 0:
        # 发布成功 → 落统一内容日历（对话页自动；发布页 web 设 AUTORECORD=0 跳过防重复）
        try:
            import calendar_ops
            ptype = ("文章" if a.platform == "zhihu"
                     else ("视频" if a.media and Path(a.media).suffix.lower() in VIDEO_EXTS
                           else "图文"))
            calendar_ops.record_publish(a.platform, a.title or (a.desc or "")[:20],
                                        ptype=ptype, tags=(a.tags or ""),
                                        note=(a.desc or ""), source="chat")
        except Exception:
            pass
    return rc


def cmd_whoami(a) -> int:
    """真校验登录态 + 读昵称/头像，输出单行 JSON（供 Web 后端解析）。
    走发布页判定（比 avatar 选择器可靠）：URL 落登录页 / 登出浮层可见 → 未登录。
    昵称/头像选择器为 best-effort，各平台登录后需校验。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(json.dumps({"loggedIn": False, "name": "", "avatar": "", "error": f"playwright:{e}"}))
        return 0
    cfg = PLATFORMS.get(a.platform)
    if not cfg:
        print(json.dumps({"loggedIn": False, "name": "", "avatar": "", "error": "unknown platform"}))
        return 0
    result = {"loggedIn": False, "name": "", "avatar": ""}
    try:
        with sync_playwright() as p:
            profile = _profile_dir(a.platform, a.profile_base)
            profile.mkdir(parents=True, exist_ok=True)
            browser = p.chromium.launch_persistent_context(
                str(profile), headless=True, locale="zh-CN",
                args=LAUNCH_ARGS)
            page = browser.pages[0] if browser.pages else browser.new_page()
            try:
                page.goto(cfg["publish_url"], wait_until="domcontentloaded", timeout=30000)
                _settle_login(page, cfg)  # 等客户端跳转落定，避免 SPA 未跳转期误判已登录
                logged = _is_logged_in(page, cfg)
                # 外壳判已登录后，再探发布子系统鉴权：外壳 token 活着但发布 token 已死时翻成未登录
                if logged and cfg.get("login_probe"):
                    pa = _probe_publish_auth(page, cfg)
                    result["publishAuth"] = pa
                    if pa == "expired":
                        logged = False
                        result["reason"] = "publish_auth_expired"
                result["loggedIn"] = logged
                if logged:
                    for s in (cfg.get("me_name_selector") or "").split(","):
                        s = s.strip()
                        if not s:
                            continue
                        el = page.query_selector(s)
                        if el:
                            t = (el.inner_text() or "").strip()
                            if t:
                                result["name"] = t.splitlines()[0][:40]
                                break
                    for s in (cfg.get("me_avatar_selector") or "").split(","):
                        s = s.strip()
                        if not s:
                            continue
                        el = page.query_selector(s)
                        if el:
                            src = el.get_attribute("src")
                            if src:
                                result["avatar"] = src
                                break
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — whoami 永远输出 JSON
        result["error"] = str(e)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_selftest(_a) -> int:
    print("web_publisher 自检（离线）...", file=sys.stderr)
    assert PLATFORMS, "配置为空"
    for k, c in PLATFORMS.items():
        for key in ("name", "login_url", "publish_url", "profile", "steps", "selector_caveat"):
            assert key in c, f"{k} 缺字段 {key}"
        assert c["steps"], f"{k} 无步骤"
        assert c.get("login_check"), f"{k} 缺 login_check（QR 登录判定用）"
        for st in c["steps"]:
            assert st["action"] in _ACTIONS, f"{k} 非法 action {st['action']}"
    # 占位符解析
    steps = _resolve_steps("kuaishou", {"media": "/x/a.mp4", "title": "标题",
                                        "desc": "", "tags": "#话题", "cover": ""})
    up = [s for s in steps if s["action"] == "upload"][0]
    assert up["value"] == "/x/a.mp4", "media 占位符未替换"
    fill = [s for s in steps if s["action"] == "fill"][0]
    assert "标题" in fill["value"] and "#话题" in fill["value"], "title/tags 未替换"
    # 未知平台
    try:
        _resolve_steps("nope", {})
        raise AssertionError("未知平台未报错")
    except SystemExit:
        pass
    # profile 目录路由
    pd = _profile_dir("zhihu", None)
    assert pd.name == "ZhihuProfile", "profile 目录名不对"
    # 登录轮询提速 + 深探（快手扫码后停在 passport 不自跳的修复）
    assert _LOGIN_POLL_MS <= 1000, "轮询间隔应 ≤1s（成功检测延迟）"
    assert _LOGIN_PROBE_EVERY >= 1 and callable(_probe_logged_in)
    assert "passport" in _LOGIN_MARKERS, "passport 应在登录标记内（快手 passport 扫码页）"
    # 二维码打分：base64 img > canvas > 普通方图；非正方/过小/过大剔除（用轻量假元素离线测）
    class _FakeEl:
        def __init__(self, box, tag="div", src=""):
            self._box, self._tag, self._src = box, tag, src
        def is_visible(self):
            return True
        def bounding_box(self):
            return self._box
        def evaluate(self, _js):
            return self._tag
        def get_attribute(self, _n):
            return self._src
    sq = {"width": 220, "height": 220}
    b64 = _score_qr_el(_FakeEl(sq, "img", "data:image/png;base64,AAAA"))
    canv = _score_qr_el(_FakeEl(sq, "canvas"))
    plain = _score_qr_el(_FakeEl(sq, "div"))
    assert b64 and canv and plain and b64 > canv > plain, "二维码本体应加权优先"
    assert _score_qr_el(_FakeEl({"width": 60, "height": 60}, "img", "data:image/x")) is None, "过小应剔除"
    assert _score_qr_el(_FakeEl({"width": 400, "height": 90}, "canvas")) is None, "非正方（横条）应剔除"
    assert _QR_LOADED_DEFAULT and "data:image" in _QR_LOADED_DEFAULT
    # 多候选选择器拆分（修 split(',')[0] 丢兜底的坑）
    assert _split_sels("a, b ,c") == ["a", "b", "c"] and _split_sels("") == []
    # 快手发布步骤健壮化：清旧草稿(optional) + 描述框多候选 + 转码等待够长
    ks = PLATFORMS["kuaishou"]["steps"]
    assert any(s.get("optional") and s["action"] == "click" for s in ks), "缺清理旧草稿的 optional 步骤"
    wf = [s for s in ks if s["action"] == "waitfor"][0]
    assert "," in wf["selector"] and int(wf["value"]) >= 120000, "描述框应多候选且等待≥120s（转码慢）"
    # 真发布按钮走 js_click（JS dispatchEvent；标准 click/:has-text 对该按钮不可靠）——
    # 断言非 optional 的 click/js_click 提交步命中 button-primary（非 <button>、非左侧导航『发布作品』）
    pub_click = [s for s in ks if s["action"] in ("click", "js_click") and not s.get("optional")][-1]
    assert "button-primary" in pub_click["selector"], \
        "快手发布按钮应为 [class*=button-primary]『发布』（走 js_click 派发；非 <button>，非导航『发布作品』）"
    # 视频流程平台的媒体类型标记（快手/视频号只收视频，给图片会晦涩超时）
    assert PLATFORMS["kuaishou"].get("media_kind") == "video", "快手应标记 media_kind=video"
    assert ".mp4" in VIDEO_EXTS and ".png" not in VIDEO_EXTS
    # 快手图文流程（发图片走 steps_image：切图文 tab + filechooser 上传图片）
    ksi = PLATFORMS["kuaishou"].get("steps_image")
    assert ksi, "快手应有 steps_image（图文发布）"
    assert any(s["action"] == "filechooser_upload" for s in ksi), "图文上传应用 filechooser_upload"
    assert any(s["action"] == "click" and "上传图文" in s.get("selector", "") for s in ksi), "图文流程应切『上传图文』tab"
    # 图文步骤占位符 + action 合法性（复用 _resolve_steps 校验）
    isteps = _resolve_steps("kuaishou", {"media": "/x/a.png", "title": "标题", "desc": "正文", "tags": ""}, "steps_image")
    assert any(s["action"] == "filechooser_upload" and s["value"] == "/x/a.png" for s in isteps), "图文 media 占位符未替换"
    # 视频号二维码在跨域 iframe（open.weixin.qq.com 的微信扫码组件）——必须配 login_qr_iframe 并走 _capture_qr 截 iframe 本体
    wc = PLATFORMS["weixin-channels"]
    assert "open.weixin.qq.com" in wc.get("login_qr_iframe", ""), "视频号应配 login_qr_iframe（码在跨域 iframe，主页面找不到）"
    assert "open.weixin.qq.com" in wc.get("logged_out_selector", ""), "视频号未登录信号应认扫码 iframe"
    assert callable(_capture_qr), "缺 _capture_qr（iframe 感知的二维码截取）"
    # SPA 客户端跳转落定后再判登录态（修视频号未跳转期 URL 启发式误报已登录的假阳性）
    assert callable(_settle_login), "缺 _settle_login（判登录态前等客户端跳转落定）"
    print(f"✅ selftest 通过（{len(PLATFORMS)} 平台配置完整 + 步骤/占位符解析 + 路由 + 登录轮询/深探 "
          "+ 二维码打分/iframe 截取 + 多候选/快手健壮化）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="通用浏览器发布框架（Playwright，配置驱动，登录态持久化）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--platform", required=True, choices=list(PLATFORMS))
        p.add_argument("--media", help="视频/图片文件")
        p.add_argument("--title", help="标题")
        p.add_argument("--desc", help="正文/简介")
        p.add_argument("--tags", help="话题标签（如 '#AI #教程'）")
        p.add_argument("--cover", help="封面")
        p.add_argument("--profile-base", help="登录态根目录（默认 ~/.easel-browser-profiles）")

    sub.add_parser("platforms", help="列出平台").set_defaults(func=cmd_platforms)
    sub.add_parser("check", help="检查 playwright/内核").set_defaults(func=cmd_check)

    p = sub.add_parser("plan", help="发布步骤预览（dry-run）")
    add_common(p)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("login", help="有头浏览器登录并持久化")
    add_common(p)
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("login-qr", help="headless 抠二维码登录（供 Web 前端）")
    add_common(p)
    p.add_argument("--qr-out", help="二维码图片输出路径")
    p.add_argument("--status-file", help="登录状态 JSON 输出路径（供 Web 后端轮询）")
    p.add_argument("--timeout", type=int, help="等待扫码超时秒数（默认 180）")
    p.set_defaults(func=cmd_login_qr)

    p = sub.add_parser("publish", help="网页发布")
    add_common(p)
    p.add_argument("--exec", action="store_true", help="真正发布（默认 dry-run）")
    p.add_argument("--allow-unsafe", action="store_true",
                   help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    p.add_argument("--headed", action="store_true", help="有头模式执行（便于观察/首次校验）")
    p.add_argument("--keep-open", action="store_true", help="发布后不关闭浏览器")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("whoami", help="真校验登录态 + 读昵称/头像（输出 JSON）")
    add_common(p)
    p.set_defaults(func=cmd_whoami)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
