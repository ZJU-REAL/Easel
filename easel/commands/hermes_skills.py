"""Safely seed Easel's built-in skills into the dedicated Hermes profile."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from easel.harnesses.base import HarnessError
from easel.harnesses.commands import hermes_command
from easel.harnesses.hermes import HermesAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = PROJECT_ROOT / "skills" / "builtin"


def profile_home(root: Path | None = None) -> Path:
    """Resolve the profile home without assuming a platform-specific Hermes path."""
    if root is not None:
        base = Path(root).expanduser()
        if base.name == "easel" and base.parent.name == "profiles":
            return base
        return base / "profiles" / "easel"

    home_root = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()
    profiles = home_root / "profiles"
    expected = profiles / "easel"
    if profiles.is_symlink() or expected.is_symlink():
        raise RuntimeError("Hermes easel profile path contains a symlink; refusing to sync skills.")

    try:
        command = hermes_command(profile="easel")
    except HarnessError:
        raise RuntimeError("Hermes CLI is unavailable; install Hermes before syncing its skills.") from None

    try:
        result = subprocess.run(
            [command[0], "--profile", "easel", "config", "path"],
            capture_output=True, text=True, timeout=10,
            env=HermesAdapter._profile_env(os.environ),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Could not resolve the Hermes easel profile; verify the Hermes CLI and profile.") from None

    config_path = result.stdout.strip()
    if result.returncode != 0 or not config_path:
        raise RuntimeError(
            "Hermes profile 'easel' is unavailable; create it first with "
            "'hermes profile create easel --no-skills'."
        )
    if len(config_path.splitlines()) != 1:
        raise RuntimeError("Hermes returned an unexpected config path for the easel profile.")
    config = Path(config_path.strip().strip('"').strip("'")).expanduser()
    if not config.is_absolute() or config.name not in {"config.yaml", "config.yml"}:
        raise RuntimeError("Hermes returned an unexpected config path for the easel profile.")
    if profiles.is_symlink() or expected.is_symlink():
        raise RuntimeError("Hermes easel profile path contains a symlink; refusing to sync skills.")
    if config.parent.resolve() != expected.resolve():
        raise RuntimeError("Hermes returned an unexpected config path for the easel profile.")
    return expected


def _ignore_symlinks(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if (Path(directory) / name).is_symlink()}


def sync_skills(*, source: Path = SKILLS_DIR, root: Path | None = None) -> tuple[list[str], list[str]]:
    """Copy missing skills only; any existing target skill remains user-owned."""
    home = profile_home(root)
    if home.is_symlink() or home.parent.is_symlink():
        raise RuntimeError("Hermes easel profile path contains a symlink; refusing to sync skills.")
    if not home.is_dir():
        raise RuntimeError("Hermes profile 'easel' is missing; create it before syncing skills.")
    if not source.is_dir():
        raise RuntimeError("Easel built-in skills directory is missing.")
    destination = home / "skills"
    if destination.is_symlink():
        raise RuntimeError("Hermes easel skills path contains a symlink; refusing to sync skills.")
    destination.mkdir(exist_ok=True)
    copied: list[str] = []
    skipped: list[str] = []
    for skill in sorted(source.iterdir()):
        if not skill.is_dir() or skill.is_symlink() or not (skill / "SKILL.md").is_file():
            continue
        target = destination / skill.name
        if target.exists() or target.is_symlink():
            skipped.append(skill.name)
            continue
        shutil.copytree(skill, target, symlinks=False, ignore=_ignore_symlinks)
        copied.append(skill.name)
    return copied, skipped


def main() -> int:
    try:
        copied, skipped = sync_skills()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Hermes easel profile: copied {len(copied)} missing skills; preserved {len(skipped)} existing skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
