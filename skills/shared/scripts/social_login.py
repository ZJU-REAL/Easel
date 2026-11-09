#!/usr/bin/env python3
"""Overseas social accounts: interactive official-site login in a dedicated browser.

This module manages browser sessions only. It does not grant API publishing scopes.
Passwords and verification codes are entered directly on the platform website.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.parse import unquote, urlparse

import login_state


PLATFORMS: dict[str, dict] = {
    "facebook": {
        "name": "Facebook", "profile": "FacebookProfile",
        "login_url": "https://www.facebook.com/login/",
        "home_url": "https://www.facebook.com/", "domains": ("facebook.com",),
        "cookies": (("c_user", "xs"),),
        "authenticated": ('[aria-label="Your profile"]', '[aria-label="你的个人主页"]',
                          '[aria-label="你的個人檔案"]', '[aria-label="Account"]'),
        "logged_out": ('input[name="email"]', 'input[name="pass"]'),
        "login_paths": ("/login", "/reg"),
        "challenge_paths": ("/checkpoint", "/two_step_verification", "/recover"),
    },
    "instagram": {
        "name": "Instagram", "profile": "InstagramProfile",
        "login_url": "https://www.instagram.com/accounts/login/",
        "home_url": "https://www.instagram.com/", "domains": ("instagram.com",),
        "cookies": (("sessionid", "ds_user_id"),),
        "authenticated": ('a[href^="/direct/inbox"]', 'a[href="/accounts/edit/"]',
                          'svg[aria-label="Settings"]', 'svg[aria-label="设置"]'),
        "logged_out": ('input[name="username"]', 'input[name="password"]'),
        "login_paths": ("/accounts/login", "/accounts/signup"),
        "challenge_paths": ("/challenge", "/checkpoint", "/accounts/login/two_factor", "/accounts/suspended"),
    },
    "tiktok": {
        "name": "TikTok", "profile": "TikTokProfile",
        "login_url": "https://www.tiktok.com/login",
        "home_url": "https://www.tiktok.com/", "domains": ("tiktok.com",),
        "cookies": (("sessionid",), ("sessionid_ss",)),
        "authenticated": ('[data-e2e="profile-icon"]', '[data-e2e="nav-profile"]'),
        "logged_out": ('[data-e2e="top-login-button"]', '[data-e2e="login-modal"]'),
        "login_paths": ("/login", "/signup"),
        "challenge_paths": ("/challenge", "/captcha", "/verify"),
    },
    "youtube": {
        "name": "YouTube", "profile": "YouTubeProfile",
        "login_url": "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fwww.youtube.com%2F",
        "home_url": "https://www.youtube.com/", "domains": ("youtube.com",),
        "cookies": (("SAPISID",), ("__Secure-3PAPISID",), ("__Secure-1PAPISID",)),
        "authenticated": ('button#avatar-btn img', 'ytd-masthead #avatar-btn img'),
        "logged_out": ('ytd-masthead a[href*="accounts.google.com/ServiceLogin"]',
                       'ytd-masthead a[aria-label="Sign in"]'),
        "login_paths": ("/signin",), "challenge_paths": (),
    },
}


def profile_dir(platform: str, base: str | None = None) -> Path:
    root = Path(base or os.environ.get("EASEL_BROWSER_PROFILES") or "~/.easel-browser-profiles").expanduser()
    return root / PLATFORMS[platform]["profile"]


def browser_options(*, headless: bool) -> dict:
    options = {"headless": headless, "locale": "en-US", "viewport": {"width": 1280, "height": 900}}
    # Chromium does not automatically consume the HTTP(S)_PROXY environment.
    # With no explicit proxy, leave Chromium's system network configuration intact.
    proxy_url = next((os.environ[key].strip() for key in (
        "EASEL_SOCIAL_PROXY", "EASEL_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY",
    ) if os.environ.get(key, "").strip()), "")
    if proxy_url:
        parsed = urlparse(proxy_url)
        if parsed.scheme not in {"http", "https", "socks5"} or not parsed.hostname:
            raise ValueError("海外平台代理配置无效，请使用 http、https 或 socks5 地址")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        proxy = {"server": f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")}
        if parsed.username:
            proxy["username"] = unquote(parsed.username)
        if parsed.password:
            proxy["password"] = unquote(parsed.password)
        options["proxy"] = proxy
    return options


def _launch_context(playwright, platform: str, base: str | None, *, headless: bool):
    profile = profile_dir(platform, base)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    return playwright.chromium.launch_persistent_context(str(profile), **browser_options(headless=headless))


def _visible(page, selectors):
    for selector in selectors:
        for element in page.locator(selector).all():
            if element.is_visible():
                return element
    return None


def inspect_account(page, cfg: dict) -> dict:
    """Require both an authenticated navigation control and a scoped session cookie.

    An incomplete page, network error or checkpoint is unknown, never a verified
    logout. The web API preserves the last verified identity when error is present.
    """
    result = {"loggedIn": False, "name": "", "avatar": ""}
    parsed = urlparse(page.url)
    host = parsed.hostname or ""
    trusted = parsed.scheme == "https" and any(host == domain or host.endswith("." + domain)
                                               for domain in cfg["domains"])
    if not trusted:
        return {**result, "error": "平台页面尚未就绪，请在浏览器完成登录或验证"}
    if any(parsed.path.startswith(path) for path in cfg["challenge_paths"]):
        return {**result, "error": "平台需要安全验证，请在浏览器窗口完成"}
    if _visible(page, cfg["logged_out"]) is not None:
        return result
    control = _visible(page, cfg["authenticated"])
    cookies = {cookie["name"] for cookie in page.context.cookies([cfg["home_url"]]) if cookie.get("value")}
    has_session = any(all(name in cookies for name in group) for group in cfg["cookies"])
    if (control is None or not has_session
            or any(parsed.path.startswith(path) for path in cfg["login_paths"])):
        return {**result, "error": "尚未取得已登录账号信息，请等待页面加载或重新登录"}
    result["loggedIn"] = True
    # Read only the authenticated account control; never borrow a feed author's identity.
    identity = control.evaluate("""el => {
        const image = el.matches('img, image') ? el : el.querySelector('img, image');
        return {avatar: image?.getAttribute('src') || image?.getAttribute('href') || '',
                name: image?.getAttribute('alt') || '', href: el.getAttribute('href') || ''};
    }""")
    if identity["avatar"].startswith("https://"):
        result["avatar"] = identity["avatar"]
    if cfg["profile"] == "YouTubeProfile":
        result["name"] = identity["name"]
    return result


def _browser_error(error: Exception) -> str:
    """Actionable errors without leaking cookie values, proxy credentials or URLs."""
    detail = str(error).lower()
    if "has been closed" in detail or "targetclosed" in detail:
        return "登录浏览器已关闭，请重新登录"
    if "executable doesn't exist" in detail:
        return "未安装登录浏览器，请运行 playwright install chromium 后重试"
    if "display" in detail or "xserver" in detail:
        return "海外平台登录需要桌面浏览器，请在运行 Easel 的电脑上启用图形桌面后重试"
    if "singleton" in detail or "processsingleton" in detail:
        return "该账号浏览器正在使用中，请关闭已有窗口后重试"
    if any(marker in detail for marker in ("net::", "timeout", "proxy", "connection")):
        return "无法连接平台，请检查运行 Easel 的电脑是否可访问海外网站及代理设置后重试"
    return "平台登录浏览器未能完成操作，请关闭窗口后重试"


def cmd_login(args) -> int:
    cfg = PLATFORMS[args.platform]
    status = args.status_file
    login_state.write_status(status, "starting", "正在打开平台登录浏览器…")
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(_signum, _frame):
        raise SystemExit(130)

    signal.signal(signal.SIGTERM, terminate)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = _launch_context(playwright, args.platform, args.profile_base, headless=False)
            succeeded = False
            try:
                page = context.pages[0] if context.pages else context.new_page()
                login_state.write_status(status, "window_login",
                    "密码与验证码请直接在平台官网输入")
                response = page.goto(cfg["login_url"], wait_until="domcontentloaded", timeout=45000)
                if response is not None and response.status >= 400:
                    login_state.write_status(status, "window_login",
                        f"平台暂时限制访问（HTTP {response.status}），请在浏览器中检查网络或完成安全验证后重试")
                deadline = time.monotonic() + args.timeout
                while time.monotonic() < deadline:
                    pages = [candidate for candidate in context.pages if not candidate.is_closed()]
                    if not pages:
                        login_state.write_status(status, "error", "登录浏览器已关闭，请重新登录")
                        return 1
                    for candidate in pages:
                        try:
                            result = inspect_account(candidate, cfg)
                        except Exception:
                            # Navigations may replace the DOM during a probe.
                            continue
                        if result["loggedIn"]:
                            succeeded = True
                            break
                    if succeeded:
                        break
                    pages[0].wait_for_timeout(1000)
            finally:
                # Flush the persistent profile before publishing success and
                # before whoami is allowed to acquire the same browser directory.
                context.close()
            if succeeded:
                login_state.write_status(status, "success", f"{cfg['name']} 登录成功，账号会话已保存")
                return 0
            login_state.write_status(status, "expired", "登录等待超时，请重新打开浏览器完成登录")
            return 1
    except (SystemExit, KeyboardInterrupt):
        login_state.write_status(status, "error", "登录已取消，可重新登录")
        return 130
    except Exception as error:
        login_state.write_status(status, "error", _browser_error(error))
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


def cmd_whoami(args) -> int:
    result = {"loggedIn": False, "name": "", "avatar": ""}
    if not profile_dir(args.platform, args.profile_base).is_dir():
        print(json.dumps(result))
        return 0
    try:
        from playwright.sync_api import sync_playwright

        cfg = PLATFORMS[args.platform]
        with sync_playwright() as playwright:
            context = _launch_context(playwright, args.platform, args.profile_base, headless=True)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                response = page.goto(cfg["home_url"], wait_until="domcontentloaded", timeout=25000)
                if response is not None and response.status >= 400:
                    raise RuntimeError("connection: platform temporarily unavailable")
                deadline = time.monotonic() + 10
                while True:
                    result = inspect_account(page, cfg)
                    if not result.get("error") or time.monotonic() >= deadline:
                        break
                    page.wait_for_timeout(500)
            finally:
                context.close()
    except Exception as error:
        result = {"loggedIn": False, "name": "", "avatar": "", "error": _browser_error(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    login_state.configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command, handler in (("login", cmd_login), ("whoami", cmd_whoami)):
        child = commands.add_parser(command)
        child.add_argument("--platform", required=True, choices=PLATFORMS)
        child.add_argument("--profile-base")
        if command == "login":
            child.add_argument("--status-file", required=True)
            child.add_argument("--timeout", type=int, default=240)
        child.set_defaults(func=handler)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
