#!/usr/bin/env python3
"""xhs_comment.py — 小红书评论抓取 + 回复（Playwright，headless 可用）。

与 xhs_publish.py **共用同一持久化登录态**（XiaohongshuProfile）；登录用 xhs_publish.py login。
确定性 IO（抓评论/定位回复框/发送）在本脚本；回复文案由上层（agent 结合画像）给定，脚本不编内容。

子命令：check / fetch / reply / plan / selftest
  - fetch：拦截 comment/page 接口响应 → 输出评论 JSON（含子评论）。
  - reply：按 [{id,nickname,reply}] 逐条回评；**默认 dry-run，加 --exec 才真发**；--replied-file 去重。
真实抓取/回复需：playwright + chromium + 已登录 + 干净网络（小红书对代理出口常判风险，建议 --no-proxy）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content_guard  # noqa: E402  出站内容安全闸门

PROFILE_NAME = "XiaohongshuProfile"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
NOTE_URL = "https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_creatormng"

# 选择器/脚本集中维护（小红书改版时单点更新）。
SELECTORS = {
    # 评论作者昵称元素（用于定位某条评论）
    "author": ".author",
    # 回复输入框（小红书用 contenteditable div，非 textarea；多候选防御式）
    "reply_input": ["[contenteditable='true']", "[placeholder*='回复']",
                    "[placeholder*='说点']", "textarea"],
    # 发送按钮
    "send_btn": ["button:has-text('发送')", "text=发送", "[class*='send-btn']", "[class*='submit']"],
    # 未登录标志（出现则说明登录态失效）
    "login_hint": ".login-container, [class*='login-btn'], button:has-text('登录')",
    # 删除评论：某条评论上的「更多/···」触发（hover 后出现，多候选防御式，不用坐标）
    "comment_more": ["[class*='more']", "[class*='dots']", "[class*='icon-more']",
                     ".more-icon", "svg[class*='more']", "[class*='operation']"],
    # 主评论输入框（底部常驻，非点击「回复」后弹出；用于发顶层评论）
    "main_comment_input": [
        "[placeholder*='说点什么']",
        "[placeholder*='来聊聊']",
        "[placeholder*='说点']",
        ".comment-input-box [contenteditable='true']",
        ".note-comment [contenteditable='true']",
        "[class*='comment-input'] [contenteditable='true']",
        "[class*='comment-bar'] [contenteditable='true']",
        "[class*='commentInput'] [contenteditable='true']",
    ],
    # 评论输入区触发器（点击后弹出输入框）
    "comment_trigger": [
        "[class*='comment-bar']",
        "[class*='input-area']",
        "[class*='comment-input-box']",
        ".comment-input",
    ],
}

# 删除流程的文案（菜单项 / 确认按钮）——按文本匹配，跨改版稳，绝不用坐标
DELETE_MENU_TEXTS = ("删除评论", "删除")
CONFIRM_TEXTS = ("确定", "删除", "确认")

# 在某昵称的评论容器内找「回复」按钮（nickname 作为参数传入，避免选择器注入）
_FIND_REPLY_BTN_JS = """(nickname) => {
    const authors = Array.from(document.querySelectorAll('.author'));
    const target = authors.find(a => a.textContent.trim() === nickname);
    if (!target) return null;
    let container = target.parentElement;
    for (let i = 0; i < 6 && container; i++) {
        for (const el of container.querySelectorAll('*')) {
            if (el.textContent.trim() === '回复' && el.children.length === 0 && el.offsetParent !== null) {
                return el;
            }
        }
        container = container.parentElement;
    }
    return null;
}"""

# 按昵称(+可选内容片段)定位某条评论的容器（返回元素，供 hover/找「更多」触发）。
# 传参数进 JS，避免选择器注入；content 用于同名去歧义（同一人多条评论时按内容片段命中）。
_FIND_COMMENT_JS = """([nickname, content]) => {
    const authors = Array.from(document.querySelectorAll('.author'));
    const cand = authors.filter(a => a.textContent.trim() === nickname);
    for (const a of cand) {
        let c = a.parentElement;
        for (let i = 0; i < 6 && c; i++) {
            if (!content || (c.textContent || '').includes(content)) return c;
            c = c.parentElement;
        }
    }
    return null;
}"""

# 点击弹出菜单里文本匹配的项（删除菜单项）；只点可见的，返回是否点到。
_CLICK_MENU_ITEM_JS = """(texts) => {
    const items = Array.from(document.querySelectorAll(
        "[class*='menu-item'], [role='menuitem'], .dropdown-item, li, [class*='dropdown'] *"));
    const el = items.find(e => e.offsetParent !== null && texts.includes((e.textContent || '').trim()));
    if (el) { el.click(); return true; }
    return false;
}"""

# 点击确认弹窗里文本匹配的按钮（确定/删除）；只点可见的，返回是否点到。
_CLICK_CONFIRM_JS = """(texts) => {
    const btns = Array.from(document.querySelectorAll(
        "[class*='foot-btn'], [class*='dialog'] button, [class*='modal'] button, "
        + "[class*='dialog'] [class*='btn'], button, [role='button']"));
    const el = btns.find(e => e.offsetParent !== null && texts.some(t => (e.textContent || '').trim() === t));
    if (el) { el.click(); return true; }
    return false;
}"""

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--no-first-run", "--no-default-browser-check", "--mute-audio",
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


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


def _debug_on() -> bool:
    return bool(os.environ.get("EASEL_COMMENT_DEBUG"))


def _shot(page, name: str) -> None:
    """排错截图：仅 EASEL_COMMENT_DEBUG=1 时存到 outputs/_login/comment-*.png。"""
    if not _debug_on():
        return
    try:
        out = PROJECT_ROOT / "outputs" / "_login" / f"comment-{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 纯函数（可离线自测）
# --------------------------------------------------------------------------- #
def _norm_comment(c: dict, parent: str = "") -> dict:
    """把小红书评论接口的一个节点规范成稳定字段（schema 可能随改版变，故全用 .get 兜底）。"""
    ui = c.get("user_info") or c.get("user") or {}
    t = c.get("create_time") or c.get("time") or 0
    try:
        t = int(t)
    except (TypeError, ValueError):
        t = 0
    time_str = ""
    if t:
        ts = t / 1000 if t > 1_000_000_000_000 else t
        try:
            time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        except (ValueError, OSError):
            time_str = ""
    like = c.get("like_count") or c.get("liked_count") or c.get("like") or ""
    return {
        "id": c.get("id") or c.get("comment_id") or "",
        "nickname": ui.get("nickname") or ui.get("nick_name") or c.get("nickname") or "",
        "content": c.get("content") or c.get("text") or "",
        "time": t,
        "time_str": time_str,
        "loc": c.get("ip_location") or c.get("ip_location_name") or "",
        "like": str(like),
        "parent": parent,
    }


def _collect_comments(raw_pages: list, limit: int = 0) -> list[dict]:
    """从多个 comment/page 响应体里抽取并去重评论（含子评论）。"""
    seen: set[str] = set()
    out: list[dict] = []

    def _add(node: dict, parent: str = ""):
        n = _norm_comment(node, parent)
        if n["id"] and n["id"] not in seen:
            seen.add(n["id"])
            out.append(n)
        for sc in (node.get("sub_comments") or node.get("subComments") or []):
            _add(sc, parent=n["id"])

    for pg in raw_pages:
        if not isinstance(pg, dict):
            continue
        data = pg.get("data") if isinstance(pg.get("data"), dict) else pg
        comments = data.get("comments") if isinstance(data, dict) else None
        for c in comments or []:
            if isinstance(c, dict):
                _add(c)
    return out[:limit] if limit and limit > 0 else out


def _load_replied(path: str | None) -> set[str]:
    if not path or not os.path.exists(path):
        return set()
    try:
        return set(json.load(open(path, encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError):
        return set()


def _save_replied(path: str | None, ids: set[str]) -> None:
    if not path:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        json.dump(sorted(ids), open(path, "w", encoding="utf-8"), ensure_ascii=False)
    except OSError:
        pass


def _parse_replies(raw: str | None) -> list[dict]:
    if not raw:
        _die("--replies-json 必填（格式 [{id,nickname,reply}]）")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _die(f"--replies-json 不是合法 JSON：{e}")
    if not isinstance(data, list):
        _die("--replies-json 应为数组 [{id,nickname,reply}]")
    out = []
    for i, r in enumerate(data):
        if not isinstance(r, dict) or not r.get("nickname") or not r.get("reply"):
            _die(f"第 {i + 1} 条缺 nickname 或 reply：{r}")
        out.append({"id": str(r.get("id") or ""), "nickname": str(r["nickname"]), "reply": str(r["reply"])})
    return out


def _parse_targets(json_str: str | None, nickname: str | None, content: str | None) -> list[dict]:
    """解析要删除的评论目标：--targets-json '[{nickname,content?,id?}]'（批量）或 --nickname(+--content)（单条）。
    content 片段用于同名去歧义。纯函数、可离线自测。"""
    if json_str:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            _die("--targets-json 不是合法 JSON")
        if not isinstance(data, list):
            _die("--targets-json 应为数组 [{nickname,content?,id?}]")
        out = []
        for i, t in enumerate(data):
            if not isinstance(t, dict) or not t.get("nickname"):
                _die(f"第 {i + 1} 条缺 nickname：{t}")
            out.append({"id": str(t.get("id") or ""), "nickname": str(t["nickname"]),
                        "content": str(t.get("content") or "")})
        return out
    if nickname:
        return [{"id": "", "nickname": str(nickname), "content": str(content or "")}]
    _die("需要 --targets-json 或 --nickname 指定要删除的评论", 2)


# --------------------------------------------------------------------------- #
# 浏览器
# --------------------------------------------------------------------------- #
def _launch(p, headed: bool, base: str | None, proxy: str | None):
    profile = _profile_dir(base)
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = dict(headless=not headed, locale="zh-CN", args=LAUNCH_ARGS)
    if proxy:
        kwargs["proxy"] = {"server": proxy}
    return p.chromium.launch_persistent_context(str(profile), **kwargs)


def _open_note(page, note_id: str, token: str):
    page.goto(NOTE_URL.format(note_id=note_id, token=token), timeout=30000)
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_timeout(5000)


def _logged_in(page) -> bool:
    """best-effort：出现登录入口即视作未登录（登录态与 xhs_publish 共用）。"""
    try:
        el = page.query_selector(SELECTORS["login_hint"])
        return not (el and el.is_visible())
    except Exception:
        return True


def _scroll_comments(page, rounds: int) -> None:
    for _ in range(max(1, rounds)):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)
    page.evaluate("window.scrollTo(0, 400)")
    page.wait_for_timeout(800)


def _do_reply(page, nickname: str, text: str) -> bool:
    """定位某昵称评论 → 点回复 → 逐字输入 → 发送。真实发送（调用方已确认 --exec）。"""
    handle = page.evaluate_handle(_FIND_REPLY_BTN_JS, nickname)
    btn = handle.as_element()
    if not btn:
        print(f"  ❌ @{nickname}: 未找到回复按钮（重名或已改版）", file=sys.stderr)
        return False
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_timeout(1500)
    _shot(page, f"{nickname[:6]}-clicked")

    inp = None
    for sel in SELECTORS["reply_input"]:
        try:
            inp = page.wait_for_selector(sel, timeout=3000, state="visible")
            if inp:
                break
        except Exception:
            continue
    if not inp:
        print(f"  ❌ @{nickname}: 回复输入框未出现", file=sys.stderr)
        return False
    inp.click()
    page.wait_for_timeout(300)
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(30, 90))
    page.wait_for_timeout(600)
    _shot(page, f"{nickname[:6]}-typed")

    for sel in SELECTORS["send_btn"]:
        try:
            sb = page.query_selector(sel)
            if sb and sb.is_visible():
                sb.click()
                print(f"  ✅ 已回复 @{nickname}：{text}")
                page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    inp.press("Control+Enter")
    page.wait_for_timeout(800)
    print(f"  ✅ 已回复 @{nickname}（Ctrl+Enter）：{text}")
    return True


def _do_delete(page, nickname: str, content: str = "") -> bool:
    """定位某昵称(+可选内容片段)的评论 → hover 出「更多」→ 点「删除评论」→ 确认。
    全程按文本/结构定位，**不用任何坐标**。真实删除（调用方已确认 --exec）。"""
    handle = page.evaluate_handle(_FIND_COMMENT_JS, [nickname, content])
    el = handle.as_element()
    if not el:
        print(f"  ❌ @{nickname}: 未找到该评论（重名/内容不匹配/已改版）", file=sys.stderr)
        return False
    el.scroll_into_view_if_needed()
    try:
        el.hover()
    except Exception:
        pass
    page.wait_for_timeout(500)
    # 找并点「更多/···」触发（hover 后才出现）
    for sel in SELECTORS["comment_more"]:
        try:
            trig = el.query_selector(sel)
            if trig and trig.is_visible():
                trig.click()
                break
        except Exception:
            continue
    page.wait_for_timeout(600)
    _shot(page, f"del-{nickname[:6]}-menu")
    # 点「删除评论/删除」菜单项（文本匹配，跨 portal）
    if not page.evaluate(_CLICK_MENU_ITEM_JS, list(DELETE_MENU_TEXTS)):
        print(f"  ❌ @{nickname}: 未找到删除菜单项（DOM 变化，EASEL_COMMENT_DEBUG=1 存 DOM 校准）",
              file=sys.stderr)
        return False
    page.wait_for_timeout(800)
    _shot(page, f"del-{nickname[:6]}-confirm")
    # 确认弹窗（有的直接删无弹窗，点不到不算失败）
    page.evaluate(_CLICK_CONFIRM_JS, list(CONFIRM_TEXTS))
    page.wait_for_timeout(1200)
    print(f"  ✅ 已删除 @{nickname} 的评论" + (f"（含“{content[:12]}…”）" if content else ""))
    return True


# --------------------------------------------------------------------------- #
# 命令
# --------------------------------------------------------------------------- #
def _parse_note_url(url: str) -> tuple[str, str]:
    """从完整笔记链接解析 (note_id, xsec_token)。支持 /explore/<id>、/discovery/item/<id>、/item/<id>。
    纯函数、可离线自测——让 fetch/reply 直接吃粘贴的链接，省去手动拆 note-id 和 token。"""
    import re
    from urllib.parse import urlparse, parse_qs
    if not url:
        return "", ""
    try:
        u = urlparse(url)
        m = re.search(r"/(?:explore|discovery/item|item)/([0-9a-zA-Z]+)", u.path)
        note_id = m.group(1) if m else ""
        token = (parse_qs(u.query).get("xsec_token") or [""])[0]
        return note_id, token
    except Exception:
        return "", ""


def _extract_note_tokens(data) -> dict:
    """递归遍历拦截到的接口 JSON，凡是同时含 note-id 与 xsec_token 的对象，收成 {note_id: token}。
    端点/字段路径无关——不依赖具体接口名或结构，抗改版，比从 DOM 的 <a href> 捞 token 可靠。"""
    out: dict = {}

    def walk(o):
        if isinstance(o, dict):
            nid = o.get("note_id") or o.get("noteId") or o.get("id") or ""
            tok = o.get("xsec_token") or o.get("xsecToken") or ""
            if isinstance(nid, str) and isinstance(tok, str) and nid and tok:
                out.setdefault(nid, tok)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return out


def _resolve_note(a) -> tuple[str, str]:
    """统一解析笔记定位：优先 --url（自动拆 id+token），否则用 --note-id + --xsec-token。缺则报错引导。"""
    nid = getattr(a, "note_id", "") or ""
    tok = getattr(a, "xsec_token", "") or ""
    url = getattr(a, "url", "") or ""
    if url:
        u_nid, u_tok = _parse_note_url(url)
        nid = nid or u_nid
        tok = tok or u_tok
    if not nid or not tok:
        _die("缺笔记定位：给 `--url '<完整笔记链接>'`（自动解析），或同时给 --note-id 和 --xsec-token。"
             "不知道链接？先用 `notes` 子命令列出你的笔记。", 2)
    return nid, tok


def cmd_check(_a) -> int:
    ok = True
    try:
        from playwright.sync_api import sync_playwright
        print("✅ playwright 已安装")
        with sync_playwright() as p:
            path = p.chromium.executable_path
            print(f"✅ chromium 内核：{path}" if path and Path(path).exists()
                  else "❌ 未安装浏览器内核（playwright install chromium）")
            ok = bool(path and Path(path).exists())
    except Exception as e:
        print(f"❌ playwright/内核不可用：{e}"); ok = False
    pd = _profile_dir(None)
    print(f"登录态目录：{pd}（{'存在' if pd.is_dir() else '不存在，先用 xhs_publish.py login 登录'}）")
    return 0 if ok else 3


def cmd_fetch(a) -> int:
    nid, tok = _resolve_note(a)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    raw_pages: list = []
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def _on_resp(resp):
            if "comment/page" in resp.url:
                try:
                    raw_pages.append(resp.json())
                except Exception:
                    pass
        page.on("response", _on_resp)
        try:
            _open_note(page, nid, tok)
            if not _logged_in(page):
                print("⚠️ 疑似未登录（登录态与 xhs_publish 共用，先 xhs_publish.py login）", file=sys.stderr)
            _scroll_comments(page, a.scroll)
            page.wait_for_timeout(1000)
        finally:
            ctx.close()
    comments = _collect_comments(raw_pages, a.max)
    result = {"note_id": nid, "count": len(comments), "comments": comments}
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(payload, encoding="utf-8")
        print(f"✅ 抓到 {len(comments)} 条评论 → {a.out}")
    else:
        print(payload)
    if not comments:
        print("⚠️ 未抓到评论：可能未登录/无评论/接口改版（加 --headed 观察，或校准 comment/page 拦截）",
              file=sys.stderr)
    return 0


_XHS_MY_NOTES_JS = """() => {
  const out = [];
  document.querySelectorAll('.note-card').forEach(c => {
    const titleEl = c.querySelector('.note-card__title');
    let noteId = '';
    try { noteId = (JSON.parse(c.getAttribute('data-impression') || '{}')
                    .noteTarget || {}).value?.noteId || ''; } catch (e) {}
    // 尽力从卡片内的链接里拿 xsec_token（列表页不一定带）
    let href = '';
    const a = c.querySelector("a[href*='xsec_token'], a[href*='/explore/'], a[href*='/item/']");
    if (a) href = a.href || '';
    const img = c.querySelector('.note-card__cover img, img');
    out.push({ title: (titleEl ? titleEl.textContent : '').trim().slice(0, 60),
               noteId, href, cover: img ? (img.src || '') : '' });
  });
  return out.slice(0, 20);
}"""


def cmd_notes(a) -> int:
    """列出「我」已发布的笔记（标题 + note_id + xsec_token），把「我的笔记→抓评论」一步打通。
    token 优先从**接口 JSON 响应**取（可靠，接口本就带），DOM 的 <a href> 仅作兜底。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    notes: list = []
    token_map: dict = {}
    raw: list = []
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def _on_resp(resp):  # 拦截 note-manager 的 JSON 接口，从中取每篇的 xsec_token
            try:
                if "json" in ((resp.headers or {}).get("content-type", "")):
                    token_map.update(_extract_note_tokens(resp.json()))
            except Exception:
                pass
        page.on("response", _on_resp)
        try:
            page.goto("https://creator.xiaohongshu.com/new/note-manager",
                      wait_until="domcontentloaded", timeout=30000)
            if not _logged_in(page):
                print("⚠️ 疑似未登录（登录态与 xhs_publish 共用，先 xhs_publish.py login）", file=sys.stderr)
            try:
                page.wait_for_selector(".note-card", timeout=8000)
            except Exception:
                page.wait_for_timeout(1500)
            # 滚动触发懒加载：多拉几篇的列表接口（token 随接口返回）
            for _ in range(max(1, a.scroll)):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(900)
            page.wait_for_timeout(800)
            raw = page.evaluate(_XHS_MY_NOTES_JS) or []
            _shot(page, "notes")
            if _debug_on():
                try:
                    (PROJECT_ROOT / "outputs" / "_login" / "comment-notes-dom.html").write_text(
                        page.content(), encoding="utf-8")
                except Exception:
                    pass
        finally:
            ctx.close()
    for n in raw:
        h_nid, h_tok = _parse_note_url(n.get("href") or "")
        nid = n.get("noteId") or h_nid
        tok = token_map.get(nid, "") or h_tok    # 接口 token 优先，DOM href 兜底
        notes.append({
            "note_id": nid, "title": n.get("title") or "(无标题)",
            "xsec_token": tok, "cover": n.get("cover") or "",
            "url": NOTE_URL.format(note_id=nid, token=tok) if nid and tok else "",
        })
    payload = json.dumps({"count": len(notes), "notes": notes}, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(payload, encoding="utf-8")
        print(f"✅ {len(notes)} 篇笔记 → {a.out}")
    else:
        print(payload)
    miss = [n for n in notes if not n["xsec_token"]]
    if miss:
        print(f"⚠️ {len(miss)}/{len(notes)} 篇未取到 xsec_token——抓这些的评论用 `fetch --url '<该笔记分享/打开链接>'`；"
              "或 EASEL_COMMENT_DEBUG=1 + --headed 看接口是否改版。", file=sys.stderr)
    return 0


def cmd_plan(a) -> int:
    replies = _parse_replies(a.replies_json)
    print(f"dry-run 预演（加 --exec 才真发）：将回复 {len(replies)} 条")
    for r in replies:
        tag = f"[{r['id'][:8]}] " if r["id"] else ""
        print(f"  → {tag}@{r['nickname']}：{r['reply']}")
    return 0


def cmd_reply(a) -> int:
    replies = _parse_replies(a.replies_json)
    replied = _load_replied(a.replied_file)
    todo = [r for r in replies if not (r["id"] and r["id"] in replied)]
    skipped = len(replies) - len(todo)

    # 出站内容安全闸门：逐条回复文本扫描内部设置泄露（dry-run 告警 / --exec 阻止）。
    content_guard.guard_or_die([r["reply"] for r in todo], exec_mode=bool(a.exec),
                               allow_unsafe=getattr(a, "allow_unsafe", False),
                               label="小红书评论回复")

    if not a.exec:  # 默认 dry-run：只预演不发
        print(f"dry-run（加 --exec 才真发）：待回复 {len(todo)} 条"
              + (f"，已回复跳过 {skipped} 条" if skipped else ""))
        for r in todo:
            tag = f"[{r['id'][:8]}] " if r["id"] else ""
            print(f"  → {tag}@{r['nickname']}：{r['reply']}")
        return 0

    if not todo:
        print(f"无待回复（{skipped} 条已在 --replied-file 中）")
        return 0

    nid, tok = _resolve_note(a)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    ok_n = fail_n = 0
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _open_note(page, nid, tok)
            if not _logged_in(page):
                _die("未登录（登录态与 xhs_publish 共用）——先 `xhs_publish.py login` 扫码", 4)
            _scroll_comments(page, a.scroll)
            for i, r in enumerate(todo):
                if _do_reply(page, r["nickname"], r["reply"]):
                    ok_n += 1
                    if r["id"]:
                        replied.add(r["id"])
                        _save_replied(a.replied_file, replied)  # 逐条落盘，中断也不丢
                else:
                    fail_n += 1
                if i < len(todo) - 1:
                    page.wait_for_timeout(int(a.gap * 1000))  # 逐条间隔防风控
        finally:
            ctx.close()
    print(f"\n完成：成功 {ok_n} / 失败 {fail_n}" + (f"（另跳过已回复 {skipped}）" if skipped else ""))
    return 0 if fail_n == 0 else 1


def cmd_delete(a) -> int:
    """删除自己笔记下的评论（含自己发的回复）。**默认 dry-run**，加 --exec 才真删——删除不可恢复。"""
    targets = _parse_targets(a.targets_json, a.nickname, a.content)

    if not a.exec:  # 默认 dry-run：只列不删
        print(f"dry-run（加 --exec 才真删）：将删除 {len(targets)} 条评论")
        for t in targets:
            print(f"  → @{t['nickname']}" + (f"：{t['content']}" if t["content"] else ""))
        print("⚠️ 删除不可恢复，确认无误后加 --exec 执行。")
        return 0

    nid, tok = _resolve_note(a)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    ok_n = fail_n = 0
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            _open_note(page, nid, tok)
            if not _logged_in(page):
                _die("未登录（登录态与 xhs_publish 共用）——先 `xhs_publish.py login` 扫码", 4)
            _scroll_comments(page, a.scroll)
            for i, t in enumerate(targets):
                if _do_delete(page, t["nickname"], t["content"]):
                    ok_n += 1
                else:
                    fail_n += 1
                if i < len(targets) - 1:
                    page.wait_for_timeout(int(a.gap * 1000))  # 逐条间隔防风控
        finally:
            ctx.close()
    print(f"\n完成：删除成功 {ok_n} / 失败 {fail_n}。可重新 `fetch` 核对是否已消失。")
    return 0 if fail_n == 0 else 1


# JS：用 dispatchEvent 点击，绕过 subtree 拦截 pointer events（XHS .not-active 外包层结构）
_JS_CLICK_COMMENT_BOX = """
() => {
    // 匹配 XHS 评论输入区的外包层（.not-active 或内嵌 span 激活后的外包）
    const candidates = [
        document.querySelector('[class*="not-active"]'),
        document.querySelector('[class*="inner-when-not-active"]'),
        document.querySelector('[class*="comment-input"]'),
        document.querySelector('[class*="commentInput"]'),
        ...Array.from(document.querySelectorAll('[contenteditable="true"]')).filter(e => e.offsetParent !== null),
    ].filter(Boolean);
    for (const el of candidates) {
        el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
        return el.className || el.tagName;
    }
    return null;
}
"""


def _do_post_comment(page, text: str) -> bool:
    """在当前打开的笔记页面发一条顶层评论。
    XHS 评论框是 .not-active 外包 + 内嵌 span，直接 click() 会被 subtree 拦截；
    改用 dispatchEvent 正确激活。"""
    # 1. 滚到评论区
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1500)

    # 2. 激活评论框：优先用 Playwright force-click（绕过 subtree 拦截），降级到 JS dispatch
    not_active_el = page.query_selector('[class*="not-active"]')
    if not_active_el:
        try:
            not_active_el.click(force=True)   # force=True 绕过 span 子元素拦截
            print(f"  ℹ️ 已触发评论框（force-click）：{(not_active_el.get_attribute('class') or '')[:60]}")
        except Exception:
            triggered = page.evaluate(_JS_CLICK_COMMENT_BOX)
            if triggered:
                print(f"  ℹ️ 已触发评论框（JS）：{str(triggered)[:60]}")
    else:
        triggered = page.evaluate(_JS_CLICK_COMMENT_BOX)
        if triggered:
            print(f"  ℹ️ 已触发评论框（JS fallback）：{str(triggered)[:60]}")
    page.wait_for_timeout(1200)

    # 3. 找激活后的 contenteditable（外包应该已变 active；排除仍 not-active 的）
    inp = None
    active_selectors = [
        "[class*='commentInput'] [contenteditable='true']",
        "[class*='comment-input'] [contenteditable='true']",
        "[class*='active']:not([class*='not-active']) [contenteditable='true']",
        "[contenteditable='true']",
        "[class*='active'] [contenteditable]",
        "textarea",
    ]
    for sel in active_selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                inp = el
                break
        except Exception:
            continue

    # 4. 备用：再尝试一次常驻主评论输入框选择器
    if not inp:
        for sel in SELECTORS["main_comment_input"]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    inp = el
                    break
            except Exception:
                continue

    if not inp:
        print("  ❌ 未找到可用评论输入框（加 --headed 观察页面结构）", file=sys.stderr)
        _shot(page, "post-no-input")
        return False

    # 5. 原生 click 设置键盘焦点（JS click 不设置 activeElement）
    try:
        inp.scroll_into_view_if_needed()
        inp.click()   # Playwright 原生 click，确保 keyboard focus
    except Exception:
        try:
            inp.evaluate("el => { el.focus(); }")
        except Exception:
            pass
    page.wait_for_timeout(600)

    # 6. 输入文字（keyboard.type 带随机delay防检测）
    page.keyboard.type(text, delay=random.randint(40, 90))
    page.wait_for_timeout(800)

    # 验证内容是否确实进入输入框
    try:
        actual = inp.evaluate("el => el.textContent || el.value || ''")
        if actual.strip() == "":
            print("  ⚠️ keyboard.type 未进入内容，改用 execCommand", file=sys.stderr)
            inp.evaluate("(el, t) => { el.focus(); document.execCommand('insertText', false, t); }", text)
            page.wait_for_timeout(500)
    except Exception:
        pass
    _shot(page, "post-typed")

    # 7. 点发送按钮（用真实鼠标点击，非 JS .click()）
    # 扩展候选：class="btn submit" 是 XHS 实测有效选择器
    extended_send_selectors = [
        "button.submit", "button[class*='submit']",
        "button:has-text('发送')", "text=发送",
        "[class*='send-btn']", "[class*='submit']",
    ] + [s for s in SELECTORS["send_btn"] if s not in ["button:has-text('发送')", "text=发送", "[class*='send-btn']", "[class*='submit']"]]
    for sel in extended_send_selectors:
        try:
            sb = page.query_selector(sel)
            if sb and sb.is_visible():
                sb.scroll_into_view_if_needed()
                sb.click()   # Playwright 原生点击，带坐标和鼠标事件
                page.wait_for_timeout(2500)
                # 禁言弹窗检测
                ban_d = page.evaluate("() => Array.from(document.querySelectorAll('*')).some(e => e.offsetParent !== null && (e.textContent||'').includes('被禁言'))")
                if ban_d:
                    page.evaluate("() => { const b=Array.from(document.querySelectorAll('button,[role=button]')).find(b=>b.offsetParent&&['我知道了','确定'].includes((b.textContent||'').trim())); if(b) b.click(); }")
                    print("  ❌ 账号被禁言（薯队长弹窗），评论被拦截", file=sys.stderr)
                    return False
                print(f"  ✅ 评论已发送：{text[:40]}{'...' if len(text) > 40 else ''}")
                return True
        except Exception:
            continue

    # 8. 兜底：Enter 键提交
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)   # 等长一点，给平台异步处理时间

    # 8a. 禁言弹窗检测（薯队长 / 社区规范 / 被禁言）
    ban_detected = page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('*'));
        return all.some(e => e.offsetParent !== null &&
            (e.textContent || '').includes('被禁言'));
    }""")
    if ban_detected:
        # 关掉弹窗再返回
        page.evaluate("""() => {
            const btns = Array.from(document.querySelectorAll('button, [role=button], a'));
            const ok = btns.find(b => b.offsetParent !== null &&
                ['我知道了','确定','关闭'].includes((b.textContent||'').trim()));
            if (ok) ok.click();
        }""")
        print("  ❌ 账号被禁言（薯队长弹窗），评论发送被拦截", file=sys.stderr)
        return False

    # 验证输入框是否已清空（常见发送成功的标志）
    try:
        val = inp.evaluate("el => el.textContent || el.value || ''")
        sent = val.strip() == ""
    except Exception:
        sent = True
    icon = "\u2705" if sent else "\u26a0\ufe0f"
    tail = "..." if len(text) > 40 else ""
    print(f"  {icon} 评论发送（Enter）：{text[:40]}{tail}")
    return sent


def cmd_post(a) -> int:
    """在指定 XHS 笔记下发顶层评论（非回复某人）。默认 dry-run，加 --exec 才真发。
    支持 --batch-json '[{"url":"...","text":"..."}]' 批量；或 --url + --text 单条。"""
    # 解析批量任务
    tasks: list[dict] = []
    if a.batch_json:
        try:
            raw = json.loads(a.batch_json)
            if not isinstance(raw, list):
                _die("--batch-json 须为 JSON 数组 [{url, text}, ...]")
            for item in raw:
                if not item.get("url") or not item.get("text"):
                    _die("batch-json 每项须含 url 和 text")
            tasks = raw
        except json.JSONDecodeError as e:
            _die(f"--batch-json JSON 解析失败：{e}")
    elif a.url and a.text:
        tasks = [{"url": a.url, "text": a.text}]
    else:
        _die("请提供 --batch-json 或同时提供 --url + --text")

    # 出站内容安全闸门：逐条评论文本扫描内部设置泄露（dry-run 告警 / --exec 阻止）。
    content_guard.guard_or_die([t["text"] for t in tasks], exec_mode=bool(a.exec),
                               allow_unsafe=getattr(a, "allow_unsafe", False),
                               label="小红书顶层评论")

    # Dry-run 预演
    if not a.exec:
        print(f"dry-run（加 --exec 才真发）：待发 {len(tasks)} 条顶层评论\n")
        for i, t in enumerate(tasks, 1):
            url_short = t["url"][:70] + ("..." if len(t["url"]) > 70 else "")
            print(f"  [{i}] 目标：{url_short}")
            print(f"       评论：{t['text']}")
            print()
        return 0

    # 真发
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)

    ok_n = fail_n = 0
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not _logged_in(page):
                # 先访问一个页面确认登录态
                page.goto("https://www.xiaohongshu.com", wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
            for i, t in enumerate(tasks):
                print(f"[{i+1}/{len(tasks)}] 打开笔记：{t['url'][:60]}...")
                try:
                    page.goto(t["url"], wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(4000)
                    if not _logged_in(page):
                        print("  ⚠️ 疑似未登录，跳过", file=sys.stderr)
                        fail_n += 1
                        continue
                    if _do_post_comment(page, t["text"]):
                        ok_n += 1
                    else:
                        fail_n += 1
                except Exception as e:
                    print(f"  ❌ 打开笔记失败：{e}", file=sys.stderr)
                    fail_n += 1
                if i < len(tasks) - 1:
                    gap = int(a.gap * 1000)
                    print(f"  等待 {a.gap}s 防风控...")
                    page.wait_for_timeout(gap)
        finally:
            ctx.close()
    print(f"\n完成：成功 {ok_n} / 失败 {fail_n}")
    return 0 if fail_n == 0 else 1


def cmd_selftest(_a) -> int:
    print("xhs_comment 自检（离线）...", file=sys.stderr)
    # 选择器字典
    for k in ("author", "reply_input", "send_btn", "login_hint"):
        assert k in SELECTORS and SELECTORS[k], f"缺选择器 {k}"
    # 路径可移植（不硬编码 /root）
    assert _profile_dir(None).name == PROFILE_NAME
    assert str(_profile_dir(None)).startswith(str(Path.home()))
    assert _profile_dir("/tmp/x").parent == Path("/tmp/x")
    # 代理逻辑
    assert _proxy(None, True) is None
    assert _proxy("http://x:1", False) == "http://x:1"
    # 评论规范化 + 去重 + 子评论 + 时间
    raw = [{"data": {"comments": [
        {"id": "a", "content": "顶", "create_time": 1700000000000,
         "user_info": {"nickname": "小明"}, "ip_location": "北京", "like_count": 3,
         "sub_comments": [{"id": "a1", "content": "同", "user_info": {"nickname": "小红"}}]},
        {"id": "a", "content": "重复应去重", "user_info": {"nickname": "x"}},
    ]}}]
    cs = _collect_comments(raw)
    assert len(cs) == 2, cs
    top = next(c for c in cs if c["id"] == "a")
    assert top["nickname"] == "小明" and top["loc"] == "北京" and top["like"] == "3"
    assert top["time_str"].startswith("20") and top["parent"] == ""
    assert next(c for c in cs if c["id"] == "a1")["parent"] == "a"
    assert len(_collect_comments(raw, limit=1)) == 1
    # 去重文件读写
    import tempfile
    tf = Path(tempfile.mkdtemp()) / "replied.json"
    _save_replied(str(tf), {"x", "y"})
    assert _load_replied(str(tf)) == {"x", "y"}
    assert _load_replied(None) == set() and _load_replied("/no/such") == set()
    # replies-json 校验
    assert _parse_replies('[{"nickname":"n","reply":"r","id":"1"}]')[0]["id"] == "1"
    for bad in ('[{"nickname":"n"}]', 'not json', '{}'):
        try:
            _parse_replies(bad); raise AssertionError(f"未校验：{bad}")
        except SystemExit:
            pass
    # 笔记链接解析（--url 便捷入口）
    nid, tok = _parse_note_url(
        "https://www.xiaohongshu.com/explore/6a6aba4d00000000090350b1?xsec_token=ABC%3D&xsec_source=pc")
    assert nid == "6a6aba4d00000000090350b1" and tok == "ABC=", (nid, tok)
    assert _parse_note_url("https://x.com/discovery/item/deadbeef01?xsec_token=T1")[0] == "deadbeef01"
    assert _parse_note_url("") == ("", "")
    assert _parse_note_url("https://www.xiaohongshu.com/explore/xyz")[1] == ""  # 无 token
    # _resolve_note：--url 补全、缺失报错
    class _A:  # noqa: E301
        note_id = xsec_token = ""
        url = "https://www.xiaohongshu.com/explore/n1?xsec_token=tk1"
    assert _resolve_note(_A()) == ("n1", "tk1")
    class _B:  # noqa: E301
        note_id = "n2"; xsec_token = "tk2"; url = ""
    assert _resolve_note(_B()) == ("n2", "tk2")
    class _C:  # noqa: E301
        note_id = xsec_token = url = ""
    try:
        _resolve_note(_C()); raise AssertionError("缺定位未报错")
    except SystemExit:
        pass
    # 删除目标解析
    assert _parse_targets('[{"nickname":"n","content":"顶"}]', None, None)[0]["content"] == "顶"
    assert _parse_targets(None, "小明", "好文")[0] == {"id": "", "nickname": "小明", "content": "好文"}
    assert _parse_targets(None, "小明", None)[0]["content"] == ""
    for bad in ('[{"content":"x"}]', 'not json', '{}'):
        try:
            _parse_targets(bad, None, None); raise AssertionError(f"未校验：{bad}")
        except SystemExit:
            pass
    try:
        _parse_targets(None, None, None); raise AssertionError("无目标未报错")
    except SystemExit:
        pass
    # 删除相关常量齐备
    assert DELETE_MENU_TEXTS and CONFIRM_TEXTS and SELECTORS.get("comment_more")
    # 接口 JSON 里递归提取 note→token（可靠取 token 的核心）
    sample = {"data": {"notes": [
        {"note_id": "n1", "xsec_token": "tk1", "display_title": "x"},
        {"id": "n2", "xsecToken": "tk2"},
        {"noteId": "n3"},  # 无 token 不收
    ], "cursor": "c"}}
    tm = _extract_note_tokens(sample)
    assert tm == {"n1": "tk1", "n2": "tk2"}, tm
    assert _extract_note_tokens([]) == {} and _extract_note_tokens("x") == {}
    print("✅ selftest 通过（选择器 + 可移植路径 + 代理 + 评论解析/去重/子评论 + replied 文件 + 入参校验 + 链接解析/note定位 + 删除目标解析 + 接口token提取）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="小红书评论抓取+回复（Playwright，headless 可用）")
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p):
        p.add_argument("--profile-base", help="登录态根目录（默认 ~/.easel-browser-profiles）")
        p.add_argument("--proxy", help="外网代理（默认取 env）")
        p.add_argument("--no-proxy", action="store_true", help="禁用代理（小红书建议直连）")
        p.add_argument("--headed", action="store_true", help="有头模式（首次校验/排错）")

    def add_note(p):
        p.add_argument("--url", help="完整笔记链接（自动解析 note-id 与 xsec_token，推荐，粘贴即用）")
        p.add_argument("--note-id", help="笔记 id（也可用 --url 代替）")
        p.add_argument("--xsec-token", help="链接里的 xsec_token（也可用 --url 代替）")
        p.add_argument("--scroll", type=int, default=8, help="滚动加载轮数（默认 8）")

    sub.add_parser("check", help="检查 playwright/内核/登录态目录").set_defaults(func=cmd_check)

    pn = sub.add_parser("notes", help="列出我已发布的笔记（标题+note_id+从接口取的 token）")
    add_common(pn)
    pn.add_argument("--scroll", type=int, default=4, help="滚动加载轮数（触发更多列表接口，默认 4）")
    pn.add_argument("--out", help="输出 JSON 文件（默认打印 stdout）")
    pn.set_defaults(func=cmd_notes)

    pf = sub.add_parser("fetch", help="抓评论 → JSON（--url 或 --note-id+--xsec-token）")
    add_common(pf); add_note(pf)
    pf.add_argument("--max", type=int, default=0, help="最多保留条数（0=全部）")
    pf.add_argument("--out", help="输出 JSON 文件（默认打印 stdout）")
    pf.set_defaults(func=cmd_fetch)

    pr = sub.add_parser("reply", help="回复评论（默认 dry-run，加 --exec 真发）")
    add_common(pr); add_note(pr)
    pr.add_argument("--replies-json", help="[{id,nickname,reply}]（id 可选，用于去重）")
    pr.add_argument("--exec", action="store_true", help="真正发送（默认 dry-run 预演）")
    pr.add_argument("--allow-unsafe", action="store_true",
                    help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    pr.add_argument("--replied-file", help="已回复 id 记录文件，重跑自动跳过")
    pr.add_argument("--gap", type=float, default=4.0, help="每条回复间隔秒数（默认 4，防风控）")
    pr.set_defaults(func=cmd_reply)

    pd = sub.add_parser("delete", help="删除评论（默认 dry-run，加 --exec 才真删；不可恢复）")
    add_common(pd); add_note(pd)
    pd.add_argument("--targets-json", help="[{nickname,content?,id?}] 批量目标（content 用于同名去歧义）")
    pd.add_argument("--nickname", help="单条删除：评论作者昵称")
    pd.add_argument("--content", help="单条删除：内容片段（同名去歧义，可选）")
    pd.add_argument("--exec", action="store_true", help="真正删除（默认 dry-run 预演）")
    pd.add_argument("--gap", type=float, default=4.0, help="每条删除间隔秒数（默认 4，防风控）")
    pd.set_defaults(func=cmd_delete)

    pp = sub.add_parser("plan", help="离线预览将回复什么（不启浏览器）")
    pp.add_argument("--note-id", help="（占位，可选）")
    pp.add_argument("--replies-json", help="[{id,nickname,reply}]")
    pp.set_defaults(func=cmd_plan)

    ppost = sub.add_parser("post", help="在任意笔记下发顶层评论（默认 dry-run，加 --exec 真发）")
    add_common(ppost)
    ppost.add_argument("--url", help="单条：笔记完整链接")
    ppost.add_argument("--text", help="单条：评论文案")
    ppost.add_argument("--batch-json",
                       help='批量：JSON 数组 [{"url":"...","text":"..."}]')
    ppost.add_argument("--exec", action="store_true", help="真正发送（默认 dry-run 预演）")
    ppost.add_argument("--allow-unsafe", action="store_true",
                       help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    ppost.add_argument("--gap", type=float, default=6.0,
                       help="每条间隔秒数（默认 6，防风控）")
    ppost.set_defaults(func=cmd_post)

    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
