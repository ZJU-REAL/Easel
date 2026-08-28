#!/usr/bin/env python3
"""account_stats.py — 归因层：抓取已登录账号的创作数据（Playwright，headless 可用）。

复用各平台**持久化登录态**（同 xhs_publish/web_publisher 的 <Platform>Profile）；登录一次两处通用。
抓取按「正文分行 + 标签就近取数」——不同平台概览区数字在标签前/后不一，故按平台配 direction，避免
把邻近的账号ID/曝光数等误当指标（曾把小红书账号号当获赞数）。数字解析/多窗口增长为纯函数，selftest 覆盖。

返回：概览(粉丝/获赞/关注) + 平台近7日各指标含环比 + 最新笔记链接 + 我方快照多窗口增长(较上次/日/周/月/年)。
子命令：check / fetch / selftest
真实抓取需：playwright + chromium + 已登录 + 干净网络（xhs 直连、其它走 env 代理，同发布层）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ANALYTICS_DIR = PROJECT_ROOT / "outputs" / "_analytics"
# 分层保留：近 KEEP_FULL_DAYS 天全部变化一条不丢；90~DAILY_DAYS 天每天≤1条；更老每周≤1条。
# 既留住 日/周/月/年 对比所需的老基线，又让总量恒定在几百条(几十KB)、用多年不膨胀。
KEEP_FULL_DAYS = 90
DAILY_DAYS = 400

# 每平台：登录 profile + 创作中心 URL + 概览标签(及数字方向) + 近7日指标标签 + 笔记链接匹配 + 代理默认。
# 概览 dir="before"：数字在标签上一行（小红书）；"after"：数字在标签下一行。真机校准见 fetch 的 debug dump。
PLATFORMS: dict[str, dict] = {
    "xiaohongshu": {
        "name": "小红书", "profile": "XiaohongshuProfile",
        "url": "https://creator.xiaohongshu.com/new/home", "default_proxy": False,
        "overview_dir": "before",
        "overview": {"followers": ["粉丝数"], "likes": ["获赞与收藏"], "following": ["关注数"]},
        "metrics": ["曝光数", "观看数", "点赞数", "评论数", "收藏数", "分享数", "净涨粉", "主页访客"],
        "note_url_re": r"xiaohongshu\.com/(explore|discovery/item)/|/publish/publish",
    },
    "douyin": {
        "name": "抖音", "profile": "DouyinProfile",
        "url": "https://creator.douyin.com/creator-micro/home", "default_proxy": True,
        "overview_dir": "after",
        "overview": {"followers": ["粉丝", "粉丝数"], "likes": ["获赞", "点赞"], "following": ["关注"]},
        "uid_anchor": "抖音号",  # 昵称=「抖音号：」上一行（主页在 抖音号 与 关注 间夹了干扰行）
        "metrics": ["播放量", "主页访问", "涨粉", "点赞", "评论", "分享", "主页访客"],
        "note_url_re": r"douyin\.com/(video|note)/|creator-micro/content",
    },
    "kuaishou": {
        "name": "快手", "profile": "KuaishouProfile",
        "url": "https://cp.kuaishou.com/profile", "default_proxy": True,
        "overview_dir": "after",
        "overview": {"followers": ["粉丝", "粉丝数"], "likes": ["获赞", "点赞"], "following": ["关注"]},
        "metrics": ["播放量", "点赞量", "净增粉丝量", "评论量", "分享量"],
        "note_url_re": r"kuaishou\.com/(short-video|profile)/|/photo/",
    },
    "zhihu": {
        "name": "知乎", "profile": "ZhihuProfile",
        "url": "https://www.zhihu.com/creator/analytics", "default_proxy": True,
        "pre_click": ["累计"],   # 数据总览默认「最近7天」，先点「累计」拿总量
        "overview_dir": "after",
        "overview": {"followers": ["关注者", "粉丝"], "likes": ["赞同总量", "赞同"], "following": []},
        "metrics": ["阅读总量", "播放总量", "收藏总量", "评论总量", "分享总量"],
        # 粉丝(关注者)在单独的「关注者分析」页，主页抓完再来这里取「关注者总数」
        "followers_url": "https://www.zhihu.com/creator/followers",
        "followers_labels": ["关注者总数", "关注者"],
        "note_url_re": r"zhihu\.com/(question/\d+/answer|p)/|zhuanlan",
    },
    "weixin-channels": {
        "name": "视频号", "profile": "ChannelsProfile",
        "url": "https://channels.weixin.qq.com/platform", "default_proxy": True,
        # 真机 2026-08 校准：主页概览是「标签+数字同行」（关注者1 / 视频0）；无总获赞（在数据中心子页）；
        # 昵称锚点不稳，用专用选择器 .finder-nickname；指标取「昨日数据」（净增关注/新增播放/新增评论）
        "overview_dir": "after",
        "overview": {"followers": ["关注者", "粉丝"], "likes": [], "following": []},
        "posts_labels": ["视频", "作品数", "内容数", "视频数"],
        "nickname_selector": ".finder-nickname",
        "metrics": ["净增关注", "新增播放", "新增评论"],
        "note_url_re": r"channels\.weixin\.qq\.com/platform/post|/finder/",
    },
}

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
    "--no-first-run", "--no-default-browser-check", "--mute-audio",
    "--blink-settings=imagesEnabled=false",  # 只读文字/属性，禁图大幅提速（封面 URL 仍在 DOM src 里）
]


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- #
# 纯函数（离线可测）
# --------------------------------------------------------------------------- #
def parse_num(s) -> int | None:
    """展示数字串 → 整数：'1,234'→1234, '1.2万'→12000, '3.4亿'→340000000, '1.5w'→15000, '2.3k'→2300。"""
    if s is None:
        return None
    t = str(s).strip().replace(",", "").replace(" ", "")
    if not t:
        return None
    m = re.match(r"^([\d.]+)\s*([万亿wWkK千]?)$", t)
    if not m:
        m2 = re.match(r"^([\d.]+)", t)
        if not m2:
            return None
        try:
            return int(float(m2.group(1)))
        except ValueError:
            return None
    num, unit = m.group(1), m.group(2)
    try:
        val = float(num)
    except ValueError:
        return None
    mult = {"": 1, "万": 1e4, "亿": 1e8, "w": 1e4, "W": 1e4, "k": 1e3, "K": 1e3, "千": 1e3}[unit]
    return int(round(val * mult))


def lines_of(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def num_by_label(lines: list[str], labels: list[str], direction: str) -> int | None:
    """按行精确匹配标签，取相邻行的数字。direction=before：标签上一行；after：标签下一行（跳过非数字最多 2 行）。
    另兼容「标签+数字同行」（视频号：关注者1 / 视频0）——标签紧跟数字、无其他字符时直接取。"""
    for i, ln in enumerate(lines):
        clean = ln.rstrip("：:")
        # 同行「标签+数字」：仅当剩余部分能解析成纯数字才认（避免「关注者1」误配标签「关注」）
        for lb in labels:
            if clean.startswith(lb) and len(clean) > len(lb):
                v = parse_num(clean[len(lb):])
                if v is not None:
                    return v
        if clean not in labels:
            continue
        if direction == "before":
            if i - 1 >= 0:
                v = parse_num(lines[i - 1])
                if v is not None:
                    return v
        else:
            for j in range(i + 1, min(i + 3, len(lines))):
                v = parse_num(lines[j])
                if v is not None:
                    return v
    return None


_NAV_WORDS = {
    "创作服务平台", "发布笔记", "首页", "笔记管理", "数据看板", "活动中心", "笔记灵感",
    "创作学院", "创作百科", "收起侧边栏", "Builder hub", "Red Skill", "去开播", "查看详情",
    "创作中心", "内容管理", "数据中心", "首页概览", "平台首页", "主页", "发布作品", "发布视频",
    "互动", "流量", "数据总览", "数据分析", "内容分析", "关注者分析", "创作主页", "消息", "私信",
    "今日", "增加", "减少", "累计", "最近", "趋势图", "数据列表", "高级数据", "详细数据",
    "数据趋势", "关注者", "关注者总数", "活跃关注者",
}


def extract_nickname(lines: list[str], overview: dict, uid_anchor: str = "") -> str:
    """昵称 = 概览标签簇之前最近的一行非数字、非导航文本（避免抓到「成长榜样」等卡片里的他人昵称）。
    若给了 uid_anchor（如抖音「抖音号」）：优先取含该锚点的账号行的**上一行**非数字文本——比
    「概览簇前最近行」更准（抖音主页在 抖音号 与 关注 之间夹了「哇哈哈」等干扰行）。"""
    if uid_anchor:
        aidx = next((i for i, ln in enumerate(lines) if uid_anchor in ln), None)
        if aidx is not None:
            for k in range(aidx - 1, max(-1, aidx - 4), -1):
                c = lines[k]
                if parse_num(c) is None and c not in _NAV_WORDS and 1 < len(c) <= 40 and not c.endswith("数"):
                    return c
    labelset = set()
    for v in overview.values():
        labelset.update(v)
    idx = next((i for i, ln in enumerate(lines) if ln.rstrip("：:") in labelset), None)
    if idx is None:
        return ""
    for k in range(idx - 1, max(-1, idx - 5), -1):
        c = lines[k]
        if parse_num(c) is None and c not in _NAV_WORDS and 1 < len(c) <= 40 and not c.endswith("数"):
            return c
    return ""


def metrics_with_vs(lines: list[str], labels: list[str]) -> list[dict]:
    """近N日各指标：标签后就近找「纯数字值」+「±环比」。兼容两种排布：
    小红书「标签\\n值\\n环比+X%」、快手「标签\\n昨日\\n+X\\n值」——值取首个不带正负号的纯数字，
    环比取 +N/-N 或「环比±X」。"""
    out = []
    seen = set()
    numre = re.compile(r"^[\d][\d.,]*\s*[万亿wWkK千]?%?$")   # 纯值（可带 % / 万）
    signre = re.compile(r"^[+\-]\d")                          # +57 / -3（涨跌）
    for i, ln in enumerate(lines):
        clean = ln.rstrip("：:")
        if clean not in labels or clean in seen:
            continue
        val, vs = None, ""
        for j in range(i + 1, min(i + 5, len(lines))):
            s = lines[j]
            if s.rstrip("：:") in labels:      # 撞到下一个指标标签就停，避免串取邻项的涨跌
                break
            if val is None and numre.match(s):
                val = s
            if not vs:
                if signre.match(s):
                    vs = s
                elif s.startswith("环比"):
                    vs = s[2:].strip()
        if val is not None:
            out.append({"label": clean, "value": val, "vs": vs})
            seen.add(clean)
    return out


def _delta(cur, base):
    return (cur - base) if (isinstance(cur, int) and isinstance(base, int)) else None


def growth_windows(history: list[dict], current: dict) -> dict:
    """多窗口增长：last=对上一条快照；day/week/month/year=对不晚于(now-窗口)的最近快照。无基线→None。"""
    now = current["ts"]
    specs = {"last": None, "day": 86400, "week": 7 * 86400, "month": 30 * 86400, "year": 365 * 86400}
    out: dict = {}
    for name, secs in specs.items():
        if name == "last":
            base = history[-1] if history else None
        else:
            older = [h for h in history if h.get("ts", 0) <= now - secs]
            base = older[-1] if older else None
        if base:
            out[name] = {
                "followers": _delta(current.get("followers"), base.get("followers")),
                "likes": _delta(current.get("likes"), base.get("likes")),
                "posts": _delta(current.get("posts"), base.get("posts")),
                "since_days": round((now - base["ts"]) / 86400, 1),
            }
        else:
            out[name] = None
    return out


def _history_path(platform: str) -> Path:
    return ANALYTICS_DIR / f"{platform}.jsonl"


def load_history(platform: str) -> list[dict]:
    p = _history_path(platform)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def append_snapshot(platform: str, snap: dict) -> None:
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    with _history_path(platform).open("a", encoding="utf-8") as f:
        f.write(json.dumps(snap, ensure_ascii=False) + "\n")


def _local_day(ts: int):
    t = time.localtime(ts)
    return (t.tm_year, t.tm_yday)


def _week_key(ts: int):
    t = time.localtime(ts)
    return (t.tm_year, t.tm_yday // 7)


def compact(history: list[dict], now: int) -> list[dict]:
    """分层保留：近 90 天全保留；90~400 天每天保留该天最新一条；>400 天每周保留最新一条。
    保留 日/周/月/年 对比所需老基线，同时把久远的冗余点合并——总量恒定在几百条。"""
    recent, daily, weekly = [], {}, {}
    for s in sorted(history, key=lambda x: x.get("ts", 0)):  # 按时间升序，同桶后者覆盖=留最新
        age = now - s.get("ts", 0)
        if age <= KEEP_FULL_DAYS * 86400:
            recent.append(s)
        elif age <= DAILY_DAYS * 86400:
            daily[_local_day(s["ts"])] = s
        else:
            weekly[_week_key(s["ts"])] = s
    merged = list(weekly.values()) + list(daily.values()) + recent
    merged.sort(key=lambda x: x.get("ts", 0))
    return merged


def should_record(history: list[dict], snap: dict) -> bool:
    """数据变了才记：与上一条快照的 followers/likes/posts 有任一不同就记，全同则跳过（不重复攒行）。"""
    if not history:
        return True
    last = history[-1]
    return any(last.get(k) != snap.get(k) for k in ("followers", "likes", "posts"))


def record_snapshot(platform: str, snap: dict) -> None:
    """数据较上一条有变化才追加；写入前做分层保留 compaction（老数据自动稀疏化，文件永不膨胀）。"""
    h = load_history(platform)
    if not should_record(h, snap):
        return
    h.append(snap)
    h = compact(h, snap["ts"])
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(x, ensure_ascii=False) for x in h)
    _history_path(platform).write_text(body + ("\n" if body else ""), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 浏览器
# --------------------------------------------------------------------------- #
def _profile_dir(platform: str, base: str | None) -> Path:
    root = Path(base).expanduser() if base else Path.home() / ".easel-browser-profiles"
    return root / PLATFORMS[platform]["profile"]


def _proxy(platform: str, explicit: str | None, disable: bool | None) -> str | None:
    if disable is True:
        return None
    if explicit:
        return explicit
    if disable is None and not PLATFORMS[platform].get("default_proxy", True):
        return None
    return os.environ.get("https_proxy") or os.environ.get("http_proxy") or os.environ.get("EASEL_PROXY")


def _scrape(platform: str, headed: bool, base: str | None, proxy: str | None) -> dict:
    from playwright.sync_api import sync_playwright
    cfg = PLATFORMS[platform]
    r = {"nickname": "", "followers": None, "likes": None, "following": None,
         "posts": None, "metrics": [], "notes": [], "logged_in": True}
    with sync_playwright() as p:
        profile = _profile_dir(platform, base)
        profile.mkdir(parents=True, exist_ok=True)
        kwargs = dict(headless=not headed, locale="zh-CN", args=LAUNCH_ARGS)
        if proxy:
            kwargs["proxy"] = {"server": proxy}
        ctx = p.chromium.launch_persistent_context(str(profile), **kwargs)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(cfg["url"], wait_until="domcontentloaded", timeout=30000)
            ov, d = cfg["overview"], cfg.get("overview_dir", "after")
            mets = cfg.get("metrics", [])
            # 稳定性轮询：概览/指标数值连续两次一致才走，避开占位0→真实值的异步坑
            def _sig(L):
                lk = num_by_label(L, ov.get("likes", []), d)
                fo = num_by_label(L, ov.get("followers", []), d)
                m = metrics_with_vs(L, mets)
                mv = m[0]["value"] if m else None
                return None if (lk is None and fo is None and mv is None) else (lk, fo, mv)
            lines = _poll_stable(page, _sig, 10000)
            clicked = False
            for txt in cfg.get("pre_click", []):   # 前置点击（如知乎点「累计」tab 拿总量）
                try:
                    page.click(f"text={txt}", timeout=3000)
                    clicked = True
                except Exception:
                    pass
            if clicked:
                lines = _poll_stable(page, _sig, 6000)   # 点「累计」后重新等稳定
            if re.search(r"(passport|/login)", page.url or "") or \
               page.query_selector('button:has-text("扫码登录"), [class*="login-btn"]'):
                r["logged_in"] = False
            r["followers"] = num_by_label(lines, ov["followers"], d)
            r["likes"] = num_by_label(lines, ov["likes"], d)
            r["following"] = num_by_label(lines, ov.get("following", []), d)
            r["posts"] = num_by_label(lines, cfg.get("posts_labels", ["笔记数", "作品数", "内容数", "视频数"]), d)
            r["metrics"] = metrics_with_vs(lines, cfg.get("metrics", []))[:8]
            r["nickname"] = extract_nickname(lines, ov, cfg.get("uid_anchor", ""))
            # 昵称优先用专用选择器（视频号文本锚点不稳：概览是「关注者1」同行，锚不到昵称）
            nsel = cfg.get("nickname_selector")
            if nsel:
                try:
                    el = page.query_selector(nsel)
                    if el:
                        t = (el.inner_text() or "").strip().splitlines()
                        if t and t[0]:
                            r["nickname"] = t[0][:40]
                except Exception:
                    pass
            if os.environ.get("EASEL_STATS_DEBUG"):
                ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
                (ANALYTICS_DIR / f"{platform}-page.txt").write_text("\n".join(lines)[:20000], encoding="utf-8")
                try:
                    page.screenshot(path=str(ANALYTICS_DIR / f"{platform}-page.png"))
                except Exception:
                    pass
            # 粉丝数在单独子页时（如知乎「关注者分析」），主页抓完再来这里取
            fu = cfg.get("followers_url")
            if fu and r["followers"] is None:
                try:
                    page.goto(fu, wait_until="domcontentloaded", timeout=30000)
                    flabels = cfg.get("followers_labels", ov["followers"])
                    flines = _poll_stable(
                        page, lambda L: (num_by_label(L, flabels, "after"),)
                        if num_by_label(L, flabels, "after") is not None else None, 8000)
                    r["followers"] = num_by_label(flines, flabels, "after")
                except Exception:
                    pass
            # 最新笔记放最后抓——小红书会跳转到笔记管理页，之后不再读首页
            r["notes"] = _scrape_notes(platform, page, cfg)
        finally:
            ctx.close()
    return r


def _has_body(page) -> bool:
    try:
        return page.query_selector("body") is not None
    except Exception:
        return False


def _poll_stable(page, sig, max_ms: int = 10000, step: int = 400) -> list[str]:
    """轮询正文，直到 sig(lines) 非 None 且**连续两次相同**（数据稳定）才返回——
    避开「占位 0 → 真实值」的异步渲染坑；真·0 账号也会很快稳定。超时返回最后一次。"""
    prev = object()
    lines: list[str] = []
    waited = 0
    while waited < max_ms:
        try:
            lines = lines_of(page.inner_text("body"))
        except Exception:
            lines = []
        cur = sig(lines)
        if cur is not None and cur == prev:
            return lines
        prev = cur
        page.wait_for_timeout(step)
        waited += step
    return lines


_XHS_NOTES_JS = """() => {
  const out = [];
  document.querySelectorAll('.note-card').forEach(c => {
    const titleEl = c.querySelector('.note-card__title');
    let noteId = '';
    try { noteId = (JSON.parse(c.getAttribute('data-impression') || '{}')
                    .noteTarget || {}).value?.noteId || ''; } catch (e) {}
    // 尽力从卡片内链接拿 xsec_token（列表页不一定带）——供直接抓评论用
    let href = '';
    const a = c.querySelector("a[href*='xsec_token'], a[href*='/explore/'], a[href*='/item/']");
    if (a) href = a.href || '';
    const img = c.querySelector('.note-card__cover img, img');
    out.push({
      title: (titleEl ? titleEl.textContent : '').trim().slice(0, 60),
      noteId, href,
      cover: img ? (img.src || '') : '',
    });
  });
  return out.slice(0, 8);
}"""

_ZHIHU_NOTES_JS = r"""() => {
  const out = [], seen = new Set();
  document.querySelectorAll('a[href]').forEach(a => {
    if (!/zhuanlan\.zhihu\.com\/p\/\d+$|\/question\/\d+\/answer\/\d+/.test(a.href)) return;
    if (seen.has(a.href)) return;
    const title = (a.innerText || '').trim().split('\n')[0];
    if (!title || title.length < 4) return;
    let card = a;
    for (let i = 0; i < 6 && card; i++) { if (/阅读/.test(card.textContent || '')) break; card = card.parentElement; }
    const txt = card ? card.textContent : '';
    const rd = (txt.match(/(\d[\d.,]*)\s*阅读/) || [])[1] || '';
    const up = (txt.match(/(\d[\d.,]*)\s*赞同/) || [])[1] || '';
    let stat = ''; if (rd) stat += '阅读' + rd; if (up) stat += (stat ? ' · ' : '') + '赞同' + up;
    seen.add(a.href);
    out.push({ title: title.slice(0, 44), href: a.href, stat });
  });
  return out.slice(0, 6);
}"""

_KUAISHOU_NOTES_JS = r"""() => {
  const rows = [...document.querySelectorAll('[class*="video-item"]')]
    .filter(e => e.querySelector('[class*="row__title"]') && /已发布|待发布|未通过/.test(e.textContent || ''));
  const top = rows.filter(e => !rows.some(o => o !== e && o.contains(e)));
  const out = [];
  top.forEach(it => {
    const tEl = it.querySelector('[class*="row__title"]');
    const title = ((tEl ? tEl.textContent : '').trim().split('\n')[0] || '').slice(0, 44);
    if (!title) return;
    const txt = (it.textContent || '').replace(/\s+/g, ' ');
    const m = txt.match(/(已发布|待发布|未通过)\D*?\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2})?\D*(\d[\d.,]*)\D+(\d[\d.,]*)\D+(\d[\d.,]*)/);
    const stat = m ? ('播放' + m[2] + ' · 赞' + m[3] + ' · 评' + m[4]) : '';
    out.push({ title, stat });
  });
  return out.slice(0, 6);
}"""


def _extract_note_tokens(data) -> dict:
    """递归遍历拦截到的接口 JSON，凡是同时含 note-id 与 xsec_token 的对象，收成 {note_id: token}。
    端点/字段路径无关，抗改版——比从 DOM 的 <a href> 捞 token 可靠（列表页 href 常不带 token）。"""
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


def _scrape_notes(platform: str, page, cfg: dict) -> list[dict]:
    """抓最新已发布内容（标题 + 可点链接 + 每条数据）。各平台内容页与结构不同，分平台解析。"""
    if platform == "xiaohongshu":
        try:
            import re as _re
            from urllib.parse import urlparse as _up, parse_qs as _pq
            token_map: dict = {}

            def _on_resp(resp):  # 拦截 note-manager 的 JSON 接口，取每篇 xsec_token（可靠）
                try:
                    if "json" in ((resp.headers or {}).get("content-type", "")):
                        token_map.update(_extract_note_tokens(resp.json()))
                except Exception:
                    pass
            page.on("response", _on_resp)
            page.goto("https://creator.xiaohongshu.com/new/note-manager",
                      wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(".note-card", timeout=6000)
            except Exception:
                page.wait_for_timeout(1500)
            page.wait_for_timeout(800)  # 等列表接口回来
            out = []
            for n in (page.evaluate(_XHS_NOTES_JS) or []):
                href = n.get("href") or ""
                h_tok = h_nid = ""
                if href:
                    try:
                        u = _up(href)
                        m = _re.search(r"/(?:explore|discovery/item|item)/([0-9a-zA-Z]+)", u.path)
                        h_nid = m.group(1) if m else ""
                        h_tok = (_pq(u.query).get("xsec_token") or [""])[0]
                    except Exception:
                        pass
                nid = n.get("noteId") or h_nid
                tok = token_map.get(nid, "") or h_tok   # 接口 token 优先，DOM href 兜底
                # 有 token 就给可直接抓评论的完整链接；否则退到裸 explore 链接
                url = (f"https://www.xiaohongshu.com/explore/{nid}?xsec_token={tok}&xsec_source=pc_creatormng"
                       if nid and tok else
                       f"https://www.xiaohongshu.com/explore/{nid}" if nid
                       else "https://creator.xiaohongshu.com/new/note-manager")
                out.append({
                    "title": n.get("title") or "(无标题)",
                    "note_id": nid, "xsec_token": tok,   # 供 xhs_comment.py 直接抓评论（统一入口）
                    "url": url,
                    "cover": n.get("cover") or "", "stat": "",
                })
            try:
                page.remove_listener("response", _on_resp)
            except Exception:
                pass
            return out
        except Exception:
            return []
    if platform == "zhihu":
        try:
            page.goto("https://www.zhihu.com/creator/manage/creation/all",
                      wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("a[href*='zhuanlan.zhihu.com/p/'], a[href*='/answer/']", timeout=6000)
            except Exception:
                page.wait_for_timeout(1500)
            return [{"title": n.get("title") or "(无标题)", "url": n.get("href") or "",
                     "cover": "", "stat": n.get("stat") or ""}
                    for n in (page.evaluate(_ZHIHU_NOTES_JS) or [])]
        except Exception:
            return []
    if platform == "kuaishou":
        try:
            page.goto("https://cp.kuaishou.com/article/manage/video",
                      wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("[class*='video-item']", timeout=6000)
            except Exception:
                page.wait_for_timeout(1500)
            # 快手作品无独立公开链接，点击回到作品管理页；完播率在每条「数据」详情、列表不含
            return [{"title": n.get("title") or "(无标题)",
                     "url": "https://cp.kuaishou.com/article/manage/video",
                     "cover": "", "stat": n.get("stat") or ""}
                    for n in (page.evaluate(_KUAISHOU_NOTES_JS) or [])]
        except Exception:
            return []
    # 其它平台：best-effort 从当前页 a[href] 按 note URL 模式抓
    note_re = cfg.get("note_url_re", "")
    notes: list[dict] = []
    if note_re:
        try:
            links = page.eval_on_selector_all(
                "a[href]", "els => els.map(e => ({t:(e.innerText||'').trim().slice(0,60), h:e.href}))")
            seen = set()
            for lk in links:
                h = lk.get("h") or ""
                if re.search(note_re, h) and h not in seen:
                    seen.add(h)
                    notes.append({"title": lk.get("t") or "(无标题)", "url": h, "cover": "", "stat": ""})
                if len(notes) >= 8:
                    break
        except Exception:
            pass
    return notes


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
            print(f"✅ chromium 内核：{path}" if path and Path(path).exists()
                  else "❌ 未安装浏览器内核（playwright install chromium）")
            ok = bool(path and Path(path).exists())
    except Exception as e:
        print(f"❌ playwright/内核不可用：{e}"); ok = False
    print(f"支持平台：{', '.join(PLATFORMS)}")
    return 0 if ok else 3


def cmd_fetch(a) -> int:
    if a.platform not in PLATFORMS:
        _die(f"未知平台：{a.platform}（支持：{', '.join(PLATFORMS)}）")
    try:
        import playwright.sync_api  # noqa: F401
    except Exception as e:
        _die(f"需要 playwright：{e}", 3)
    disable = True if a.no_proxy else (False if a.proxy else None)
    s = _scrape(a.platform, a.headed, a.profile_base, _proxy(a.platform, a.proxy, disable))

    now = int(time.time())
    snap = {"ts": now, "followers": s["followers"], "likes": s["likes"], "posts": s["posts"]}
    history = load_history(a.platform)
    growth = growth_windows(history, snap)
    if any(snap[k] is not None for k in ("followers", "likes", "posts")):
        record_snapshot(a.platform, snap)

    out = {
        "platform": a.platform, "name": PLATFORMS[a.platform]["name"],
        "nickname": s["nickname"], "loggedIn": s["logged_in"],
        "followers": s["followers"], "likes": s["likes"],
        "following": s["following"], "posts": s["posts"],
        "metrics": s["metrics"], "notes": s["notes"],
        "growth": growth, "fetched_at": now,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_selftest(_a) -> int:
    print("account_stats 自检（离线）...", file=sys.stderr)
    # 数字解析
    assert parse_num("1,234") == 1234 and parse_num("1.2万") == 12000
    assert parse_num("3.4亿") == 340000000 and parse_num("1.5w") == 15000 and parse_num("2.3k") == 2300
    assert parse_num("") is None and parse_num("暂无") is None
    # 概览：小红书真实排布「数字\n标签」（direction=before），不能把账号号当获赞
    xhs = lines_of("小红薯68691DBC\n1\n关注数\n4\n粉丝数\n11\n获赞与收藏\n小红书账号: 95561083127")
    assert num_by_label(xhs, ["粉丝数"], "before") == 4, num_by_label(xhs, ["粉丝数"], "before")
    assert num_by_label(xhs, ["获赞与收藏"], "before") == 11
    assert num_by_label(xhs, ["关注数"], "before") == 1
    # 昵称 = 概览簇前最近的非数字非导航行（不能是「小鹿喜嘻嘻」这类成长榜样他人名）
    xhs2 = lines_of("创作服务平台\n小红薯68691DBC\n1\n关注数\n4\n粉丝数\n11\n获赞与收藏\n"
                    "成长榜样\n小鹿喜嘻嘻\n粉丝数：4.7万")
    assert extract_nickname(xhs2, {"followers": ["粉丝数"], "likes": ["获赞与收藏"], "following": ["关注数"]}) == "小红薯68691DBC"
    # after 方向（标签\n数字）
    af = lines_of("粉丝\n1234\n获赞\n5.6万")
    assert num_by_label(af, ["粉丝"], "after") == 1234 and num_by_label(af, ["获赞"], "after") == 56000
    # 标签+数字同行（视频号：关注者1 / 视频0）——仅剩余部分是纯数字才认，避免「关注者1」误配标签「关注」
    wc = lines_of("碎碎念bla\n视频号ID:\nsphFUzP6qiOrDmD\n视频0\n关注者1")
    assert num_by_label(wc, ["关注者", "粉丝"], "after") == 1, num_by_label(wc, ["关注者"], "after")
    assert num_by_label(wc, ["视频", "作品数"], "after") == 0
    assert num_by_label(wc, ["关注"], "after") is None, "「关注者1」不能被标签「关注」误取"
    # 近N日指标：兼容小红书「标签\n值\n环比±%」与快手「标签\n昨日\n+值\n值」
    m = lines_of("曝光数\n111\n环比+11000%\n点赞数\n7\n环比-\n评论数\n14")
    mm = metrics_with_vs(m, ["曝光数", "点赞数", "评论数"])
    assert mm[0] == {"label": "曝光数", "value": "111", "vs": "+11000%"}, mm
    assert mm[1]["vs"] == "-" and mm[2]["label"] == "评论数"
    ks = lines_of("播放量\n昨日\n+57\n57\n完播率\n30.8%\n点赞量\n昨日\n+0\n0")
    km = metrics_with_vs(ks, ["播放量", "完播率", "点赞量"])
    assert km[0] == {"label": "播放量", "value": "57", "vs": "+57"}, km
    assert km[1] == {"label": "完播率", "value": "30.8%", "vs": ""}, km
    assert km[2]["value"] == "0" and km[2]["vs"] == "+0"
    # 多窗口增长
    now = 100 * 86400
    hist = [{"ts": now - 40 * 86400, "followers": 10, "likes": 5, "posts": 1},   # >month
            {"ts": now - 5 * 86400, "followers": 20, "likes": 8, "posts": 2},    # >day,>week? 5d: >day, <week
            {"ts": now - 0.5 * 86400, "followers": 28, "likes": 9, "posts": 2}]  # last
    cur = {"ts": now, "followers": 30, "likes": 10, "posts": 3}
    g = growth_windows(hist, cur)
    assert g["last"]["followers"] == 2                       # 30-28
    assert g["day"]["followers"] == 10                       # vs 5d 前(<=now-1d 最近) =20 → 10
    assert g["week"]["followers"] == 20                      # vs 40d 前 =10 → 20（无 5-7d 间快照）
    assert g["month"]["followers"] == 20 and g["year"] is None
    assert growth_windows([], cur)["last"] is None
    # 快照「变了才记」：空→记，全同→不记，任一变→记
    assert should_record([], {"followers": 4, "likes": 11, "posts": None}) is True
    assert should_record([{"followers": 4, "likes": 11, "posts": None}],
                         {"followers": 4, "likes": 11, "posts": None}) is False
    assert should_record([{"followers": 4, "likes": 11, "posts": None}],
                         {"followers": 5, "likes": 11, "posts": None}) is True
    # 分层保留 compact：近90天全留、90~400天每天1条、>400天每周1条
    NOW = 500 * 86400
    hist = []
    hist += [{"ts": NOW - 2 * 86400 - h * 3600, "followers": 100 + h} for h in range(5)]   # 近2天5条→全留
    hist += [{"ts": NOW - 200 * 86400 - h * 3600, "followers": 50 + h} for h in range(4)]  # 200天前同一天4条→留1
    hist += [{"ts": NOW - 450 * 86400 - h * 3600, "followers": 10 + h} for h in range(6)]  # 450天前同周6条→留1
    c = compact(hist, NOW)
    recent_n = sum(1 for s in c if NOW - s["ts"] <= KEEP_FULL_DAYS * 86400)
    day200_n = sum(1 for s in c if _local_day(s["ts"]) == _local_day(NOW - 200 * 86400))
    week450_n = sum(1 for s in c if _week_key(s["ts"]) == _week_key(NOW - 450 * 86400))
    assert recent_n == 5, recent_n            # 近期全留
    assert day200_n == 1, day200_n            # 老中期每天1条
    assert week450_n == 1, week450_n          # 久远每周1条
    assert c == sorted(c, key=lambda x: x["ts"])  # 结果按时间升序
    # 平台配置完整
    for k, c in PLATFORMS.items():
        for f in ("name", "profile", "url", "overview", "overview_dir"):
            assert c.get(f), f"{k} 缺 {f}"
        assert set(c["overview"]) >= {"followers", "likes"}
    assert _proxy("xiaohongshu", None, None) is None and _proxy("douyin", "http://x:1", False) == "http://x:1"
    # 接口 JSON 递归提取 note→token（可靠取 xhs 笔记 token）
    assert _extract_note_tokens({"d": {"notes": [{"note_id": "n1", "xsec_token": "t1"},
                                                 {"id": "n2", "xsecToken": "t2"}, {"noteId": "n3"}]}}) \
        == {"n1": "t1", "n2": "t2"}
    assert _extract_note_tokens([]) == {}
    print("✅ selftest 通过（解析 + 概览分方向取数(修获赞bug) + 近7日环比 + 多窗口增长 + 配置/代理 + 接口token提取）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="归因层：抓取已登录账号创作数据（Playwright）")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("check", help="检查 playwright/内核").set_defaults(func=cmd_check)
    pf = sub.add_parser("fetch", help="抓某平台账号数据 → JSON")
    pf.add_argument("--platform", required=True, help=f"平台：{', '.join(PLATFORMS)}")
    pf.add_argument("--profile-base", help="登录态根目录（默认 ~/.easel-browser-profiles）")
    pf.add_argument("--proxy", help="外网代理（默认按平台：xhs 直连、其它走 env）")
    pf.add_argument("--no-proxy", action="store_true", help="强制直连")
    pf.add_argument("--headed", action="store_true", help="有头模式（首次校准）")
    pf.set_defaults(func=cmd_fetch)
    sub.add_parser("selftest", help="离线自检").set_defaults(func=cmd_selftest)
    a = ap.parse_args()
    if not getattr(a, "func", None):
        ap.print_help()
        return 1
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
