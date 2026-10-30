from __future__ import annotations

import os
import shutil
from pathlib import Path


WINDOWS = os.name == "nt"


def _version_directories(root: Path, pattern: str) -> list[Path]:
    versions = []
    try:
        for directory in root.glob(pattern):
            version_name = next((part for part in reversed(directory.parts) if part.startswith("v")), "")
            parts = version_name[1:].split(".")
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                versions.append((tuple(int(part) for part in parts), directory))
    except OSError:
        return []
    return [directory for version, directory in sorted(versions, reverse=True)]


def _installation_directories(environment: dict[str, str], home: Path) -> list[Path]:
    from easel.openclaw_cmd import _npmrc_prefix

    directories = []
    prefixes = []
    for variable in ("EASEL_NPM_GLOBAL_PREFIX", "npm_config_prefix", "NPM_CONFIG_PREFIX"):
        if environment.get(variable):
            prefixes.append(Path(environment[variable]).expanduser())
    user_config = environment.get("NPM_CONFIG_USERCONFIG") or environment.get("npm_config_userconfig")
    configs = [Path(__file__).resolve().parents[1] / ".npmrc",
               Path(user_config).expanduser() if user_config else home / ".npmrc"]
    for config in configs:
        prefix = _npmrc_prefix(config)
        if prefix is not None:
            prefixes.append(prefix if prefix.is_absolute() else config.parent / prefix)
    prefixes.append(home / ".npm-global")
    directories.extend(prefix if WINDOWS else prefix / "bin" for prefix in prefixes)
    directories.extend([home / ".local" / "bin", home / ".opencode" / "bin",
                        Path(environment.get("VOLTA_HOME") or home / ".volta").expanduser() / "bin"])
    if WINDOWS:
        appdata = Path(environment.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(environment.get("LOCALAPPDATA") or home / "AppData" / "Local")
        directories.extend([appdata / "npm", local / "Programs" / "nodejs"])
        for variable in ("NVM_SYMLINK", "NVM_HOME"):
            if environment.get(variable):
                directories.append(Path(environment[variable]).expanduser())
        if environment.get("NVM_HOME"):
            directories.extend(_version_directories(Path(environment["NVM_HOME"]).expanduser(), "v*"))
        if environment.get("ProgramFiles"):
            directories.append(Path(environment["ProgramFiles"]) / "nodejs")
    else:
        nvm_root = Path(environment.get("NVM_DIR") or home / ".nvm").expanduser()
        directories.extend(_version_directories(nvm_root / "versions" / "node", "v*/bin"))
        if environment.get("NVM_BIN"):
            directories.append(Path(environment["NVM_BIN"]).expanduser())
        if environment.get("FNM_MULTISHELL_PATH"):
            directories.append(Path(environment["FNM_MULTISHELL_PATH"]).expanduser() / "bin")
        fnm_roots = [Path(environment["FNM_DIR"]).expanduser()] if environment.get("FNM_DIR") else [
            Path(environment.get("XDG_DATA_HOME") or home / ".local" / "share") / "fnm",
            home / "Library" / "Application Support" / "fnm",
        ]
        for root in fnm_roots:
            directories.extend(_version_directories(root / "node-versions", "v*/installation/bin"))
        brew = Path(environment.get("HOMEBREW_PREFIX") or "/opt/homebrew")
        directories.extend([brew / "opt" / "node@24" / "bin", brew / "opt" / "node@22" / "bin",
                            brew / "opt" / "node" / "bin", brew / "bin", Path("/usr/local/bin"), Path("/usr/bin")])
    return directories


def web_environment(environment: dict[str, str]) -> dict[str, str]:
    """Find user-installed Agent CLIs when a non-interactive launcher loses PATH."""
    result = dict(environment)
    path_key = next((key for key in result if key.upper() == "PATH"), "PATH") if WINDOWS else "PATH"
    current_path = result.get(path_key, os.defpath)
    missing = {command for command in ("openclaw", "opencode", "codex", "hermes", "node")
               if shutil.which(command, path=current_path) is None}
    if not missing:
        return result
    try:
        directories = _installation_directories(result, Path.home())
    except (OSError, RuntimeError):
        return result
    separator = ";" if WINDOWS else os.pathsep
    seen = {os.path.normcase(directory) for directory in current_path.split(separator)}
    additions = []
    for directory in directories:
        if os.path.normcase(str(directory)) in seen:
            continue
        seen.add(os.path.normcase(str(directory)))
        found = {command for command in missing
                 if shutil.which(command, path=str(directory)) is not None}
        if not found:
            continue
        additions.append(str(directory))
        missing -= found
        if not missing:
            break
    if additions:
        result[path_key] = separator.join([current_path, *additions])
    return result
