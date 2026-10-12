import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from easel import cli, runtime_env


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_env.Path, "home", staticmethod(lambda: tmp_path))
    discover = runtime_env._installation_directories
    monkeypatch.setattr(runtime_env, "_installation_directories", lambda environment, home: [
        directory for directory in discover(environment, home) if directory.is_relative_to(tmp_path)])
    return tmp_path


def executable(directory, name):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_recovers_nvm_agents_and_matching_node(home):
    older = home / ".nvm/versions/node/v22.22.0/bin"
    newer = home / ".nvm/versions/node/v24.21.0/bin"
    for directory in (older, newer):
        executable(directory, "node")
        executable(directory, "openclaw")
    executable(newer, "opencode")
    original = {"PATH": str(home / "empty"), "EASEL_AGENT_RUNTIME": "openclaw", "API_KEY": "unchanged"}
    result = runtime_env.web_environment(original)
    assert result["PATH"].split(os.pathsep)[1] == str(newer)
    assert runtime_env.shutil.which("openclaw", path=result["PATH"]) == str(newer / "openclaw")
    assert runtime_env.shutil.which("opencode", path=result["PATH"]) == str(newer / "opencode")
    assert runtime_env.shutil.which("node", path=result["PATH"]) == str(newer / "node")
    assert result["API_KEY"] == original["API_KEY"]
    assert result["EASEL_AGENT_RUNTIME"] == "openclaw"
    assert original["PATH"] == str(home / "empty")


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_preserves_an_existing_complete_path(home):
    current = home / "current"
    for name in ("openclaw", "opencode", "codex", "node"):
        executable(current, name)
    executable(home / ".opencode/bin", "opencode")
    environment = {"PATH": str(current)}
    assert runtime_env.web_environment(environment) == environment


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_ignores_absent_and_nonexecutable_agents(home):
    directory = home / ".local/bin"
    directory.mkdir(parents=True)
    (directory / "opencode").write_text("not executable", encoding="utf-8")
    environment = {"PATH": str(home / "empty")}
    assert runtime_env.web_environment(environment) == environment


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_supports_user_and_custom_prefixes(home):
    prefix = home / "custom prefix"
    native = home / ".opencode/bin"
    executable(prefix / "bin", "openclaw")
    executable(native, "opencode")
    environment = {"PATH": str(home / "empty"), "EASEL_NPM_GLOBAL_PREFIX": str(prefix)}
    result = runtime_env.web_environment(environment)
    assert runtime_env.shutil.which("openclaw", path=result["PATH"]) == str(prefix / "bin/openclaw")
    assert runtime_env.shutil.which("opencode", path=result["PATH"]) == str(native / "opencode")


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_prefers_explicit_easel_prefix(home):
    preferred = home / "easel-prefix"
    fallback = home / "npm-prefix"
    executable(preferred / "bin", "openclaw")
    executable(fallback / "bin", "openclaw")
    environment = {"PATH": str(home / "empty"), "EASEL_NPM_GLOBAL_PREFIX": str(preferred),
                   "npm_config_prefix": str(fallback)}
    result = runtime_env.web_environment(environment)
    assert runtime_env.shutil.which("openclaw", path=result["PATH"]) == str(preferred / "bin/openclaw")


def test_web_environment_preserves_windows_path(home, monkeypatch):
    monkeypatch.setattr(runtime_env, "WINDOWS", True)
    environment = {"PATH": r"C:\Tools;C:\Windows"}
    assert runtime_env.web_environment(environment) == environment


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_does_not_replace_existing_cli_or_node(home):
    current = home / "current"
    recovered = home / ".nvm/versions/node/v24.21.0/bin"
    for name in ("codex", "node"):
        executable(current, name)
        executable(recovered, name)
    executable(recovered, "openclaw")
    executable(recovered, "opencode")
    result = runtime_env.web_environment({"PATH": str(current)})
    assert runtime_env.shutil.which("codex", path=result["PATH"]) == str(current / "codex")
    assert runtime_env.shutil.which("node", path=result["PATH"]) == str(current / "node")
    assert runtime_env.shutil.which("openclaw", path=result["PATH"]) == str(recovered / "openclaw")
    assert runtime_env.web_environment(result) == result


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
@pytest.mark.parametrize("custom_config", [False, True])
def test_web_environment_reads_npmrc_prefix_with_spaces(home, custom_config):
    prefix = home / "custom npm prefix"
    config = home / ("custom.npmrc" if custom_config else ".npmrc")
    config.write_text(f'# settings\nprefix = "{prefix}"\n', encoding="utf-8")
    executable(prefix / "bin", "opencode")
    environment = {"PATH": str(home / "empty")}
    if custom_config:
        environment["NPM_CONFIG_USERCONFIG"] = str(config)
    result = runtime_env.web_environment(environment)
    assert runtime_env.shutil.which("opencode", path=result["PATH"]) == str(prefix / "bin/opencode")


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
@pytest.mark.parametrize("variable,relative", [
    ("NVM_DIR", "versions/node/v24.21.0/bin"),
    ("FNM_DIR", "node-versions/v24.21.0/installation/bin"),
    ("VOLTA_HOME", "bin"),
    ("HOMEBREW_PREFIX", "bin"),
])
def test_web_environment_supports_custom_node_installations(home, variable, relative):
    root = home / "node toolchain"
    directory = root / relative
    executable(directory, "openclaw")
    executable(directory, "opencode")
    executable(directory, "node")
    result = runtime_env.web_environment({"PATH": str(home / "empty"), variable: str(root)})
    assert runtime_env.shutil.which("openclaw", path=result["PATH"]) == str(directory / "openclaw")
    assert runtime_env.shutil.which("opencode", path=result["PATH"]) == str(directory / "opencode")


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_recovers_node_even_when_agents_are_on_path(home):
    current = home / "current"
    for name in ("openclaw", "opencode", "codex"):
        executable(current, name)
    node = executable(home / ".nvm/versions/node/v24.21.0/bin", "node")
    result = runtime_env.web_environment({"PATH": str(current)})
    assert runtime_env.shutil.which("node", path=result["PATH"]) == str(node)


def windows_which(command, path=None):
    for directory in (path or "").split(";"):
        for suffix in (".exe", ".cmd", ".bat"):
            candidate = Path(directory) / f"{command}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return None


@pytest.mark.parametrize("installation", ["appdata", "custom-prefix", "nvm"])
def test_web_environment_recovers_windows_user_installations(home, monkeypatch, installation):
    monkeypatch.setattr(runtime_env, "WINDOWS", True)
    monkeypatch.setattr(runtime_env.shutil, "which", windows_which)
    environment = {"Path": str(home / "empty"), "APPDATA": str(home / "Roaming")}
    if installation == "appdata":
        directory = home / "Roaming/npm"
    elif installation == "custom-prefix":
        directory = home / "custom npm prefix"
        environment["EASEL_NPM_GLOBAL_PREFIX"] = str(directory)
    else:
        directory = home / "nvm/v24.21.0"
        environment["NVM_HOME"] = str(home / "nvm")
    for name in ("openclaw.cmd", "opencode.cmd", "codex.cmd", "node.exe"):
        executable(directory, name)
    result = runtime_env.web_environment(environment)
    assert "PATH" not in result
    assert result["Path"].split(";")[0] == environment["Path"]
    for name in ("openclaw", "opencode", "codex", "node"):
        assert windows_which(name, result["Path"]) == str(directory / (f"{name}.exe" if name == "node" else f"{name}.cmd"))
    assert runtime_env.web_environment(result) == result


@pytest.mark.skipif(os.name == "nt", reason="Unix user installation directories")
def test_web_environment_does_not_discover_other_users(home):
    other = home.parent / "other-user"
    executable(other / ".local/bin", "opencode")
    environment = {"PATH": str(home / "empty")}
    assert runtime_env.web_environment(environment) == environment


def test_web_environment_tolerates_inaccessible_installations(home, monkeypatch):
    discover = Mock(side_effect=PermissionError("cannot inspect home"))
    monkeypatch.setattr(runtime_env, "_installation_directories", discover)
    environment = {"PATH": str(home / "empty")}
    assert runtime_env.web_environment(environment) == environment


def test_web_launcher_passes_recovered_environment(monkeypatch):
    environment = {"PATH": "/current", "EASEL_AGENT_RUNTIME": "openclaw"}
    recovered = {**environment, "PATH": "/agents:/current"}
    monkeypatch.setattr(cli, "_proxy_env", lambda: environment)
    resolve = Mock(return_value=recovered)
    monkeypatch.setattr(runtime_env, "web_environment", resolve)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.cmd_web(SimpleNamespace(port=7860)) == 0
    resolve.assert_called_once_with(environment)
    assert run.call_args.kwargs["env"]["PATH"] == "/agents:/current"
    assert run.call_args.kwargs["env"]["EASEL_PORT"] == "7860"
    assert run.call_args.kwargs["cwd"] == str(Path(cli.PROJECT_ROOT))
