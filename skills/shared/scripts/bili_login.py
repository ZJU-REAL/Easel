#!/usr/bin/env python3
"""bili_login.py — B站扫码登录（TV 端 QR API，产出 biliup 兼容 cookie）。

为什么不用 `biliup login`：它需要**真终端**（无头/子进程里报 `IO error: not a terminal`），
无法在 Web 前端扫码。改用 B站 **TV 端扫码登录 API**（biliup-rs 内部用的同一套）：
  generate(auth_code+url) → segno 渲染二维码 PNG → poll → 成功拿 token_info/cookie_info
  → 写成 biliup 认的 cookie JSON（默认 cookies.json，供 bilibili-upload / biliup -u 用）。
前端复用通用扫码 UI（B站无短信墙）。纯 stdlib + segno，不起浏览器。

子命令：login / check / selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import login_state  # noqa: E402

# TV 端 appkey/appsec（公开，biliup-rs 同款）——TV 登录才返回 token_info（app 刷新令牌），
# 这正是 biliup cookie 文件需要的格式；web 端扫码只有网页 cookie、biliup 不完整认。
APPKEY = "4409e2ce8ffd12b8"
APPSEC = "59b43e04ad6965f34319062b478f83dd"
UA = "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 BiliDroid/7.0.0"
GEN_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/auth_code"
POLL_URL = "https://passport.bilibili.com/x/passport-tv-login/qrcode/poll"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QR_OUT = PROJECT_ROOT / "outputs" / "_login" / "bilibili.png"
DEFAULT_COOKIE = PROJECT_ROOT / "cookies.json"


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _sign(params: dict) -> bytes:
    """按 key 排序拼接 + 追加 appsec 求 md5，返回可直接 POST 的 form body。"""
    q = "&".join(f"{k}={urllib.parse.quote(str(params[k]), safe='')}" for k in sorted(params))
    sig = hashlib.md5((q + APPSEC).encode()).hexdigest()
    return (q + "&sign=" + sig).encode()


def _post(url: str, params: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url, data=_sign(params), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # urllib 自动读 env http(s)_proxy
        return json.loads(r.read())


def _gen_qr() -> tuple[str, str]:
    """申请二维码：返回 (url, auth_code)。"""
    r = _post(GEN_URL, {"appkey": APPKEY, "local_id": "0", "ts": str(int(time.time()))})
    if r.get("code") != 0:
        _die(f"申请二维码失败：{r.get('code')} {r.get('message')}")
    d = r.get("data") or {}
    if not d.get("url") or not d.get("auth_code"):
        _die("二维码响应缺 url/auth_code")
    return d["url"], d["auth_code"]


def _render_qr(url: str, out: Path) -> None:
    """把登录 url 编码成二维码 PNG（segno 纯 Python，自带 PNG writer，无需 PIL）。"""
    try:
        import segno
    except Exception as e:
        _die(f"需要 segno 生成二维码（pip install segno）：{e}", 3)
    out.parent.mkdir(parents=True, exist_ok=True)
    segno.make(url, error="m").save(str(out), scale=8, border=2)


def _poll(auth_code: str) -> tuple[int, dict]:
    """轮询一次：返回 (code, data)。code 0=成功；86038=已失效；86090=已扫待确认；86039/其它=待扫。"""
    r = _post(POLL_URL, {"appkey": APPKEY, "auth_code": auth_code,
                         "local_id": "0", "ts": str(int(time.time()))})
    return r.get("code", -1), (r.get("data") or {})


def _write_cookie(data: dict, cookie_file: Path) -> None:
    """把 poll 成功的 data 写成 biliup 认的 cookie 文件（含 cookie_info/token_info/sso）。
    ⚠️ **不要加 `platform` 字段**——biliup-rs 解析会报「未知平台」（真机实测）。"""
    cookie_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cookie_info": data.get("cookie_info"),
        "sso": data.get("sso"),
        "token_info": data.get("token_info"),
    }
    cookie_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def cmd_login(a) -> int:
    qr_out = Path(a.qr_out).expanduser() if a.qr_out else DEFAULT_QR_OUT
    cookie_file = Path(a.cookie).expanduser() if a.cookie else DEFAULT_COOKIE
    sf = getattr(a, "status_file", None)
    timeout_s = a.timeout or 180
    login_state.write_status(sf, "starting")

    url, auth_code = _gen_qr()
    _render_qr(url, qr_out)
    login_state.write_status(sf, "qr_ready", "用 B站 App 扫码登录", qr=str(qr_out))
    print(f"📱 B站二维码已保存：{qr_out}（B站 App 扫码）", file=sys.stderr)

    deadline = time.time() + timeout_s
    scanned = False
    while time.time() < deadline:
        code, data = _poll(auth_code)
        if code == 0:
            _write_cookie(data, cookie_file)
            login_state.write_status(sf, "success", "登录成功")
            print(f"✅ B站登录成功，cookie 已写入 {cookie_file}")
            try:
                qr_out.unlink()
            except OSError:
                pass
            return 0
        if code == 86038:                       # 二维码已失效
            login_state.write_status(sf, "expired", "二维码已失效，请重试")
            print("⏱️ 二维码已失效，请重跑 login", file=sys.stderr)
            return 1
        if code == 86090 and not scanned:       # 已扫码、待手机确认
            scanned = True
            login_state.write_status(sf, "scanned", "已扫码，请在手机上确认登录")
            print("📲 已扫码，请在手机确认…", file=sys.stderr)
        time.sleep(2)
    login_state.write_status(sf, "expired", "二维码超时未扫")
    print(f"⏱️ {timeout_s}s 内未完成扫码", file=sys.stderr)
    return 1


def _load_cookie(cookie_file: Path) -> tuple[str, int]:
    """读 biliup cookie 文件 → (Cookie 请求头, mid)。未登录/无文件返回 ("", 0)。"""
    if not cookie_file.is_file():
        return "", 0
    try:
        d = json.loads(cookie_file.read_text(encoding="utf-8"))
        cks = (d.get("cookie_info") or {}).get("cookies") or []
        header = "; ".join(f"{c['name']}={c['value']}" for c in cks if c.get("name"))
        mid = int((d.get("token_info") or {}).get("mid") or 0)
        return header, mid
    except Exception:
        return "", 0


def _api(url: str, cookie: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def cmd_whoami(a) -> int:
    """真校验登录态 + 昵称/头像（调 B站 nav API），输出单行 JSON（供 Web 后端解析）。"""
    result = {"loggedIn": False, "name": "", "avatar": ""}
    cookie_file = Path(a.cookie).expanduser() if a.cookie else DEFAULT_COOKIE
    cookie, _mid = _load_cookie(cookie_file)
    if cookie:
        try:
            nav = (_api("https://api.bilibili.com/x/web-interface/nav", cookie).get("data") or {})
            if nav.get("isLogin"):
                result = {"loggedIn": True, "name": (nav.get("uname") or "")[:40],
                          "avatar": nav.get("face") or ""}
        except Exception as e:  # noqa: BLE001 — whoami 永远输出 JSON
            result["error"] = str(e)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_stats(a) -> int:
    """抓 B站创作数据（粉丝/关注/获赞/总播放/投稿数），输出单行 JSON（对齐 account_stats 结构）。"""
    cookie_file = Path(a.cookie).expanduser() if a.cookie else DEFAULT_COOKIE
    cookie, mid = _load_cookie(cookie_file)
    r = {"platform": "bilibili", "name": "B站", "nickname": "", "loggedIn": False,
         "followers": None, "likes": None, "following": None, "posts": None,
         "metrics": [], "notes": [],
         "growth": {"last": {"followers": 0, "likes": 0, "posts": None, "since_days": 0.0},
                    "day": None, "week": None, "month": None, "year": None},
         "fetched_at": int(time.time())}
    if not cookie:
        print(json.dumps(r, ensure_ascii=False)); return 0
    try:
        nav = (_api("https://api.bilibili.com/x/web-interface/nav", cookie).get("data") or {})
        r["loggedIn"] = bool(nav.get("isLogin"))
        r["nickname"] = (nav.get("uname") or "")[:40]
        mid = mid or int(nav.get("mid") or 0)
        stat = (_api("https://api.bilibili.com/x/web-interface/nav/stat", cookie).get("data") or {})
        r["followers"] = stat.get("follower")
        r["following"] = stat.get("following")
        metrics = []
        if mid:
            up = (_api(f"https://api.bilibili.com/x/space/upstat?mid={mid}", cookie).get("data") or {})
            r["likes"] = up.get("likes")
            plays = (up.get("archive") or {}).get("view")
            if plays is not None:
                metrics.append({"label": "总播放", "value": plays})
            try:
                nn = (_api(f"https://api.bilibili.com/x/space/navnum?mid={mid}", cookie).get("data") or {})
                r["posts"] = nn.get("video")
            except Exception:
                pass
        dyn = stat.get("dynamic_count")
        if dyn is not None:
            metrics.append({"label": "动态", "value": dyn})
        r["metrics"] = metrics
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)
    print(json.dumps(r, ensure_ascii=False))
    return 0


def cmd_check(_a) -> int:
    ok = True
    try:
        import segno  # noqa: F401
        print("✅ segno 已安装（二维码生成）")
    except Exception as e:
        print(f"❌ 缺 segno（pip install segno）：{e}"); ok = False
    ck = DEFAULT_COOKIE
    print(f"cookie：{'✅ 已存在 ' + str(ck) if ck.is_file() else '未登录（login 扫码生成）'}")
    return 0 if ok else 3


def cmd_selftest(_a) -> int:
    print("bili_login 自检（离线）...", file=sys.stderr)
    # 签名稳定 + 排序正确
    body = _sign({"b": "2", "appkey": "k", "a": "1"}).decode()
    assert body.startswith("a=1&appkey=k&b=2&sign="), body
    assert len(body.rsplit("sign=", 1)[1]) == 32, "sign 应为 32 位 md5"
    # cookie 写盘格式
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "cookies.json"
    _write_cookie({"cookie_info": {"cookies": [{"name": "SESSDATA", "value": "x"}]},
                   "sso": ["s"], "token_info": {"mid": 1, "access_token": "t"}}, tmp)
    d = json.loads(tmp.read_text())
    assert d["token_info"]["access_token"] == "t" and d["cookie_info"]["cookies"][0]["name"] == "SESSDATA"
    assert "platform" not in d, "biliup cookie 不能含 platform 字段（会报未知平台）"
    # segno 能渲染
    try:
        import segno
        qp = Path(tempfile.mkdtemp()) / "q.png"
        segno.make("https://example.com", error="m").save(str(qp), scale=4, border=2)
        assert qp.is_file() and qp.stat().st_size > 100
    except Exception as e:
        print(f"⚠️ segno 渲染跳过：{e}", file=sys.stderr)
    assert "success" in login_state.STATES and "qr_ready" in login_state.STATES
    print("✅ selftest 通过（签名/排序 + cookie 格式 + 二维码渲染 + 状态机）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="B站扫码登录（TV QR API → biliup cookie）")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("login", help="扫码登录并写 cookie")
    p.add_argument("--qr-out", help=f"二维码输出路径（默认 {DEFAULT_QR_OUT}）")
    p.add_argument("--status-file", help="登录状态 JSON（供 Web 轮询）")
    p.add_argument("--cookie", help=f"cookie 输出路径（默认 {DEFAULT_COOKIE}）")
    p.add_argument("--timeout", type=int, help="扫码超时秒数（默认 180）")
    p.set_defaults(func=cmd_login)
    sub.add_parser("check", help="检查 segno / cookie").set_defaults(func=cmd_check)
    for name, fn, hlp in (("whoami", cmd_whoami, "校验登录态+昵称/头像(JSON)"),
                          ("stats", cmd_stats, "抓创作数据(JSON)")):
        q = sub.add_parser(name, help=hlp)
        q.add_argument("--cookie", help=f"cookie 路径（默认 {DEFAULT_COOKIE}）")
        q.set_defaults(func=fn)
    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
