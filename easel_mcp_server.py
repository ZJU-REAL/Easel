"""Easel's native MCP server for Hermes Agent.

This is deliberately a standalone stdio server: Hermes discovers the tools as
``mcp_easel_*`` and Easel remains upgradeable independently.  It exposes the
Easel data plane (personas, skills, outputs, accounts, analytics, schedules,
ideas and publishing) without exposing arbitrary shell, cookies or secrets.

High-risk operations are fail-closed:
- login/cookie/profile mutation is not exposed;
- publishing requires EASEL_MCP_ALLOW_PUBLISH=1 and a one-time confirmation;
- schedule/idea writes require a one-time write confirmation;
- publish results are never converted to success without the publisher's
  actual exit code.

All logs go to stderr. stdout is reserved for the MCP stdio protocol.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from easel.manual_publish import PLATFORMS as MANUAL_PLATFORMS, build_package

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUTS = PROJECT_ROOT / "outputs"
SCRIPTS = PROJECT_ROOT / "skills" / "shared" / "scripts"
BUILTIN_SKILLS = PROJECT_ROOT / "skills" / "builtin"
PROFILES = PROJECT_ROOT / "profiles"
BROWSER_PROFILES = Path.home() / ".easel-browser-profiles"
LOGIN_DIR = OUTPUTS / "_login"
PUBLISH_DIR = OUTPUTS / "_publish"
MCP_DIR = OUTPUTS / "_mcp"
CONFIRM_FILE = MCP_DIR / "confirmations.json"
SCHEDULE_FILE = OUTPUTS / "_schedule.json"
IDEAS_FILE = OUTPUTS / "_ideas.json"

# The publish gate is environment-driven so a bot session can never widen it.
# Only the host process that launches this MCP server may enable real publishing.
PUBLISH_ENABLED = os.environ.get("EASEL_MCP_ALLOW_PUBLISH") == "1"

# This is metadata only. No cookie values or credential fields are returned.
ACCOUNT_CONFIG: dict[str, dict[str, Any]] = {
    "xiaohongshu": {"name": "小红书", "backend": "xhs", "profile": "XiaohongshuProfile", "analytics": True},
    "kuaishou": {"name": "快手", "backend": "web", "wp": "kuaishou", "profile": "KuaishouProfile", "analytics": True},
    "weixin-channels": {"name": "视频号", "backend": "web", "wp": "weixin-channels", "profile": "ChannelsProfile", "analytics": True},
    "zhihu": {"name": "知乎", "backend": "web", "wp": "zhihu", "profile": "ZhihuProfile", "analytics": True},
    "bilibili": {"name": "B站", "backend": "biliup", "profile": "BilibiliProfile", "analytics": True},
    "douyin": {"name": "抖音", "backend": "douyin", "profile": "DouyinProfile", "analytics": True},
    "wechat-oa": {"name": "公众号", "backend": "wechat-oa", "profile": "WeixinMpProfile", "analytics": True},
    "alipay": {"name": "支付宝", "backend": "unsupported", "analytics": False},
    "toutiao": {"name": "今日头条", "backend": "unsupported", "analytics": False},
}

# Platform constraints are imported from the existing deterministic dispatcher.
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "builtin" / "skill-cross-platform-publish" / "scripts"))
try:
    from publish_dispatch import PLATFORMS as DISPATCH_PLATFORMS, _check_platform
except Exception:  # pragma: no cover - a broken Easel install should fail visibly
    DISPATCH_PLATFORMS = {}
    _check_platform = None

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s [%(levelname)s] easel-mcp: %(message)s")
log = logging.getLogger("easel-mcp")

_SECRET_RE = re.compile(
    r"(?i)(?:bearer\s+|(?:api[_-]?key|token|secret|password|cookie|sessionid|sessdata)\s*[=:]\s*)[^\s,;]+"
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _safe_error(exc: Any) -> str:
    return _SECRET_RE.sub("[REDACTED]", str(exc))[:500]


def _result(ok: bool = True, **data: Any) -> str:
    return _json({"ok": ok, **data})


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else fallback
    except Exception:
        return fallback


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _safe_output(rel: str) -> Path:
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("输出路径不能为空")
    root = OUTPUTS.resolve()
    full = (root / rel).resolve()
    if root not in full.parents and full != root:
        raise ValueError("路径必须位于 Easel outputs 内")
    if any(part.startswith(".") or part.startswith("_") for part in full.relative_to(root).parts):
        raise ValueError("不能读取系统目录或隐藏输出")
    if not full.is_file():
        raise ValueError("输出文件不存在")
    return full


def _safe_media(rel: str) -> Path:
    p = _safe_output(rel)
    if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv", ".ts"}:
        raise ValueError("只允许图片或视频素材")
    return p


def _status_file(platform: str) -> Path:
    if platform not in ACCOUNT_CONFIG:
        raise ValueError("未知平台")
    return LOGIN_DIR / f"{platform}.json"


def _account_fast_status(platform: str, cfg: dict[str, Any]) -> dict[str, Any]:
    backend = cfg["backend"]
    if backend == "unsupported":
        return {"state": "unsupported", "logged_in": False, "source": "unsupported"}
    if backend == "biliup":
        logged = (PROJECT_ROOT / "cookies.json").is_file()
        return {"state": "success" if logged else "unknown", "logged_in": logged, "source": "cookies_file_presence_only"}
    if backend == "wechat-oa":
        st = _read_json(LOGIN_DIR / "wechat-oa-mp.json", {})
        ok = st.get("state") == "success"
        return {"state": st.get("state", "unknown"), "logged_in": ok, "source": "login_marker"}
    st = _read_json(LOGIN_DIR / f"{platform}.json", {})
    state = st.get("state", "unknown") if isinstance(st, dict) else "unknown"
    return {"state": state, "logged_in": state == "success", "source": "login_marker"}


def _run(cmd: list[str], *, timeout: int = 120, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    """Run only an explicitly constructed Easel script command."""
    merged = dict(os.environ)
    merged.update(env or {})
    merged.setdefault("PYTHONUTF8", "1")
    merged.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        p = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=merged, capture_output=True,
                           text=True, encoding="utf-8", timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Easel 子程序超时（{timeout}s）") from exc
    except FileNotFoundError as exc:
        raise RuntimeError(f"Easel 依赖不存在：{Path(str(exc.filename or '')).name}") from exc


def _last_json(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    return None


def _public_file_name(path: Path) -> str:
    # Avoid returning filenames that could expose a credential-bearing artifact.
    if re.search(r"(?i)(cookie|token|secret|password|session|credential)", path.name):
        return "[REDACTED]"
    return path.name


def _load_confirmations() -> list[dict[str, Any]]:
    now = time.time()
    rows = _read_json(CONFIRM_FILE, [])
    rows = rows if isinstance(rows, list) else []
    return [r for r in rows if isinstance(r, dict) and float(r.get("expires_at", 0)) > now and not r.get("used")]


def _issue_confirmation(kind: str, payload: dict[str, Any], ttl: int = 600) -> dict[str, Any]:
    rows = _load_confirmations()
    token = secrets.token_urlsafe(18)
    digest = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
    rows.append({"token": token, "kind": kind, "digest": digest, "payload": payload,
                 "created_at": time.time(), "expires_at": time.time() + ttl, "used": False})
    _atomic_json(CONFIRM_FILE, rows)
    return {"confirmation_id": token, "expires_in": ttl, "request_digest": digest}


def _consume_confirmation(token: str, kind: str, payload: dict[str, Any]) -> None:
    if not token:
        raise PermissionError("缺少一次性确认凭证；先调用对应的 request_confirmation 工具")
    rows = _load_confirmations()
    digest = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
    for row in rows:
        if row.get("token") == token and row.get("kind") == kind:
            if row.get("digest") != digest:
                raise PermissionError("确认凭证与请求内容不一致，必须重新生成")
            row["used"] = True
            _atomic_json(CONFIRM_FILE, rows)
            return
    raise PermissionError("确认凭证不存在、已使用或已过期")


def _load_list(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, [])
    return value if isinstance(value, list) else []


# Skill execution is exposed through Easel's existing skill router rather than
# an arbitrary shell tool.  High-risk skills still need a payload-bound one-time
# confirmation; safe skills can run directly with the same profile-aware agent
# path used by the CLI/Web entry points.
_SKILL_CONFIRM_MARKERS = (
    "upload", "publisher", "comment-reply", "community-ops", "livestream",
    "cross-platform-publish", "publish-scheduler", "profile-manager", "voice-clone",
)
# Only skills with real platform side-effects sit behind the host publish gate.
# Scheduling/log/checklist/analytics skills are internal write ops: they need a
# one-time confirmation but must stay runnable while the publish gate is closed.
_SKILL_GATE_MARKERS = (
    "upload", "publisher", "comment-reply", "community-ops", "livestream",
    "cross-platform-publish",
)
_SHARED_ROOT = Path(os.environ.get("EASEL_SHARED_ROOT", str(PROJECT_ROOT / "shared"))).expanduser().resolve()
_SKILL_INPUT_ROOTS = tuple({p.resolve() for p in (PROJECT_ROOT, OUTPUTS, PROFILES, _SHARED_ROOT)})


def _resolve_skill(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", name):
        raise ValueError("技能名称格式无效")
    candidates = [name] if name.startswith("skill-") else [name, f"skill-{name}"]
    for candidate in candidates:
        if (BUILTIN_SKILLS / candidate / "SKILL.md").is_file():
            return candidate
    raise ValueError("技能不存在")


def _skill_requires_confirmation(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SKILL_CONFIRM_MARKERS)


def _skill_requires_publish_gate(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SKILL_GATE_MARKERS)


def _validate_skill_input(raw_input: str) -> str:
    if not isinstance(raw_input, str) or not raw_input.strip():
        raise ValueError("技能输入不能为空")
    if len(raw_input) > 120_000:
        raise ValueError("技能输入过大")
    candidate = Path(raw_input).expanduser()
    # Easel's CLI accepts a path as input. Keep that feature, but do not let an
    # MCP caller ask the skill agent to ingest arbitrary home/system files.
    if candidate.is_absolute() or candidate.is_file():
        resolved = candidate.resolve(strict=False)
        if not any(root == resolved or root in resolved.parents for root in _SKILL_INPUT_ROOTS):
            raise ValueError("输入文件必须位于 Easel 项目、outputs 或 profiles 内")
    return raw_input


def easel_skill_policy(name: str) -> str:
    """返回技能的 MCP 执行策略，不执行技能。"""
    try:
        full = _resolve_skill(name)
        return _result(skill=full, requires_confirmation=_skill_requires_confirmation(full),
                       confirmation_kind="skill_run", input_roots=[str(p) for p in _SKILL_INPUT_ROOTS])
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_request_skill_confirmation(skill_name: str, input_text: str, profile: str = "") -> str:
    """为高风险技能执行申请一次性、payload 绑定的确认凭证。"""
    try:
        full = _resolve_skill(skill_name)
        content = _validate_skill_input(input_text)
        if profile and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile):
            raise ValueError("画像名称格式无效")
        if _skill_requires_publish_gate(full) and not PUBLISH_ENABLED:
            return _result(False, state="blocked", skill=full, publish_enabled=False,
                           error="该技能会真实发布或上传到平台；主机未启用 EASEL_MCP_ALLOW_PUBLISH，已阻断")
        payload = {"skill": full, "input": content, "profile": profile}
        confirmation = _issue_confirmation("skill_run", payload)
        return _result(skill=full, requires_confirmation=_skill_requires_confirmation(full), **confirmation)
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_run_skill(skill_name: str, input_text: str, profile: str = "", confirmation_id: str = "") -> str:
    """运行任一已安装 Easel 技能；高风险技能必须先确认，禁止任意 shell。"""
    try:
        full = _resolve_skill(skill_name)
        content = _validate_skill_input(input_text)
        if profile and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile):
            raise ValueError("画像名称格式无效")
        payload = {"skill": full, "input": content, "profile": profile}
        if _skill_requires_publish_gate(full) and not PUBLISH_ENABLED:
            return _result(False, state="blocked", skill=full, publish_enabled=False,
                           error="该技能会真实发布或上传到平台；主机未启用 EASEL_MCP_ALLOW_PUBLISH，已阻断")
        if _skill_requires_confirmation(full):
            if not confirmation_id:
                return _result(False, state="blocked", skill=full,
                               error="该技能属于高风险能力；请先调用 easel_request_skill_confirmation")
            _consume_confirmation(confirmation_id, "skill_run", payload)
        cmd = [sys.executable, "-m", "easel", "skill", full, "--input", content]
        if profile:
            cmd.extend(["--profile", profile])
        rc, stdout, stderr = _run(cmd, timeout=900)
        return _result(rc == 0, state="completed" if rc == 0 else "failed", skill=full,
                       profile=profile or None, exit_code=rc,
                       output=_redact_text(stdout), diagnostics=_redact_text(stderr))
    except subprocess.TimeoutExpired:
        return _result(False, state="unknown", skill=skill_name, error="技能执行超时，结果未知")
    except Exception as exc:
        return _result(False, state="failed", error=_safe_error(exc))


def _redact_text(value: str, limit: int = 12000) -> str:
    return _SECRET_RE.sub("[REDACTED]", str(value or ""))[:limit]


# --------------------------- read-only tools ---------------------------

def easel_status() -> str:
    """返回 Easel MCP 集成状态、版本路径和安全能力开关，不返回凭据。"""
    return _result(project=str(PROJECT_ROOT), outputs_exists=OUTPUTS.is_dir(),
                   mcp_server="easel", protocol="stdio", publish_enabled=PUBLISH_ENABLED,
                   write_confirmations=True, raw_shell=False, raw_credentials=False,
                   supported_platforms=list(DISPATCH_PLATFORMS))


def easel_list_personas() -> str:
    """列出 Easel 画像名称和简短身份描述。"""
    rows = []
    for d in sorted(PROFILES.iterdir()) if PROFILES.is_dir() else []:
        if not d.is_dir() or d.name.startswith("_"):
            continue
        identity = d / "identity.md"
        first = ""
        if identity.is_file():
            for line in identity.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("<!--"):
                    first = line[:120]
                    break
        rows.append({"name": d.name, "description": first})
    return _result(personas=rows, count=len(rows))


def easel_read_persona(name: str) -> str:
    """读取一个画像的非敏感 Markdown 配置文件。"""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name or ""):
        return _result(False, error="画像名称格式无效")
    d = (PROFILES / name).resolve()
    if PROFILES.resolve() not in d.parents or not d.is_dir():
        return _result(False, error="画像不存在")
    files = {}
    for p in sorted(d.glob("*.md")):
        files[p.name] = p.read_text(encoding="utf-8", errors="ignore")[:20000]
    return _result(persona=name, files=files)


def easel_list_skills(query: str = "") -> str:
    """列出 Easel 内置技能；可按名称过滤。"""
    q = (query or "").lower().strip()
    rows = []
    for p in sorted(BUILTIN_SKILLS.iterdir()) if BUILTIN_SKILLS.is_dir() else []:
        if not p.is_dir() or (q and q not in p.name.lower()):
            continue
        skill = p / "SKILL.md"
        desc = ""
        if skill.is_file():
            for line in skill.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip() and not line.startswith("#"):
                    desc = line.strip()[:180]
                    break
        rows.append({"name": p.name, "has_skill_md": skill.is_file(), "description": desc})
    return _result(skills=rows, count=len(rows))


def easel_read_skill(name: str) -> str:
    """读取一个 Easel 技能说明文件，不执行技能脚本。"""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", name or ""):
        return _result(False, error="技能名称格式无效")
    p = (BUILTIN_SKILLS / name / "SKILL.md").resolve()
    if BUILTIN_SKILLS.resolve() not in p.parents or not p.is_file():
        return _result(False, error="技能不存在")
    return _result(name=name, content=p.read_text(encoding="utf-8", errors="ignore")[:50000])


def easel_list_outputs(prefix: str = "", limit: int = 200) -> str:
    """列出内容库中的安全输出文件；系统目录和凭据样文件不返回。"""
    limit = max(1, min(int(limit or 200), 500))
    root = OUTPUTS.resolve()
    q = (prefix or "").strip().replace("\\", "/")
    rows = []
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        if not p.is_file() or root not in p.parents:
            continue
        rel = p.relative_to(root).as_posix()
        if any(part.startswith((".", "_")) for part in Path(rel).parts):
            continue
        if q and not rel.lower().startswith(q.lower()):
            continue
        if _public_file_name(p) == "[REDACTED]":
            continue
        rows.append({"path": rel, "name": p.name, "size": p.stat().st_size})
        if len(rows) >= limit:
            break
    return _result(files=rows, count=len(rows), truncated=len(rows) >= limit)


def easel_read_output(path: str, max_chars: int = 30000) -> str:
    """读取内容库中的文本产物；禁止读取系统目录、二进制和凭据文件。"""
    try:
        p = _safe_output(path)
    except ValueError as exc:
        return _result(False, error=str(exc))
    if _public_file_name(p) == "[REDACTED]":
        return _result(False, error="拒绝读取疑似凭据文件")
    if p.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html"}:
        return _result(False, error="仅允许读取文本产物")
    return _result(path=p.relative_to(OUTPUTS).as_posix(), content=p.read_text(encoding="utf-8", errors="replace")[:max(100, min(int(max_chars or 30000), 100000))])


def easel_list_accounts() -> str:
    """列出平台账号元数据和最近登录标记；不返回 cookie、密码或 token。"""
    rows = []
    for platform, cfg in ACCOUNT_CONFIG.items():
        s = _account_fast_status(platform, cfg)
        rows.append({"platform": platform, "name": cfg["name"], "backend": cfg["backend"],
                     "supported": cfg["backend"] != "unsupported", "logged_in": s["logged_in"], "state": s["state"]})
    return _result(accounts=rows, count=len(rows))


def easel_login_status(platform: str = "") -> str:
    """读取一个或全部平台的登录标记；这是快速状态，不冒充深度身份校验。"""
    if platform and platform not in ACCOUNT_CONFIG:
        return _result(False, error="未知平台")
    targets = [platform] if platform else list(ACCOUNT_CONFIG)
    rows = []
    for pf in targets:
        cfg = ACCOUNT_CONFIG[pf]
        s = _account_fast_status(pf, cfg)
        rows.append({"platform": pf, "name": cfg["name"], **s, "verification": "marker_or_file_presence_only"})
    return _result(accounts=rows)


def easel_check_account(platform: str, force: bool = False) -> str:
    """对一个平台做只读身份/登录检查；不会登录、改 profile 或发布。"""
    if platform not in ACCOUNT_CONFIG:
        return _result(False, error="未知平台")
    cfg = ACCOUNT_CONFIG[platform]
    if cfg["backend"] == "unsupported":
        return _result(False, platform=platform, state="unsupported", logged_in=False)
    py = sys.executable
    if cfg["backend"] == "biliup":
        cmd = [py, str(SCRIPTS / "bili_login.py"), "whoami", "--cookie", str(PROJECT_ROOT / "cookies.json")]
    elif cfg["backend"] == "xhs":
        cmd = [py, str(SCRIPTS / "xhs_publish.py"), "whoami", "--no-proxy"]
    elif cfg["backend"] == "douyin":
        cmd = [py, str(SCRIPTS / "douyin_publish.py"), "whoami", "--no-proxy"]
    elif cfg["backend"] == "wechat-oa":
        cmd = [py, str(SCRIPTS / "weixin_mp_stats.py"), "whoami", "--no-proxy"]
    else:
        cmd = [py, str(SCRIPTS / "web_publisher.py"), "whoami", "--platform", cfg["wp"]]
    try:
        rc, out, err = _run(cmd, timeout=90)
        data = _last_json(out)
        if isinstance(data, dict):
            data.pop("cookies", None)
            data.pop("token", None)
            return _result(platform=platform, return_code=rc, **data)
        return _result(False, platform=platform, return_code=rc, state="unknown", error=_safe_error(err or out)[-500:])
    except Exception as exc:
        return _result(False, platform=platform, state="unknown", error=_safe_error(exc))


def easel_fetch_analytics(platform: str) -> str:
    """读取一个平台的创作数据；只读，会更新 Easel 的分析快照。"""
    cfg = ACCOUNT_CONFIG.get(platform)
    if not cfg or not cfg.get("analytics"):
        return _result(False, error="该平台暂不支持分析")
    py = sys.executable
    if platform == "bilibili":
        cmd = [py, str(SCRIPTS / "bili_login.py"), "stats", "--cookie", str(PROJECT_ROOT / "cookies.json")]
    elif platform == "wechat-oa":
        proxy = os.environ.get("EASEL_PROXY") or os.environ.get("https_proxy") or ""
        cmd = [py, str(SCRIPTS / "weixin_mp_stats.py"), "stats", "--proxy", proxy, "--count", "20"]
    else:
        cmd = [py, str(SCRIPTS / "account_stats.py"), "fetch", "--platform", platform]
    try:
        rc, out, err = _run(cmd, timeout=180)
        data = _last_json(out)
        if not isinstance(data, dict):
            return _result(False, platform=platform, return_code=rc, error=_safe_error(err or out)[-500:])
        return _result(rc == 0 and not data.get("error"), platform=platform, return_code=rc, data=data,
                       error=_safe_error(data.get("error", "")) if data.get("error") else "")
    except Exception as exc:
        return _result(False, platform=platform, error=_safe_error(exc))


def easel_get_publish_policy() -> str:
    """返回发布模式和 MCP 高风险闸状态。"""
    mode = os.environ.get("EASEL_PUBLISH_MODE", "automated").strip().lower() or "automated"
    return _result(mode=mode if mode in {"automated", "manual"} else "manual",
                   mcp_publish_enabled=PUBLISH_ENABLED,
                   confirmation_required=True, result_verification="publisher_exit_code_only")


def easel_plan_publish(platforms: list[str], title: str = "", body: str = "", tags: list[str] | None = None, media_type: str = "") -> str:
    """生成跨平台发布计划并做标题/正文/标签/媒体类型约束检查；不接触平台。"""
    if not isinstance(platforms, list) or not platforms:
        return _result(False, error="platforms 不能为空")
    content = {"title": title or "", "body": body or "", "tags": tags or [], "media_type": media_type or ""}
    if _check_platform is None:
        return _result(False, error="Easel 发布派发模块不可用")
    plan = [_check_platform(p, content) for p in platforms]
    return _result(content_title=content["title"], target_count=len(plan), dispatch=plan,
                   hint="计划不等于发布；发布前必须人工审核并取得一次性确认")


def easel_request_manual_export(platform: str, title: str, body: str, tags: str = "", media: list[str] | None = None) -> str:
    """请求导出人工发布包；不会上传或发布。返回待确认凭证。"""
    payload = {"platform": platform, "title": title or "", "body": body or "", "tags": tags or "", "media": media or []}
    if platform not in MANUAL_PLATFORMS:
        return _result(False, error="未知平台")
    try:
        for rel in payload["media"]:
            _safe_media(rel)
    except ValueError as exc:
        return _result(False, error=str(exc))
    return _result(**_issue_confirmation("manual_export", payload), operation="manual_export",
                   note="下一步必须由用户确认后调用 easel_export_manual_package")


def easel_export_manual_package(platform: str, title: str, body: str, tags: str = "", media: list[str] | None = None, confirmation_id: str = "") -> str:
    """在确认后导出人工发布包；导出不等于上传或发布。"""
    payload = {"platform": platform, "title": title or "", "body": body or "", "tags": tags or "", "media": media or []}
    try:
        _consume_confirmation(confirmation_id, "manual_export", payload)
        package = build_package(OUTPUTS, platform, title or "", body or "", tags or "", media or [], True)
        return _result(path=package.relative_to(OUTPUTS.resolve()).as_posix(), filename=package.name, published=False,
                       status="ready_for_manual_submission")
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_request_publish_confirmation(platform: str, title: str, body: str, media: list[str] | None = None, tags: str = "") -> str:
    """创建真实发布的一次性确认请求；不会启动发布。"""
    payload = {"platform": platform, "title": title or "", "body": body or "", "media": media or [], "tags": tags or ""}
    if platform not in ACCOUNT_CONFIG or ACCOUNT_CONFIG[platform]["backend"] == "unsupported":
        return _result(False, error="该平台不支持真实发布")
    try:
        for rel in payload["media"]:
            _safe_media(rel)
    except ValueError as exc:
        return _result(False, error=str(exc))
    return _result(**_issue_confirmation("publish", payload), operation="publish",
                   safety="需要 Gary 明确确认；此调用尚未发布")


def _publish_command(platform: str, title: str, body: str, tags: str, media: list[str]) -> list[str]:
    files = [_safe_media(x) for x in media]
    vids = [str(p) for p in files if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".flv", ".ts"}]
    imgs = [str(p) for p in files if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}]
    if platform in {"bilibili", "douyin", "weixin-channels"} and not vids:
        raise ValueError("该平台需要视频素材")
    if platform in {"xiaohongshu", "kuaishou"} and not (vids or imgs):
        raise ValueError("该平台需要图片或视频素材")
    title = (title or body[:20]).strip()
    py = sys.executable
    cfg = ACCOUNT_CONFIG[platform]
    if platform == "bilibili":
        tag = tags.replace("#", "").replace("，", ",").strip().strip(",") or "日常"
        cmd = ["biliup", "-u", str(PROJECT_ROOT / "cookies.json"), "upload", vids[0], "--title", title[:80], "--tid", "36", "--copyright", "1", "--tag", tag]
        if body.strip():
            cmd += ["--desc", body[:2000]]
        return cmd
    if platform == "xiaohongshu":
        base = [py, str(SCRIPTS / "xhs_publish.py")]
        cmd = base + (["publish-video", "--no-proxy", "--video", vids[0]] if vids else ["publish", "--no-proxy", "--images", ",".join(imgs)])
        return cmd + ["--title", title, "--content", body, "--tags", tags, "--exec"]
    if platform == "douyin":
        base = [py, str(SCRIPTS / "douyin_publish.py")]
        cmd = base + (["publish-video", "--no-proxy", "--video", vids[0]] if vids else ["publish", "--no-proxy", "--images", ",".join(imgs)])
        return cmd + ["--title", title, "--content", body, "--tags", tags, "--exec"]
    if platform == "wechat-oa":
        raise ValueError("公众号真实发布需要后台会话和 HTML 转换，当前 MCP 默认只提供人工导出；请使用 Easel Web 复核")
    return [py, str(SCRIPTS / "web_publisher.py"), "publish", "--platform", cfg["wp"], "--title", title, "--desc", body, "--tags", tags, "--exec", "--media", vids[0] if vids else imgs[0]]


def easel_publish(platform: str, title: str, body: str, media: list[str] | None = None, tags: str = "", confirmation_id: str = "") -> str:
    """执行一次真实发布；默认禁用，必须显式启用 MCP 发布闸并提供未使用确认凭证。"""
    payload = {"platform": platform, "title": title or "", "body": body or "", "media": media or [], "tags": tags or ""}
    try:
        if not PUBLISH_ENABLED:
            raise PermissionError("MCP 真实发布闸未开启；当前仅可做计划、人工导出和状态查询")
        _consume_confirmation(confirmation_id, "publish", payload)
        cmd = _publish_command(platform, title or "", body or "", tags or "", media or [])
        rc, out, err = _run(cmd, timeout=900, env={"EASEL_CALENDAR_AUTORECORD": "0"})
        detail = _safe_error((err or out).strip()[-2000:])
        # rc != 0 is never rewritten to success. Platform readback remains a separate unknown state.
        return _result(rc == 0, platform=platform, state="submitted" if rc == 0 else "failed",
                       verified=False, verification="unknown_requires_platform_readback", return_code=rc, detail=detail)
    except Exception as exc:
        return _result(False, platform=platform, state="blocked", error=_safe_error(exc))


def easel_publish_status(platform: str = "") -> str:
    """读取 Easel 异步发布状态文件；不把启动或未知状态当作成功。"""
    targets = [platform] if platform else list(ACCOUNT_CONFIG)
    rows = []
    for pf in targets:
        if pf not in ACCOUNT_CONFIG:
            continue
        p = PUBLISH_DIR / f"{pf}.json"
        d = _read_json(p, {"state": "unknown", "message": ""})
        rows.append({"platform": pf, "state": d.get("state", "unknown"), "message": _safe_error(d.get("message", ""))})
    return _result(statuses=rows)


# --------------------------- controlled state tools ---------------------------

def easel_request_write_confirmation(operation: str, payload: dict[str, Any] | None = None) -> str:
    """为排期/选题等非发布写操作创建一次性确认凭证；不会写业务数据。"""
    if operation not in {"schedule_create", "schedule_update", "schedule_delete", "idea_create", "idea_update", "idea_delete"}:
        return _result(False, error="不允许的写操作类型")
    return _result(**_issue_confirmation("write:" + operation, payload or {}), operation=operation,
                   note="必须先得到用户确认，再调用对应写工具")


def _write_payload(operation: str, payload: dict[str, Any], token: str) -> None:
    _consume_confirmation(token, "write:" + operation, payload)


def easel_list_schedule() -> str:
    """读取 Easel 排期。"""
    items = _load_list(SCHEDULE_FILE)
    return _result(items=items, count=len(items))


def easel_schedule_context(days: int = 14) -> str:
    """读取排期节奏和近期节点摘要。"""
    cmd = [sys.executable, str(SCRIPTS / "calendar_ops.py"), "--data", str(SCHEDULE_FILE), "context", "--days", str(max(1, min(int(days or 14), 90)))]
    try:
        rc, out, err = _run(cmd, timeout=30)
        data = _last_json(out)
        return _result(rc == 0, data=data or {}, error=_safe_error(err[-500:]) if rc else "")
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_create_schedule(title: str, date: str, platform: str = "", time_text: str = "", status: str = "idea", note: str = "", confirmation_id: str = "") -> str:
    """在确认后创建排期项。"""
    payload = {"title": title, "date": date, "platform": platform, "time": time_text, "status": status, "note": note}
    try:
        _write_payload("schedule_create", payload, confirmation_id)
        items = _load_list(SCHEDULE_FILE)
        item = {"id": uuid.uuid4().hex[:12], **payload, "kind": "content", "source": "mcp"}
        items.append(item)
        _atomic_json(SCHEDULE_FILE, items)
        return _result(item=item)
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_update_schedule(schedule_id: str, title: str, date: str, platform: str = "", time_text: str = "", status: str = "idea", note: str = "", confirmation_id: str = "") -> str:
    """在确认后更新排期项。"""
    payload = {"id": schedule_id, "title": title, "date": date, "platform": platform, "time": time_text, "status": status, "note": note}
    try:
        _write_payload("schedule_update", payload, confirmation_id)
        items = _load_list(SCHEDULE_FILE)
        for item in items:
            if item.get("id") == schedule_id:
                item.update({k: v for k, v in payload.items() if k != "id"})
                _atomic_json(SCHEDULE_FILE, items)
                return _result(item=item)
        return _result(False, error="排期不存在")
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_delete_schedule(schedule_id: str, confirmation_id: str = "") -> str:
    """在确认后删除排期项。"""
    payload = {"id": schedule_id}
    try:
        _write_payload("schedule_delete", payload, confirmation_id)
        items = _load_list(SCHEDULE_FILE)
        new = [x for x in items if x.get("id") != schedule_id]
        if len(new) == len(items):
            return _result(False, error="排期不存在")
        _atomic_json(SCHEDULE_FILE, new)
        return _result(deleted=schedule_id)
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_list_ideas() -> str:
    """读取选题池。"""
    items = _load_list(IDEAS_FILE)
    return _result(items=items, count=len(items))


def easel_create_idea(title: str, note: str = "", source: str = "", status: str = "pending", confirmation_id: str = "") -> str:
    """在确认后创建选题。"""
    payload = {"title": title, "note": note, "source": source, "status": status}
    try:
        _write_payload("idea_create", payload, confirmation_id)
        items = _load_list(IDEAS_FILE)
        item = {"id": uuid.uuid4().hex[:12], **payload, "created": int(time.time())}
        items.insert(0, item)
        _atomic_json(IDEAS_FILE, items)
        return _result(item=item)
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_update_idea(idea_id: str, title: str, note: str = "", source: str = "", status: str = "pending", confirmation_id: str = "") -> str:
    """在确认后更新选题。"""
    payload = {"id": idea_id, "title": title, "note": note, "source": source, "status": status}
    try:
        _write_payload("idea_update", payload, confirmation_id)
        items = _load_list(IDEAS_FILE)
        for item in items:
            if item.get("id") == idea_id:
                item.update({k: v for k, v in payload.items() if k != "id"})
                _atomic_json(IDEAS_FILE, items)
                return _result(item=item)
        return _result(False, error="选题不存在")
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def easel_delete_idea(idea_id: str, confirmation_id: str = "") -> str:
    """在确认后删除选题。"""
    payload = {"id": idea_id}
    try:
        _write_payload("idea_delete", payload, confirmation_id)
        items = _load_list(IDEAS_FILE)
        new = [x for x in items if x.get("id") != idea_id]
        if len(new) == len(items):
            return _result(False, error="选题不存在")
        _atomic_json(IDEAS_FILE, new)
        return _result(deleted=idea_id)
    except Exception as exc:
        return _result(False, error=_safe_error(exc))


def _schema_for_callable(fn: Any) -> dict[str, Any]:
    """Build the small JSON-schema subset needed by the MCP 1.x low-level API."""
    import inspect
    from typing import get_args, get_origin, get_type_hints
    import types
    hints = get_type_hints(fn)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        if name == "self":
            continue
        ann = hints.get(name, str)
        origin = get_origin(ann)
        args = get_args(ann)
        if origin in (types.UnionType, __import__("typing").Union):
            non_none = [x for x in args if x is not type(None)]
            ann = non_none[0] if non_none else str
            origin = get_origin(ann)
            args = get_args(ann)
        if origin in (list, tuple):
            item = args[0] if args else str
            item_type = "string" if item is str else "integer" if item is int else "number" if item is float else "boolean" if item is bool else "object"
            spec: dict[str, Any] = {"type": "array", "items": {"type": item_type}}
        elif origin is dict:
            spec = {"type": "object"}
        elif ann is bool:
            spec = {"type": "boolean"}
        elif ann is int:
            spec = {"type": "integer"}
        elif ann is float:
            spec = {"type": "number"}
        else:
            spec = {"type": "string"}
        props[name] = spec
        if param.default is inspect.Parameter.empty:
            required.append(name)
    result: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        result["required"] = required
    return result


def _build_server() -> Any:
    """Use Hermes' MCPServer when available, otherwise the MCP 1.x low-level Server."""
    instructions = (
        "Easel native MCP data plane. Use read-only tools for personas, skills, outputs, "
        "account status, analytics, publishing plans, schedules and ideas. Write tools "
        "require a one-time confirmation. Real publishing is disabled unless the host "
        "explicitly enables EASEL_MCP_ALLOW_PUBLISH=1 and supplies a confirmation id. "
        "Never request or expose cookies, passwords, tokens or raw shell execution. "
        "Unknown publication state must remain unknown. Skill execution is available through "
        "easel_run_skill; high-risk skills require easel_request_skill_confirmation."
    )
    tools = [
        easel_status, easel_list_personas, easel_read_persona, easel_list_skills, easel_read_skill,
        easel_skill_policy, easel_request_skill_confirmation, easel_run_skill,
        easel_list_outputs, easel_read_output, easel_list_accounts, easel_login_status, easel_check_account,
        easel_fetch_analytics, easel_get_publish_policy, easel_plan_publish, easel_request_manual_export,
        easel_export_manual_package, easel_request_publish_confirmation, easel_publish, easel_publish_status,
        easel_request_write_confirmation, easel_list_schedule, easel_schedule_context, easel_create_schedule,
        easel_update_schedule, easel_delete_schedule, easel_list_ideas, easel_create_idea,
        easel_update_idea, easel_delete_idea,
    ]
    try:
        from mcp.server import MCPServer
    except ImportError:
        from mcp.server import Server
        from mcp.types import CallToolRequest, TextContent, Tool
        import asyncio
        import inspect
        server = Server("easel", instructions=instructions)
        definitions = [Tool(name=fn.__name__, description=(fn.__doc__ or "").strip(),
                             inputSchema=_schema_for_callable(fn)) for fn in tools]
        by_name = {fn.__name__: fn for fn in tools}

        @server.list_tools()
        async def _list_tools() -> list[Tool]:
            return definitions

        @server.call_tool()
        async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            fn = by_name.get(name)
            if fn is None:
                return [TextContent(type="text", text=_result(False, error="未知工具"))]
            try:
                value = await asyncio.to_thread(fn, **(arguments or {}))
                return [TextContent(type="text", text=str(value))]
            except Exception as exc:
                return [TextContent(type="text", text=_result(False, error=_safe_error(exc)))]
        log.info("registered %d Easel MCP tools (low-level SDK)", len(tools))
        return server
    else:
        server = MCPServer("easel", instructions=instructions)
        for fn in tools:
            server.add_tool(fn, name=fn.__name__, description=(fn.__doc__ or "").strip())
        log.info("registered %d Easel MCP tools", len(tools))
        return server


def main() -> int:
    os.environ.setdefault("EASEL_MCP_SERVER", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        server = _build_server()
        # MCP 1.x exposes the low-level async Server; Hermes' newer MCPServer
        # retains a synchronous ``run('stdio')`` convenience method.
        if hasattr(server, "create_initialization_options"):
            import asyncio
            from mcp.server.stdio import stdio_server

            async def _serve_lowlevel() -> None:
                async with stdio_server() as (read_stream, write_stream):
                    await server.run(read_stream, write_stream, server.create_initialization_options())

            asyncio.run(_serve_lowlevel())
        else:
            server.run("stdio")
    except KeyboardInterrupt:
        return 0
    except Exception:
        log.exception("Easel MCP server stopped")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
