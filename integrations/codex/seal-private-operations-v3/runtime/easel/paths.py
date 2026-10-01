"""Canonical paths for the self-contained Seal V3 runtime."""
from __future__ import annotations

import os
from pathlib import Path


RUNTIME_ROOT = Path(
    os.environ.get("SEAL_RUNTIME_ROOT", Path(__file__).resolve().parents[1])
).expanduser().resolve()
SKILL_ROOT = Path(
    os.environ.get("SEAL_SKILL_ROOT", RUNTIME_ROOT.parent)
).expanduser().resolve()
BUNDLED_SKILLS_DIR = Path(
    os.environ.get("SEAL_BUNDLED_SKILLS", SKILL_ROOT / "bundled-skills")
).expanduser().resolve()
PROFILES_DIR = RUNTIME_ROOT / "profiles"
OUTPUTS_DIR = RUNTIME_ROOT / "outputs"


def venv_bin_dir(platform: str | None = None) -> Path:
    return RUNTIME_ROOT / ".venv" / ("Scripts" if (platform or os.name) == "nt" else "bin")


def node_bin_dir() -> Path:
    return RUNTIME_ROOT / "tools" / "node_modules" / ".bin"


def media_bin_dir() -> Path | None:
    configured = os.environ.get("SEAL_MEDIA_BIN", "").strip()
    if configured:
        return Path(configured).expanduser()
    marker = RUNTIME_ROOT / ".seal-media-bin"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            path = Path(value).expanduser()
            return path if path.is_absolute() else RUNTIME_ROOT / path
    return None


def runtime_path_entries() -> list[str]:
    entries = [str(venv_bin_dir()), str(node_bin_dir())]
    media = media_bin_dir()
    if media:
        entries.insert(0, str(media))
    return entries
