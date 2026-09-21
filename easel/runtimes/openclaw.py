"""OpenClaw runtime adapter."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from easel.openclaw_cmd import openclaw_base_cmd
from easel.openclaw_workspace import workspace_dir
from . import openclaw_config
from .base import (
    ActionResult, Diagnostic, QuestionAnswer, RunRequest, RunResult, RuntimeDescriptor,
    RuntimeEvent, RuntimeHealth, ServiceAction, SetupContext, SetupResult,
)
from .common import PROJECT_ROOT, clean_output, runtime_env

# OpenClaw 已验证的稳定下限（= 我们实测跑通过的最老版本）。低于它会命中 anthropic provider 必须
# 原子写入、models.providers.*.timeoutSeconds 被判 Unrecognized key 等破坏性变更（见 issue #9/#11）。
#
# 别拿「记忆检索 memory.search.*」当抬高下限的理由：2026.6.11 **没有** memory.search（实测
# `config set memory.search.…` 报 Unrecognized key），那是 2026.9.x 才有的 schema，setup.sh:613
# 已经按「先试新的、失败退回 agents.defaults.memorySearch」探测处理，不需要版本下限兜。
MIN_OPENCLAW = (2026, 6, 11)

_SESSION_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

OPENCLAW_PROFILE = "easel"
# OpenClaw 会话历史（transcript）目录：<profile 配置目录>/agents/main/sessions/<session-id>.jsonl
OPENCLAW_SESSIONS_DIR = Path.home() / f".openclaw-{OPENCLAW_PROFILE}" / "agents" / "main" / "sessions"

# 对话传输层：http＝直连常驻 gateway 的 OpenAI 兼容端点，agent 在 gateway 进程里直接跑，
# 省掉每轮 spawn `openclaw agent` 瘦客户端的冷启动（本机实测同一句话：CLI 7.1-7.6s/轮，
# HTTP 4.1-4.5s/轮，差值就是客户端冷启动）；cli＝每轮 spawn 的老路径。
#
# 默认 http，但**只对新会话生效**：见 resolve_transport。同一会话绝不中途换边——两条路径
# 写的是不同的 transcript，换边等于静默清空整段对话记忆（实测拿 CLI 去续一个 HTTP 起的会话，
# agent 直接答"无历史"）。设 EASEL_CHAT_TRANSPORT=cli 可整机回到老路径。
CHAT_TRANSPORT = os.environ.get("EASEL_CHAT_TRANSPORT", "http").strip().lower()

# gateway 进程把原始事件流（token/thinking/收尾）写到的**单个共享文件**。
# 关键：`openclaw agent` 只是瘦客户端，没有 --raw-stream 标志——只有常驻 gateway 按它自己
# 的 OPENCLAW_RAW_STREAM/OPENCLAW_RAW_STREAM_PATH 写这个文件（见 scripts/gateway.sh）；
# 适配层 tail 它做流式。默认值必须与 gateway.sh 里 EASEL_RAW_STREAM_PATH 的默认一致。
SHARED_RAW_STREAM = Path(os.environ.get("EASEL_RAW_STREAM_PATH", "/tmp/easel-raw-stream.jsonl"))

# 问答题桥接的一次性诊断标记：连接失败/旧版本无 question RPC 的告警每进程只打一次，
# 避免每开一个新会话就在后端刷一行同样的错（用户反馈的噪音）。
_QBRIDGE_WARNED: set[str] = set()
# 进程级熔断：一旦确认桥接不可用（旧版本无 question RPC、或 connect 持续失败如
# NOT_PAIRED/scope-upgrade），就彻底停掉桥接，后续每轮直接跳过——不再连接，也就不再
# 每轮在网关上触发新的配对/权限申请。恢复需重启 easel。
_QBRIDGE_DISABLED = False


def _qbridge_warn_once(key: str, message: str) -> None:
    if key in _QBRIDGE_WARNED:
        return
    _QBRIDGE_WARNED.add(key)
    print(message, file=sys.stderr, flush=True)


def openclaw_version() -> tuple[int, int, int] | None:
    """解析 `openclaw --version`，返回 (year, month, patch)；无法确定时返回 None。"""
    try:
        # 不能裸调 ["openclaw", ...]：Windows 上它是 npm 装的 `.cmd` shim，
        # CreateProcess 不按 PATHEXT 解析、裸名找不到文件 → FileNotFoundError
        # → 版本被误判「未知」。统一走 openclaw_cmd 的解析（Windows 上解析为
        # node + openclaw.mjs，Unix 上为直接可执行路径）。
        result = subprocess.run(
            openclaw_base_cmd() + ["--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        # e.g. "OpenClaw 2026.9.4 (3a9d69d)"
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
        if not m:
            return None
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def node_requirement() -> tuple[bool, str]:
    """当前 OpenClaw 要求的 Node 引擎 → (strict, floor)，供 doctor 的通用检查消费。

    strict=True 对齐 openclaw@latest（2026.9.x）：>=24.16.0 <25 || >=26.1.0（25.x/26.0 被排除）。
    strict=False 用于较旧 OpenClaw（我们支持的下限 2026.6.11）。**下限是 22.19**，不是 20.10：
    实测 openclaw@2026.6.11 的 package.json engines 就是 `">=22.19.0"`，且其 openclaw.mjs 里还有
    一道硬运行时检查（不满足直接 process.exit(1)）。写 20.10 的后果是：Node 20.10–22.18 上
    doctor 报绿，而每一条 openclaw 命令都起不来。未装 openclaw 时按 setup 的默认安装目标
    （openclaw@latest）从严要求 24.16+。
    """
    version = openclaw_version()
    if version is None or version >= (2026, 9, 0):
        return True, "24.16"
    return False, "22.19"


def skills_synced() -> tuple[bool, str]:
    """检查 agent 真正读取的那个 workspace 里有没有 skills。

    不能硬编码目标目录：OpenClaw 的默认布局在 2026.6.x / 2026.9.x 之间变过
    （见 easel/openclaw_workspace.py）。写死旧布局的后果是同步脚本报 "synced"、
    doctor 报绿，agent 却读不到任何技能（issue #19）。
    """
    ws = workspace_dir()
    skills_dir = ws / "skills"
    try:
        ok = skills_dir.is_dir() and any(skills_dir.iterdir())
    except OSError:
        ok = False
    return ok, f"agent 实际读取的 workspace 是 {ws}，其中 skills/ 为空或不存在"


def stable_session_id(session_key: str) -> str:
    """session_key → 稳定的 OpenClaw session-id（transcript 文件名）。同 sk 永远同 id，无需落盘映射。

    背景（实测根因）：OpenClaw 靠 --session-key 解析 transcript，但空闲超过约 24h（threadBindings
    默认 idleHours:24）后该绑定过期，下一条消息会新起一个空 transcript → 历史全丢（用户「关页两天
    后再问就忘了」）。同一天内没事，隔天就断。解法：我们自己钉死 --session-id（对同一会话恒定），
    让 OpenClaw 每轮都续同一个 transcript 文件，绕开 key→绑定的过期/轮换逻辑；CLI 与 HTTP 两条
    传输路径必须用同一个 id，否则对话历史会劈叉。
    """
    return str(uuid.uuid5(_SESSION_NS, session_key))


def _heal_session(session_key: str) -> None:
    """每轮 spawn openclaw 前，清洗该会话历史里的无签名 thinking 块 + 空消息（自愈防回放失效）。

    best-effort：任何异常都不阻断对话（清洗失败大不了退回原样，仍可 /new）。
    web 与 CLI 共用的唯一实现。
    """
    try:
        scripts = PROJECT_ROOT / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import session_heal
        path = OPENCLAW_SESSIONS_DIR / f"{stable_session_id(session_key)}.jsonl"
        if path.is_file():
            session_heal.sanitize_history_file(path)
    except Exception:
        pass


_HTTP_READY_CACHE: dict = {"at": -1e9, "ok": False}
_HTTP_READY_TTL = 60.0          # 探针要打一次真端点，别每轮都付这个 RTT


def gateway_http_ready(force: bool = False) -> bool:
    """探测 gateway 的 /v1/chat/completions 到底挂没挂上。

    **不能探 /v1/models**：那个路径会被 gateway 控制台 SPA 的 catch-all 接走，端点没开也照样
    返回 200（body 是 OpenClaw Control 的 HTML 首页）—— 探了等于没探，只要网关活着就恒为 True。
    这里直接打真端点：openclaw 要求 gateway.http.endpoints.chatCompletions.enabled === true
    才挂这条路由（默认 false），没开就是 404；开了则因为 body 缺 messages 返回 400。用 400 当
    "端点在"的证据，既走完整条路由又不消耗一次模型调用。
    """
    now = time.monotonic()
    if not force and now - _HTTP_READY_CACHE["at"] < _HTTP_READY_TTL:
        return bool(_HTTP_READY_CACHE["ok"])
    ok = False
    try:
        import httpx  # noqa: F401  HTTP 路径全靠它做 SSE；没装就当端点不可用，回退 CLI
        rq = urllib.request.Request(
            "http://127.0.0.1:18789/v1/chat/completions", data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(rq, timeout=3):
                ok = False       # 空 body 还给 200 说明这不是我们要的端点，不敢用
        except urllib.error.HTTPError as e:
            ok = e.code == 400   # 400 Missing user message ⇒ 端点在；404 ⇒ 没开
    except Exception:  # noqa: BLE001
        ok = False
    _HTTP_READY_CACHE.update(at=now, ok=ok)
    return ok


def transport_pin_file(session_key: str, pin_dir: Path) -> Path:
    """会话传输「钉子」文件路径（钉过 http 的会话用它自证，web 重启后依然成立）。"""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_key)[:120]
    return pin_dir / f"{safe}.transport"


def resolve_transport(session_key: str, *, pin_dir: Path | None = None,
                       transcript_dir: Path | None = None, enabled: str | None = None,
                       probe=None) -> str:
    """决定这一轮走哪条传输层，并保证同一会话**永不中途换边**。

    换边的代价是静默丢光上下文，不是慢一点：CLI 路径用 `--session-id`（uuid5(sk)）把 transcript
    钉死，而 /v1/chat/completions **压根不读 x-openclaw-session-id** —— openclaw 2026.6.11 全量
    实测：该 header 只有 MCP 端点和对上游供应商的出站请求会用，OpenAI 兼容端点只认
    x-openclaw-session-key，transcript 文件名由网关自己挑。于是同一个 web 会话在两条路径下落在
    两份不同的 jsonl 上。实测拿 CLI 去续一个已有两轮 HTTP 历史的会话，agent 回答"无历史"。

    所以判定顺序（都不依赖内存态，web 重启后依然成立）：
      1) uuid5 那份 transcript 已落盘 → 这会话是 CLI 起的，继续 cli；
      2) 有 http 钉子文件 → 继续 http；
      3) 两者都没有 → 新会话，按总开关 + 真探针决定。
    """
    enabled = CHAT_TRANSPORT if enabled is None else enabled
    probe = gateway_http_ready if probe is None else probe
    transcript_dir = OPENCLAW_SESSIONS_DIR if transcript_dir is None else transcript_dir
    if (transcript_dir / f"{stable_session_id(session_key)}.jsonl").is_file():
        return "cli"
    if pin_dir is not None:
        try:
            if transport_pin_file(session_key, pin_dir).read_text(encoding="utf-8").strip() == "http":
                return "http"
        except OSError:
            pass
    return "http" if (enabled == "http" and probe()) else "cli"


def pin_transport(session_key: str, kind: str, pin_dir: Path | None) -> None:
    """把会话钉在某条传输层上。只需钉 http —— cli 侧由 uuid5 transcript 文件自证。"""
    if kind != "http" or pin_dir is None:
        return
    try:
        pin_dir.mkdir(parents=True, exist_ok=True)
        transport_pin_file(session_key, pin_dir).write_text("http", encoding="utf-8")
    except OSError:
        pass


def raw_event_for_run(line: str, expected_run_id: str | None) -> dict | None:
    """Parse one OpenClaw raw event and reject events from other runs.

    The gateway multiplexes every run into one shared raw-stream file, and its
    events carry `runId` (not `sessionId`). A turn latches onto its own runId —
    the first event seen after the turn starts — and must ignore any event with
    a different runId. `expected_run_id=None` means not-yet-latched → accept, so
    the caller can latch from `event['runId']`.
    """
    line = line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(event, dict):
        return None
    if expected_run_id is not None:
        rid = event.get("runId")
        if rid is not None and rid != expected_run_id:
            return None
    return event


def askuser_cards_enabled() -> bool:
    """本部署的 ask_user 选项卡片是否可用：卡片依赖 gateway 的 question.* RPC（仅 2026.9.x 有）。

    不可用时 skill 改用「文字问答跨轮等待」拿短信验证码，而不是空等卡片超时。
    """
    try:
        from easel.gateway_questions import question_bridge_supported
    except Exception:  # noqa: BLE001 — 缺依赖时按不可用处理
        return False
    try:
        return bool(question_bridge_supported())
    except Exception:  # noqa: BLE001
        return False


class _GatewayHttpProc:
    """HTTP 直连模式下的「伪进程」：给句柄 / 停止逻辑提供 poll/wait/kill 兼容面。"""

    def __init__(self) -> None:
        self._done = threading.Event()

    def finish(self) -> None:
        self._done.set()

    def poll(self):
        return 0 if self._done.is_set() else None

    def terminate(self) -> None:
        self._done.set()

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._done.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("gateway-http-turn", timeout)
            time.sleep(0.05)
        return 0


class OpenClawRunHandle:
    """一个 OpenClaw 对话回合的句柄（CLI 共享 raw 流 tail 或 HTTP 直连网关）。

    - CLI：spawn `openclaw agent`，tail 常驻 gateway 写的共享 raw 文件（起始偏移 + runId 闩锁），
      并把 stdout 的 stopReason/工具调用等收尾信号记进诊断。
    - HTTP：线程内直连 /v1/chat/completions 的 SSE（content→text、reasoning→thinking）。
    两种传输都通过 events() 发 text/thinking/activity/question，把收尾诊断放进
    RunResult.diagnostics（stop_reason/last_ev/字符数/text_tail/stdout_tail 等）。
    """

    def __init__(self, process, session_key: str, questions: bool, *, transport: str,
                 raw_start_offset: int = 0, http_payload: tuple | None = None,
                 pin_dir: Path | None = None):
        self.process = process
        self.session_key = session_key
        self.questions = questions
        self.transport = transport
        self.raw_start_offset = raw_start_offset
        self.pin_dir = pin_dir                  # 传输钉子目录（web 的 SESSIONS_DIR；CLI 侧为 None）
        self._cancel = threading.Event()
        self._drain_lock = threading.RLock()   # 同一时刻只允许一个消费方 drain 事件队列
        self._stdout: list[str] = []
        self._text: list[str] = []
        self._result: RunResult | None = None
        self._events_done = False
        self._q: queue.Queue = queue.Queue()
        self._info: dict = {
            "transport": transport, "stop_reason": None, "last_ev": None,
            "saw_message_end": False, "fetch_count": 0, "token_chars": 0,
            "thinking_chars": 0, "delegated": False, "ignored_foreign_events": 0,
            "run_id": None, "text_tail": "", "error": None, "sse_thinking": False,
        }
        # raw 流两条传输都要 tail：HTTP 模式正文以 SSE 为准，但思考流只在 raw 流里
        # （openclaw 2026.6.11 的 chat/completions 不回传任何 reasoning 增量），
        # 见 _handle_raw_line 里按 transport 分流。
        threading.Thread(target=self._tail_shared_raw, daemon=True).start()
        if transport == "http":
            if http_payload is not None:
                threading.Thread(target=self._run_http_turn, args=http_payload, daemon=True).start()
        else:
            threading.Thread(target=self._read_stdout, daemon=True).start()
        if questions:
            threading.Thread(target=self._poll_questions, daemon=True).start()

    def _read_stdout(self):
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._stdout.append(line)
            clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
            if "model-fetch] start" in clean:
                self._info["fetch_count"] += 1
                fc = self._info["fetch_count"]
                self._q.put(RuntimeEvent("activity", "🧠 正在思考…" if fc == 1 else f"🔧 调用工具后继续推理（第 {fc} 步）…"))
            elif "[agent]" in clean and "delegat" in clean.lower():
                self._info["delegated"] = True
                self._q.put(RuntimeEvent("activity", "🛠️ 制作中…"))
            m = re.search(r"ended with stopReason=(\S+)", clean)
            if m:
                self._info["stop_reason"] = m.group(1)

    def _tail_shared_raw(self):
        """tail 常驻 gateway 写的共享 raw 流，只取本轮 runId 的事件（起始偏移隔离历史轮次）。"""
        try:
            f = None
            # gateway 刚起或本轮还没产生事件时文件可能暂不存在：轮询等它出现（进程先退出则收尾）。
            while f is None and not self._cancel.is_set():
                try:
                    f = open(SHARED_RAW_STREAM, "r", encoding="utf-8")
                except OSError:
                    if self.process.poll() is not None:
                        return
                    time.sleep(0.04)
            if f is None:
                return
            with f:
                f.seek(self.raw_start_offset)   # 只读本轮开始后追加的行，跳过历史轮次
                buf = ""
                while not self._cancel.is_set():
                    chunk = f.readline()
                    if chunk == "":
                        if self.process.poll() is not None:
                            buf += f.read()
                            for line in buf.split("\n"):
                                self._handle_raw_line(line)
                            break
                        time.sleep(0.04)
                        continue
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._handle_raw_line(line)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._q.put(None)

    def _handle_raw_line(self, line: str):
        o = raw_event_for_run(line, self._info["run_id"])
        if o is None:
            # 属其它并发 run 的事件（或无法解析）：绝不混入本轮可见流/收尾诊断，仅计数。
            try:
                parsed = json.loads(line)
                rid = parsed.get("runId") if isinstance(parsed, dict) else None
                if rid is not None and self._info["run_id"] is not None and rid != self._info["run_id"]:
                    self._info["ignored_foreign_events"] += 1
            except Exception:  # noqa: BLE001
                pass
            return
        # 首个带 runId 的事件闩锁本轮 run（之后 raw_event_for_run 只放行这个 run）。
        if self._info["run_id"] is None:
            rid = o.get("runId")
            if rid is None:
                return          # 还没拿到 runId，等下一条带 runId 的事件再闩锁
            self._info["run_id"] = rid
        ev, et, delta = o.get("event"), o.get("evtType"), o.get("delta") or ""
        # 记录最后一个 raw 事件：正常收尾 last_ev == assistant_message_end；
        # 若停在 text_delta/thinking_delta 说明输出或思考流被中断、没正常收尾（排查关键信号）。
        if ev:
            self._info["last_ev"] = ev
        if ev == "assistant_message_end":
            self._info["saw_message_end"] = True
        if not delta:
            return
        if ev == "assistant_text_stream" and et == "text_delta":
            if self.transport == "http":
                # HTTP 模式正文以 SSE 为准（那条才是本请求自己的响应流）。这里再发一遍
                # 就是同一段内容进两次队列 —— 前端会看到每个字重复。
                return
            self._info["token_chars"] += len(delta)
            self._info["text_tail"] = (self._info.get("text_tail", "") + delta)[-160:]
            self._text.append(delta)
            self._q.put(RuntimeEvent("text", delta))
            return
        if ev == "assistant_thinking_stream" and et == "thinking_delta":
            if self._info.get("sse_thinking"):
                return      # SSE 已经在供思考流了，别叠第二份
            self._info["thinking_chars"] += len(delta)
            self._q.put(RuntimeEvent("thinking", delta))
            return

    def _run_http_turn(self, body: dict, headers: dict, timeout: int):
        """线程内直连常驻网关的 OpenAI 兼容端点（原生 SSE），事件语义与 CLI 路径一致。"""
        try:
            import httpx
            saw_done = False
            got_text = False
            tool_noted = False
            req_timeout = httpx.Timeout(timeout + 60, connect=10)
            with httpx.Client(timeout=req_timeout) as client:
                with client.stream("POST", "http://127.0.0.1:18789/v1/chat/completions",
                                   json=body, headers=headers) as resp:
                    if resp.status_code != 200:
                        raw = resp.read()[:200].decode("utf-8", "replace")
                        self._info["error"] = f"对话失败（HTTP {resp.status_code}）：{raw[:160]}"
                        return
                    for line in resp.iter_lines():
                        if self._cancel.is_set():
                            return
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].lstrip()   # SSE 允许 `data:{…}`（冒号后无空格）
                        if payload == "[DONE]":
                            saw_done = True
                            break
                        try:
                            d = json.loads(payload)
                        except ValueError:
                            continue
                        if isinstance(d.get("error"), dict):   # 200 里夹错误对象：不能当正常流吞掉
                            self._info["error"] = f"网关返回错误：{str(d['error'])[:160]}"
                            return
                        delta = (d.get("choices") or [{}])[0].get("delta") or {}
                        # 思考流的两个可能来源，先到先得（`sse_thinking` 闩锁，防两路都来时重复）：
                        # ① 这里的 reasoning 增量 —— openclaw 2026.6.11 的 chat/completions
                        #    实现里 reasoning/thinking 出现 0 次，**不会**给；留着是给别的网关/
                        #    以后的版本用。② 常驻 gateway 写的共享 raw 流（见 _tail_shared_raw），
                        #    它按自己的 env 写，跟这一轮是谁触发的无关，所以 HTTP 模式照样能读到。
                        rc = delta.get("reasoning_content") or delta.get("reasoning")
                        if rc:
                            self._info["sse_thinking"] = True
                            self._info["thinking_chars"] += len(rc)
                            self._q.put(RuntimeEvent("thinking", rc))
                        c = delta.get("content")
                        if c:
                            got_text = True
                            self._info["token_chars"] += len(c)
                            self._text.append(c)
                            self._q.put(RuntimeEvent("text", c))
                        if delta.get("tool_calls") and not tool_noted:
                            tool_noted = True
                            self._q.put(RuntimeEvent("activity", "🔧 正在执行操作…"))
            if saw_done:
                self._info["last_ev"] = "assistant_message_end"
                self._info["saw_message_end"] = True
            elif not got_text:
                # 流正常结束却既没正文也没 [DONE]：多半是端点没真开或中途断了。
                # 不报错的话这一轮会静默落一条空回答，还会被 /api/chat/last 原样取回。
                self._info["error"] = ("网关流异常结束：没有收到任何内容（检查 "
                                       "gateway.http.endpoints.chatCompletions 是否开启，"
                                       "或设 EASEL_CHAT_TRANSPORT=cli 回退）")
        except Exception as e:  # noqa: BLE001
            self._info["error"] = f"网关连接失败：{str(e)[:140]}"
        finally:
            self.process.finish()
            self._q.put(None)

    def _poll_questions(self):
        """轮询 gateway 的 pending question 推给消费方（ask_user 选项卡片桥接）。

        connect 失败或版本无 question RPC 时熔断整个桥接（见 _QBRIDGE_DISABLED），
        不再每轮重试，避免在网关上堆配对/权限申请。每进程只告警一次。
        """
        global _QBRIDGE_DISABLED
        try:
            if _QBRIDGE_DISABLED:
                return
            if not askuser_cards_enabled():
                _QBRIDGE_DISABLED = True
                _qbridge_warn_once(
                    "unsupported",
                    "[question-bridge] 当前 OpenClaw 版本无 question RPC（需 2026.9.x+），"
                    "已跳过 ask_user 选项卡片桥接，改用文字问答。")
                return
            from easel.gateway_questions import GatewayClient, GatewayUnsupportedError
            client = None
            pushed: set[str] = set()
            try:
                client = GatewayClient()
                client.connect()
            except Exception as e:  # noqa: BLE001
                # connect 失败（如 NOT_PAIRED/scope-upgrade，或网关不可达）：熔断整个桥接。
                _QBRIDGE_DISABLED = True
                _qbridge_warn_once(
                    "connect",
                    f"[question-bridge] connect gateway failed，已停用桥接（本进程），"
                    f"ask_user 改用文字问答: {e}")
                return
            try:
                while self.process.poll() is None and not self._cancel.is_set():
                    try:
                        items = client.list_questions(
                            session_key=f"agent:main:{self.session_key}", status="pending")
                    except GatewayUnsupportedError as e:
                        # 连上了但没有 question RPC（版本判断漏网时的兜底）：熔断，安静退出。
                        _QBRIDGE_DISABLED = True
                        _qbridge_warn_once(
                            "unsupported",
                            f"[question-bridge] 当前 OpenClaw 版本无 question RPC，"
                            f"已停用 ask_user 选项卡片桥接（需 2026.9.x+）: {e}")
                        return
                    except Exception:  # noqa: BLE001
                        time.sleep(2)
                        continue
                    for it in items:
                        qid = it.get("id")
                        if qid and qid not in pushed:
                            pushed.add(qid)
                            self._q.put(RuntimeEvent("question", data={
                                "id": qid, "questions": it.get("questions", []),
                                "expiresAtMs": it.get("expiresAtMs"),
                            }))
                    time.sleep(2)
            finally:
                try:
                    if client is not None:
                        client.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            return

    def events(self):
        if self._events_done:
            return
        # 事件队列只有一个 sentinel：同一时刻只允许一个消费方，另一个消费方在 wait() 里
        # 等锁释放（见 wait），避免两个消费者互相等一个不存在的 sentinel。
        with self._drain_lock:
            if self._events_done:
                return
            while True:
                try:
                    event = self._q.get(timeout=.25)
                except queue.Empty:
                    continue
                if event is None:
                    break
                yield event
            self._events_done = True

    def _diagnostics(self) -> dict:
        info = dict(self._info)
        tail = clean_output("".join(self._stdout))
        info["stdout_tail"] = tail[-800:]
        if info["error"]:
            return info
        if self.transport == "cli":
            rc = self.process.poll()
            if rc not in (0, None):
                err = tail[:200]
                info["error"] = f"执行失败（退出码 {rc}）{' — ' + err if err else ''}"
        return info

    def wait(self) -> RunResult:
        if self._result:
            return self._result
        if not self._events_done:
            if self._cancel.is_set():
                self._events_done = True        # 取消后不再等流结束（阻塞读可能很晚才返回）
            else:
                # 已有消费方（如 web 的 drain 线程）持锁 drain 时，这里等它把事件流消费完；
                # 抢到锁则自己 drain 完。RLock 允许 events() 在本线程内重入。
                with self._drain_lock:
                    if not self._events_done and not self._cancel.is_set():
                        for _ in self.events():
                            pass
        if self.transport == "http":
            rc = 0 if self._info["error"] is None else 1
            text = "".join(self._text)
        else:
            rc = self.process.wait()
            text = "".join(self._text) or clean_output("".join(self._stdout))
        # 正常收尾的唯一标志：raw 流最后一个事件是 assistant_message_end（HTTP 模式为收到 [DONE]）。
        clean_end = self._info["last_ev"] == "assistant_message_end"
        self._result = RunResult(rc, text, clean_end, self._info["stop_reason"], self._diagnostics())
        # 只有真的在 HTTP 上跑出了内容，才把这个会话钉到 http 上。钉早了（比如选路时就钉）
        # 会把一个其实没跑成的会话锁死在 http，之后每轮都往一条不通的路上撞；而钉住之后
        # 就绝不能再换回 cli —— 网关那份 transcript 我们按名字找不回来，换边即丢历史。
        if self.transport == "http" and self._info["token_chars"]:
            pin_transport(self.session_key, "http", self.pin_dir)
        return self._result

    def cancel(self) -> None:
        self._cancel.set()
        if self.process.poll() is None:
            self.process.terminate()
        # 立刻结束事件流：阻塞中的 HTTP 读/进程收尾可能还要等一阵，停止/超时不能等它。
        # （晚到的线程还会再排一个 sentinel，无人消费，无副作用。）
        self._q.put(None)

    def close(self) -> None:
        self._cancel.set()
        if self.process.poll() is None:
            self.process.terminate()
            if self.transport == "cli":
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)

    def poll(self) -> int | None:
        return self.process.poll()


class OpenClawAdapter:
    descriptor = RuntimeDescriptor(
        "openclaw", "OpenClaw", "npm install -g openclaw@latest",
        frozenset({"interactive", "managed_service", "session_delete", "questions",
                   "thinking_events", "activity_events", "native_stream"}),
    )

    def setup(self, context: SetupContext) -> SetupResult:
        if shutil.which("openclaw") is None:
            result = subprocess.run(["npm", "install", "-g", "openclaw@latest", "--loglevel", "warn"],
                                    cwd=context.project_root, env=context.env or None)
            if result.returncode:
                return SetupResult(False, "OpenClaw 安装失败")
        try:
            openclaw_base_cmd()
        except FileNotFoundError as exc:
            return SetupResult(False, str(exc))
        return SetupResult(True, "OpenClaw 已就绪")

    def open_chat(self, prompt: str | None) -> int:
        from easel.timeouts import TIMEOUT_CHAT
        cmd = openclaw_base_cmd() + [
            "--profile", "easel", "tui", "--session", f"easel-{time.strftime('%m%d-%H%M%S')}",
            "--timeout-ms", str(TIMEOUT_CHAT * 1000),
        ]
        if prompt:
            cmd += ["--message", prompt]
        return subprocess.run(cmd, cwd=PROJECT_ROOT, env=runtime_env()).returncode

    def start(self, run: RunRequest) -> OpenClawRunHandle:
        _heal_session(run.session_key)       # 清洗历史里无签名 thinking 块，防回放失效
        questions = "questions" in self.descriptor.capabilities
        env = dict(run.env)
        # 告诉 skill：本部署的 ask_user 选项卡片是否可用（见 askuser_cards_enabled）。
        env["EASEL_ASKUSER_CARDS"] = "1" if askuser_cards_enabled() else "0"

        # 只有调用方要求流式（web 对话）才可能走 http；其余（skill/ping/非流式）保持 CLI。
        # 同一会话的传输由 resolve_transport 钉死，绝不中途换边（换边即丢 transcript 历史）。
        kind = "cli" if not run.stream else resolve_transport(
            run.session_key, pin_dir=run.sessions_dir)

        if kind == "http":
            body = {
                "model": "openclaw/default",
                "stream": True,
                "messages": [{"role": "user", "content": run.prompt}],
            }
            # 这两颗 header 里只有 session-key 对这轮有意义（端点靠它认会话）；
            # session-id 在 openclaw 2026.6.11 的 chat/completions 上被静默忽略（见
            # resolve_transport），带上只是为了网关升级后能对齐，不指望它钉 transcript。
            headers = {"x-openclaw-session-key": f"agent:main:{run.session_key}",
                       "x-openclaw-session-id": stable_session_id(run.session_key)}
            return OpenClawRunHandle(
                _GatewayHttpProc(), run.session_key, questions, transport="http",
                http_payload=(body, headers, run.timeout), pin_dir=run.sessions_dir,
            )

        # 原始事件流由常驻 gateway 写到共享文件（见 SHARED_RAW_STREAM / scripts/gateway.sh），
        # 不是 agent 客户端写的。本轮开始时记下文件当前尾偏移：只读此偏移之后追加的行，
        # 再用首个新事件的 runId 闩锁本轮，隔离其它并发会话的事件。
        try:
            raw_start_offset = SHARED_RAW_STREAM.stat().st_size
        except OSError:
            raw_start_offset = 0
        cmd = openclaw_base_cmd() + [
            "--profile", OPENCLAW_PROFILE, "agent", "--agent", "main",
            "--session-key", f"agent:main:{run.session_key}",
            "--session-id", stable_session_id(run.session_key),
            "--thinking", run.thinking, "--timeout", str(run.timeout),
            "--message", run.prompt,
        ]
        # 注意：不要在客户端 env 上设 OPENCLAW_RAW_STREAM*——`agent` 客户端不写 raw 流，
        # 设了也没用；raw 流开关在 gateway 侧（scripts/gateway.sh）。
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                cwd=run.cwd, text=True, bufsize=1, env=env)
        return OpenClawRunHandle(
            proc, run.session_key, questions, transport="cli",
            raw_start_offset=raw_start_offset, pin_dir=run.sessions_dir,
        )

    def health(self) -> RuntimeHealth:
        port = os.environ.get("EASEL_GATEWAY_PORT", "18789")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
                return RuntimeHealth(response.status == 200)
        except (OSError, urllib.error.URLError) as exc:
            return RuntimeHealth(False, str(exc))

    def node_requirement(self) -> tuple[bool, str]:
        return node_requirement()

    def is_local_gateway_base(self, url: str) -> bool:
        return openclaw_config.is_local_gateway_base(url)

    def provider_creds(self) -> dict[str, tuple[str, str]]:
        return openclaw_config.provider_creds()

    def sync_chat_providers(self, provider_updates: dict[str, dict], keep_custom: set[str],
                            primary_ref: str) -> str:
        return openclaw_config.sync_chat_providers(provider_updates, keep_custom, primary_ref)

    def config_snapshot(self) -> dict:
        return openclaw_config.config_snapshot()

    def diagnose(self) -> list[Diagnostic]:
        command_ok = True
        try:
            openclaw_base_cmd()
        except FileNotFoundError:
            command_ok = False
        version = openclaw_version()
        synced, synced_detail = skills_synced()
        route_ok, route_detail = openclaw_config.primary_model_routable()
        minimum = ".".join(map(str, MIN_OPENCLAW))
        return [
            Diagnostic("OpenClaw command", command_ok, self.descriptor.install_hint),
            Diagnostic(f"OpenClaw >= {minimum}", version is not None and version >= MIN_OPENCLAW,
                       "请升级：npm install -g openclaw@latest"),
            Diagnostic(".env (API Key)", openclaw_config.auth_configured(), "请配置模型 API key"),
            Diagnostic("OpenClaw model routing", route_ok, route_detail),
            Diagnostic("Skills synced", synced,
                       f"{synced_detail}；重新运行 setup.ps1（Windows）或 bash openclaw/sync.sh（Linux/macOS）"),
            Diagnostic("OpenClaw gateway", self.health().ok, "运行 python -m easel gateway start"),
        ]

    def manage_service(self, action: ServiceAction) -> ActionResult:
        from .opencode import _run_service_script
        return _run_service_script("gateway", action)

    def delete_session(self, session_key: str, sessions_dir: Path | None = None) -> ActionResult:
        path = Path.home() / ".openclaw-easel" / "agents" / "main" / "sessions" / "sessions.json"
        if not path.is_file():
            return ActionResult(False, "sessions file not found", data={"deleted": False})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            full = session_key if session_key.startswith("agent:") else f"agent:main:{session_key}"
            for key in (full, session_key):
                if key in data:
                    del data[key]
                    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    return ActionResult(True, data={"deleted": True})
            return ActionResult(False, "session not found", data={"deleted": False})
        except Exception as exc:
            return ActionResult(False, str(exc), data={"deleted": False})

    def answer_question(self, request: QuestionAnswer) -> ActionResult:
        try:
            from easel.gateway_questions import GatewayClient
            client = GatewayClient()
            client.connect()
            try:
                result = client.resolve(request.question_id, request.answers, request.resolved_by)
                return ActionResult(True, data={"result": result})
            finally:
                client.close()
        except Exception as exc:
            return ActionResult(False, str(exc))

    def question_status(self, question_ids: list[str]) -> ActionResult:
        try:
            from easel.gateway_questions import GatewayClient, GatewayQuestionError
            client = GatewayClient()
            client.connect()
            try:
                out = {}
                for qid in question_ids:
                    try:
                        item = client.get_question(qid)
                        out[qid] = {"status": item.get("status") if item else "not_found"}
                    except GatewayQuestionError:
                        out[qid] = {"status": "not_found"}
                    except Exception:
                        out[qid] = {"status": "unknown"}
                return ActionResult(True, data={"questions": out})
            finally:
                client.close()
        except Exception as exc:
            return ActionResult(False, str(exc), data={"questions": {}})
