from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-moneyprinterturbo.sh"


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _source_call(function_call: str) -> subprocess.CompletedProcess[str]:
    return _run("bash", "-c", f'source "$1"; {function_call}', "bash", str(INSTALLER))


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True)
    assert _run("git", "init", "-q", str(path)).returncode == 0
    assert _run("git", "config", "user.email", "tests@example.invalid", cwd=path).returncode == 0
    assert _run("git", "config", "user.name", "Tests", cwd=path).returncode == 0
    (path / "tracked.txt").write_text("clean\n", encoding="utf-8")
    assert _run("git", "add", "tracked.txt", cwd=path).returncode == 0
    assert _run("git", "commit", "-qm", "fixture", cwd=path).returncode == 0
    result = _run("git", "rev-parse", "HEAD", cwd=path)
    assert result.returncode == 0
    return result.stdout.strip()


def test_installer_pins_tag_commit_and_frozen_uv_sync():
    text = INSTALLER.read_text(encoding="utf-8")

    assert "MPT_TAG=v1.3.7" in text
    assert "MPT_COMMIT=cf5a3aedad1741d012152d355aa909d224fc4557" in text
    assert "uv sync --frozen" in text
    assert "mv \"$stage_source\" \"$source_dir\"" in text
    lowered = text.lower()
    assert "docker" not in lowered
    assert "conda" not in lowered
    assert "pip install" not in lowered


def test_check_rejects_missing_non_git_wrong_revision_and_dirty_source(tmp_path):
    missing = _run("bash", str(INSTALLER), "--check", "--root", str(tmp_path))
    assert missing.returncode != 0
    assert "missing" in (missing.stdout + missing.stderr).lower()

    source = tmp_path / ".tools" / "moneyprinterturbo" / "source"
    source.mkdir(parents=True)
    marker = source / "keep-me.txt"
    marker.write_text("preserve", encoding="utf-8")
    non_git = _run("bash", str(INSTALLER), "--check", "--root", str(tmp_path))
    assert non_git.returncode != 0
    assert "not a git checkout" in (non_git.stdout + non_git.stderr).lower()
    assert marker.read_text(encoding="utf-8") == "preserve"

    marker.unlink()
    source.rmdir()
    actual = _git_repo(source)
    wrong = _source_call(f'check_source_checkout "{source}" "0000000000000000000000000000000000000000"')
    assert wrong.returncode != 0
    assert "wrong revision" in (wrong.stdout + wrong.stderr).lower()

    (source / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = _source_call(f'check_source_checkout "{source}" "{actual}"')
    assert dirty.returncode != 0
    assert "dirty" in (dirty.stdout + dirty.stderr).lower()
    assert len(dirty.stdout + dirty.stderr) < 2_000


def test_installer_never_deletes_an_unsafe_existing_path(tmp_path):
    source = tmp_path / ".tools" / "moneyprinterturbo" / "source"
    source.mkdir(parents=True)
    marker = source / "user-data.txt"
    marker.write_text("must survive", encoding="utf-8")

    result = _run("bash", str(INSTALLER), "--install", "--root", str(tmp_path))

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "must survive"
    assert len(result.stdout + result.stderr) < 2_000


def test_runtime_links_must_resolve_inside_moneyprinterturbo_state(tmp_path):
    state = tmp_path / ".state" / "moneyprinterturbo"
    state.mkdir(parents=True)
    expected = state / "config.toml"
    expected.write_text("managed", encoding="utf-8")
    source = tmp_path / ".tools" / "moneyprinterturbo" / "source"
    source.mkdir(parents=True)
    safe_link = source / "config.toml"
    safe_link.symlink_to(os.path.relpath(expected, source))

    safe = _source_call(f'check_managed_link "{safe_link}" "{expected}"')
    assert safe.returncode == 0, safe.stderr

    outside = tmp_path / "outside.toml"
    outside.write_text("outside", encoding="utf-8")
    safe_link.unlink()
    safe_link.symlink_to(outside)
    unsafe = _source_call(f'check_managed_link "{safe_link}" "{expected}"')
    assert unsafe.returncode != 0
    assert "unexpected target" in (unsafe.stdout + unsafe.stderr).lower()


def test_moneyprinterturbo_runtime_directories_are_gitignored():
    tools = _run("git", "check-ignore", "-q", ".tools/moneyprinterturbo/probe", cwd=ROOT)
    state = _run("git", "check-ignore", "-q", ".state/moneyprinterturbo/probe", cwd=ROOT)

    assert tools.returncode == 0
    assert state.returncode == 0
