"""Windows contracts that can be checked without pretending macOS is Windows."""
from pathlib import Path
from unittest.mock import Mock

from easel import codex_adapter as adapter
from easel.paths import RUNTIME_ROOT, venv_bin_dir


def test_windows_virtualenv_path():
    assert venv_bin_dir("nt") == RUNTIME_ROOT / ".venv" / "Scripts"
    assert venv_bin_dir("posix") == RUNTIME_ROOT / ".venv" / "bin"


def test_windows_cmd_codex_uses_comspec(monkeypatch):
    monkeypatch.setenv("EASEL_CODEX_BIN", r"C:\Program Files\Codex\codex.cmd")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    prefix = adapter.codex_command_prefix("nt")
    assert prefix[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert prefix[-1].endswith("codex.cmd")


def test_windows_exe_codex_runs_directly(monkeypatch):
    monkeypatch.setenv("EASEL_CODEX_BIN", r"C:\Tools\codex.exe")
    assert adapter.codex_command_prefix("nt") == [r"C:\Tools\codex.exe"]


def test_windows_process_creation_flag():
    flags = adapter._popen_platform_kwargs("nt")
    assert flags["creationflags"] != 0
    assert "start_new_session" not in flags


def test_posix_process_creation_is_preserved():
    assert adapter._popen_platform_kwargs("posix") == {"start_new_session": True}


def test_windows_terminate_then_kill_on_timeout():
    proc = Mock()
    proc.poll.return_value = None
    proc.wait.side_effect = [adapter.subprocess.TimeoutExpired("codex", 3), None]
    adapter._terminate(proc, "nt")
    proc.terminate.assert_called_once_with()
    proc.kill.assert_called_once_with()


def test_install_scripts_exist_and_do_not_require_git():
    root = Path(__file__).resolve().parents[2]
    windows = (root / "scripts/install-windows.ps1").read_text(encoding="utf-8")
    macos = (root / "scripts/install-macos.sh").read_text(encoding="utf-8")
    assert "git " not in windows.lower()
    assert "git " not in macos.lower()
    assert "ffmpeg" in windows.lower() and "ffmpeg" in macos.lower()
    assert windows.count("$LASTEXITCODE -ne 0") >= 14
    for step in ("Python 依赖", "Playwright Chromium", "Node.js 依赖", "前端", "完整性校验", "运行环境检查"):
        assert step in windows
