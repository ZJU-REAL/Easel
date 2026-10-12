"""One workspace identity shared by all native harness adapters."""
from __future__ import annotations

import os
from pathlib import Path

from .base import HarnessError, RunRequest


def workspace_documents(root: Path) -> list[Path]:
    source = root / "agents" / "workspace"
    if not source.is_dir():
        source = Path(__file__).resolve().parents[2] / "agents" / "workspace"
    documents = sorted(source.glob("*.md"),
                       key=lambda document: (document.name != "SOUL.md",
                                             document.name != "AGENTS.md", document.name))
    if not documents or not (source / "AGENTS.md").is_file():
        raise HarnessError("缺少 agents/workspace/AGENTS.md，请检查 Easel 安装")
    return documents


def harness_instructions(request: RunRequest) -> str:
    root = request.cwd.resolve()
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    runtime = request.env.get("EASEL_AGENT_RUNTIME", "当前所选引擎")
    documents = "\n\n".join(
        f"## 共享工作区：{document.name}\n\n{document.read_text(encoding='utf-8')}"
        for document in workspace_documents(root))
    return (
        documents + "\n\n## 运行时项目根与执行引擎\n\n"
        f"当前执行引擎：{runtime}；权限范围：{request.sandbox}。"
        "引擎与模型供应商分开选择；只使用当前引擎真实提供的工具，不冒充其它引擎。"
        f"项目根绝对路径：{root}；先切换到该目录再运行项目脚本。"
        f"技能库：{root / 'skills' / 'builtin'}；共享脚本：{root / 'skills' / 'shared' / 'scripts'}。"
        "每个 SKILL.md 是流程规范，不要求使用原生 /skill 命令；先读取对应技能再执行。"
        f"Python 优先使用 {python}；产物保存到 {root / 'outputs'}。"
        f"账号画像位于 {root / 'profiles'}；直接使用该实际路径，"
        "easel-profiles/ 仅在另有工作区链接时可用，不是项目根中的必需目录。"
        "遵循用户选择的画像和每轮技能提醒。配置检查只使用项目 .env 的脱敏结果，不回显凭证。"
        "公开发布、修改账号状态和其它不可逆操作必须先取得明确同意。"
        "不要泄露凭证、私有配置或内部地址。额外工具权限必须由用户确认，不得绕过权限限制。"
    )
