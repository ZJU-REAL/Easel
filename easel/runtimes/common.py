"""Small shared runtime helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def env_file_value(name: str, path: Path | None = None) -> str | None:
    try:
        lines = (path or ENV_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key.replace("_", "a").isalnum():
            env.setdefault(key, value.strip().strip('"').strip("'"))
    env.setdefault("EASEL_ROOT", str(PROJECT_ROOT))
    return env


def clean_output(output: str) -> str:
    hidden = ("[provider-", "[agents/", "[agent/", "[plugins]", "[tools]",
              "[diagnostic]", "[fetch-", "[heartbeat]", "[health-", "[gateway]")
    lines = []
    for line in output.splitlines():
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
        if clean.startswith("[") and any(tag in clean[:40] for tag in hidden):
            continue
        if clean.strip():
            lines.append(clean)
    return "\n".join(lines).strip()
