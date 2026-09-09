"""Resolve the openclaw executable as [node, openclaw.mjs].

Windows pitfall this solves: `openclaw` on PATH is a `.cmd` shim. Python's
CreateProcess cannot run it directly, and wrapping in cmd.exe /c breaks
messages containing newlines (cmd treats the rest of the line as a separate
command -> "your message got cut off" / silently truncated input).

Running node + openclaw.mjs directly avoids both problems on all platforms.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def openclaw_base_cmd() -> list[str]:
    """Return [node, /path/to/openclaw.mjs] (raise FileNotFoundError if missing)."""
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node not found on PATH")

    node_dir = Path(node).resolve().parent
    candidates = [
        # npm global prefix == node dir (zip/nvm-style installs)
        node_dir / "node_modules" / "openclaw" / "openclaw.mjs",
        # npm global prefix == %APPDATA%/npm (standard Windows installs)
        Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "openclaw" / "openclaw.mjs",
    ]
    for cand in candidates:
        if cand.is_file():
            return [node, str(cand)]

    raise FileNotFoundError(
        "openclaw.mjs not found under npm global dirs (node_dir / %APPDATA%/npm)"
    )
