"""Resolve the package selected by an npm shim, including mixed V1/V2 installs."""
import pytest

from easel.harnesses import describe
from easel.harnesses.base import HarnessError
from easel.harnesses.commands import base_command


def install_entry(tmp_path, package, entry):
    path = tmp_path / "node_modules" / package / "bin" / entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def launcher_for(tmp_path, monkeypatch, package, entry, suffix=".cmd", prefix="%dp0%\\"):
    launcher = tmp_path / f"opencode{suffix}"
    target = f"{package}/bin/{entry}".replace("/", "\\")
    program = ('endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "%_prog%"  '
               if entry == "opencode" else "")
    launcher.write_text(f'@ECHO off\n{program}"{prefix}node_modules\\{target}" %*\n', encoding="utf-8")
    monkeypatch.setattr("easel.harnesses.commands.shutil.which",
                        lambda command: str(tmp_path / "node.exe") if command == "node" else str(launcher))
    return launcher


@pytest.mark.parametrize("package", ["@opencode/cli", "opencode-ai"])
@pytest.mark.parametrize("entry", ["opencode", "opencode.exe"])
@pytest.mark.parametrize("suffix", [".cmd", ".bat"])
def test_windows_opencode_matches_installed_wrapper(tmp_path, monkeypatch, package, entry, suffix):
    expected = install_entry(tmp_path, package, entry)
    launcher_for(tmp_path, monkeypatch, package, entry, suffix)
    assert base_command("opencode") == ([str(expected)] if entry.endswith(".exe") else [
        str(tmp_path / "node.exe"), str(expected)])
    assert describe("opencode")["installed"] is True


@pytest.mark.parametrize("package", ["@opencode/cli", "opencode-ai"])
@pytest.mark.parametrize("entry", ["opencode", "opencode.exe"])
def test_mixed_packages_do_not_override_wrapper_selection(tmp_path, monkeypatch, package, entry):
    for installed in ("@opencode/cli", "opencode-ai"):
        for filename in ("opencode", "opencode.exe"):
            install_entry(tmp_path, installed, filename)
    launcher_for(tmp_path, monkeypatch, package, entry)
    expected = tmp_path / "node_modules" / package / "bin" / entry
    assert base_command("opencode") == ([str(expected)] if entry.endswith(".exe") else [
        str(tmp_path / "node.exe"), str(expected)])


@pytest.mark.parametrize("package", ["@opencode/cli", "opencode-ai"])
def test_missing_selected_package_does_not_launch_other_version(tmp_path, monkeypatch, package):
    other = "opencode-ai" if package == "@opencode/cli" else "@opencode/cli"
    install_entry(tmp_path, other, "opencode.exe")
    launcher_for(tmp_path, monkeypatch, package, "opencode.exe")
    with pytest.raises(HarnessError, match="Windows npm 启动入口"):
        base_command("opencode")
    assert describe("opencode")["installed"] is False


@pytest.mark.parametrize("prefix", ["%~dp0", "%~dp0\\", "%dp0%/"])
def test_standard_batch_directory_variants(tmp_path, monkeypatch, prefix):
    expected = install_entry(tmp_path, "@opencode/cli", "opencode.exe")
    launcher_for(tmp_path, monkeypatch, "@opencode/cli", "opencode.exe", prefix=prefix)
    assert base_command("opencode") == [str(expected)]


def test_windows_opencode_js_uses_adjacent_node(tmp_path, monkeypatch):
    expected = install_entry(tmp_path, "@opencode/cli", "opencode")
    launcher_for(tmp_path, monkeypatch, "@opencode/cli", "opencode")
    node = tmp_path / "node.exe"
    node.touch()
    monkeypatch.setattr("easel.harnesses.commands.shutil.which",
                        lambda command: str(tmp_path / "wrong-node.exe") if command == "node" else str(
                            tmp_path / "opencode.cmd"))
    assert base_command("opencode") == [str(node), str(expected)]


def test_missing_js_entry_does_not_substitute_adjacent_native_binary(tmp_path, monkeypatch):
    install_entry(tmp_path, "@opencode/cli", "opencode.exe")
    launcher_for(tmp_path, monkeypatch, "@opencode/cli", "opencode")
    with pytest.raises(HarnessError, match="Windows npm 启动入口不存在"):
        base_command("opencode")


@pytest.mark.parametrize("content", [
    "@ECHO off\n",
    'REM "%dp0%\\node_modules\\opencode-ai\\bin\\opencode.exe" %*\n',
    'echo "%dp0%\\node_modules\\opencode-ai\\bin\\opencode.exe" %*\n',
    '"%dp0%\\node_modules\\unknown\\bin\\opencode.exe" %*\n',
    '"%dp0%\\node_modules\\@opencode\\cli\\bin\\..\\opencode.exe" %*\n',
    '"%dp0%\\node_modules\\@opencode\\cli\\bin\\opencode.exe" %*\n'
    '"%dp0%\\node_modules\\opencode-ai\\bin\\opencode.exe" %*\n',
    "x" * (64 * 1024 + 1),
], ids=["empty", "comment", "echo", "unknown-package", "traversal", "ambiguous", "oversize"])
def test_unrecognized_or_ambiguous_wrapper_does_not_guess_package(tmp_path, monkeypatch, content):
    install_entry(tmp_path, "opencode-ai", "opencode.exe")
    install_entry(tmp_path, "@opencode/cli", "opencode.exe")
    launcher = launcher_for(tmp_path, monkeypatch, "@opencode/cli", "opencode.exe")
    launcher.write_text(content, encoding="utf-8")
    with pytest.raises(HarnessError, match="Windows npm 启动入口"):
        base_command("opencode")


def test_opencode_install_hint_uses_v2_package():
    assert "npm install -g @opencode/cli" in describe("opencode")["install_hint"]
