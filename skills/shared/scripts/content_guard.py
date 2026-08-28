#!/usr/bin/env python3
"""content_guard.py — 出站内容安全闸门（确定性扫描）.

Easel 的 agent 会把生成的文案 / 评论 / 回答**真实发布到公开平台**。从 agent
生成文本到 `--exec` 真发之间，过去没有任何安全过滤：一旦 agent 把内部设置误写进
内容（API key、内部 URL、代理 IP、绝对路径、模型名、env 变量名、"由 AI 生成 /
OpenClaw / Claude Code" 之类自曝措辞），就会**公开泄露且删不掉**。

本模块作为唯一真相源，扫描任意「要发到公开平台的文本」，检出疑似内部设置泄露。
发布脚本在真发前调用 `guard_or_die(...)`。**分两级强制**（见 BLOCK_CATEGORIES）：
- BLOCK 级 = 真·敏感信息（密钥 / 内部域名 / 代理 IP / 内部路径 / env 名 / .env 真值），
  几乎无正当理由出现在对外内容里 → **fail-closed 阻止发布（退出码 7）**，让 agent 改稿重发。
- WARN 级 = AI 措辞（由 AI 生成 / OpenClaw / Claude / Anthropic / system prompt / 大模型）与
  模型名（claude-* / gpt-image-2 / happyhorse）→ 这些在论文解读、AI 科普、技术文章里
  **可能是正常内容，硬拦会误伤** → **只告警、绝不拦截**，交给 agent/用户判断。

设计原则（同仓库其它确定性脚本）：纯 stdlib、可移植、带 selftest；不联网、不改文件
（redact 只在显式子命令里输出脱敏文本，不动原文）。

子命令:
  scan   --text "..." | --file PATH        # 有 BLOCK 级命中退出 7；仅 WARN 级退出 0（打印提醒）
  redact --file PATH [--out PATH]          # 输出脱敏文本（命中片段→[已隐藏]）
  selftest                                 # 正例必抓 / 反例必放行 / 分级强制正确

作为库:
  from content_guard import scan, redact, guard_or_die
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 阻止发布的退出码（区别于一般错误 1；发布脚本据此判定"被安全闸门拦下"）。
EXIT_LEAK = 7


# ── 敏感模式表 ───────────────────────────────────────────────────────────────
# (分类, 严重度, 编译后正则, 一句话说明)。severity: high=凭证/真值级，med=内部拓扑，
# low=AI 自曝措辞。**分级见 BLOCK_CATEGORIES**：只有 BLOCK 类（密钥/内部拓扑）真发 fail-closed；
# ai-disclosure/model-name 属 WARN，只告警不拦（论文/科普里可能是正常内容）。severity 仅用于报告排序。
def _p(pat: str, flags: int = 0) -> "re.Pattern[str]":
    return re.compile(pat, flags)


SECRET_PATTERNS: list[tuple[str, str, "re.Pattern[str]", str]] = [
    # ── 凭证 / 密钥 ──
    ("api-key", "high", _p(r"\bsk-[A-Za-z0-9_\-]{16,}\b"), "疑似 API key（sk- 开头）"),
    ("api-key", "high", _p(r"(?i)\b(?:api[_-]?key|auth[_-]?token|access[_-]?key|"
                           r"secret[_-]?key|app[_-]?secret|secret)\b\s*[:=]\s*['\"]?[A-Za-z0-9/_\-\.]{8,}"),
     "键值形式的密钥/令牌"),
    ("api-key", "high", _p(r"(?i)\bBearer\s+[A-Za-z0-9/_\-\.]{12,}"), "Bearer 令牌"),
    # ── 内部域名 / 服务地址 ──
    ("internal-host", "med", _p(r"\bmaas\.devops\.(?:xiaohongshu|rednote)\.(?:com|life)\b"),
     "内部 MaaS 域名"),
    ("internal-host", "med", _p(r"\bwebide-gateway\.devops\.xiaohongshu\.com\b"), "内部 WebIDE 域名"),
    ("internal-host", "med", _p(r"\b[a-z0-9\-]+\.devops\.(?:xiaohongshu|rednote)\.(?:com|life)\b"),
     "内部 devops 域名"),
    ("internal-host", "low", _p(r"\bcodewiz\b", re.I), "内部代理标识"),
    ("internal-host", "med", _p(r"\bapi-version=[0-9]"), "API 版本查询串（内部接口特征）"),
    # ── 代理 / 私网 IP ──
    # 10.x.x.x（需 3 段）/ 192.168.x.x / 172.16-31.x.x（需 2 段），带可选 :port。
    ("proxy-ip", "med", _p(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))"
                           r"(?:\.\d{1,3}){2,3}(?::\d+)?\b"), "私网/代理 IP"),
    ("proxy-ip", "med", _p(r":3128\b"), "代理端口 3128（独立出现）"),
    # ── 内部绝对路径 ──
    ("internal-path", "med", _p(r"/mnt/tidal-alsh01\S*"), "内部数据盘路径"),
    ("internal-path", "med", _p(r"(?:~|/root)?/\.openclaw\S*"), "OpenClaw 内部路径"),
    ("internal-path", "med", _p(r"(?:~|/root)?/\.easel-browser-profiles\S*"), "登录态 profile 路径"),
    ("internal-path", "low", _p(r"/root/\.cc-mirror\S*"), "内部镜像路径"),
    # ── env 变量名 ──
    ("env-name", "med", _p(r"\bANTHROPIC_[A-Z_]+\b"), "Anthropic env 变量名"),
    ("env-name", "med", _p(r"\b(?:IMG_API_KEY[A-Z_]*|IMG_BASE_URL|DASHSCOPE_API_KEY|"
                           r"XHS_MAAS_API_KEY|MINERU_API_TOKEN|ARK_API_KEY|KLING_ACCESS_KEY|"
                           r"VIDEO_API_KEY|MUSIC_API_KEY|FISH_API_KEY|MINIMAX_API_KEY|"
                           r"EASEL_PROXY|EASEL_ROOT)\b"), "Easel env 变量名"),
    # ── 模型 / 供应商内部名 ──
    ("model-name", "low", _p(r"\bclaude-[a-z0-9][a-z0-9.\-\[\]]*\b", re.I), "Claude 模型 ID"),
    ("model-name", "low", _p(r"\banthropic/claude\S*", re.I), "anthropic/claude 模型引用"),
    ("model-name", "low", _p(r"\bgpt-image-2\b", re.I), "内部生图模型名"),
    ("model-name", "low", _p(r"\bhappyhorse\b", re.I), "内部生视频模型名"),
    # ── AI 自曝措辞（发出去会暴露"这是 AI/内部工具做的"）──
    ("ai-disclosure", "low", _p(r"由\s*AI\s*(?:生成|创作|撰写|制作|完成)"), "「由 AI 生成」类措辞"),
    ("ai-disclosure", "low", _p(r"\bOpenClaw\b", re.I), "内部编排框架名"),
    ("ai-disclosure", "low", _p(r"Claude\s*Code", re.I), "内部制作引擎名"),
    ("ai-disclosure", "low", _p(r"\bAnthropic\b", re.I), "模型厂商名"),
    ("ai-disclosure", "low", _p(r"降级生成"), "内部降级措辞"),
    ("ai-disclosure", "low", _p(r"(?i)(?:append-)?system[\s\-]?prompt"), "系统提示词字样"),
    ("ai-disclosure", "low", _p(r"(?:我(?:们)?是|作为|身为|本|自称)(?:一[个只])?(?:大语言模型|大模型)"
                                r"|(?:大语言模型|大模型)(?:生成|创作|撰写|制作)"), "自曝为大模型（自指语境）"),
]

# ── 强制分级 ─────────────────────────────────────────────────────────────────
# BLOCK：真·敏感信息（密钥/内部拓扑），**几乎没有正当理由**出现在对外内容里 → 真发时
#        fail-closed 拦截（退出码 7）。
# 其余分类（ai-disclosure / model-name）= WARN：这些词（Claude、大模型、system prompt、
#   "由 AI 生成"…）在论文解读、AI 科普、技术文章里**可能是正常内容**，硬拦会误伤 →
#   只告警、不阻断发布，交给 agent/用户判断。
BLOCK_CATEGORIES = {
    "api-key", "env-value", "internal-host", "proxy-ip", "internal-path", "env-name",
}

# .env 里哪些键的**值**算敏感、要作为字面量精确扫描（避免把普通配置值也当秘密）。
_SENSITIVE_ENV_NAME = re.compile(
    r"(?:API_KEY|AUTH_TOKEN|_TOKEN|SECRET|ACCESS_KEY|BASE_URL|AUTH)", re.I)


@dataclass
class Finding:
    category: str
    severity: str
    hint: str
    snippet: str      # 脱敏后的命中上下文（不回显完整秘密）
    span: tuple[int, int]


def _mask(value: str) -> str:
    """把命中值本身打码：保留首尾少量字符，中间 ***，避免报告里再次泄露完整秘密。"""
    v = value.strip()
    if len(v) <= 8:
        return v[0] + "***" if v else "***"
    return f"{v[:4]}***{v[-2:]}"


def _snippet(text: str, start: int, end: int, ctx: int = 12) -> str:
    """取命中前后文，命中片段本体打码。"""
    lo = max(0, start - ctx)
    hi = min(len(text), end + ctx)
    before = text[lo:start].replace("\n", " ")
    after = text[end:hi].replace("\n", " ")
    hit = _mask(text[start:end])
    pre = "…" if lo > 0 else ""
    suf = "…" if hi < len(text) else ""
    return f"{pre}{before}【{hit}】{after}{suf}"


def load_env_literals(root: str | Path | None = None) -> set[str]:
    """读项目 .env，把敏感键的**字面值**收进扫描集——精确命中泄露的真值，与格式无关。

    root 缺省依次探测：EASEL_ROOT env → 从本文件向上找含 .env 的目录。
    找不到 .env 返回空集（selftest 不依赖 .env）。
    """
    candidates: list[Path] = []
    if root:
        candidates.append(Path(root))
    env_root = os.environ.get("EASEL_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    # 从脚本位置向上找（skills/shared/scripts → 项目根在 parents[2]）
    here = Path(__file__).resolve()
    candidates.extend([here.parents[2] if len(here.parents) > 2 else here.parent, Path.cwd()])

    literals: set[str] = set()
    seen: set[Path] = set()
    for base in candidates:
        env_path = base / ".env"
        try:
            rp = env_path.resolve()
        except OSError:
            continue
        if rp in seen or not env_path.is_file():
            continue
        seen.add(rp)
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"').strip("'")
            if len(value) >= 6 and _SENSITIVE_ENV_NAME.search(name):
                literals.add(value)
    return literals


def scan(text: str, extra_literals: set[str] | None = None) -> list[Finding]:
    """扫描出站文本，返回所有命中。正则 + .env 字面值双路。"""
    if not text:
        return []
    findings: list[Finding] = []

    # 1) .env 真值精确匹配（最高危：泄露的是真 key/URL）
    literals = set(extra_literals) if extra_literals else set()
    literals |= load_env_literals()
    for lit in literals:
        idx = text.find(lit)
        while idx != -1:
            findings.append(Finding("env-value", "high", ".env 里的真实敏感值",
                                    _snippet(text, idx, idx + len(lit)),
                                    (idx, idx + len(lit))))
            idx = text.find(lit, idx + len(lit))

    # 2) 正则模式
    for category, severity, pat, hint in SECRET_PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span()
            if e == s:
                continue
            findings.append(Finding(category, severity, hint, _snippet(text, s, e), (s, e)))

    # 按位置排序，去掉完全重叠的重复命中（同一片段被多规则命中只留一条）
    findings.sort(key=lambda f: (f.span[0], -(f.span[1] - f.span[0])))
    deduped: list[Finding] = []
    for f in findings:
        if any(f.span[0] >= d.span[0] and f.span[1] <= d.span[1] for d in deduped):
            continue
        deduped.append(f)
    return deduped


def redact(text: str, extra_literals: set[str] | None = None) -> tuple[str, list[Finding]]:
    """把命中片段替换成 [已隐藏]，返回 (脱敏文本, 命中列表)。从后往前替换以保持 span 有效。"""
    findings = scan(text, extra_literals)
    out = text
    for f in sorted(findings, key=lambda x: x.span[0], reverse=True):
        s, e = f.span
        out = out[:s] + "[已隐藏]" + out[e:]
    return out, findings


def _print_findings(findings: list[Finding], stream=None) -> None:
    stream = stream if stream is not None else sys.stderr  # 晚绑定，配合 redirect_stderr
    order = {"high": 0, "med": 1, "low": 2}
    for f in sorted(findings, key=lambda x: order.get(x.severity, 3)):
        print(f"  · [{f.severity}] {f.category}｜{f.hint}：{f.snippet}", file=stream)


def guard_or_die(parts, *, exec_mode: bool, allow_unsafe: bool = False,
                 label: str = "发布内容", extra_literals: set[str] | None = None) -> None:
    """发布脚本在真发前调用的便捷闸门。

    parts: 出站文本片段（title/content/tags/comment…），None/空自动跳过。
    分级（见 BLOCK_CATEGORIES）：
    - BLOCK 级（真·密钥/内部拓扑）+ exec_mode + 非 allow_unsafe → 打印并 sys.exit(EXIT_LEAK)。
    - WARN 级（AI 措辞/模型名，论文/科普里可能是正常内容）→ **永不拦截**，只 ⚠️ 提醒。
    - dry-run 或 allow_unsafe：全部只告警、不拦。
    - 无命中：静默返回。
    """
    if isinstance(parts, str):
        parts = [parts]
    text = "\n".join(str(p) for p in parts if p)
    findings = scan(text, extra_literals)
    if not findings:
        return
    block = [f for f in findings if f.category in BLOCK_CATEGORIES]
    warn = [f for f in findings if f.category not in BLOCK_CATEGORIES]

    if exec_mode and not allow_unsafe and block:
        print(f"❌ {label}检测到疑似敏感信息泄露（密钥/内部地址等），已阻止本次发布（{len(block)} 处）：",
              file=sys.stderr)
        _print_findings(block)
        if warn:
            print(f"（另有 {len(warn)} 处 AI 措辞/模型名仅提醒、未计入拦截，请自行判断是否合适：）",
                  file=sys.stderr)
            _print_findings(warn)
        print("→ 请从内容中删除上述敏感信息后重发；确需放行可加 --allow-unsafe（谨慎）。",
              file=sys.stderr)
        sys.exit(EXIT_LEAK)

    # 到这：dry-run / allow_unsafe / 只有 WARN 级 → 只提醒不拦
    if allow_unsafe:
        tag = "allow-unsafe 放行"
    elif not exec_mode:
        tag = "dry-run 预演"
    else:
        tag = "仅提醒项，未拦截"
    print(f"⚠️ {label}检测到需留意的内容（{len(findings)} 处，{tag}）：", file=sys.stderr)
    if block:
        print("  【敏感·建议删除】", file=sys.stderr)
        _print_findings(block)
    if warn:
        print("  【AI 措辞/模型名·请判断是否合适（正常科普/论文里可能没问题）】", file=sys.stderr)
        _print_findings(warn)


# ── CLI ──────────────────────────────────────────────────────────────────────
def _read_input(a) -> str:
    if getattr(a, "text", None) is not None:
        return a.text
    if getattr(a, "file", None):
        return Path(a.file).read_text(encoding="utf-8", errors="ignore")
    return sys.stdin.read()


def cmd_scan(a) -> int:
    findings = scan(_read_input(a))
    if not findings:
        print("✅ 未检出敏感信息。")
        return 0
    block = [f for f in findings if f.category in BLOCK_CATEGORIES]
    warn = [f for f in findings if f.category not in BLOCK_CATEGORIES]
    if block:
        print(f"❌ 检出 {len(block)} 处敏感信息（密钥/内部地址等，发布会被拦截）：", file=sys.stderr)
        _print_findings(block)
    if warn:
        print(f"⚠️ 另有 {len(warn)} 处 AI 措辞/模型名（仅提醒，不拦截；论文/科普里可能正常）：",
              file=sys.stderr)
        _print_findings(warn)
    return EXIT_LEAK if block else 0


def cmd_redact(a) -> int:
    clean, findings = redact(_read_input(a))
    if getattr(a, "out", None):
        Path(a.out).write_text(clean, encoding="utf-8")
        print(f"已写脱敏文本 → {a.out}（脱敏 {len(findings)} 处）", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    return 0


def cmd_selftest(_a) -> int:
    import contextlib
    import io

    # BLOCK 级正例：应命中且至少一条属于 BLOCK 分类（真发会被拦）。
    block_positives = [
        ("api-key sk", "我的 key 是 sk-ABCDefgh12345678ijkl 记得保密"),
        ("kv secret", "配置 api_key=abcd1234efgh5678"),
        ("bearer", "Authorization: Bearer abcdef1234567890xyz"),
        ("maas host", "调用 https://maas.devops.xiaohongshu.com/openai 出图"),
        ("webide", "打开 webide-gateway.devops.xiaohongshu.com/xxx"),
        ("proxy ip", "代理设成 10.140.24.177:3128 就行"),
        ("port 3128", "端口 :3128 是代理"),
        ("path mnt", "产物在 /mnt/tidal-alsh01/dataset/xxx"),
        ("path profile", "登录态在 ~/.easel-browser-profiles/XhsProfile"),
        ("env name", "把 XHS_MAAS_API_KEY 填到 .env"),
        ("env anthropic", "设 ANTHROPIC_AUTH_TOKEN 就能用"),
        ("api-version", "接口带 api-version=2024-05 参数"),
    ]
    # WARN 级正例：应命中，但**全部**是 WARN 分类（AI 措辞/模型名）→ 真发不拦。
    # 关键：论文解读 / AI 科普 / 技术文章里这些词是正常内容，硬拦会误伤。
    warn_positives = [
        ("model claude", "用的是 claude-4.8-opus 模型"),
        ("model happyhorse", "视频走 happyhorse i2v"),
        ("ai disclosure", "本文由 AI 生成，仅供参考"),
        ("openclaw", "这是 OpenClaw 帮我做的"),
        ("claude code", "让 Claude Code 处理一下"),
        # 真实场景：一篇讲 LLM 的科普/论文解读，含 AI 词但绝不该被拦
        ("paper explainer", "这期解读这篇大模型论文，对比了 Claude 和 GPT 的推理能力，"
                            "还聊了 system prompt 怎么影响输出。"),
        # 自指语境的「大模型」仍应命中（自曝为 AI）
        ("self disclosure llm", "作为一个大模型，我来帮你分析一下这个问题。"),
    ]
    # 反例：正常文案，scan 应完全无命中（连 WARN 都不该有）。
    negatives = [
        "今天分享 3 个提效小技巧，记得点赞收藏～",
        "这家咖啡店的手冲真的绝，氛围也好，强烈安利给周末想放松的姐妹",
        "新品上线啦！前 100 名下单送小样，评论区抽 3 位送正装",
        "秋天第一杯奶茶，配上这条围巾，温柔到犯规🧣",
        "客服热线 400-820-8820，官网 www.example.com 了解更多",
        "Transformer 是所有大模型的共同底座，值得每个开发者了解。",
    ]
    failed = 0

    def _guard_exits(text) -> bool:
        """exec 模式下 guard_or_die 是否触发拦截（SystemExit）。静默其输出。"""
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                guard_or_die([text], exec_mode=True, allow_unsafe=False)
            return False
        except SystemExit:
            return True

    for name, txt in block_positives:
        hits = scan(txt)
        if not any(h.category in BLOCK_CATEGORIES for h in hits):
            print(f"  ✗ BLOCK 正例未命中 block 分类: {name} :: {txt}", file=sys.stderr)
            failed += 1
        elif not _guard_exits(txt):
            print(f"  ✗ BLOCK 正例 exec 未拦截: {name} :: {txt}", file=sys.stderr)
            failed += 1

    for name, txt in warn_positives:
        hits = scan(txt)
        if not hits:
            print(f"  ✗ WARN 正例漏检: {name} :: {txt}", file=sys.stderr)
            failed += 1
        elif any(h.category in BLOCK_CATEGORIES for h in hits):
            bad = [h.category for h in hits if h.category in BLOCK_CATEGORIES]
            print(f"  ✗ WARN 正例被误判为 BLOCK({bad}): {name} :: {txt}", file=sys.stderr)
            failed += 1
        elif _guard_exits(txt):
            print(f"  ✗ WARN 正例 exec 竟被拦截（应放行）: {name} :: {txt}", file=sys.stderr)
            failed += 1

    for txt in negatives:
        hits = scan(txt)
        if hits:
            print(f"  ✗ 反例误报: {txt} :: {[h.category for h in hits]}", file=sys.stderr)
            failed += 1

    # redact 应移除命中并保留其余文本
    clean, fnd = redact("正常开头 sk-ABCDefgh12345678ijkl 正常结尾")
    if "sk-ABCDefgh" in clean or "[已隐藏]" not in clean or not fnd:
        print(f"  ✗ redact 未生效: {clean!r}", file=sys.stderr)
        failed += 1
    # guard_or_die dry-run 不应退出（无异常即通过）
    with contextlib.redirect_stderr(io.StringIO()):
        guard_or_die(["含泄露 10.140.24.177:3128"], exec_mode=False, allow_unsafe=False)
    if failed:
        print(f"selftest 失败：{failed} 项", file=sys.stderr)
        return 1
    print(f"selftest 通过（BLOCK 正例 {len(block_positives)} 必拦 / "
          f"WARN 正例 {len(warn_positives)} 只提醒不拦 / 反例 {len(negatives)} 放行 + redact + guard）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="出站内容安全闸门：扫描/脱敏疑似内部设置泄露")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("scan", help="扫描文本：有敏感(BLOCK)命中退出 7，仅 AI 措辞(WARN)退出 0")
    g = ps.add_mutually_exclusive_group()
    g.add_argument("--text", help="直接传入文本")
    g.add_argument("--file", help="从文件读")
    ps.set_defaults(func=cmd_scan)

    pr = sub.add_parser("redact", help="输出脱敏文本")
    gr = pr.add_mutually_exclusive_group()
    gr.add_argument("--text", help="直接传入文本")
    gr.add_argument("--file", help="从文件读")
    pr.add_argument("--out", help="脱敏结果输出文件（默认 stdout）")
    pr.set_defaults(func=cmd_redact)

    pt = sub.add_parser("selftest", help="自测")
    pt.set_defaults(func=cmd_selftest)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
