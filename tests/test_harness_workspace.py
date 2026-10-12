from pathlib import Path
from dataclasses import replace
import asyncio
import json
import os
import subprocess
import sys

import pytest

from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.workspace import harness_instructions, workspace_documents
from easel.harnesses.rpc import close_sessions
from easel.harnesses.codex import CodexAdapter
from easel.harnesses.acp import ACPAdapter


def workspace_at(root):
    source = root / "agents" / "workspace"
    source.mkdir(parents=True)
    (source / "AGENTS.md").write_text("共享业务规则", encoding="utf-8")
    (source / "SOUL.md").write_text("共享人格", encoding="utf-8")
    (source / "EXTRA.md").write_text("额外说明", encoding="utf-8")
    return source


@pytest.mark.parametrize("runtime", ["codex", "opencode", "acp"])
def test_native_harnesses_receive_all_shared_documents_and_actual_runtime(tmp_path, runtime):
    workspace_at(tmp_path)
    request = RunRequest("hello", tmp_path, {"EASEL_AGENT_RUNTIME": runtime})
    instructions = harness_instructions(request)
    assert all(value in instructions for value in ("共享业务规则", "共享人格", "额外说明"))
    assert instructions.index("SOUL.md") < instructions.index("AGENTS.md")
    assert f"当前执行引擎：{runtime}" in instructions
    assert str(tmp_path.resolve()) in instructions
    assert str(tmp_path / "skills" / "builtin") in instructions
    assert str(tmp_path / "skills" / "shared" / "scripts") in instructions
    assert str(tmp_path / "profiles") in instructions
    assert "直接使用该实际路径" in instructions
    assert "不是项目根中的必需目录" in instructions
    assert "OpenClaw gateway" not in instructions
    assert "额外工具权限必须由用户确认" in instructions


def test_missing_shared_agents_document_is_not_silently_ignored(tmp_path):
    source = tmp_path / "agents" / "workspace"
    source.mkdir(parents=True)
    (source / "SOUL.md").write_text("only soul", encoding="utf-8")
    with pytest.raises(HarnessError, match="agents/workspace/AGENTS.md"):
        workspace_documents(tmp_path)


def test_external_request_root_uses_installed_shared_workspace(tmp_path):
    documents = workspace_documents(tmp_path)
    assert all(document.is_file() for document in documents)
    assert {document.name for document in documents} >= {"SOUL.md", "AGENTS.md"}


@pytest.mark.parametrize(("runtime", "adapter_type"), [("codex", CodexAdapter), ("acp", ACPAdapter)])
def test_workspace_changes_reload_instructions_and_resume_original_session(tmp_path, runtime, adapter_type):
    source = workspace_at(tmp_path)
    audit_file = tmp_path / "audit.jsonl"
    request = RunRequest("hello", tmp_path, {
        **os.environ, "EASEL_AGENT_RUNTIME": runtime, "FAKE_HARNESS_MODE": "stable-resume",
        "FAKE_HARNESS_AUDIT": str(audit_file),
    }, command=(sys.executable, str(Path(__file__).parent / "fixtures" / "harness_rpc.py"), runtime),
        timeout=10, session_key="workspace-test")

    async def reject(questions):
        raise AssertionError("No permission expected")

    async def scenario():
        identifiers = []
        current = request
        adapter = adapter_type()
        try:
            for turn in range(3):
                if turn == 2:
                    (source / "SOUL.md").write_text("更新人格", encoding="utf-8")
                await adapter.run(current, lambda *event: None, reject, identifiers.append)
                current = replace(current, native_id=identifiers[-1], prompt="next question")
            messages = [json.loads(line) for line in audit_file.read_text().splitlines()]
            methods = [message.get("method") for message in messages]
            assert methods.count("initialize") == 2
            assert methods.count("thread/start" if runtime == "codex" else "session/new") == 1
            assert methods.count("thread/resume" if runtime == "codex" else "session/load") == 1
            assert len(set(identifiers)) == 1
            assert "更新人格" in json.dumps(messages, ensure_ascii=False)
        finally:
            await close_sessions()

    asyncio.run(scenario())


def test_shared_identity_does_not_assume_openclaw_gateway_or_env_authentication():
    root = Path(__file__).resolve().parents[1]
    identity = (root / "agents" / "workspace" / "AGENTS.md").read_text(encoding="utf-8")
    assert "运行在 OpenClaw gateway" not in identity
    assert "当前执行引擎的配置管理" in identity
    assert not (root / "openclaw" / "workspace" / "AGENTS.md").exists()


@pytest.mark.skipif(os.name == "nt", reason="Bash workspace sync is Unix-only")
def test_openclaw_sync_uses_shared_workspace_and_preserves_instruction_source(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "workspace"
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", str(root / "agents" / "sync.sh")],
        cwd=root, env={**os.environ, "HOME": str(home),
                       "EASEL_OPENCLAW_WORKSPACE": str(target)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
    for document in (root / "agents" / "workspace").glob("*.md"):
        synced = target / document.name
        assert synced.read_text(encoding="utf-8").startswith(document.read_text(encoding="utf-8"))
        assert synced.stat().st_nlink == 1
    instructions = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "当前执行引擎：OpenClaw" in instructions
    assert f'cd "{root}"' in instructions
    assert (target / "easel-profiles").resolve() == root / "profiles"
    assert (target / "outputs").resolve() == root / "outputs"
    original_skills = {skill.name for skill in (root / "skills" / "builtin").iterdir() if skill.is_dir()}
    assert {skill.name for skill in (target / "skills").iterdir()} == original_skills
    assert (target / "shared" / "scripts" / "web_publisher.py").is_file()


@pytest.mark.skipif(os.name == "nt", reason="Bash workspace sync is Unix-only")
def test_document_only_sync_preserves_memory_custom_skills_scripts_and_links(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / "workspace with spaces"
    original = {
        "USER.md": "custom user",
        "MEMORY.md": "custom memory",
        "skills/custom/SKILL.md": "custom skill",
        "skills/ai-image-gen/local.md": "custom reference",
        "shared/scripts/custom.py": "custom script",
    }
    for relative, content in original.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    outputs = target / "outputs"
    outputs.symlink_to(tmp_path / "custom-output")
    result = subprocess.run(
        ["bash", str(root / "agents" / "sync.sh"), "--docs-only"],
        cwd=root, env={**os.environ, "HOME": str(tmp_path),
                       "EASEL_OPENCLAW_WORKSPACE": str(target)},
        capture_output=True, text=True, timeout=45,
    )
    assert result.returncode == 0, result.stderr
    for relative, content in original.items():
        assert (target / relative).read_text(encoding="utf-8") == content
    assert outputs.readlink() == tmp_path / "custom-output"
    assert not (target / "easel-profiles").exists()
    assert not (target / "shared" / "scripts" / "web_publisher.py").exists()
    assert (target / "skills" / "ai-image-gen" / "SKILL.md").read_bytes() == (
        root / "skills" / "builtin" / "ai-image-gen" / "SKILL.md"
    ).read_bytes()
    instructions = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert instructions.startswith((root / "agents" / "workspace" / "AGENTS.md").read_text(encoding="utf-8"))
    context = (target / "CONTEXT.md").read_text(encoding="utf-8")
    assert f'cd "{root}"' in context
    assert str(root / ".venv" / "bin" / "python") in context
