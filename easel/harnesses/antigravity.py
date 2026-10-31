"""Antigravity (AGY) harness adapter for Easel.

Connects Easel Web to the official Antigravity CLI (agy) or cloud Gemini models,
enabling streaming turns, multi-turn session persistence, and subscription token usage.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

from easel import __version__
from .base import Descriptor, HarnessError, RunRequest
from .commands import base_command
from .workspace import harness_instructions


class AntigravityAdapter:
    descriptor = Descriptor(
        "antigravity",
        "Antigravity",
        "AGY Harness",
        "使用本机 Antigravity 环境与订阅",
    )

    async def run(self, request: RunRequest, emit, ask, bind):
        """Execute a conversation turn via Antigravity CLI (or Direct API fallback)."""
        emit("activity", "连接本地 Antigravity 运行中…")

        prompt = request.prompt
        try:
            instructions = harness_instructions(request)
        except Exception:
            instructions = ""

        # Determine CLI command
        try:
            cmd_base = base_command("antigravity")
        except Exception:
            cmd_base = None

        if cmd_base and Path(cmd_base[0]).exists():
            # Run via official agy.exe
            # Note: In headless print mode, --dangerously-skip-permissions is required
            # so that agent tools (e.g. read_file, search, run_command) can execute without terminal prompts.
            cmd = list(cmd_base) + [
                "--output-format", "stream-json",
                "--dangerously-skip-permissions",
                "--print", prompt
            ]
            
            if request.model and request.model.strip():
                cmd.extend(["--model", request.model.strip()])
            if request.native_id and request.native_id.strip():
                cmd.extend(["--conversation", request.native_id.strip()])

            env = {
                **os.environ,
                **request.env,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }

            model_name = request.model or "gemini-3.8-flash-high"
            emit("thinking", f"Antigravity Agent 正在启动 ({model_name})，准备执行任务…\n")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(request.cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            tokens_emitted = False
            error_output = []

            async def read_stderr():
                while True:
                    err_line = await proc.stderr.readline()
                    if not err_line:
                        break
                    err_text = err_line.decode("utf-8", errors="replace").strip()
                    if err_text:
                        error_output.append(err_text)

            stderr_task = asyncio.create_task(read_stderr())

            tool_labels = {
                "read_file": "读取技能/文件",
                "write_file": "生成脚本/文件",
                "run_command": "执行数据抓取命令",
                "search_web": "联网搜索热点",
                "browser_get_dom": "抓取页面内容",
                "browser_refresh_page": "刷新浏览器页面",
            }

            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if not text:
                        continue
                    try:
                        data = json.loads(text)
                    except Exception:
                        continue

                    event = data.get("event")
                    if event == "init":
                        conv_id = data.get("conversation_id")
                        if conv_id:
                            bind(conv_id)
                        emit("activity", "Antigravity Agent 会话已建立")
                    elif event == "step_update":
                        su = data.get("step_update", {})
                        stype = su.get("step_type")
                        state = su.get("state")
                        delta = su.get("text_delta")

                        if delta and stype == "agent_response":
                            tokens_emitted = True
                            emit("token", delta)
                        elif stype == "tool":
                            tname = su.get("tool_name", "tool")
                            tlabel = tool_labels.get(tname, tname)
                            if state == "ACTIVE":
                                emit("activity", f"🔧 正在执行: {tlabel}…")
                            elif state == "DONE":
                                emit("activity", f"✅ 完成: {tlabel}")
                        elif stype == "agent_response" and state == "ACTIVE" and not delta:
                            emit("activity", "🧠 深度思考与分析中…")

                    elif event == "result":
                        res = data.get("result", {})
                        resp_text = res.get("response")
                        if resp_text and not tokens_emitted:
                            tokens_emitted = True
                            emit("token", resp_text)

                await proc.wait()
                await stderr_task

                if proc.returncode != 0 and not tokens_emitted:
                    err_summary = "\n".join(error_output) or f"进程退出码: {proc.returncode}"
                    emit("token", f"\n[Antigravity CLI 执行异常: {err_summary}]")
                elif not tokens_emitted:
                    emit("token", "\n（任务执行完成）")

            except asyncio.CancelledError:
                if proc.returncode is None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                raise
            return

        # Fallback to Direct API if configured
        from easel.direct_api import read_settings, stream_chat, history_path
        settings = read_settings(request.cwd / ".env")
        api_key = (
            settings.get("ANTIGRAVITY_API_KEY")
            or settings.get("GEMINI_API_KEY")
            or settings.get("EASEL_DIRECT_API_KEY")
        )
        base_url = (
            settings.get("ANTIGRAVITY_BASE_URL")
            or settings.get("EASEL_DIRECT_API_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        model = request.model or "gemini-3.8-flash"

        if api_key and not api_key.startswith("REPLACE_ME") and api_key.strip():
            emit("thinking", f"Antigravity 通过 API ({model}) 响应中…\n")
            hist_file = (
                history_path(request.cwd / "outputs" / "_sessions", request.session_key)
                if request.session_key
                else None
            )
            adapted_settings = dict(settings)
            adapted_settings["EASEL_DIRECT_API_BASE_URL"] = base_url
            adapted_settings["EASEL_DIRECT_API_MODEL"] = model
            adapted_settings["EASEL_DIRECT_API_KEY"] = api_key

            try:
                async for kind, text in stream_chat(
                    adapted_settings,
                    prompt,
                    system=instructions,
                    history_file=hist_file,
                    timeout=request.timeout,
                ):
                    if kind in ("token", "finish"):
                        emit("token", text)
                    elif kind == "thinking":
                        emit("thinking", text)
            except Exception as e:
                emit("token", f"\n[Antigravity 接口异常: {e}]")
        else:
            emit(
                "token",
                f"【未检测到 Antigravity CLI】\n\n"
                f"请确保 `agy.exe` 已安装于系统路径，或在 `.env` 中配置 `GEMINI_API_KEY`。"
            )
