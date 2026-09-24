#!/usr/bin/env python3
"""
微信公众号「后台网页端」数据回收（mp.weixin.qq.com 管理员会话）。

用途：开发者接口 datacube 需认证+群发+接口权限，很多号取不到数；而后台网页端
（appmsgpublish 发表记录 / appmsganalysis 数据分析）只要管理员登录会话即可看到数据。
本脚本用 Playwright 扫码登录 mp 后台并持久化会话，再用会话调后台接口取数。

⚠️ 这是公众号管理员级会话（权限大于 AppID/AppSecret），仅用于取数；抓后台接口属灰色，注意频率。
mp 走直连（不经 JP 出口），避免异地安全校验。

子命令：login / whoami / stats / selftest
输出：stats 打印与 account_stats.py/bili_login.py 一致的统一 JSON dict（stdout 末行以 { 开头）。
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote

if os.name == "nt":
    import msvcrt
else:
    import fcntl

sys.path.insert(0, str(Path(__file__).resolve().parent))
import login_state  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOGIN_DIR = PROJECT_ROOT / "outputs" / "_login"
PROFILE_NAME = "WeixinMpProfile"
MP_HOME = "https://mp.weixin.qq.com/"
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
]
TOKEN_RE = re.compile(r"[?&]token=(\d+)")

EMPTY = {
    "platform": "wechat-oa", "name": "微信公众号", "nickname": "",
    "loggedIn": False, "followers": None, "likes": None, "following": None, "posts": None,
    "reads": None, "metrics": [], "notes": [], "overview": [],
    "period_metrics": {},
    "growth": {"last": None, "day": None, "week": None, "month": None, "year": None},
    "fetched_at": "",
}


def _die(msg, code=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _profile_dir(base):
    root = Path(base).expanduser() if base else Path.home() / ".easel-browser-profiles"
    return root / PROFILE_NAME


_IMG_OK = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_API_MEDIA = re.compile(
    r"(?:https?://(?:127\.0\.0\.1|localhost)(?::\d+)?)?/api/media/",
    re.IGNORECASE,
)


def resolve_content_image(src, html_path):
    """Turn preview /api/media/ or relative src into a local file, else None."""
    src = unquote(str(src or "").strip())
    if not src:
        return None
    media = _API_MEDIA.search(src)
    if media:
        parts = Path(src[media.end():]).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            return None
        if str(parts[0]).startswith(("_", ".")) or str(parts[0]).lower() in {"analytics", "wechat"}:
            return None
        candidate = (PROJECT_ROOT / "outputs").joinpath(*parts).resolve()
        try:
            candidate.relative_to((PROJECT_ROOT / "outputs").resolve())
        except ValueError:
            return None
        if candidate.suffix.lower() in _IMG_OK and candidate.is_file():
            return candidate
        return None
    if src.lower().startswith("http://") or src.lower().startswith("https://") or src.startswith("//"):
        return None
    img = Path(src)
    if not img.is_absolute() and not img.is_file():
        img = Path(html_path).resolve().parent / src
    if img.is_file() and img.suffix.lower() in _IMG_OK:
        return img
    return None


def _lock_profile(prof):
    lock_path = Path(prof) / ".easel.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+b")
    try:
        if os.name == "nt":
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            fh.close()
        except OSError:
            pass
        raise RuntimeError("公众号后台会话正被占用，请等当前登录、数据同步或另一篇草稿结束后再试。")
    return fh


def _unlock_profile(fh):
    if fh is None:
        return
    try:
        if os.name == "nt":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fh.close()
    except OSError:
        pass


def _proxy(explicit, disable):
    # mp 默认直连（domestic）；仅当显式 --proxy 才走代理
    if disable:
        return None
    if explicit:
        return explicit
    return None


def _launch(p, headed, base, proxy):
    prof = _profile_dir(base)
    prof.mkdir(parents=True, exist_ok=True)
    lock = _lock_profile(prof)
    kw = dict(headless=not headed, locale="zh-CN", args=LAUNCH_ARGS,
              viewport={"width": 1440, "height": 900})
    # mp 为国内站，直连即可。仅显式 --proxy 时才走代理；否则不传 proxy，
    # 并靠进程环境已清空 http(s)_proxy（见启动命令的 env -u）让 Chromium 直连。
    if proxy:
        kw["proxy"] = {"server": proxy}
    try:
        ctx = p.chromium.launch_persistent_context(str(prof), **kw)
    except Exception:
        _unlock_profile(lock)
        raise
    original_close = ctx.close

    def close(*args, **kwargs):
        try:
            return original_close(*args, **kwargs)
        finally:
            _unlock_profile(lock)

    ctx.close = close
    return ctx


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _extract_token(url):
    m = TOKEN_RE.search(url or "")
    return m.group(1) if m else ""


def _capture_qr(page, qr_out):
    """等二维码 img 真正渲染(complete && naturalWidth>0)后再截图。"""
    Path(qr_out).parent.mkdir(parents=True, exist_ok=True)
    sel = "img[src*='qrcode'], img.login__type__container__scan__qrcode, .login__type__container__scan img"
    for _ in range(25):  # 最多等 ~25s
        try:
            el = page.query_selector(sel)
            if el:
                box = el.bounding_box()
                loaded = False
                try:
                    loaded = page.evaluate("(e)=>e.complete && e.naturalWidth>10", el)
                except Exception:
                    loaded = bool(box and box["width"] > 80)
                if loaded and box and box["width"] > 80:
                    el.screenshot(path=str(qr_out))
                    return True
        except Exception:
            pass
        page.wait_for_timeout(1000)
    # 兜底：整页截（仍可能白，但至少给个东西）
    try:
        page.screenshot(path=str(qr_out), timeout=15000)
        return True
    except Exception:
        return False


def cmd_login(a):
    try:
        return _run_login(a)
    except Exception as exc:
        # 异常类型对用户可见；不把可能包含会话令牌的浏览器异常全文写进状态。
        login_state.write_status(a.status_file, "error",
                                 f"公众号登录失败（{type(exc).__name__}），请检查浏览器、网络及会话占用")
        print(f"login failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        return 1


def _run_login(a):
    from playwright.sync_api import sync_playwright
    status = a.status_file
    qr_out = a.qr_out or str(LOGIN_DIR / "wechat-oa-mp.png")
    login_state.write_status(status, "starting", "启动 mp 后台登录…")
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(MP_HOME, wait_until="commit", timeout=60000)
            page.wait_for_timeout(1500)
            # 已登录（持久化会话仍有效）→ 直接成功
            if _extract_token(page.url):
                login_state.write_status(status, "success", "已登录（复用会话）")
                print("already logged in, token acquired")
                return 0
            if not _capture_qr(page, qr_out):
                raise RuntimeError("二维码截图失败")
            if a.headed:
                login_state.write_status(
                    status, "window_login",
                    "请在弹出的浏览器窗口里用管理员微信扫码，不要关掉那个窗口。也可以扫下面这张图。",
                    qr=str(qr_out))
            else:
                login_state.write_status(status, "qr_ready", "请用公众号管理员微信扫码", qr=str(qr_out))
            deadline = time.time() + a.timeout
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                if _extract_token(page.url):
                    login_state.write_status(status, "success", "登录成功")
                    # 不打印 token 值：它是 mp 后台会话令牌，stdout 会落进
                    # outputs/_login/wechat-oa-mp.log，避免敏感值明文落盘。
                    print("login success, token acquired")
                    return 0
                # 二维码可能刷新，定期重截
                try:
                    if not _extract_token(page.url):
                        _capture_qr(page, qr_out)
                except Exception:
                    pass
            login_state.write_status(status, "expired", "二维码超时未扫")
            _die("login timeout", 1)
        finally:
            ctx.close()


def _fetch_json(page, url):
    try:
        r = page.request.get(url, timeout=20000)
        txt = r.text()
        try:
            return json.loads(txt), txt
        except Exception:
            return None, txt
    except Exception as e:
        return None, f"__ERR__ {e}"


def cmd_stats(a):
    from playwright.sync_api import sync_playwright
    result = dict(EMPTY)
    result["fetched_at"] = _now()
    cap = {"publish": None, "tendency": None, "article_list": None, "user": None}

    def on_resp(resp):
        try:
            if "json" not in resp.headers.get("content-type", ""):
                return
            u = resp.url
            if "appmsgpublish" in u and cap["publish"] is None:
                cap["publish"] = resp.text()
            elif "get_article_stat_tendency" in u and cap["tendency"] is None:
                cap["tendency"] = resp.text()
            elif "get_article_list" in u and cap["article_list"] is None:
                cap["article_list"] = resp.text()
            elif ("usersummary" in u or "get_user_summary" in u or "usercumulate" in u
                  or "user_cumulate" in u) and cap["user"] is None:
                cap["user"] = resp.text()
        except Exception:
            pass

    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", on_resp)
        try:
            page.goto(MP_HOME, wait_until="commit", timeout=60000)
            page.wait_for_timeout(1800)
            token = _extract_token(page.url)
            if not token:
                result["error"] = "未登录或会话失效，请重新 login 扫码"
                print(json.dumps(result, ensure_ascii=False))
                return 1
            result["loggedIn"] = True
            # 打开发表记录页，让 Vue 自然发出带正确参数的数据 XHR（我们拦截它，避免自己拼易变参数/fingerprint）
            page.goto(f"https://mp.weixin.qq.com/cgi-bin/appmsgpublish?sub=list&begin=0&count={a.count}"
                      f"&token={token}&lang=zh_CN", wait_until="commit", timeout=60000)
            for _ in range(10):
                if cap["publish"]:
                    break
                page.wait_for_timeout(1000)
            # 打开数据分析页，触发阅读/分享趋势 + 单篇文章数据 + 用户数据 XHR
            try:
                page.goto(f"https://mp.weixin.qq.com/misc/appmsganalysis?action=report&type=daily_v2"
                          f"&token={token}&lang=zh_CN", wait_until="commit", timeout=60000)
                for _ in range(8):
                    if cap["tendency"] and cap["article_list"]:
                        break
                    page.wait_for_timeout(1000)
            except Exception:
                pass
            if a.dump_dir:
                Path(a.dump_dir).mkdir(parents=True, exist_ok=True)
                for k, v in cap.items():
                    if v:
                        Path(a.dump_dir, f"{k}.json").write_text(v, encoding="utf-8")
            _parse_publish(cap["publish"], result)
            _parse_analytics(cap, result)
            if result.get("followers") is None:
                _fetch_followers(page, token, result)
            _apply_nickname(page, result)
            _attach_growth(result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        finally:
            ctx.close()


def _deep_find(obj, keys, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (str, int)):
                out.setdefault(k, v)
            _deep_find(v, keys, out)
    elif isinstance(obj, list):
        for x in obj:
            _deep_find(x, keys, out)


def _parse_publish(raw, result):
    """解析 appmsgpublish 数据 XHR 的 JSON → notes[] / posts / metrics。
    结构：外层 JSON.publish_page 是转义 JSON 字符串，内含 total_count/publish_count/
    masssend_count 和 publish_list[]；每条 publish_info 又是转义 JSON，含文章 appmsgex/appmsg_info。"""
    if not raw:
        result["error"] = "未捕获到发表记录数据（会话可能失效，重新 login）"
        return
    try:
        d = json.loads(raw)
        page = json.loads(d.get("publish_page", "{}")) if isinstance(d.get("publish_page"), str) else (d.get("publish_page") or {})
        total = int(page.get("total_count", 0) or 0)
        pub_cnt = int(page.get("publish_count", 0) or 0)
        mass_cnt = int(page.get("masssend_count", 0) or 0)
        notes, total_read, like_sum = [], 0, 0
        for it in (page.get("publish_list") or []):
            info = it.get("publish_info")
            info = json.loads(info) if isinstance(info, str) else (info or {})
            arts = info.get("appmsgex") or info.get("appmsg_info") or []
            if not arts:
                found = {}
                _deep_find(info, {"title", "link", "content_url", "read_num", "like_num", "cover"}, found)
                if found:
                    arts = [found]
            for am in arts:
                rn = int(am.get("read_num", 0) or 0)
                ln = int(am.get("like_num", 0) or 0)
                total_read += rn
                like_sum += ln
                notes.append({
                    "title": am.get("title", ""),
                    "url": am.get("link") or am.get("content_url", ""),
                    "cover": am.get("cover", ""),
                    "stat": (f"阅读 {rn} · 赞 {ln}" if rn or ln else ""),
                })
        result["notes"] = notes[:20]
        published = pub_cnt or total or len(notes)
        result["posts"] = published
        result["likes"] = like_sum or None
        result["reads"] = total_read or None
        result["metrics"] = [
            {"label": "已发表", "value": published, "vs": ""},
            {"label": "群发次数", "value": mass_cnt, "vs": ""},
            {"label": "发表记录总数", "value": total, "vs": ""},
        ]
        if total_read:
            result["metrics"].append({"label": "列表累计阅读", "value": total_read, "vs": ""})
    except Exception as e:
        result["error"] = f"发表记录解析失败：{e}"


def _daily_totals(lst):
    """后台趋势按 scene 拆行，scene=9999 才是当天合计。按行去尾会把「近 30 日」算成最近几条分场景。"""
    has_total = any(int(x.get("scene", -1) or -1) == 9999 for x in lst)
    by_date = {}
    for x in lst:
        scene = int(x.get("scene", -1) or -1)
        if has_total and scene != 9999:
            continue
        day = int(x.get("date") or 0)
        prev = by_date.get(day)
        if prev is None or int(x.get("read_uv") or 0) >= int(prev.get("read_uv") or 0):
            by_date[day] = x
    return [by_date[k] for k in sorted(by_date)]


def _parse_analytics(cap, result):
    """解析数据分析页的 XHR：阅读/分享趋势、单篇文章数据、粉丝数。数据为 0 属新号真实值。"""
    try:
        if cap.get("tendency"):
            d = json.loads(cap["tendency"])
            daily = _daily_totals((d.get("all_article_stat_tendency") or {}).get("list") or [])
            read = sum(int(x.get("read_uv", 0) or 0) for x in daily)
            result["reads"] = read or result.get("reads")
            result["period_metrics"] = {
                "day": _tendency_metrics(daily, 1),
                "week": _tendency_metrics(daily, 7),
                "month": _tendency_metrics(daily, 30),
                "year": _tendency_metrics(daily, 365),
                "last": _tendency_metrics(daily, 7),
            }
            result["metrics"] = result["period_metrics"]["week"]
    except Exception:
        pass
    try:
        if cap.get("article_list"):
            d = json.loads(cap["article_list"])
            by_title = {}
            extras = []
            for a in (d.get("article_list") or []):
                info = a.get("appmsg_info") or a
                title = info.get("title") or a.get("title")
                if not title:
                    continue
                uv = int(info.get("total_read_uv") or info.get("read_num") or info.get("int_page_read_uv") or 0)
                share = int(info.get("share_num") or info.get("share_uv") or 0)
                stat = f"阅读 {uv} · 分享 {share}"
                by_title[title] = stat
                extras.append({"title": title, "url": info.get("link") or info.get("content_url") or "", "cover": info.get("cover") or "", "stat": stat})
            for n in result.get("notes", []):
                if n.get("title") in by_title:
                    n["stat"] = by_title[n["title"]]
            if not result.get("notes"):
                result["notes"] = extras[:20]
    except Exception:
        pass
    # 粉丝数（尽力：从用户汇总的累计关注取；新号为 0）
    try:
        if cap.get("user"):
            d = json.loads(cap["user"])
            found = {}
            _deep_find(d, {"cumulate_user", "user_cumulate", "total_user", "cur_user"}, found)
            if found:
                result["followers"] = int(next(iter(found.values())) or 0)
    except Exception:
        pass


def _tendency_metrics(lst, days):
    chunk = lst[-days:] if days and lst else []
    read = sum(int(x.get("read_uv", 0) or 0) for x in chunk)
    share = sum(int(x.get("share_uv", 0) or 0) for x in chunk)
    return [
        {"label": "阅读人数", "value": read, "vs": ""},
        {"label": "分享次数", "value": share, "vs": ""},
        {"label": "统计天数", "value": len(chunk), "vs": ""},
    ]


def _fetch_followers(page, token, result):
    for path in (
        f"https://mp.weixin.qq.com/misc/useranalysis?token={token}&lang=zh_CN",
        f"https://mp.weixin.qq.com/cgi-bin/home?t=home/index&token={token}&lang=zh_CN",
    ):
        try:
            page.goto(path, wait_until="commit", timeout=30000)
            page.wait_for_timeout(1500)
            html = page.content()
            m = re.search(r"(累计关注|关注用户|粉丝数)[^\d%]{0,12}(\d[\d,]*)", html)
            if m and "%" not in html[m.end(): m.end() + 2]:
                result["followers"] = int(m.group(2).replace(",", ""))
                return
            txt = page.inner_text("body")
            for label in ("累计关注", "关注用户", "粉丝数"):
                mm = re.search(rf"{label}\s*[:：]?\s*([\d,]+)", txt)
                if mm:
                    result["followers"] = int(mm.group(1).replace(",", ""))
                    return
        except Exception:
            continue


def _apply_nickname(page, result):
    if result.get("nickname") and result["nickname"] != result.get("name"):
        return
    for sel in (".weui-desktop-account__nickname", ".account_nickname", "#nickname", ".weui-desktop-account__info"):
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.inner_text() or "").strip().splitlines()[0].strip()
                if text and text not in ("微信公众号", result.get("name")):
                    result["nickname"] = text
                    return
        except Exception:
            continue
    if not result.get("nickname"):
        result["nickname"] = result.get("name") or "微信公众号"


def _attach_growth(result):
    import account_stats
    now = int(time.time())
    snap = {
        "ts": now,
        "followers": result.get("followers"),
        "likes": result.get("likes"),
        "posts": result.get("posts"),
        "reads": result.get("reads"),
    }
    history = account_stats.load_history("wechat-oa")
    result["growth"] = account_stats.growth_windows(history, snap)
    if not result.get("error") and any(snap.get(k) is not None for k in ("followers", "likes", "posts")):
        account_stats.record_snapshot("wechat-oa", snap)
    result["overview"] = [
        {"key": "followers", "label": "粉丝", "value": result.get("followers")},
        {"key": "posts", "label": "已发表", "value": result.get("posts")},
        {"key": "likes", "label": "点赞", "value": result.get("likes")},
    ]
    result["fetched_at"] = now
    result["following"] = None


def _editor_ctx(page, token):
    """打开图文编辑器页，抽取上传所需的 ticket / user_name。

    ticket / user_name 就在**服务端渲染的 HTML** 里，因此优先用纯 HTTP 抓取（page.request.get），
    不经浏览器渲染——这样就不依赖编辑器 Vue 界面的 JS/CSS（res.wx.qq.com CDN）能否加载。
    实测该 CDN 偶发 TLS 握手卡死时，page.goto()+page.content() 会停在只有 <head> 的空壳、
    读不到 ticket（误报“编辑器改版 / 未取到 ticket”）；纯 HTTP 抓服务端 HTML 不受此影响。
    纯 HTTP 少数情况下没拿到时，再退回浏览器渲染兜底。"""
    edit = (f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1"
            f"&type=77&createType=0&token={token}&lang=zh_CN")

    def grab(key, html):
        m = re.search(rf'{key}["\']?\s*[:=]\s*["\']?([\w%.-]+)', html)
        return m.group(1) if m else ""

    # 1) 优先纯 HTTP 抓服务端 HTML（不渲染、不加载 res.wx.qq.com 资源）
    html = ""
    try:
        r = page.request.get(edit, timeout=30000)
        if r.ok:
            html = r.text()
    except Exception:
        html = ""

    # 2) 纯 HTTP 没拿到 ticket（少见）→ 退回浏览器渲染再取一次
    if not grab("ticket", html):
        try:
            page.goto(edit, wait_until="commit", timeout=60000)
            page.wait_for_timeout(3500)
            html = page.content()
        except Exception:
            pass

    return {"ticket": grab("ticket", html), "user_name": grab("user_name", html),
            "nick_name": grab("nick_name", html)}


def cmd_publish(a):
    """用后台会话建草稿（免 AppID/AppSecret、免 IP 白名单）。
    步骤：编辑器取 ticket → filetransfer 传封面 → operate_appmsg sub=create 建草稿。"""
    from playwright.sync_api import sync_playwright
    import time as _t
    out = {"success": False, "media_id": "", "error": None}
    html = Path(a.html).read_text(encoding="utf-8")
    title = a.title[:64]
    digest = (a.digest or "")[:120]
    author = a.author or ""
    with sync_playwright() as p:
        ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(MP_HOME, wait_until="commit", timeout=60000); page.wait_for_timeout(1500)
            token = _extract_token(page.url)
            if not token:
                out["error"] = "未登录 mp 后台，请先 login 扫码"; print(json.dumps(out, ensure_ascii=False)); return 1
            info = _editor_ctx(page, token)
            if not info.get("ticket"):
                out["error"] = "未取到上传 ticket（编辑器页结构可能变化）"; print(json.dumps(out, ensure_ascii=False)); return 1

            # 上传素材统一走 filetransfer?action=upload_material&writetype=doublewrite
            # （真实编辑器用的接口；uploadimg2cdn 在会话模式下常返回 errcode -1 / invalid referrer，
            #  且响应里的 cdn_url 才是新版编辑器识别封面/正文图所需的字段）
            def _upload_material(fpath, mime):
                svr = str(int(_t.time() * 1000))
                u = (f"https://mp.weixin.qq.com/cgi-bin/filetransfer?action=upload_material&f=json&scene=8"
                     f"&writetype=doublewrite&groupid=1&ticket_id={info['user_name']}&ticket={info['ticket']}"
                     f"&svr_time={svr}&token={token}&lang=zh_CN")
                rr = page.request.post(u, multipart={
                    "file": {"name": fpath.name, "mimeType": mime, "buffer": fpath.read_bytes()}},
                    headers={"Referer": page.url})
                try:
                    return rr.json()
                except Exception:
                    return {"_raw": rr.text()[:200]}

            # 1) 上传封面为永久素材
            cover = Path(a.cover)
            up = _upload_material(cover, "image/jpeg")
            content = up.get("content")
            if isinstance(content, str):
                thumb_media_id = content            # filetransfer 直接返回 media_id 字符串
            elif isinstance(content, dict):
                thumb_media_id = content.get("media_id", "")
            else:
                thumb_media_id = up.get("media_id", "")
            cover_cdn_url = up.get("cdn_url") or (content.get("cdn_url") if isinstance(content, dict) else "") or ""
            if str(up.get("base_resp", {}).get("ret", 0)) != "0":
                out["error"] = f"封面上传失败: {json.dumps(up, ensure_ascii=False)[:200]}"
                print(json.dumps(out, ensure_ascii=False)); return 1
            if not thumb_media_id:
                out["error"] = f"封面上传失败: {json.dumps(up, ensure_ascii=False)[:200]}"
                print(json.dumps(out, ensure_ascii=False)); return 1

            # 1.5) 正文内嵌图片 → 同一 upload_material 接口，取响应 cdn_url 替换 src
            def _upload_content_img(path):
                img = Path(path) if path else None
                if img is None or not img.is_file():
                    return None
                mime = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
                jj = _upload_material(img, mime)
                c = jj.get("content")
                url = jj.get("cdn_url") or (c.get("cdn_url") if isinstance(c, dict) else None)
                return url

            def _repl(m):
                src = m.group(1)
                if src.startswith("http") and "/api/media/" not in src:
                    return m.group(0)
                local = resolve_content_image(src, a.html)
                if local is None:
                    return m.group(0)
                url = _upload_content_img(local)
                return m.group(0).replace(src, url) if url else m.group(0)
            html = re.sub(r'<img[^>]*\bsrc=["\']([^"\']+)["\']', _repl, html)

            # 2) operate_appmsg 建草稿
            op_url = (f"https://mp.weixin.qq.com/cgi-bin/operate_appmsg?t=ajax-response&sub=create&type=10"
                      f"&token={token}&lang=zh_CN&f=json&ajax=1")
            form = {
                "token": token, "lang": "zh_CN", "f": "json", "ajax": "1",
                "random": str(_t.time())[-6:], "AppMsgId": "", "count": "1",
                "data_seq": "0", "operate_from": "Chrome", "isnew": "1", "articlenum": "1",
                "title0": title, "author0": author, "digest0": digest,
                "content0": html, "sourceurl0": a.source_url or "",
                "show_cover_pic0": "0", "thumb_media_id0": thumb_media_id,
                "shortvideofileid0": "", "copyright_type0": "0", "fileid0": "",
                "need_open_comment0": "0", "only_fans_can_comment0": "0",
                "can_reward0": "0",
            }
            # 新版编辑器封面不再只读 thumb_media_id0，还读 cdn_*_url0；没拿到 cdn_url 就不加（避免传空字符串覆盖）
            if cover_cdn_url:
                form.update({
                    "cdn_url0": cover_cdn_url, "cdn_235_1_url0": cover_cdn_url,
                    "cdn_1_1_url0": cover_cdn_url, "cdn_16_9_url0": cover_cdn_url,
                })
            r2 = page.request.post(op_url, form=form,
                                   headers={"Referer": page.url, "X-Requested-With": "XMLHttpRequest"})
            try:
                res = r2.json()
            except Exception:
                out["error"] = f"建草稿返回非JSON: {r2.text()[:200]}"; print(json.dumps(out, ensure_ascii=False)); return 1
            ret = res.get("ret", res.get("base_resp", {}).get("ret", -1))
            if str(ret) == "0":
                media_id = str(res.get("appMsgId") or res.get("appmsgid") or res.get("app_id") or "").strip()
                if not media_id:
                    out["error"] = "建草稿成功但未返回草稿 ID"
                    print(json.dumps(out, ensure_ascii=False)); return 1
                out["success"] = True
                out["media_id"] = media_id
                out["thumb_media_id"] = thumb_media_id
                print(json.dumps(out, ensure_ascii=False)); return 0
            out["error"] = f"建草稿失败 ret={ret}: {json.dumps(res, ensure_ascii=False)[:250]}"
            print(json.dumps(out, ensure_ascii=False)); return 1
        finally:
            ctx.close()


def cmd_selftest(_a=None):
    raw = json.dumps({
        "publish_page": json.dumps({
            "total_count": 37, "publish_count": 0, "masssend_count": 12,
            "publish_list": [{
                "publish_info": json.dumps({
                    "appmsgex": [{"title": "a", "link": "https://mp.weixin.qq.com/s/x", "read_num": 80, "like_num": 3}],
                }, ensure_ascii=False),
            }],
        }, ensure_ascii=False),
    }, ensure_ascii=False)
    result = dict(EMPTY)
    result["metrics"] = []
    _parse_publish(raw, result)
    assert result["posts"] == 37, result["posts"]
    assert result["likes"] == 3, result["likes"]
    assert result["reads"] == 80, result["reads"]
    assert result["likes"] != result["reads"]
    lst = [{"date": i, "scene": 9999, "read_uv": 10, "share_uv": 1} for i in range(30)]
    noisy = lst + [{"date": 29, "scene": 1, "read_uv": 99, "share_uv": 9}]
    daily = _daily_totals(noisy)
    week = _tendency_metrics(daily, 7)
    month = _tendency_metrics(daily, 30)
    assert len(daily) == 30, len(daily)
    assert week[0]["value"] == 70 and month[0]["value"] == 300
    print("weixin_mp_stats selftest ok")
    return 0


def cmd_whoami(a):
    from playwright.sync_api import sync_playwright
    out = {"loggedIn": False, "name": "", "avatar": ""}
    try:
        with sync_playwright() as p:
            ctx = _launch(p, a.headed, a.profile_base, _proxy(a.proxy, a.no_proxy))
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(MP_HOME, wait_until="commit", timeout=60000)
                page.wait_for_timeout(1200)
                out["loggedIn"] = bool(_extract_token(page.url))
            finally:
                ctx.close()
    except Exception as e:
        out["error"] = str(e)
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="微信公众号后台数据回收（mp 管理员会话）")
    sub = ap.add_subparsers(dest="cmd")

    def common(x):
        x.add_argument("--profile-base")
        x.add_argument("--proxy")
        x.add_argument("--no-proxy", action="store_true")
        x.add_argument("--headed", action="store_true")

    lp = sub.add_parser("login"); common(lp)
    lp.add_argument("--qr-out"); lp.add_argument("--status-file")
    lp.add_argument("--timeout", type=int, default=240)
    lp.set_defaults(func=cmd_login)

    sp = sub.add_parser("stats"); common(sp)
    sp.add_argument("--count", type=int, default=20)
    sp.add_argument("--dump-dir", help="调试：把原始响应落盘")
    sp.set_defaults(func=cmd_stats)

    wp = sub.add_parser("whoami"); common(wp)
    wp.set_defaults(func=cmd_whoami)

    tp = sub.add_parser("selftest")
    tp.set_defaults(func=cmd_selftest)

    pp = sub.add_parser("publish"); common(pp)
    pp.add_argument("--html", required=True, help="已排版的公众号 HTML 文件")
    pp.add_argument("--cover", required=True, help="封面图路径")
    pp.add_argument("--title", required=True)
    pp.add_argument("--digest", default="")
    pp.add_argument("--author", default="")
    pp.add_argument("--source-url", default="")
    pp.set_defaults(func=cmd_publish)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help(); return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
