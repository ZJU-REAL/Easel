#!/usr/bin/env python3
"""platform_readback.py — 平台读回对账（发布可靠性核心）。

发布后回到创作者中心**读本人作品列表**，与本次发布对账（标题 + 时间窗），
对上才算「已发布」。协议取自生产级发布引擎的读回对账实践：
抖音 = 页面内 fetch work_list 接口（同域、登录态随 cookie 走），快手 = 捕获
作品管理页自身发出的 XHR（借页面生成参数/签名，不复刻请求），小红书 = 捕获
页面自身签名响应（待补），B站 = 直连 member 稿件接口读回（cookies.json，无需浏览器）。原则：没有平台侧证据时保留「未核实」，
不凭脚本结束声明已提交。

outcome 四档（调用方据此落回执，绝不把未核实当成功）：
  verified       读回对上（标题前缀 + since 时间窗）——附带作品 id 与状态为准
  unverified     读回通了但多轮未见新作品（索引延迟/审核队列等，保留待查）
  login_required 读回时登录态已失效——明确报「需重新登录」
  readback_error 读回通道本身失败（网络/页面结构改版），附原始证据

非目标：不管理登录、不碰凭据、不写状态文件（由调用方决定如何落回执）。
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

DOUYIN_MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"
DOUYIN_WORK_LIST_URL = "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
DOUYIN_PROFILE_API = "https://creator.douyin.com/web/api/media/user/info/?aid=1128"

# 标题前缀匹配长度：与 douyin_publish._verify_published 现有口径一致（前 12 字）
TITLE_KEY_LEN = 12
# 时间窗容差：允许平台时间戳精度/索引延迟（发布到出现在列表里的间隔）
SINCE_TOLERANCE_MS = 10 * 60 * 1000


@dataclass
class WorkItem:
    platform_content_id: str
    title: str
    status: str
    published_at_ms: int | None = None
    stats: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform_content_id": self.platform_content_id,
            "title": self.title,
            "status": self.status,
            "published_at_ms": self.published_at_ms,
            "stats": self.stats,
        }


@dataclass
class ReadbackResult:
    outcome: str  # verified | unverified | login_required | readback_error
    matched: WorkItem | None = None
    candidates: list[WorkItem] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "matched": self.matched.as_dict() if self.matched else None,
            "candidates": [w.as_dict() for w in self.candidates],
            "evidence": self.evidence,
            "error": self.error,
        }


class LoginRequiredError(RuntimeError):
    """读回时确认登录态已失效（区别于通道故障——那是 readback_error）。"""


# 页面内 fetch：同域请求自动带 cookie；返回结构化结果而不是裸文本，便于错误诊断。
_JS_FETCH_JSON = """
async ([url, timeoutMs]) => {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, {
      credentials: 'include',
      signal: ctrl.signal,
      headers: { 'accept': 'application/json, text/plain, */*' },
    });
    const text = await resp.text();
    let body = null, parseError = null;
    try { body = JSON.parse(text); } catch (e) { parseError = String(e); }
    return { httpStatus: resp.status, finalUrl: resp.url, body, parseError,
             textHead: text.slice(0, 300) };
  } catch (e) {
    return { fetchError: String((e && e.message) || e) };
  } finally { clearTimeout(timer); }
}
"""


def _navigation_safe_evaluate(page, script: str, arg, *, retries: int = 3):
    """page.evaluate 的导航竞态容错（页面跳转瞬间 context 销毁会抛错，重试即可）。"""
    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        try:
            return page.evaluate(script, arg)
        except Exception as e:  # noqa: BLE001 —— 只挑导航竞态重试，其余上抛
            msg = str(e)
            racing = ("Execution context was destroyed" in msg
                      or "Cannot find context" in msg
                      or "navigation" in msg.lower())
            if not racing:
                raise
            last_error = e
            time.sleep(0.8 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def _epoch_ms(value: Any) -> int | None:
    """秒/毫秒 epoch 归一化。"""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    return int(n * 1000) if n < 10_000_000_000 else int(n)


def _normalize_douyin_status(status: Any, public_time: Any) -> str:
    """作品状态归一化（平台状态码 → 统一枚举）。"""
    if isinstance(status, (int, float)):
        return str(status)
    s = status if isinstance(status, dict) else {}
    if s.get("is_delete"):
        return "deleted"
    if s.get("is_prohibited"):
        return "prohibited"
    if s.get("in_reviewing"):
        return "reviewing"
    if s.get("is_private"):
        return "private"
    try:
        public_s = float(public_time or 0)
    except (TypeError, ValueError):
        public_s = 0
    if public_s > time.time():
        return "scheduled"
    return "published"


def _first_id(item: dict) -> str:
    for key in ("aweme_id", "item_id", "id"):
        v = item.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    raise ValueError("作品缺少 id（aweme_id/item_id）")


def read_douyin_works(page, *, limit: int = 20, evaluate_retries: int = 3) -> list[WorkItem]:
    """在创作者中心页读取本人作品列表（页面内 fetch，登录态随 cookie 走）。

    取数口径：
    count / max_cursor / status=0 / scene=7 / device_platform=webapp / aid=2906，
    解析 data.work_list（回退 aweme_list/items）。本函数只取第一页（对账不需要全量）。
    登录失效 → raise LoginRequiredError；通道故障 → 抛原始异常（调用方分类）。
    """
    limit = max(1, min(50, int(limit or 20)))
    try:
        current_url = page.url or ""
    except Exception:  # noqa: BLE001
        current_url = ""
    if DOUYIN_MANAGE_URL not in current_url:
        page.goto(DOUYIN_MANAGE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # 页面异步渲染，等上下文稳定
    try:
        landed = page.url or ""
    except Exception:  # noqa: BLE001
        landed = ""
    if "creator.douyin.com" in landed and "login" in landed.lower():
        raise LoginRequiredError(f"会话已失效（跳转登录页：{landed[:120]}）")

    query = urlencode({
        "count": limit,
        "max_cursor": 0,
        "status": "0",
        "scene": "7",
        "device_platform": "webapp",
        "aid": "2906",
    })
    result = _navigation_safe_evaluate(
        page, _JS_FETCH_JSON, [f"{DOUYIN_WORK_LIST_URL}?{query}", 15000],
        retries=evaluate_retries,
    )
    if not isinstance(result, dict):
        raise RuntimeError(f"读回返回结构异常：{type(result).__name__}")
    if result.get("fetchError"):
        raise RuntimeError(f"读回请求失败：{result['fetchError']}")
    http_status = int(result.get("httpStatus") or 0)
    if http_status in (401, 403):
        raise LoginRequiredError(f"读回 HTTP {http_status}")
    body = result.get("body")
    if not isinstance(body, dict):
        final_url = str(result.get("finalUrl") or "")
        try:
            page_url = page.url or ""
        except Exception:  # noqa: BLE001
            page_url = ""
        if "login" in final_url.lower() or "login" in page_url.lower():
            raise LoginRequiredError("会话已失效（响应重定向到登录页）")
        raise RuntimeError(
            f"读回响应非 JSON（HTTP {http_status}）：{str(result.get('textHead') or '')[:120]}")
    status_code = body.get("status_code")
    if status_code not in (0, None):
        msg = str(body.get("status_msg") or body.get("message") or "")
        if "登录" in msg or "login" in msg.lower() or status_code in (8, 1002, 2154):
            raise LoginRequiredError(f"读回被拒：status_code={status_code} {msg}")
        raise RuntimeError(f"读回接口报错：status_code={status_code} {msg}")

    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    raw_items = (data.get("work_list") or body.get("aweme_list")
                 or data.get("aweme_list") or body.get("items") or [])
    if not isinstance(raw_items, list):
        raise RuntimeError("读回响应缺少 work_list（页面结构可能改版）")

    works: list[WorkItem] = []
    for raw in raw_items[:limit]:
        if not isinstance(raw, dict):
            continue
        statistics = raw.get("statistics") if isinstance(raw.get("statistics"), dict) else {}
        works.append(WorkItem(
            platform_content_id=_first_id(raw),
            title=str(raw.get("desc") or raw.get("title") or "").strip(),
            status=_normalize_douyin_status(raw.get("status"), raw.get("public_time")),
            published_at_ms=_epoch_ms(raw.get("create_time") or raw.get("public_time")),
            stats={
                "play_count": statistics.get("play_count"),
                "digg_count": statistics.get("digg_count"),
                "comment_count": statistics.get("comment_count"),
            },
        ))
    return works


def read_douyin_account(page) -> dict[str, Any]:
    """读创作者中心当前登录账号身份（uid/昵称/粉丝）——「我是谁」接口。

    读当前账号（user/info, aid=1128）：
    登录态上报、发布回执的账号身份快照、身份核验共用这一条读法。
    登录失效 raise LoginRequiredError；响应缺 uid raise RuntimeError。
    """
    try:
        current_url = page.url or ""
    except Exception:  # noqa: BLE001
        current_url = ""
    if "creator.douyin.com" not in current_url:
        page.goto(DOUYIN_MANAGE_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    result = _navigation_safe_evaluate(
        page, _JS_FETCH_JSON, [DOUYIN_PROFILE_API, 15000], retries=2)
    if not isinstance(result, dict):
        raise RuntimeError(f"账号读取返回结构异常：{type(result).__name__}")
    if result.get("fetchError"):
        raise RuntimeError(f"账号读取请求失败：{result['fetchError']}")
    body = result.get("body")
    if not isinstance(body, dict):
        raise RuntimeError(f"账号读取响应非 JSON（HTTP {result.get('httpStatus')}）")
    status_code = body.get("status_code")
    if status_code not in (0, None):
        msg = str(body.get("status_msg") or "")
        if "登录" in msg or status_code in (8, 1002, 2154):
            raise LoginRequiredError(f"账号读取被拒：status_code={status_code} {msg}")
        raise RuntimeError(f"账号读取接口报错：status_code={status_code} {msg}")
    user = body.get("user_info") if isinstance(body.get("user_info"), dict) else (
        body.get("user") if isinstance(body.get("user"), dict) else {})
    uid = str(user.get("uid") or user.get("sec_uid") or user.get("open_id") or "").strip()
    if not uid:
        raise RuntimeError("账号信息缺少 uid（页面结构可能改版）")

    def _num(v):  # noqa: ANN001
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return {
        "platform_account_id": uid,
        "display_name": str(user.get("nickname") or user.get("name") or uid).strip(),
        "username": str(user.get("unique_id") or user.get("short_id") or "").strip() or None,
        "fans_count": _num(user.get("follower_count")),
        "work_count": _num(user.get("aweme_count")),
    }


def capture_douyin_snapshot(page) -> set[str]:
    """发前快照：读取当前作品列表的全部作品 id。
    发布前抓一遍，读回时用它排除「本来就存在的旧作品」，让对账只认**新出现**的条目。
    失败（未登录/通道异常）返回空集合——对账自动退化为标题+时间窗，不影响主流程。"""
    try:
        works = read_douyin_works(page, limit=30)
        return {w.platform_content_id for w in works}
    except Exception:
        return set()


def find_published_work(works: list[WorkItem], title: str, *,
                        since_ms: int | None = None,
                        key_len: int = TITLE_KEY_LEN,
                        exclude_ids: set[str] | None = None) -> WorkItem | None:
    """对账：列表中找属于本次发布的作品（标题前缀命中 + 不早于 since 时间窗）。

    - 标题为空 → 无法对账（返回 None，调用方按 unverified 处理）。
    - since_ms 给了时：作品发布时间明显早于 since 的跳过（防同标题旧作品误判），
      容差 SINCE_TOLERANCE_MS 吸收平台时间戳精度与索引延迟。
    - exclude_ids（发前快照）里的 id 视为旧作品跳过——发布前就存在的条目不可能是本次，
      同标题+时间戳精度边缘时它是比时间窗更硬的证据。
    """
    key = (title or "").strip().replace("\n", " ")[:key_len]
    if not key:
        return None
    for w in works:
        if key not in (w.title or ""):
            continue
        if exclude_ids and w.platform_content_id in exclude_ids:
            continue
        if since_ms and w.published_at_ms and (w.published_at_ms + SINCE_TOLERANCE_MS) < since_ms:
            continue
        return w
    return None


def verify_douyin_publish(page, *, title: str, since_ms: int | None = None,
                          limit: int = 20, attempts: int = 4,
                          delay_s: float = 12.0,
                          snapshot_ids: set[str] | None = None) -> ReadbackResult:
    """发布后对账入口：多轮读回（列表异步更新，给平台索引时间）。

    返回 ReadbackResult；除 KeyboardInterrupt 外不抛异常——
      verified        对上（matched 为对应作品）
      unverified      通道通、未见新作品（candidates 为读到的近期作品，供诊断）
      login_required  登录失效
      readback_error  通道故障（error 带原始信息）
    """
    last_error: Exception | None = None
    last_candidates: list[WorkItem] = []
    evidence: dict[str, Any] = {"attempts": 0}
    for i in range(max(1, attempts)):
        evidence = {"attempts": i + 1, "checked_at": int(time.time())}
        try:
            works = read_douyin_works(page, limit=limit)
        except LoginRequiredError as e:
            return ReadbackResult(outcome="login_required", evidence=evidence, error=str(e))
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"⚠️ 读回第 {i + 1}/{attempts} 轮失败：{e}", file=sys.stderr)
            if i + 1 < attempts:
                time.sleep(delay_s)
            continue
        last_candidates = works
        evidence["count"] = len(works)
        matched = find_published_work(works, title, since_ms=since_ms, exclude_ids=snapshot_ids)
        if matched:
            # 顺带读账号身份快照（回执标准件；失败不影响对账结论）
            try:
                evidence["account"] = read_douyin_account(page)
            except Exception as e:  # noqa: BLE001
                evidence["account_error"] = str(e)
            print(f"✅ 读回对账通过：{matched.platform_content_id}（{matched.status}）", file=sys.stderr)
            return ReadbackResult(outcome="verified", matched=matched,
                                  candidates=works[:5], evidence=evidence)
        print(f"… 读回第 {i + 1}/{attempts} 轮：列表 {len(works)} 条未见本次作品", file=sys.stderr)
        if i + 1 < attempts:
            time.sleep(delay_s)
    if last_error is not None and not last_candidates:
        return ReadbackResult(outcome="readback_error", evidence=evidence, error=str(last_error))
    return ReadbackResult(outcome="unverified", candidates=last_candidates[:5], evidence=evidence)


# ═══════════════════════════════════════════════════════════════════════
# 快手读回（创作者中心）
#
# 快手接口参数带构建签名，不复刻请求：导航到作品管理页，捕获页面自身发出的
# JSON 响应（借页面的手——参数/签名随页面自然生成），从响应里找「作品列表
# 数组」（按 id 键计分选最优）映射为统一 WorkItem。
# ═══════════════════════════════════════════════════════════════════════

KUAISHOU_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video"
KUAISHOU_CAPTURE_PATTERNS = ("article", "video", "photo", "creator", "account", "user", "rest", "works")
KUAISHOU_ID_KEYS = ("photo_id", "photoId", "video_id", "videoId", "work_id", "workId", "id")
KUAISHOU_TITLE_KEYS = ("title", "caption", "description", "desc", "name")
KUAISHOU_TIME_KEYS = ("publish_time", "publishTime", "create_time", "createTime",
                      "created_at", "upload_time", "time")
KUAISHOU_ACCOUNT_ID_KEYS = ("user_id", "userId", "author_id", "authorId", "kwai_id", "kwaiId", "uid")
KUAISHOU_ACCOUNT_NAME_KEYS = ("nickname", "user_name", "userName", "display_name", "name")
# 已知「登录态失效」result 码（外壳 token 活着但模块未授权时返回）
KUAISHOU_LOGOUT_RESULTS = (109, 100110000)


def _capture_json_responses(page, navigate_url: str, url_includes_any: tuple[str, ...],  # noqa: ANN001
                            *, wait_ms: int = 12000,
                            wait_urls_any: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """导航到目标页并捕获页面自身发出的 JSON 响应（借页面的手：参数/签名随页面生成）。

    等待策略：最多等 wait_ms；给了 wait_urls_any 时，一旦捕获到命中该子串的响应即提前
    结束（+800ms 让同批响应落地）——目标接口出现即走，不等满窗口。
    监听器只收集响应对象、遍历时再读 body——单条读不到就跳过（捕获而非构造，容忍缺失）。
    返回 [{"url", "data"}]（仅 200 且能解析 JSON 的响应）。
    """
    collected: list[Any] = []

    def _on_response(resp) -> None:  # noqa: ANN001
        try:
            url = resp.url or ""
        except Exception:  # noqa: BLE001
            return
        if any(p in url for p in url_includes_any):
            collected.append(resp)

    def _hit_target() -> bool:
        if not wait_urls_any:
            return False
        for r in collected:
            try:
                u = r.url or ""
            except Exception:  # noqa: BLE001
                continue
            if any(w in u for w in wait_urls_any):
                return True
        return False

    page.on("response", _on_response)
    try:
        page.goto(navigate_url, wait_until="domcontentloaded")
        deadline = time.time() + max(0.5, wait_ms / 1000)
        while time.time() < deadline:
            if _hit_target():
                page.wait_for_timeout(800)
                break
            page.wait_for_timeout(300)
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:  # noqa: BLE001
            pass
    out: list[dict[str, Any]] = []
    for resp in collected:
        try:
            if int(resp.status) != 200:
                continue
            out.append({"url": resp.url, "data": resp.json()})
        except Exception:  # noqa: BLE001
            continue
    return out


def _record_values(root: Any, depth: int = 0) -> list[dict[str, Any]]:
    """深度优先收集 JSON 里的全部 dict 记录（限深防环）。"""
    if depth > 7 or not isinstance(root, (dict, list)):
        return []
    if isinstance(root, list):
        out: list[dict[str, Any]] = []
        for item in root:
            out.extend(_record_values(item, depth + 1))
        return out
    out = [root]
    for value in root.values():
        out.extend(_record_values(value, depth + 1))
    return out


def _first_value(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_content_array(responses: list[dict[str, Any]],
                        id_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """在捕获响应里找「作品记录数组」：按含 id 键的记录数计分，取最优数组。"""
    arrays: list[tuple[int, int, list[dict[str, Any]]]] = []

    def _visit(value: Any, depth: int = 0) -> None:
        if depth > 7 or not isinstance(value, (dict, list)):
            return
        if isinstance(value, list):
            records = [r for r in value if isinstance(r, dict)]
            score = sum(1 for r in records if _first_value(r, id_keys) is not None)
            if records and score > 0:
                arrays.append((score, len(records), records))
            for item in value:
                _visit(item, depth + 1)
            return
        for item in value.values():
            _visit(item, depth + 1)

    for resp in responses:
        _visit(resp.get("data"))
    if not arrays:
        return []
    arrays.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return arrays[0][2]


def _map_kuaishou_item(raw: dict[str, Any]) -> WorkItem | None:
    """作品记录 → WorkItem（缺 id 的记录跳过）。"""
    pid = _first_value(raw, KUAISHOU_ID_KEYS)
    if pid is None:
        return None
    raw_status = _first_value(raw, ("status_name", "publish_status", "status"))
    if isinstance(raw_status, dict):
        raw_status = (raw_status.get("name") or raw_status.get("text")
                      or raw_status.get("desc") or raw_status)
    stats_in = raw.get("statistics") if isinstance(raw.get("statistics"), dict) else raw
    return WorkItem(
        platform_content_id=str(pid).strip(),
        title=str(_first_value(raw, KUAISHOU_TITLE_KEYS) or "").strip(),
        status=(str(raw_status).strip() if raw_status is not None else ""),
        published_at_ms=_epoch_ms(_first_value(raw, KUAISHOU_TIME_KEYS)),
        stats={
            "play_count": _int_or_none(_first_value(
                stats_in, ("play_count", "playCount", "view_count", "viewCount", "go_detail_count"))),
            "like_count": _int_or_none(_first_value(
                stats_in, ("like_count", "likeCount", "digg_count", "real_like_count", "realLikeCount"))),
            "comment_count": _int_or_none(_first_value(
                stats_in, ("comment_count", "commentCount"))),
        },
    )


def _find_kuaishou_identity(responses: list[dict[str, Any]]) -> dict[str, Any] | None:
    """从捕获响应里找本人账号身份（同时有 id 与昵称的记录；同账号多来源按字段补全）。"""
    base: dict[str, Any] | None = None
    for resp in responses:
        for record in _record_values(resp.get("data")):
            rid = _first_value(record, KUAISHOU_ACCOUNT_ID_KEYS)
            name = _first_value(record, KUAISHOU_ACCOUNT_NAME_KEYS)
            if rid is None or not name:
                continue
            cand = {
                "platform_account_id": str(rid),
                "display_name": str(name).strip(),
                "username": (str(_first_value(record, ("username", "user_name", "unique_id", "short_id",
                                                       "kwai_id", "kwaiId")) or "").strip() or None),
                "fans_count": _int_or_none(_first_value(
                    record, ("fans_count", "fansCount", "fansNum", "follower_count", "followers_count", "fans"))),
                "following_count": _int_or_none(_first_value(
                    record, ("following_count", "follow_count", "followingCount"))),
                "work_count": _int_or_none(_first_value(
                    record, ("work_count", "works_count", "post_count", "content_count"))),
            }
            if base is None:
                base = cand
                continue
            # 同一账号的多来源记录 → 补齐缺失字段（如作品页 userInfo 里的粉丝数）
            if str(cand["platform_account_id"]) == str(base["platform_account_id"]):
                for k, v in cand.items():
                    if base.get(k) is None and v is not None:
                        base[k] = v
    return base


def _kuaishou_assert_logged_in(page) -> None:  # noqa: ANN001
    try:
        landed = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        landed = ""
    if "passport" in landed or "login" in landed:
        raise LoginRequiredError(f"会话已失效（跳转登录页：{landed[:120]}）")


def _extract_kuaishou_photo_list(responses: list[dict[str, Any]]) -> tuple[list[Any] | None, int | None]:
    """从 photo/list 响应直取作品数组（快手作品管理页实锤口径：data.list + data.total）。"""
    for resp in responses:
        if "photo/list" not in (resp.get("url") or ""):
            continue
        d = resp.get("data")
        if not isinstance(d, dict):
            continue
        data = d.get("data") if isinstance(d.get("data"), dict) else {}
        lst = data.get("list")
        if isinstance(lst, list):
            return lst, _int_or_none(data.get("total"))
    return None, None


def read_kuaishou_works(page, *, limit: int = 20, wait_ms: int = 25000) -> list[WorkItem]:
    """读快手创作者中心作品列表（捕获页面自身 XHR——参数/签名随页面生成，不复刻请求）。

    优先直取作品管理页的 photo/list 响应（data.list/data.total 实锤口径，接口出现即提前结束
    等待）；该响应缺席时才退回通用「作品数组计分」扫描（页面改版兜底）。
    登录失效 → raise LoginRequiredError；通道故障/页面改版 → RuntimeError（不把失败伪装成空列表）。
    显式 total=0 / 空数组 → 返回空列表（合法的「暂无作品」）。
    """
    limit = max(1, min(50, int(limit or 20)))
    url = f"{KUAISHOU_MANAGE_URL}?page=1&currentPage=1&pageSize={limit}"
    responses = _capture_json_responses(page, url, KUAISHOU_CAPTURE_PATTERNS,
                                        wait_ms=wait_ms, wait_urls_any=("photo/list",))
    _kuaishou_assert_logged_in(page)
    if not responses:
        raise RuntimeError("创作者后台没有返回可识别的 JSON 数据；可能未登录、页面改版或账号暂无读取权限")
    for resp in responses:   # 接口层明确「未登录」信号
        d = resp.get("data")
        if isinstance(d, dict) and d.get("result") in KUAISHOU_LOGOUT_RESULTS:
            raise LoginRequiredError(
                f"读回被拒：result={d.get('result')} {d.get('message') or d.get('msg') or ''}")
    lst, _total = _extract_kuaishou_photo_list(responses)
    if lst is not None:
        works: list[WorkItem] = []
        for raw in lst[:limit]:
            if isinstance(raw, dict):
                item = _map_kuaishou_item(raw)
                if item is not None:
                    works.append(item)
        if lst and not works:
            raise RuntimeError("photo/list 有记录但无一条带 id——页面结构可能改版，未把失败伪装为空数据")
        return works
    # photo/list 缺席（页面改版等）→ 通用计分扫描兜底（排除已知非作品接口）
    records = _find_content_array(
        [r for r in responses if not any(x in (r.get("url") or "")
                                         for x in ("emotion", "kconf", "config", "tips", "radar", "/log/"))],
        KUAISHOU_ID_KEYS)
    if not records:
        total = None
        for resp in responses:
            for record in _record_values(resp.get("data")):
                if "total" in record or "total_count" in record or "totalCount" in record:
                    total = _int_or_none(_first_value(record, ("total", "total_count", "totalCount")))
                    break
            if total is not None:
                break
        if total == 0:
            return []
        raise RuntimeError("快手作品响应无法识别，未把失败伪装为空数据")
    works = []
    for raw in records[:limit]:
        item = _map_kuaishou_item(raw)
        if item is not None:
            works.append(item)
    return works


def read_kuaishou_account(page) -> dict[str, Any]:
    """读快手创作者中心当前登录账号（id/昵称/粉丝）——读回回执的账号身份快照。"""
    responses = _capture_json_responses(page, KUAISHOU_MANAGE_URL, KUAISHOU_CAPTURE_PATTERNS,
                                        wait_ms=15000,
                                        wait_urls_any=("home/userInfo",))
    _kuaishou_assert_logged_in(page)
    if not responses:
        raise RuntimeError("账号读取：创作者后台没有返回可识别的 JSON 数据")
    identity = _find_kuaishou_identity(responses)
    if not identity:
        raise RuntimeError("账号信息缺少稳定 ID（页面结构可能改版或未登录）")
    return identity


def capture_kuaishou_snapshot(page) -> set[str]:
    """发前快照：读当前作品列表的全部作品 id。
    失败（未登录/通道异常）返回空集合——对账自动退化为标题+时间窗，不影响主流程。"""
    try:
        works = read_kuaishou_works(page, limit=30)
        return {w.platform_content_id for w in works}
    except Exception:  # noqa: BLE001
        return set()


def verify_kuaishou_publish(page, *, title: str, since_ms: int | None = None,
                            limit: int = 20, attempts: int = 4,
                            delay_s: float = 12.0,
                            snapshot_ids: set[str] | None = None) -> ReadbackResult:
    """快手发布后对账入口：多轮读回（列表异步更新/审核队列，给平台索引时间）。四档同抖音。"""
    last_error: Exception | None = None
    last_candidates: list[WorkItem] = []
    evidence: dict[str, Any] = {"attempts": 0}
    for i in range(max(1, attempts)):
        evidence = {"attempts": i + 1, "checked_at": int(time.time())}
        try:
            works = read_kuaishou_works(page, limit=limit)
        except LoginRequiredError as e:
            return ReadbackResult(outcome="login_required", evidence=evidence, error=str(e))
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"⚠️ 快手读回第 {i + 1}/{attempts} 轮失败：{e}", file=sys.stderr)
            if i + 1 < attempts:
                time.sleep(delay_s)
            continue
        last_candidates = works
        evidence["count"] = len(works)
        matched = find_published_work(works, title, since_ms=since_ms, exclude_ids=snapshot_ids)
        if matched:
            try:
                evidence["account"] = read_kuaishou_account(page)
            except Exception as e:  # noqa: BLE001
                evidence["account_error"] = str(e)
            print(f"✅ 快手读回对账通过：{matched.platform_content_id}（{matched.status}）", file=sys.stderr)
            return ReadbackResult(outcome="verified", matched=matched,
                                  candidates=works[:5], evidence=evidence)
        print(f"… 快手读回第 {i + 1}/{attempts} 轮：列表 {len(works)} 条未见本次作品", file=sys.stderr)
        if i + 1 < attempts:
            time.sleep(delay_s)
    if last_error is not None and not last_candidates:
        return ReadbackResult(outcome="readback_error", evidence=evidence, error=str(last_error))
    return ReadbackResult(outcome="unverified", candidates=last_candidates[:5], evidence=evidence)


# ═══════════════════════════════════════════════════════════════════════
# B站读回（创作中心 · 纯 API 直连）
#
# 与抖音/快手不同：B站稿件列表是稳定的 web API（member.bilibili.com/x/web/archives），
# 带 biliup cookies.json 的 SESSDATA 直连即可读——不需要浏览器、不需要捕获签名。
# 探针实测（2026-09-18）：code=0；列表在 data.arc_audits[]；条目 = {Archive:{aid,bvid,
# title,state,state_desc,ctime,ptime,duration,...}, stat:{view,like,...}}；data.page.count=总数。
# ═══════════════════════════════════════════════════════════════════════

BILIBILI_ARCHIVES_API = "https://member.bilibili.com/x/web/archives"
BILIBILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BILIBILI_REFERER = "https://member.bilibili.com/platform/upload-manager/article"
# 未登录 / csrf 校验失败（会话失效）
BILIBILI_LOGOUT_CODES = (-101, -111)
# 兜底状态映射（以接口返回的 state_desc 为主；此表仅当 state_desc 缺失时生效）
BILIBILI_STATE_FALLBACK = {0: "published", -1: "pending", -2: "pending", -30: "pending",
                           -4: "rejected", -16: "private", -100: "deleted"}


def _bilibili_load_cookies(cookie_file) -> str:
    """读 biliup 格式 cookies.json → Cookie 头字符串（同时容忍裸 {name,value} 列表）。"""
    data = json.loads(Path(cookie_file).expanduser().read_text(encoding="utf-8"))
    try:
        cookies = data["cookie_info"]["cookies"]
    except (KeyError, TypeError):
        cookies = data.get("cookies", [])
    pairs = [f"{c['name']}={c['value']}" for c in cookies if c.get("name")]
    if not pairs:
        raise RuntimeError("cookies.json 里没有可用的 cookie 项")
    return "; ".join(pairs)


# 读回也走直连：urllib 默认会吃 http_proxy/https_proxy 环境变量，开着系统代理/VPN 时
# 读回会从境外出口打 B站（投稿侧已由 bili_upload._direct_env 直连）——空 ProxyHandler 屏蔽之，
# 保证「投稿直连、读回也直连」一致，不触发风控。
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _bilibili_api(cookie_file, url: str, *, timeout_s: float = 20.0) -> dict[str, Any]:
    """直连请求 B站 web API（带 cookies，绕过环境/系统代理）。网络类错误包成 RuntimeError。"""
    req = urllib.request.Request(url, headers={
        "Cookie": _bilibili_load_cookies(cookie_file),
        "User-Agent": BILIBILI_UA,
        "Referer": BILIBILI_REFERER,
    })
    last: Exception | None = None
    for attempt in (1, 2):
        try:
            with _DIRECT_OPENER.open(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 1:
                time.sleep(1.5)  # 冷连接被重置（B站常见）——给一次机会
    raise RuntimeError(f"B站 API 请求失败：{type(last).__name__}: {last}") from last


def _bilibili_assert_logged_in(cookie_file) -> dict[str, Any]:
    """登录态确认（nav）。未登录 → LoginRequiredError；返回 data。"""
    data = _bilibili_api(cookie_file, BILIBILI_NAV_API)
    d = data.get("data") or {}
    if data.get("code") in BILIBILI_LOGOUT_CODES or not d.get("isLogin"):
        raise LoginRequiredError("B站登录态已失效（nav.isLogin=False）——请重新扫码登录（bili_login.py）")
    return d


def _map_bilibili_item(raw: dict[str, Any]) -> WorkItem | None:
    """arc_audits 条目 → 统一 WorkItem（纯函数，供离线测试）。"""
    arc = raw.get("Archive") or raw
    bvid = arc.get("bvid")
    if not bvid and arc.get("aid"):
        bvid = "av" + str(arc["aid"])
    if not bvid:
        return None
    ts = arc.get("pubtime") or arc.get("ptime") or arc.get("ctime")
    stat = raw.get("stat") or {}
    return WorkItem(
        platform_content_id=str(bvid),
        title=arc.get("title") or "",
        status=arc.get("state_desc") or BILIBILI_STATE_FALLBACK.get(arc.get("state"), f"state:{arc.get('state')}"),
        published_at_ms=int(ts) * 1000 if ts else None,
        stats={k: stat.get(k) for k in ("view", "like", "comment", "danmaku") if k in stat},
    )


def read_bilibili_works(cookie_file, *, limit: int = 20) -> list[WorkItem]:
    """读当前账号稿件列表（投稿管理，含审核中/已发布/未通过）。"""
    url = BILIBILI_ARCHIVES_API + "?" + urlencode({
        "status": "is_pubing,pubed,not_pubed", "pn": 1,
        "ps": max(1, min(limit, 50)), "coop": 1, "interactive": 1,
    })
    data = _bilibili_api(cookie_file, url)
    code = data.get("code")
    if code in BILIBILI_LOGOUT_CODES:
        raise LoginRequiredError(f"B站登录态已失效（archives code={code}）")
    if code != 0:
        raise RuntimeError(f"B站稿件列表接口返回 code={code}：{data.get('message') or data.get('msg')}")
    audits = (data.get("data") or {}).get("arc_audits") or []
    works: list[WorkItem] = []
    for item in audits:
        if not isinstance(item, dict):
            continue
        w = _map_bilibili_item(item)
        if w:
            works.append(w)
    return works


def read_bilibili_account(cookie_file) -> dict[str, Any]:
    """账号身份快照：uid + 昵称（读回回执标准件）。"""
    d = _bilibili_assert_logged_in(cookie_file)
    return {"platform": "bilibili", "uid": d.get("mid"), "name": d.get("uname")}


def capture_bilibili_snapshot(cookie_file) -> set[str]:
    """发前快照：读当前稿件的全部 bvid。
    失败（未登录/通道异常）返回空集合——对账自动退化为标题+时间窗，不影响主流程。"""
    try:
        return {w.platform_content_id for w in read_bilibili_works(cookie_file, limit=50)}
    except Exception:  # noqa: BLE001
        return set()


def verify_bilibili_publish(cookie_file, *, title: str, since_ms: int | None = None,
                            limit: int = 20, attempts: int = 4,
                            delay_s: float = 12.0,
                            snapshot_ids: set[str] | None = None) -> ReadbackResult:
    """B站发布后对账入口：多轮读回（审核队列/索引延迟）。四档同抖音。"""
    last_error: Exception | None = None
    last_candidates: list[WorkItem] = []
    evidence: dict[str, Any] = {"attempts": 0}
    for i in range(max(1, attempts)):
        evidence = {"attempts": i + 1, "checked_at": int(time.time())}
        try:
            works = read_bilibili_works(cookie_file, limit=limit)
        except LoginRequiredError as e:
            return ReadbackResult(outcome="login_required", evidence=evidence, error=str(e))
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"⚠️ B站读回第 {i + 1}/{attempts} 轮失败：{e}", file=sys.stderr)
            if i + 1 < attempts:
                time.sleep(delay_s)
            continue
        last_candidates = works
        evidence["count"] = len(works)
        matched = find_published_work(works, title, since_ms=since_ms, exclude_ids=snapshot_ids)
        if matched:
            try:
                evidence["account"] = read_bilibili_account(cookie_file)
            except Exception as e:  # noqa: BLE001
                evidence["account_error"] = str(e)
            print(f"✅ B站读回对账通过：{matched.platform_content_id}（{matched.status}）", file=sys.stderr)
            return ReadbackResult(outcome="verified", matched=matched,
                                  candidates=works[:5], evidence=evidence)
        print(f"… B站读回第 {i + 1}/{attempts} 轮：列表 {len(works)} 条未见本次稿件", file=sys.stderr)
        if i + 1 < attempts:
            time.sleep(delay_s)
    if last_error is not None and not last_candidates:
        return ReadbackResult(outcome="readback_error", evidence=evidence, error=str(last_error))
    return ReadbackResult(outcome="unverified", candidates=last_candidates[:5], evidence=evidence)
