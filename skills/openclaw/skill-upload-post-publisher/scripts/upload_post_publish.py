#!/usr/bin/env python3
"""upload_post_publish.py — 海外平台发布（Upload-Post API）。

一次调用把视频 / 图文 / 纯文本发到 TikTok、Instagram、YouTube、LinkedIn、X、Facebook、
Threads、Pinterest、Bluesky。纯 API：不开浏览器、不用 cookie，无头环境可用。
与国内平台的 publisher（浏览器 / CLI）互补，不替换。

⚠️ 环境依赖：
    - `.env` 配 UPLOAD_POST_API_KEY（https://upload-post.com 控制台创建）
    - UPLOAD_POST_USER：在 Upload-Post 里连好各平台账号的 profile 名（或 --user）
    - 外网
  无 key 时 `platforms` / `publish`（dry-run）/ `selftest` 仍可用。

发布判定：上传是异步的——提交后按 request_id 轮询状态接口，逐平台给结论
（completed 带链接 / failed 带平台原因 / skipped = 该 profile 没连这个平台）。
客户端自己生成 request_id 并作为 Idempotency-Key 发送：网络中断时**不重发文件**，
改为轮询同一个 request_id 确认是否已到达，避免重复发布。

子命令：
    platforms  列出支持平台与内容类型
    check      校验 key + profile，列出已连接的平台
    publish    发布（默认 dry-run 预览；--exec 真正发布）
    status     按 request_id / job_id 查询发布结果
    selftest   自检（离线）

用法举例：
    upload_post_publish.py check
    upload_post_publish.py publish --platforms tiktok,instagram,youtube \\
        --media out.mp4 --title "标题 #AI"            # dry-run 预览
    upload_post_publish.py publish ... --exec          # 真正发布
    upload_post_publish.py status --id <request_id>
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

SHARED_SCRIPTS = Path(__file__).resolve().parents[3] / "shared" / "scripts"
sys.path.insert(0, str(SHARED_SCRIPTS))
import content_guard  # noqa: E402  出站内容安全闸门

API_BASE = os.environ.get("UPLOAD_POST_API_BASE", "https://api.upload-post.com")

# 平台 → 支持的内容类型 + 展示名
PLATFORMS: dict[str, dict] = {
    "tiktok":    {"name": "TikTok", "types": ["video", "image"]},
    "instagram": {"name": "Instagram", "types": ["video", "image"]},
    "youtube":   {"name": "YouTube", "types": ["video"]},
    "linkedin":  {"name": "LinkedIn", "types": ["video", "image", "text"]},
    "x":         {"name": "X", "types": ["video", "image", "text"]},
    "facebook":  {"name": "Facebook", "types": ["video", "image", "text"]},
    "threads":   {"name": "Threads", "types": ["video", "image", "text"]},
    "pinterest": {"name": "Pinterest", "types": ["video", "image"]},
    "bluesky":   {"name": "Bluesky", "types": ["video", "image", "text"]},
}
ALIASES = {"twitter": "x", "ig": "instagram", "yt": "youtube", "reels": "instagram",
           "shorts": "youtube"}
ENDPOINTS = {"video": "/api/upload", "image": "/api/upload_photos", "text": "/api/upload_text"}

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
YOUTUBE_PRIVACY = ("private", "unlisted", "public")
TIKTOK_PRIVACY = ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                  "SELF_ONLY")
FINAL_STATUSES = {"completed", "failed", "not_found"}

POLL_INTERVAL = 10          # 状态接口有缓存，10s 一次足够
DEFAULT_WAIT = 600          # 默认最多等 10 分钟；超时不取消，服务端继续
UPLOAD_TIMEOUT = 900.0      # 上传大文件
API_TIMEOUT = 60.0


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _env(name: str) -> str:
    """环境变量优先，其次从当前目录向上找 .env（与 model_registry 同一套读法）。"""
    import model_registry
    value = model_registry.read_env_file().get(name, "").strip()
    return "" if model_registry._PLACEHOLDER_RE.search(value) else value


def api_key() -> str:
    return _env("UPLOAD_POST_API_KEY")


def default_user() -> str:
    return _env("UPLOAD_POST_USER")


# --------------------------------------------------------------------------- #
# HTTP（单独封装，测试里 monkeypatch 这两个函数即可离线）
# --------------------------------------------------------------------------- #
def _headers(key: str) -> dict:
    return {"Authorization": f"Apikey {key}"}  # 注意是 Apikey，不是 Bearer


def _json_or_raise(resp) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"message": resp.text[:300]}
    if resp.status_code >= 400:
        msg = body.get("message") or body.get("error") or body if isinstance(body, dict) else body
        raise ApiError(f"HTTP {resp.status_code}: {msg}", resp.status_code)
    return body


def http_get(path: str, key: str, params: dict | None = None) -> dict:
    import httpx
    resp = httpx.get(f"{API_BASE}{path}", headers=_headers(key), params=params,
                     timeout=API_TIMEOUT)
    if resp.status_code == 404 and path.endswith("/status"):
        return {"status": "not_found"}
    return _json_or_raise(resp)


def http_post(path: str, key: str, data: dict, files: list, headers: dict) -> dict:
    import httpx
    # httpx 的 data 必须是 dict；重复字段（platform[] 等）用 list 值
    resp = httpx.post(f"{API_BASE}{path}", headers={**_headers(key), **headers},
                      data=data, files=files or None, timeout=UPLOAD_TIMEOUT)
    return _json_or_raise(resp)


# --------------------------------------------------------------------------- #
# 请求构造
# --------------------------------------------------------------------------- #
def parse_platforms(raw: str) -> list[str]:
    out: list[str] = []
    for p in re.split(r"[,，\s]+", raw or ""):
        p = ALIASES.get(p.strip().lower(), p.strip().lower())
        if p and p not in out:
            out.append(p)
    return out


def media_kind(media: list[str]) -> str:
    if not media:
        return "text"
    exts = {Path(m).suffix.lower() for m in media}
    if exts <= VIDEO_EXTS and len(media) == 1:
        return "video"
    if exts <= IMAGE_EXTS:
        return "image"
    _die("--media 只能是 1 个视频，或 1~N 张图片（不能混用）")
    return ""


def caption(title: str, tags: str) -> str:
    """把话题标签接到标题后（海外平台的 caption 就是标题 + #tags）。"""
    tags = " ".join(t if t.startswith("#") else f"#{t}"
                    for t in re.split(r"[,，\s]+", tags or "") if t)
    return f"{title} {tags}".strip() if tags else (title or "")


def build_form(a, kind: str, request_id: str) -> dict:
    form: dict = {
        "user": a.user,
        "platform[]": a.platform_list,
        "title": caption(a.title or "", a.tags or ""),
        "request_id": request_id,
        "async_upload": "true",
    }
    if a.desc:
        form["description"] = a.desc
    if a.schedule:
        form["scheduled_date"] = a.schedule
        if a.timezone:
            form["timezone"] = a.timezone
    if a.ai_generated:
        form["is_ai_generated"] = "true"  # TikTok / Instagram / YouTube / X 的 AI 标识
    if "youtube" in a.platform_list:
        form["privacyStatus"] = a.youtube_privacy
    if "tiktok" in a.platform_list and a.tiktok_privacy:
        form["privacy_level"] = a.tiktok_privacy
    if "pinterest" in a.platform_list and a.pinterest_board:
        form["pinterest_board_id"] = a.pinterest_board
    if "facebook" in a.platform_list and a.facebook_page_id:
        form["facebook_page_id"] = a.facebook_page_id
    return form


def validate(a) -> str:
    """返回内容类型；参数有误直接退出。在任何网络调用前执行。"""
    a.platform_list = parse_platforms(a.platforms)
    if not a.platform_list:
        _die(f"--platforms 必填，可选：{', '.join(PLATFORMS)}")
    unknown = [p for p in a.platform_list if p not in PLATFORMS]
    if unknown:
        _die(f"不支持的平台：{', '.join(unknown)}（可选：{', '.join(PLATFORMS)}）")
    media = a.media or []
    for m in media:
        if not Path(m).expanduser().is_file():
            _die(f"媒体文件不存在：{m}")
    kind = media_kind(media)
    bad = [p for p in a.platform_list if kind not in PLATFORMS[p]["types"]]
    if bad:
        _die(f"{', '.join(bad)} 不支持{ {'video': '视频', 'image': '图文', 'text': '纯文本'}[kind] }发布")
    if not (a.title or "").strip():
        _die("--title 必填（海外平台的文案 / 标题）")
    if "youtube" in a.platform_list and len(a.title) > 100:
        _die(f"YouTube 标题≤100 字符，当前 {len(a.title)}")
    if "pinterest" in a.platform_list and not a.pinterest_board:
        _die("Pinterest 需要 --pinterest-board")
    if not a.user:
        _die("缺少 profile：配置 UPLOAD_POST_USER 或传 --user")
    if a.schedule:
        raw = a.schedule.strip()
        try:
            dt = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            _die(f"--schedule 不是合法的 ISO8601 时间：{a.schedule}")
        if dt.tzinfo is None and not a.timezone:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo and dt <= datetime.now(timezone.utc):
            _die("--schedule 必须是将来时间")
    return kind


# --------------------------------------------------------------------------- #
# 结果
# --------------------------------------------------------------------------- #
def summarize(status: dict) -> list[dict]:
    """把状态接口的 results 统一成 [{platform, status, url, post_id, note, error}]。"""
    raw = status.get("results") or []
    if isinstance(raw, dict):
        raw = [{"platform": p, **r} for p, r in raw.items()]
    out = []
    for r in raw:
        if r.get("skipped"):
            state = "skipped"
        elif r.get("status"):
            state = r["status"]
        else:
            state = "completed" if r.get("success") else "failed"
        post_id = r.get("platform_post_id")
        raw_url = r.get("post_url") or r.get("url")
        url = raw_url if raw_url and str(raw_url).startswith("http") else ""
        if not url and r.get("platform") == "youtube" and post_id:
            url = f"https://www.youtube.com/watch?v={post_id}"  # 私密视频本人可见
        out.append({
            "platform": r.get("platform"),
            "status": state,
            "url": url,
            "post_id": post_id,
            "note": raw_url if raw_url and not url else "",
            "error": (r.get("error_message") or r.get("error") or "") if state != "completed" else "",
            "inbox": bool(r.get("fallback_to_inbox")),
        })
    return out


def wait_for(key: str, request_id: str, wait: int) -> dict:
    deadline = time.monotonic() + wait
    last = None
    while True:
        st = http_get("/api/uploadposts/status", key, {"request_id": request_id})
        cur = (st.get("status"), st.get("completed"), st.get("total"))
        if cur != last:
            print(f"  状态：{cur[0]}（{cur[1] or 0}/{cur[2] or '?'} 个平台完成）", file=sys.stderr)
            last = cur
        if st.get("status") in FINAL_STATUSES:
            return st
        if time.monotonic() >= deadline:
            st["timed_out"] = True
            return st
        time.sleep(POLL_INTERVAL)


def record(results: list[dict], a, kind: str) -> None:
    """发布成功的平台落内容日历 + skill-publish-log（record_publish 内部转发）。"""
    try:
        import calendar_ops
    except Exception:
        return
    ptype = {"video": "视频", "image": "图文", "text": "文字"}[kind]
    for r in results:
        if r["status"] == "completed":
            calendar_ops.record_publish(PLATFORMS.get(r["platform"], {}).get("name", r["platform"]),
                                        a.title, url=r["url"], ptype=ptype,
                                        tags=a.tags or "", note=a.desc or "", source="chat")


def report(status: dict, results: list[dict]) -> int:
    for r in results:
        name = PLATFORMS.get(r["platform"], {}).get("name", r["platform"])
        if r["status"] == "completed":
            where = ("已进 TikTok 收件箱草稿，需在 App 内手动发布" if r["inbox"]
                     else r["url"] or r["note"] or f"已发布（post id {r['post_id']}）")
            print(f"  ✅ {name}：{where}")
        elif r["status"] == "skipped":
            print(f"  ⏭️  {name}：跳过——该 profile 未连接此平台")
        elif r["status"] in ("failed", "retryable"):
            print(f"  ❌ {name}：{r['status']} — {r['error']}")
        else:
            print(f"  … {name}：{r['status']}")
    failed = [r for r in results if r["status"] in ("failed", "retryable")]
    done = [r for r in results if r["status"] == "completed"]
    if status.get("timed_out"):
        print("  ⏳ 等待超时，服务端仍在处理（不要重发）。稍后用 status 子命令查询。")
        return 0 if not failed else 1
    if status.get("status") == "not_found":
        return 1
    return 0 if done and not failed else 1


# --------------------------------------------------------------------------- #
# 子命令
# --------------------------------------------------------------------------- #
def cmd_platforms(_a) -> int:
    print(f"支持 {len(PLATFORMS)} 个海外平台：")
    names = {"video": "视频", "image": "图文", "text": "文字"}
    for k, c in PLATFORMS.items():
        print(f"  {k:10s} {c['name']:10s} {'/'.join(names[t] for t in c['types'])}")
    return 0


def cmd_check(a) -> int:
    key = api_key()
    if not key:
        _die("未配置 UPLOAD_POST_API_KEY（见 SKILL.md）", 2)
    user = a.user or default_user()
    try:
        me = http_get("/api/uploadposts/me", key)
        print(f"✅ key 有效（套餐：{me.get('plan')}）")
        if not user:
            print("⚠️ 未配置 UPLOAD_POST_USER；发布时需 --user")
            return 0
        prof = http_get(f"/api/uploadposts/users/{user}", key)
    except ApiError as e:
        _die(str(e), 2)
    accounts = (prof.get("profile") or prof).get("social_accounts") or {}
    connected = sorted(p for p, v in accounts.items() if v and p in PLATFORMS)
    print(f"✅ profile「{user}」已连接：{', '.join(connected) or '（无）'}")
    missing = [p for p in PLATFORMS if p not in connected]
    if missing:
        print(f"   未连接：{', '.join(missing)}（在 Upload-Post 控制台连接后可用）")
    return 0


def cmd_publish(a) -> int:
    a.user = a.user or default_user()
    kind = validate(a)
    request_id = str(uuid.uuid4())  # 带连字符，与 32 位 hex 的排期 job_id 区分
    form = build_form(a, kind, request_id)
    guard_parts = [a.title, a.desc, a.tags]
    label = "海外平台发布内容"

    if not a.exec:
        print("dry-run（加 --exec 真正发布）：")
        content_guard.guard_or_die(guard_parts, exec_mode=False,
                                   allow_unsafe=a.allow_unsafe, label=label)
        preview = {k: v for k, v in form.items() if k not in ("request_id", "async_upload")}
        print(json.dumps({"endpoint": ENDPOINTS[kind], "kind": kind, "media": a.media or [],
                          "form": preview}, ensure_ascii=False, indent=2))
        key = api_key()
        if not key:
            print("⚠️ 未配置 UPLOAD_POST_API_KEY，真发前需配置")
            return 0
        try:
            prof = http_get(f"/api/uploadposts/users/{a.user}", key)
            accounts = (prof.get("profile") or prof).get("social_accounts") or {}
            missing = [p for p in a.platform_list if not accounts.get(p)]
            if missing:
                print(f"⚠️ profile「{a.user}」未连接：{', '.join(missing)}——这些平台会被跳过")
            else:
                print(f"✅ profile「{a.user}」已连接全部目标平台")
        except ApiError as e:
            print(f"⚠️ 账号检查失败：{e}")
        return 0

    content_guard.guard_or_die(guard_parts, exec_mode=True,
                               allow_unsafe=a.allow_unsafe, label=label)
    key = api_key()
    if not key:
        _die("未配置 UPLOAD_POST_API_KEY（见 SKILL.md）", 2)

    print(f"→ 发布到 {', '.join(a.platform_list)}（profile：{a.user}）...", file=sys.stderr)
    field = {"video": "video", "image": "photos[]", "text": None}[kind]
    try:
        with ExitStack() as stack:
            files = [(field, (Path(m).name, stack.enter_context(open(Path(m).expanduser(), "rb")),
                              mimetypes.guess_type(m)[0] or "application/octet-stream"))
                     for m in (a.media or [])] if field else []
            resp = http_post(ENDPOINTS[kind], key, form, files,
                             {"Idempotency-Key": request_id})
    except ApiError as e:
        _die(str(e), 3)
    except Exception as e:  # noqa: BLE001 — 网络中断：文件可能已到达，绝不重发
        print(f"⚠️ 上传时网络异常（{e}），改为查询同一 request_id 是否已到达...", file=sys.stderr)
        resp = {"request_id": request_id}

    if a.schedule:
        print(f"✅ 已排期 {a.schedule}{' ' + a.timezone if a.timezone else ''}"
              f"（job_id {resp.get('job_id')}）。查询：status --id {request_id}")
        return 0
    if a.no_wait:
        print(f"✅ 已提交。查询：status --id {request_id}")
        return 0

    status = wait_for(key, request_id, a.wait_timeout)
    results = summarize(status)
    rc = report(status, results)
    record(results, a, kind)
    print(f"request_id: {request_id}")
    return rc


def cmd_status(a) -> int:
    key = api_key()
    if not key:
        _die("未配置 UPLOAD_POST_API_KEY", 2)
    # 排期 job_id 是 32 位 hex，本脚本的 request_id 是带连字符的 UUID：先按更可能的类型查
    kinds = ["job_id", "request_id"] if re.fullmatch(r"[0-9a-f]{32}", a.id) else ["request_id", "job_id"]
    try:
        for kind in kinds:
            st = http_get("/api/uploadposts/status", key, {kind: a.id})
            if st.get("status") != "not_found":
                break
    except ApiError as e:
        _die(str(e), 2)
    if st.get("status") == "not_found":
        print(f"未找到 {a.id}")
        return 1
    print(f"状态：{st.get('status')}")
    return report(st, summarize(st))


def cmd_selftest(_a) -> int:
    print("upload_post_publish 自检（离线）...", file=sys.stderr)
    assert parse_platforms("TikTok, ig，shorts twitter tiktok") == ["tiktok", "instagram",
                                                                    "youtube", "x"]
    assert caption("标题", "AI,#教程") == "标题 #AI #教程"
    ns = argparse.Namespace(user="u", platform_list=["youtube", "tiktok"], title="t", tags="",
                            desc="", schedule=None, timezone=None, ai_generated=True,
                            youtube_privacy="private", tiktok_privacy="SELF_ONLY",
                            pinterest_board=None, facebook_page_id=None)
    f = build_form(ns, "video", "rid")
    assert f["platform[]"] == ["youtube", "tiktok"] and f["privacyStatus"] == "private"
    assert f["privacy_level"] == "SELF_ONLY" and f["is_ai_generated"] == "true"
    res = summarize({"results": [
        {"platform": "youtube", "success": True, "platform_post_id": "abc",
         "post_url": "Post uploaded as Private. No public URL available."},
        {"platform": "x", "success": False, "error_message": "boom"},
        {"platform": "linkedin", "success": False, "skipped": True}]})
    assert [r["status"] for r in res] == ["completed", "failed", "skipped"]
    assert res[0]["url"].endswith("v=abc") and res[1]["error"] == "boom"
    print("✅ selftest 通过（平台解析/表单/结果归一）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="海外平台发布（Upload-Post API：TikTok/Instagram/YouTube/LinkedIn/X 等）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("platforms", help="列出平台").set_defaults(func=cmd_platforms)

    p = sub.add_parser("check", help="校验 key + profile 已连接平台")
    p.add_argument("--user", help="Upload-Post profile（默认 UPLOAD_POST_USER）")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("publish", help="发布（默认 dry-run）")
    p.add_argument("--platforms", required=True, help=f"逗号分隔：{','.join(PLATFORMS)}")
    p.add_argument("--media", action="append", help="1 个视频或多张图片（可重复）；不传即纯文本")
    p.add_argument("--title", help="文案 / 标题（YouTube ≤100 字符）")
    p.add_argument("--desc", help="长描述（YouTube / LinkedIn / Facebook / Pinterest）")
    p.add_argument("--tags", help="话题标签，逗号或空格分隔，会以 #tag 接在文案后")
    p.add_argument("--user", help="Upload-Post profile（默认 UPLOAD_POST_USER）")
    p.add_argument("--schedule", help="定时发布 ISO8601，如 2026-10-01T09:00:00")
    p.add_argument("--timezone", help="--schedule 的时区（IANA，如 Asia/Shanghai；默认 UTC）")
    p.add_argument("--youtube-privacy", choices=YOUTUBE_PRIVACY, default="private",
                   help="YouTube 可见性（默认 private）")
    p.add_argument("--tiktok-privacy", choices=TIKTOK_PRIVACY, help="TikTok 可见性（默认账号设置）")
    p.add_argument("--pinterest-board", help="Pinterest 画板 ID（发 Pinterest 必填）")
    p.add_argument("--facebook-page-id", help="Facebook 主页 ID（默认 profile 的主页）")
    p.add_argument("--ai-generated", action="store_true", help="声明 AI 生成内容（平台 AI 标识）")
    p.add_argument("--exec", action="store_true", help="真正发布（默认 dry-run）")
    p.add_argument("--allow-unsafe", action="store_true",
                   help="放行内容安全闸门（检出内部设置泄露也照发，谨慎）")
    p.add_argument("--no-wait", action="store_true", help="提交后不等待结果")
    p.add_argument("--wait-timeout", type=int, default=DEFAULT_WAIT, help="等待结果秒数（默认 600）")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("status", help="查询发布结果")
    p.add_argument("--id", required=True, help="request_id 或 job_id")
    p.set_defaults(func=cmd_status)

    sub.add_parser("selftest", help="自检").set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
