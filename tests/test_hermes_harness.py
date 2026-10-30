import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from easel.harnesses import describe, store
from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.commands import hermes_command
from easel.harnesses.hermes import HermesAdapter
from easel.harnesses import models as native_models

FIXTURE = Path(__file__).parent / "fixtures" / "harness_rpc.py"


def test_hermes_command_resolves_executable_without_a_shell(tmp_path, monkeypatch):
    executable = tmp_path / "hermes"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setattr("easel.harnesses.commands.shutil.which", lambda name: str(executable))

    assert hermes_command() == (str(executable), "acp")
    assert all(isinstance(part, str) and part for part in hermes_command())


def request_for(tmp_path, mode="normal", native_id="", model=""):
    env = {**os.environ, "OPENAI_API_KEY": "fake-secret-never-print"}
    command = (sys.executable, str(FIXTURE), "hermes", f"--fake-mode={mode}",
               f"--fake-audit={tmp_path / 'audit.jsonl'}")
    return RunRequest("hello", tmp_path, env, native_id, model, "read-only", 10, command)


def audit(tmp_path):
    return [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]


def test_hermes_is_registered_and_profile_is_explicit():
    from easel.harnesses import adapter

    assert "hermes" in store.IDS
    assert isinstance(adapter("hermes"), HermesAdapter)
    assert HermesAdapter().launch_command()[1:] == ("--profile", "easel", "acp")


def test_hermes_does_not_inherit_easel_provider_credentials():
    env = HermesAdapter._profile_env({
        "OPENAI_API_KEY": "must-not-pass", "ANTHROPIC_AUTH_TOKEN": "also-secret",
        "HERMES_HOME": "/tmp/hermes-profile-root", "HTTPS_PROXY": "http://proxy",
        "EASEL_ROOT": "/tmp/project",
    })
    assert env == {"HERMES_HOME": "/tmp/hermes-profile-root", "HTTPS_PROXY": "http://proxy",
                   "EASEL_ROOT": "/tmp/project"}


def test_hermes_profile_env_uses_a_safe_allowlist_and_drops_authenticated_proxies():
    env = HermesAdapter._profile_env({
        "PATH": "/usr/bin", "HOME": "/home/test", "HERMES_HOME": "/home/test/.hermes",
        "HTTPS_PROXY": "http://proxy.local:7897", "NO_PROXY": "localhost,127.0.0.1",
        "EASEL_ROOT": "/srv/easel", "EASEL_AGENT_RUNTIME": "hermes",
        "GOOGLE_API_KEY": "synthetic-google-key", "DEEPSEEK_TOKEN": "synthetic-token",
        "GITHUB_TOKEN": "synthetic-github-token", "CUSTOM_CREDENTIALS": "synthetic-credential",
        "OPENAI_BASE_URL": "https://example.invalid/v1",
        "HTTP_PROXY": "http://proxy-user:synthetic-password@proxy.local:7897",
    })
    assert env == {
        "PATH": "/usr/bin", "HOME": "/home/test", "HERMES_HOME": "/home/test/.hermes",
        "HTTPS_PROXY": "http://proxy.local:7897", "NO_PROXY": "localhost,127.0.0.1",
        "EASEL_ROOT": "/srv/easel", "EASEL_AGENT_RUNTIME": "hermes",
    }
    assert "synthetic" not in repr(env)


def test_hermes_model_catalog_comes_from_session_new_and_ignores_request_command(tmp_path, monkeypatch):
    from dataclasses import replace

    safe_request = request_for(tmp_path)
    monkeypatch.setattr("easel.harnesses.commands.hermes_command",
                        lambda **_kwargs: safe_request.command)
    untrusted_request = replace(safe_request, command=(sys.executable, "-c", "raise SystemExit(42)"))
    result = asyncio.run(native_models.available_models("hermes", untrusted_request))
    assert result == [
        {"id": "provider/alpha", "label": "Alpha", "default": True},
        {"id": "provider/beta", "label": "provider/beta", "default": False},
    ]
    assert [item.get("method") for item in audit(tmp_path)] == [
        "initialize", "initialized", "session/new"]


def test_hermes_session_continues_with_session_load_and_same_identity(tmp_path):
    async def reject(_questions):
        raise AssertionError("No permission expected")

    adapter = HermesAdapter()
    bound = []
    async def run(native_id):
        await adapter.run(request_for(tmp_path, "stable-resume", native_id=native_id),
                          lambda *_: None, reject, bound.append)
    asyncio.run(run(""))
    asyncio.run(run(bound[-1]))
    methods = [item.get("method") for item in audit(tmp_path)]
    assert methods.count("session/new") == 1
    assert methods.count("session/load") == 1
    assert methods.count("session/prompt") == 2
    assert bound == ["native-session", "native-session"]


def test_hermes_rejects_a_replacement_session_on_resume(tmp_path):
    async def reject(_questions):
        raise AssertionError("No permission expected")

    with pytest.raises(HarnessError, match="不会替换已有历史"):
        asyncio.run(HermesAdapter().run(request_for(tmp_path, "wrong-resume", native_id="original"),
                                        lambda *_: None, reject, lambda _value: None))
    assert not any(item.get("method") == "session/prompt" for item in audit(tmp_path))


def test_hermes_model_override_uses_session_set_model(tmp_path):
    async def reject(_questions):
        raise AssertionError("No permission expected")

    asyncio.run(HermesAdapter().run(request_for(tmp_path, model="provider/beta"),
                                    lambda *_: None, reject, lambda _value: None))
    changes = [item for item in audit(tmp_path) if item.get("method") == "session/set_model"]
    assert changes[0]["params"] == {"sessionId": "native-session", "modelId": "provider/beta"}


def test_hermes_permission_offers_only_once_options(tmp_path):
    async def choose(questions):
        options = questions[0]["options"]
        assert [option["label"] for option in options] == ["1. Allow", "2. Reject"]
        return {"permission": ["1. Allow"]}

    asyncio.run(HermesAdapter().run(request_for(tmp_path, "permission"),
                                    lambda *_: None, choose, lambda _value: None))


def test_hermes_safe_check_does_not_surface_command_output(monkeypatch, tmp_path):
    from easel.harnesses import hermes

    captured = []
    class Result:
        returncode = 2
        stdout = ""
        stderr = "private token fake-secret-never-print"
    monkeypatch.setattr(hermes, "hermes_command", lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"))
    monkeypatch.setattr(hermes.subprocess, "run", lambda command, **kwargs: (captured.append(command) or Result()))
    info = describe("hermes")
    assert info["installed"] is False
    assert "fake-secret" not in str(info)
    assert captured[0][-2:] == ["acp", "--check"]


def test_hermes_readiness_check_uses_sanitized_environment(monkeypatch):
    from easel.harnesses import hermes

    captured = {}
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""
    monkeypatch.setattr(hermes, "hermes_command", lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"))
    monkeypatch.setattr(hermes.subprocess, "run", lambda command, **kwargs: (captured.update(kwargs) or Result()))
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")

    assert hermes.available() is True
    assert captured["env"]["PATH"] == "/usr/bin"
    assert "GITHUB_TOKEN" not in captured["env"]
    assert "OPENAI_API_KEY" not in captured["env"]
    assert "synthetic" not in repr(captured["env"])


def test_hermes_unknown_and_windows_shim_fail_closed(monkeypatch):
    monkeypatch.setattr("easel.harnesses.commands.shutil.which", lambda _name: r"C:\\tools\\hermes.cmd")
    with pytest.raises(HarnessError, match="Windows"):
        hermes_command()


def test_hermes_profile_skill_sync_copies_only_missing_skills(tmp_path, monkeypatch):
    from easel.commands.hermes_skills import sync_skills

    source = tmp_path / "source"
    (source / "skill-a").mkdir(parents=True)
    (source / "skill-a" / "SKILL.md").write_text("managed", encoding="utf-8")
    (source / "skill-b").mkdir()
    (source / "skill-b" / "SKILL.md").write_text("new", encoding="utf-8")
    root = tmp_path / ".hermes"
    home = root / "profiles" / "easel"
    (home / "skills" / "skill-a").mkdir(parents=True)
    (home / "skills" / "skill-a" / "SKILL.md").write_text("user-owned", encoding="utf-8")

    copied, skipped = sync_skills(source=source, root=root)
    assert copied == ["skill-b"]
    assert skipped == ["skill-a"]
    assert (home / "skills" / "skill-a" / "SKILL.md").read_text() == "user-owned"
    assert (home / "skills" / "skill-b" / "SKILL.md").read_text() == "new"


def test_hermes_skill_sync_does_not_follow_source_symlinks(tmp_path):
    from easel.commands.hermes_skills import sync_skills

    source = tmp_path / "source"
    skill = source / "skill-a"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("managed", encoding="utf-8")
    external = tmp_path / "outside-secret.txt"
    external.write_text("not part of this skill", encoding="utf-8")
    try:
        (skill / "linked-file.txt").symlink_to(external)
    except OSError:
        pytest.skip("symlink creation is not available")

    root = tmp_path / ".hermes"
    home = root / "profiles" / "easel"
    home.mkdir(parents=True)
    copied, _skipped = sync_skills(source=source, root=root)

    assert copied == ["skill-a"]
    assert not (home / "skills" / "skill-a" / "linked-file.txt").exists()


def test_hermes_skill_sync_resolves_profile_home_from_cli(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from easel.commands import hermes_skills

    home_root = tmp_path / "custom-root"
    config_path = home_root / "profiles" / "easel" / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(home_root))
    captured = {}
    monkeypatch.setattr(hermes_skills, "hermes_command",
                        lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"), raising=False)
    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs.get("env", {})
        return SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-github-token")

    assert hermes_skills.profile_home() == config_path.parent
    assert captured["command"] == ["/fake/hermes", "--profile", "easel", "config", "path"]
    assert "GITHUB_TOKEN" not in captured["env"]


def test_hermes_skill_sync_refuses_to_create_a_missing_profile(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from easel.commands import hermes_skills

    home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(hermes_skills, "hermes_command",
                        lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"), raising=False)
    monkeypatch.setattr(subprocess, "run",
                        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="synthetic-secret"))
    source = tmp_path / "source"
    (source / "skill-a").mkdir(parents=True)
    (source / "skill-a" / "SKILL.md").write_text("managed", encoding="utf-8")

    with pytest.raises(RuntimeError, match="profile.*create"):
        hermes_skills.sync_skills(source=source)
    assert not (home / "profiles" / "easel").exists()


def test_hermes_skill_sync_rejects_cli_path_outside_selected_home(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from easel.commands import hermes_skills

    home_root = tmp_path / "hermes-home"
    outside_profile = tmp_path / "attacker" / "profiles" / "easel"
    outside_profile.mkdir(parents=True)
    config_path = outside_profile / "config.yaml"
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home_root))
    monkeypatch.setattr(hermes_skills, "hermes_command",
                        lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"), raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr=""))

    with pytest.raises(RuntimeError, match="unexpected config path"):
        hermes_skills.sync_skills(source=source)
    assert not (outside_profile / "skills").exists()


def test_hermes_skill_sync_rejects_symlinked_profile_directory(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from easel.commands import hermes_skills

    home_root = tmp_path / "hermes-home"
    profiles = home_root / "profiles"
    profiles.mkdir(parents=True)
    outside_profile = tmp_path / "outside-profile"
    outside_profile.mkdir()
    try:
        (profiles / "easel").symlink_to(outside_profile, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available")
    config_path = profiles / "easel" / "config.yaml"
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home_root))
    monkeypatch.setattr(hermes_skills, "hermes_command",
                        lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"), raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr=""))

    with pytest.raises(RuntimeError, match="symlink"):
        hermes_skills.sync_skills(source=source)
    assert not (outside_profile / "skills").exists()


def test_hermes_skill_sync_rejects_symlinked_skills_directory(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace
    from easel.commands import hermes_skills

    home_root = tmp_path / "hermes-home"
    profile = home_root / "profiles" / "easel"
    profile.mkdir(parents=True)
    outside_skills = tmp_path / "outside-skills"
    outside_skills.mkdir()
    try:
        (profile / "skills").symlink_to(outside_skills, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not available")
    source = tmp_path / "source"
    source.mkdir()
    managed = source / "managed-skill"
    managed.mkdir()
    (managed / "SKILL.md").write_text("managed", encoding="utf-8")
    config_path = profile / "config.yaml"
    monkeypatch.setenv("HERMES_HOME", str(home_root))
    monkeypatch.setattr(hermes_skills, "hermes_command",
                        lambda **kwargs: ("/fake/hermes", "--profile", "easel", "acp"), raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr=""))

    with pytest.raises(RuntimeError, match="symlink"):
        hermes_skills.sync_skills(source=source)
    assert not (outside_skills / "managed-skill").exists()
