#!/usr/bin/env python
"""Verified RedFox Xiaohongshu API client and local snapshot reporter."""

from __future__ import annotations

import argparse
import calendar
import http.client
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BASE_URL = "https://redfox.hk"
SUCCESS_CODE = 2000
SORT_VALUES = {"default": "_0", "latest": "_2", "hot": "_4"}
ENDPOINTS = {
    "search-accounts": "/story/api/xhsUser/searchUser",
    "search-notes": "/story/api/xhsUser/searchArticle",
    "account": "/story/api/xhsUser/queryAccountDetail",
    "note": "/story/api/xhsUser/queryWorkDetail",
    "search-ai-notes": "/story/api/parseWork/queryXhsAiMsgs",
    "comments-submit": "/story/api/xhs/commentSubmit",
    "comments-result": "/story/api/xhs/commentResult",
    "viral-insight": "/story/api/xhs/search/search",
    "video-transcript-submit": "/story/api/parseWork/audioTextExtract/submit/xhs",
    "video-transcript-result": "/story/api/parseWork/audioTextExtract/result/xhs",
    "weekly-top": "/story/api/cozeSkill/getXhsCozeSkillDataSeven",
}
ENDPOINT_METHODS = {operation: "POST" for operation in ENDPOINTS}
ENDPOINT_METHODS["weekly-top"] = "GET"
ENDPOINT_PARAMETER_LOCATIONS = {operation: "body" for operation in ENDPOINTS}
ENDPOINT_PARAMETER_LOCATIONS["weekly-top"] = "query"
ENDPOINT_PARAMETER_LOCATIONS["comments-result"] = "query"
API_IDS = {
    "account": "4IVIDHEN",
    "note": "KR1LPTBF",
    "search-accounts": "439NFLBD",
    "search-notes": "384C6W6B",
    "search-ai-notes": "047JJ3UA",
    "comments-submit": "5AM3X4HZ",
    "comments-result": "LO93CE5K",
    "viral-insight": "3X8FGEEM",
    "video-transcript-submit": "DCZW5V7A",
    "video-transcript-result": "9UHXOXSF",
    "weekly-top": "LBYLC5AK",
}
SOURCE_TYPES = {
    "account": "RF_ACCOUNT",
    "note": "RF_NOTE",
    "search-accounts": "RF_SEARCH_ACCOUNT",
    "search-notes": "RF_SEARCH_NOTE",
    "search-ai-notes": "RF_SEARCH_NOTE",
    "comments-submit": "RF_COMMENTS",
    "comments-result": "RF_COMMENTS",
    "viral-insight": "RF_VIRAL",
    "video-transcript-submit": "RF_TRANSCRIPT",
    "video-transcript-result": "RF_TRANSCRIPT",
    "weekly-top": "RF_WEEKLY",
}
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
EMPTY_SEARCH_CODE = 3203
EMPTY_SEARCH_PATHS = {
    ENDPOINTS["search-accounts"],
    ENDPOINTS["search-notes"],
    ENDPOINTS["search-ai-notes"],
}
REPORT_TIMEZONE = "Asia/Shanghai"
COST_NOTICE = "所有 RedFox API 请求都会消耗点数；具体扣点以 RedFox 控制台实时规则为准。"


class RedFoxError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_api(
    path: str,
    payload: dict[str, Any],
    retries: int = 2,
    method: str = "POST",
    parameter_location: str | None = None,
) -> dict[str, Any]:
    api_key = os.environ.get("REDFOX_API_KEY", "").strip()
    if not api_key:
        raise RedFoxError("Missing REDFOX_API_KEY environment variable")

    method = method.upper()
    if method not in {"GET", "POST"}:
        raise RedFoxError(f"Unsupported HTTP method: {method}")
    location = parameter_location or ("query" if method == "GET" else "body")
    if location not in {"body", "query"}:
        raise RedFoxError(f"Unsupported parameter location: {location}")
    request_path = path
    body: bytes | None = None
    if location == "query":
        query = urlencode(payload, doseq=True)
        request_path = f"{path}?{query}" if query else path
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    target = urlsplit(BASE_URL)

    for attempt in range(retries + 1):
        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(target.hostname, target.port or 443, timeout=30)
            connection.request(
                method,
                request_path,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": api_key,
                    "User-Agent": "xiaohongshu-omni-v4/1.0",
                },
            )
            response = connection.getresponse()
            response_body = response.read().decode("utf-8")
            if 300 <= response.status < 400:
                raise RedFoxError("RedFox redirect refused to protect the API key")
            if response.status in RETRYABLE_HTTP and attempt < retries:
                time.sleep(0.5 * (2**attempt))
                continue
            if response.status >= 400:
                raise RedFoxError(f"RedFox HTTP error {response.status}: {response_body[:500]}")
            try:
                result = json.loads(response_body)
            except json.JSONDecodeError as exc:
                raise RedFoxError(f"RedFox returned invalid JSON: {response_body[:200]}") from exc
            if result.get("code") == EMPTY_SEARCH_CODE and path in EMPTY_SEARCH_PATHS:
                result["data"] = {"list": [], "hasMore": False}
                return result
            if result.get("code") != SUCCESS_CODE:
                code = result.get("code", "unknown")
                message = result.get("msg") or result.get("message") or "Unknown RedFox error"
                raise RedFoxError(f"RedFox API error {code}: {message}")
            return result
        except (OSError, http.client.HTTPException) as exc:
            if attempt < retries:
                time.sleep(0.5 * (2**attempt))
                continue
            raise RedFoxError(f"RedFox network error: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    raise RedFoxError("RedFox request failed after retries")


def envelope(operation: str, path: str, params: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "redfox.hk",
        "source_type": SOURCE_TYPES.get(operation),
        "fetched_at": utc_now(),
        "operation": operation,
        "api_id": API_IDS.get(operation),
        "http_method": ENDPOINT_METHODS.get(operation, "POST"),
        "api_path": path,
        "parameters": params,
        "provider_code": response.get("code"),
        "provider_message": response.get("msg") or response.get("message"),
        "data": response.get("data"),
        "request_count": 1,
        "billing_notice": COST_NOTICE,
    }


def write_json(data: Any, output: str | None) -> None:
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if output:
        path = Path(output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        print(path)
    else:
        print(rendered, end="")


def collect(
    operation: str,
    params: dict[str, Any],
    output: str | None,
    pages: int = 1,
    retries: int = 2,
) -> dict[str, Any]:
    path = ENDPOINTS[operation]
    method = ENDPOINT_METHODS[operation]
    parameter_location = ENDPOINT_PARAMETER_LOCATIONS[operation]
    responses: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for page_index in range(pages):
        page_params = dict(params)
        if operation in {"search-notes", "search-accounts"}:
            page_params["offset"] = int(params.get("offset", 0)) + page_index * 20
        elif operation == "search-ai-notes":
            page_params["pageNum"] = int(params.get("pageNum", 1)) + page_index
        request_options: dict[str, Any] = {}
        if retries != 2:
            request_options["retries"] = retries
        if parameter_location == "query":
            response = request_api(
                path,
                page_params,
                method=method,
                parameter_location=parameter_location,
                **request_options,
            )
        else:
            response = request_api(path, page_params, **request_options)
        responses.append((page_params, response))
        data = response.get("data")
        if operation != "search-ai-notes" and isinstance(data, dict) and not data.get("hasMore", True):
            break

    result = envelope(operation, path, params, responses[0][1])
    result["request_count"] = len(responses)
    if len(responses) > 1:
        combined: list[Any] = []
        seen: set[str] = set()
        for _, response in responses:
            data = response.get("data")
            items = data.get("list", []) if isinstance(data, dict) else []
            for item in items if isinstance(items, list) else []:
                key = str(item.get("workId") or item.get("photoId") or item.get("userId") or item.get("accountId") or item)
                if key not in seen:
                    seen.add(key)
                    combined.append(item)
        if not isinstance(result.get("data"), dict):
            result["data"] = {}
        result["data"]["list"] = combined
        result["pages_fetched"] = [page_params for page_params, _ in responses]
    write_json(result, output)
    return result


def require_cost_confirmation(command: str, confirmed: bool) -> None:
    if command in ENDPOINTS and not confirmed:
        raise RedFoxError(f"{COST_NOTICE} 完成本批次内部成本规划后增加 --confirm-cost。")


def add_cost_confirmation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirm-cost",
        action="store_true",
        help="声明本批次已完成内部成本规划并记录点数消耗",
    )


def command_search(args: argparse.Namespace, operation: str) -> None:
    params = {
        "keyword": args.keyword,
        "offset": args.offset,
        "sortType": SORT_VALUES[args.sort],
    }
    collect(operation, params, args.output, pages=args.pages, retries=getattr(args, "retries", 2))


def command_search_ai(args: argparse.Namespace) -> None:
    validate_redfox_time(args.start_time, "--start-time")
    validate_redfox_time(args.end_time, "--end-time")
    if datetime.strptime(args.end_time, "%Y-%m-%d %H:%M:%S") < datetime.strptime(args.start_time, "%Y-%m-%d %H:%M:%S"):
        raise RedFoxError("--end-time must be on or after --start-time")
    params = {
        "keyword": args.keyword,
        "pageNum": args.page_num,
        "pageSize": args.page_size,
        "startTime": args.start_time,
        "endTime": args.end_time,
    }
    if args.source:
        params["source"] = args.source
    collect("search-ai-notes", params, args.output, pages=args.pages, retries=getattr(args, "retries", 2))


def command_account(args: argparse.Namespace) -> None:
    params = {"accountId": args.account_id}
    if args.user_id:
        params["userId"] = args.user_id
    output = args.output
    if args.snapshot_dir:
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in args.account_id)
        output = str(Path(args.snapshot_dir) / safe_id / f"{timestamp}.json")
    collect("account", params, output)


def command_note(args: argparse.Namespace) -> None:
    if not args.work_id and not args.work_link:
        raise RedFoxError("Provide --work-id or --work-link")
    params: dict[str, Any] = {}
    if args.work_id:
        params["workId"] = args.work_id
    if args.work_link:
        params["workLink"] = args.work_link
    collect("note", params, args.output)


def validate_date(value: str, label: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise RedFoxError(f"{label} must use YYYY-MM-DD") from exc


def command_comments_submit(args: argparse.Namespace) -> None:
    if args.count == 0 or args.count < -1:
        raise RedFoxError("--count must be -1 or a positive integer")
    collect("comments-submit", {"opusId": args.work_id, "dataNum": args.count}, args.output)


def load_comment_submission(path_value: str) -> tuple[str, datetime]:
    path = Path(path_value).expanduser().resolve()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RedFoxError(f"Unable to read comment submission response: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RedFoxError(f"Comment submission response is not valid JSON: {path}") from exc
    if not isinstance(record, dict) or record.get("operation") not in {None, "comments-submit"}:
        raise RedFoxError("--submit-response must point to a comments-submit response")
    data = record.get("data")
    if not isinstance(data, dict):
        raise RedFoxError("Comment submission response is missing data")
    task_id = data.get("taskId")
    visible_after_value = data.get("visibleAfterTime")
    if not isinstance(task_id, str) or not task_id.strip():
        raise RedFoxError("Comment submission response is missing data.taskId")
    if not isinstance(visible_after_value, str) or not visible_after_value.strip():
        raise RedFoxError("Comment submission response is missing data.visibleAfterTime")
    try:
        visible_after = datetime.strptime(visible_after_value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo(REPORT_TIMEZONE)
        )
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise RedFoxError("data.visibleAfterTime must use YYYY-MM-DD HH:MM:SS") from exc
    return task_id.strip(), visible_after


def command_comments_result(args: argparse.Namespace, now: datetime | None = None) -> None:
    task_id = args.task_id
    if args.submit_response:
        task_id, visible_after = load_comment_submission(args.submit_response)
        current_time = now or datetime.now(ZoneInfo(REPORT_TIMEZONE))
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=ZoneInfo(REPORT_TIMEZONE))
        current_time = current_time.astimezone(ZoneInfo(REPORT_TIMEZONE))
        if current_time < visible_after:
            raise RedFoxError(
                f"Comment result is not visible until {visible_after.strftime('%Y-%m-%d %H:%M:%S %Z')}; "
                "no request was sent"
            )
    collect("comments-result", {"taskId": task_id}, args.output)


def command_task_result(args: argparse.Namespace, operation: str) -> None:
    collect(operation, {"taskId": args.task_id}, args.output)


def command_viral_insight(args: argparse.Namespace) -> None:
    if not 1 <= args.page_size <= 50:
        raise RedFoxError("--page-size must be between 1 and 50")
    if args.page_num < 1:
        raise RedFoxError("--page-num must be at least 1")
    if bool(args.start_date) != bool(args.end_date):
        raise RedFoxError("Provide both --start-date and --end-date, or neither")
    params: dict[str, Any] = {"pageNum": args.page_num, "pageSize": args.page_size}
    if args.keyword:
        params["keyword"] = args.keyword
    if args.start_date and args.end_date:
        validate_date(args.start_date, "--start-date")
        validate_date(args.end_date, "--end-date")
        if args.end_date < args.start_date:
            raise RedFoxError("--end-date must be on or after --start-date")
        params.update({"startDate": args.start_date, "endDate": args.end_date})
    collect("viral-insight", params, args.output)


def command_weekly_top(args: argparse.Namespace) -> None:
    params: dict[str, Any] = {}
    if args.rank_date:
        validate_date(args.rank_date, "--rank-date")
        params["rankDate"] = args.rank_date
    if args.category:
        params["category"] = args.category
    collect("weekly-top", params, args.output)


def command_video_transcript_submit(args: argparse.Namespace) -> None:
    parsed = urlsplit(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RedFoxError("--url must be an absolute HTTP(S) Xiaohongshu video URL")
    collect("video-transcript-submit", {"url": args.url}, args.output)


def walk_json(input_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    records = []
    for path in sorted(input_dir.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append((path, value))
    return records


def parse_month(value: str) -> tuple[datetime, datetime]:
    try:
        year, month = (int(part) for part in value.split("-", 1))
        timezone_info = ZoneInfo(REPORT_TIMEZONE)
        start = datetime(year, month, 1, tzinfo=timezone_info)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise RedFoxError("Month must use YYYY-MM") from exc
    end = datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59, 999999, tzinfo=timezone_info)
    return start, end


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(REPORT_TIMEZONE))
        return parsed.astimezone(ZoneInfo(REPORT_TIMEZONE))
    except ValueError:
        return None


def validate_redfox_time(value: str, label: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise RedFoxError(f"{label} must use YYYY-MM-DD HH:MM:SS in {REPORT_TIMEZONE}") from exc


def numeric_metric(data: dict[str, Any], key: str) -> int | None:
    raw = data.get(key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise RedFoxError(f"Invalid numeric account metric {key}: {raw!r}") from exc


def iter_notes(record: dict[str, Any]) -> list[dict[str, Any]]:
    data = record.get("data")
    if not isinstance(data, dict):
        return []
    if record.get("operation") == "note" or "workId" in data:
        return [data]
    items = data.get("list")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def interaction(note: dict[str, Any]) -> dict[str, int]:
    mapping = {
        "likes": ("workLikedCount", "likeCount"),
        "collections": ("workCollectedCount", "collectCount"),
        "comments": ("workCommentsCount", "commentCount"),
        "shares": ("workSharedCount", "shareCount"),
    }
    result: dict[str, int] = {}
    for target, candidates in mapping.items():
        raw = next((note.get(key) for key in candidates if note.get(key) is not None), 0)
        try:
            result[target] = int(raw)
        except (TypeError, ValueError):
            result[target] = 0
    result["total"] = sum(result.values())
    return result


def command_report(args: argparse.Namespace) -> None:
    root = Path(args.input_dir).expanduser().resolve()
    start, end = parse_month(args.month)
    records = walk_json(root)
    notes_by_id: dict[str, tuple[dict[str, Any], str | None, str]] = {}
    snapshots: list[dict[str, Any]] = []
    source_files: set[str] = set()

    for path, record in records:
        operation = record.get("operation")
        if (
            operation == "account"
            and isinstance(record.get("data"), dict)
            and str(record.get("parameters", {}).get("accountId", "")) == args.account_id
        ):
            snapshots.append(record)

    snapshots = [
        item
        for item in snapshots
        if (fetched := parse_datetime(item.get("fetched_at"))) and start <= fetched <= end
    ]
    snapshots.sort(key=lambda item: parse_datetime(item.get("fetched_at")) or start)
    source_files.update(
        str(path.relative_to(root))
        for path, record in records
        if record in snapshots
    )
    account_user_ids = {
        str(item["data"].get("userId"))
        for item in snapshots
        if item["data"].get("userId")
    }
    if args.account_user_id:
        account_user_ids.add(args.account_user_id)
    if not account_user_ids:
        raise RedFoxError(
            "Cannot verify note ownership: provide --account-user-id or collect an account snapshot containing userId"
        )

    for path, record in records:
        for note in iter_notes(record):
            author_id = str(note.get("accountUserid") or note.get("authorId") or "")
            published = parse_datetime(note.get("workPublishTime") or note.get("gmtCreate"))
            if author_id in account_user_ids and published and start <= published <= end:
                key = str(note.get("workId") or note.get("photoId") or note.get("workUrl") or "")
                if key:
                    fetched_at = record.get("fetched_at")
                    existing = notes_by_id.get(key)
                    if existing is None or (parse_datetime(fetched_at) or start) >= (parse_datetime(existing[1]) or start):
                        notes_by_id[key] = (note, fetched_at, str(path.relative_to(root)))
                    source_files.add(str(path.relative_to(root)))

    notes = list(notes_by_id.values())
    totals = {"likes": 0, "collections": 0, "comments": 0, "shares": 0, "total": 0}
    ranked = []
    for note, fetched_at, source_file in notes:
        metrics = interaction(note)
        for key in totals:
            totals[key] += metrics[key]
        ranked.append({
            "workId": note.get("workId") or note.get("photoId"),
            "title": note.get("workTitle") or note.get("title"),
            "url": note.get("workUrl") or note.get("url"),
            "publishTime": note.get("workPublishTime") or note.get("gmtCreate"),
            "metricsObservedAt": fetched_at,
            "sourceFile": source_file,
            "interactions": metrics,
        })
    ranked.sort(key=lambda item: item["interactions"]["total"], reverse=True)

    growth = None
    if len(snapshots) >= 2:
        first, last = snapshots[0]["data"], snapshots[-1]["data"]
        deltas: dict[str, int | None] = {}
        for output_key, source_key in {
            "fans_change": "accountFans",
            "likes_change": "accountLikes",
            "collections_change": "accountCollectes",
            "works_change": "accountTotalWorks",
        }.items():
            first_value = numeric_metric(first, source_key)
            last_value = numeric_metric(last, source_key)
            deltas[output_key] = None if first_value is None or last_value is None else last_value - first_value
        growth = {
            "from": snapshots[0].get("fetched_at"),
            "to": snapshots[-1].get("fetched_at"),
            **deltas,
        }

    report = {
        "report_type": "xiaohongshu_public_data_monthly_summary",
        "month": args.month,
        "generated_at": utc_now(),
        "report_timezone": REPORT_TIMEZONE,
        "account": {
            "account_id": args.account_id,
            "user_ids": sorted(account_user_ids),
        },
        "coverage": {
            "note_count": len(notes),
            "account_snapshot_count": len(snapshots),
            "source_files": sorted(source_files),
            "limitations": [
                "Only notes present in local RedFox results are included; this is not a complete account export.",
                "Note interactions are cumulative public values observed at metricsObservedAt for notes published in the month; they are not interactions generated during the month.",
                "Impressions, profile visits, follow sources, leads, sales and conversions require creator-center or business data.",
                "Growth is omitted unless at least two valid account snapshots exist inside the reporting month.",
            ],
        },
        "account_growth": growth,
        "note_interactions": totals,
        "top_notes": ranked[:10],
    }
    write_json(report, args.output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verified RedFox Xiaohongshu data CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("search-notes", "search-accounts"):
        command = subparsers.add_parser(name)
        command.add_argument("--keyword", required=True)
        command.add_argument("--offset", type=int, default=0)
        command.add_argument("--sort", choices=SORT_VALUES, default="default")
        command.add_argument("--pages", type=int, choices=range(1, 11), default=1)
        command.add_argument("--retries", type=int, choices=range(0, 3), default=2)
        command.add_argument("--output")
        add_cost_confirmation(command)

    ai = subparsers.add_parser("search-ai-notes")
    ai.add_argument("--keyword", required=True)
    ai.add_argument("--start-time", required=True)
    ai.add_argument("--end-time", required=True)
    ai.add_argument("--page-num", type=int, default=1)
    ai.add_argument("--page-size", type=int, default=20)
    ai.add_argument("--pages", type=int, choices=range(1, 11), default=1)
    ai.add_argument("--retries", type=int, choices=range(0, 3), default=2)
    ai.add_argument("--source")
    ai.add_argument("--output")
    add_cost_confirmation(ai)

    account = subparsers.add_parser("account")
    account.add_argument("--account-id", required=True)
    account.add_argument("--user-id")
    account.add_argument("--snapshot-dir")
    account.add_argument("--output")
    add_cost_confirmation(account)

    note = subparsers.add_parser("note")
    note.add_argument("--work-id")
    note.add_argument("--work-link")
    note.add_argument("--output")
    add_cost_confirmation(note)

    comments_submit = subparsers.add_parser("comments-submit", help="提交一级评论采集任务")
    comments_submit.add_argument("--work-id", required=True)
    comments_submit.add_argument("--count", type=int, required=True, help="-1 表示全部，否则填写正整数")
    comments_submit.add_argument("--output")
    add_cost_confirmation(comments_submit)

    comments_result = subparsers.add_parser("comments-result", help="查询一级评论采集任务")
    comments_result_source = comments_result.add_mutually_exclusive_group(required=True)
    comments_result_source.add_argument("--task-id")
    comments_result_source.add_argument(
        "--submit-response",
        help="评论提交响应JSON；自动读取taskId并在visibleAfterTime前阻止请求",
    )
    comments_result.add_argument("--output")
    add_cost_confirmation(comments_result)

    viral = subparsers.add_parser("viral-insight", help="查询爆款笔记、热点和相关搜索")
    viral.add_argument("--keyword")
    viral.add_argument("--page-num", type=int, default=1)
    viral.add_argument("--page-size", type=int, default=10)
    viral.add_argument("--start-date")
    viral.add_argument("--end-date")
    viral.add_argument("--output")
    add_cost_confirmation(viral)

    weekly = subparsers.add_parser("weekly-top", help="查询七日爆款笔记榜")
    weekly.add_argument("--rank-date")
    weekly.add_argument("--category")
    weekly.add_argument("--output")
    add_cost_confirmation(weekly)

    transcript_submit = subparsers.add_parser("video-transcript-submit", help="提交视频提文案任务")
    transcript_submit.add_argument("--url", required=True)
    transcript_submit.add_argument("--output")
    add_cost_confirmation(transcript_submit)

    transcript_result = subparsers.add_parser("video-transcript-result", help="查询视频提文案任务")
    transcript_result.add_argument("--task-id", required=True)
    transcript_result.add_argument("--output")
    add_cost_confirmation(transcript_result)

    report = subparsers.add_parser("report")
    report.add_argument("--input-dir", required=True)
    report.add_argument("--account-id", required=True)
    report.add_argument("--account-user-id")
    report.add_argument("--month", required=True)
    report.add_argument("--output")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        require_cost_confirmation(args.command, bool(getattr(args, "confirm_cost", False)))
        if args.command == "search-notes":
            command_search(args, "search-notes")
        elif args.command == "search-accounts":
            command_search(args, "search-accounts")
        elif args.command == "search-ai-notes":
            command_search_ai(args)
        elif args.command == "account":
            command_account(args)
        elif args.command == "note":
            command_note(args)
        elif args.command == "comments-submit":
            command_comments_submit(args)
        elif args.command == "comments-result":
            command_comments_result(args)
        elif args.command == "viral-insight":
            command_viral_insight(args)
        elif args.command == "weekly-top":
            command_weekly_top(args)
        elif args.command == "video-transcript-submit":
            command_video_transcript_submit(args)
        elif args.command == "video-transcript-result":
            command_task_result(args, "video-transcript-result")
        elif args.command == "report":
            command_report(args)
        else:
            parser.error(f"Unknown command: {args.command}")
    except RedFoxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
