from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from easel.harnesses import store
from easel import installation

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="POSIX installer")
@pytest.mark.parametrize("runtime", ["codex", "opencode"])
@pytest.mark.parametrize("existing", [False, True])
def test_skip_run_installs_web_without_overwriting_native_selection(tmp_path, runtime, existing):
    shutil.copy(ROOT / "setup.sh", tmp_path / "setup.sh")
    (tmp_path / "web" / "frontend").mkdir(parents=True)
    (tmp_path / ".env.example").write_text("ANTHROPIC_API_KEY=sk-ant-REPLACE_ME\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("EASEL_CHAT_TRANSPORT=http\nOPENAI_API_KEY=keep-secret\n", encoding="utf-8")
    original_env = env_file.read_bytes()
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    native_settings = {"runtime": runtime, "models": {runtime: "private-model"}, "sandbox": "read-only"}
    if existing:
        store.write_json(config_path, native_settings)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    for command in ("python3", "node", "npm", "easel", "ffmpeg", "openclaw", runtime):
        source = "#!/bin/bash\n"
        source += f'printf "%s\\n" {shlex.quote(command)} >> {shlex.quote(str(calls))}\n'
        if command == "node":
            source += 'echo v22.19.0\n'
        elif command == "ffmpeg":
            source += "echo 'ffmpeg version 9'\n"
        elif command == "python3":
            source += (
                f'if [ "$1" = "-m" ] && [ "$2" = "easel.installation" ]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
                f'if [ "$1" = "-c" ] && [[ "$2" == *sys.version_info* ]]; then exec {shlex.quote(sys.executable)} "$@"; fi\n'
                'if [ "$1" = "--version" ]; then echo "Python 3.12.0"; fi\n')
        elif command in ("openclaw", runtime):
            source += "exit 91\n"
        source += "exit 0\n"
        binary = bin_dir / command
        binary.write_text(source, encoding="utf-8")
        binary.chmod(0o755)
    environment = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                   "PYTHONPATH": str(ROOT), "HOME": str(tmp_path / "home"),
                   "EASEL_PIP_INDEX": "https://example.invalid",
                   "EASEL_NPM_REGISTRY": "https://example.invalid"}
    environment.pop("EASEL_AGENT_RUNTIME", None)
    environment.pop("EASEL_SETUP_MODE", None)
    environment.pop("EASEL_SETUP_STRICT", None)
    process = subprocess.run(["bash", str(tmp_path / "setup.sh"), "--skip-openclaw"],
                             env=environment, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    assert "openclaw" not in calls.read_text().splitlines()
    assert runtime not in calls.read_text().splitlines()
    assert env_file.read_bytes() == original_env
    config = store.read_json(config_path)
    assert config == (native_settings if existing else {"runtime": "api"})
    assert "安装 Node.js" not in process.stdout
    assert "Codex / OpenCode" in process.stdout
    assert not (tmp_path / "home" / ".openclaw-easel").exists()


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="POSIX installer")
def test_conflicting_install_choices_stop_before_any_installation():
    process = subprocess.run(["bash", str(ROOT / "setup.sh"), "--skip-openclaw", "--openclaw"],
                             capture_output=True, text=True, timeout=10)
    assert process.returncode == 1
    assert "不能重复或同时指定" in process.stderr


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="POSIX installer")
@pytest.mark.parametrize(("answer", "expected"), [("n", "api true"), ("", "http false")])
def test_interactive_installation_choice(answer, expected):
    import pty

    source = (ROOT / "setup.sh").read_text(encoding="utf-8")
    selection = source[source.index('if [ "$INSTALL_CHOICE" = false ]'):source.index("# ---- 1. Node.js")]
    script = (
        "set -euo pipefail\nCHAT_MODE=http\nSKIP_OPENCLAW=false\nINSTALL_CHOICE=false\n"
        "SETUP_MODE=run\nDIM=''\nNC=''\nPROFILE=easel\ninfo() { :; }\n"
        'ask() { read -r REPLY; printf "%s" "$REPLY"; }\n'
        + selection + '\nprintf "\\nSELECTED=%s %s\\n" "$CHAT_MODE" "$SKIP_OPENCLAW"\n')
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(["bash", "-c", script], stdin=slave,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.write(master, (answer + "\n").encode())
        stdout, stderr = process.communicate(timeout=10)
    finally:
        os.close(master)
        os.close(slave)
    assert process.returncode == 0, stderr
    assert f"SELECTED={expected}" in stdout


@pytest.mark.parametrize("existing", [False, True])
def test_windows_skip_executes_real_branch_without_calling_openclaw(tmp_path, existing):
    executable = shutil.which("powershell") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("Requires PowerShell; exercised in Windows CI")
    (tmp_path / ".env.example").write_text("ANTHROPIC_API_KEY=sk-ant-REPLACE_ME\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=keep-secret\n", encoding="utf-8")
    original = env_file.read_bytes()
    config_path = tmp_path / "outputs" / "_harness" / "config.json"
    if existing:
        store.write_json(config_path, {"runtime": "codex", "models": {"codex": "native-model"}})
    source = (ROOT / "setup.ps1").read_text(encoding="utf-8-sig")
    install_start = source.index("if (-not $SkipOpenClaw) {\nStep '2/8'")
    install_end = source.index("Step '3/8'", install_start)
    profile_start = source.index("$envPath = Join-Path $Root '.env'")
    profile_end = source.index("\nShow-Summary", profile_start)
    script_path = tmp_path / "skip-probe.ps1"
    def ps_string(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference = 'Stop'\n$SkipOpenClaw = $true\n"
        f"$Root = {ps_string(tmp_path)}\n$Python = {ps_string(sys.executable)}\n"
        "function Info($Message) {}\nfunction Ok($Message) {}\n"
        "function Step($Index, $Title, $Subtitle) {}\n"
        "function Fail($Message) { throw $Message }\nfunction Read-EnvFile($Path) { return @{} }\n"
        "function openclaw { throw 'Must not call OpenClaw' }\n"
        "function npm { throw 'Must not install OpenClaw' }\n"
        "function Invoke-NativeCapture { throw 'Must not invoke OpenClaw or Gateway' }\n"
        + source[install_start:install_end] + source[profile_start:profile_end])
    script_path.write_text(script, encoding="utf-8-sig")
    environment = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1",
                   "PYTHONIOENCODING": "utf-8"}
    environment.pop("EASEL_AGENT_RUNTIME", None)
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
        cwd=tmp_path, env=environment, capture_output=True, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")
    assert env_file.read_bytes() == original
    assert store.read_json(config_path)["runtime"] == ("codex" if existing else "api")


@pytest.mark.parametrize("runtime", ["codex", "opencode"])
def test_skipped_install_can_save_native_harness_from_web(tmp_path, monkeypatch, runtime):
    import asyncio
    import web.app as web

    monkeypatch.delenv("EASEL_AGENT_RUNTIME", raising=False)
    monkeypatch.delenv("EASEL_CHAT_TRANSPORT", raising=False)
    monkeypatch.setattr(web, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(web, "OUTPUTS_DIR", tmp_path / "outputs")
    for name in ("_RUNNING_CHAT", "_BG_TASKS", "_DIRECT_CHAT_TASKS", "_HARNESS_TASKS"):
        monkeypatch.setattr(web, name, set())
    web.ENV_FILE.write_text("EASEL_CHAT_TRANSPORT=http\nOPENAI_API_KEY=keep-secret\n", encoding="utf-8")
    config = web.OUTPUTS_DIR / "_harness" / "config.json"
    config.unlink(missing_ok=True)
    installation.initialize_runtime(web.PROJECT_ROOT)
    assert web._harness_settings()["runtime"] == "api"
    monkeypatch.setattr(web.harnesses, "describe", lambda selected: {"id": selected, "installed": selected != "openclaw"})
    result = asyncio.run(web.api_harness_settings_save(web.HarnessSettingsRequest(runtime=runtime, model="native-model")))
    assert result["runtime"] == runtime
    assert result["locked"] is False
    assert web._harness_settings()["runtime"] == runtime
    assert "OPENAI_API_KEY=keep-secret" in web.ENV_FILE.read_text()
