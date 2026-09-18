#!/usr/bin/env python3
"""Deterministic integrity checks for a Seal V3 installation or package."""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
BUNDLED = ROOT / "bundled-skills"
sys.path.insert(0, str(RUNTIME))

from easel.paths import runtime_path_entries  # noqa: E402

FORBIDDEN_DIRS = {
    "openclaw", "node_modules", "__pycache__", ".pytest_cache", ".playwright-cli",
    "browser-profiles", "outputs",
}
COOKIE_DATA_SUFFIXES = {"", ".json", ".jsonl", ".txt", ".db", ".sqlite", ".sqlite3"}
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def fail(message: str, problems: list[str]) -> None:
    problems.append(message)
    print(f"FAIL  {message}")


def ok(message: str) -> None:
    print(f"OK    {message}")


def runtime_path() -> str:
    return os.pathsep.join((*runtime_path_entries(), os.environ.get("PATH", "")))


def runtime_which(command: str) -> str | None:
    return shutil.which(command, path=runtime_path())


def ffmpeg_has_filters(command: str | None, required: tuple[str, ...]) -> bool:
    if not command:
        return False
    try:
        result = subprocess.run(
            [command, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=15,
            env={**os.environ, "PATH": runtime_path()},
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    output = result.stdout + result.stderr
    return result.returncode == 0 and all(re.search(rf"\b{re.escape(name)}\b", output) for name in required)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true", help="同时检查本机运行依赖")
    args = parser.parse_args()
    problems: list[str] = []

    required = [ROOT / "SKILL.md", ROOT / "launch.py", RUNTIME / "AGENTS.md", RUNTIME / "web/frontend/dist/index.html"]
    for path in required:
        ok(str(path.relative_to(ROOT))) if path.is_file() else fail(f"缺少 {path.relative_to(ROOT)}", problems)

    if os.name != "nt":
        launchers = [ROOT / "launch.py", ROOT / "scripts/install-macos.sh", ROOT / "scripts/start-macos.sh"]
        not_executable = [path for path in launchers if not os.access(path, os.X_OK)]
        ok("macOS 启动脚本具有可执行权限") if not not_executable else fail(
            "启动脚本不可执行: " + ", ".join(str(path.relative_to(ROOT)) for path in not_executable),
            problems,
        )

    skills = sorted(path for path in BUNDLED.iterdir() if path.is_dir() and (path / "CAPABILITY.md").is_file()) if BUNDLED.is_dir() else []
    ok("内置能力恰好 113 项") if len(skills) == 113 else fail(f"内置能力数量为 {len(skills)}，应为 113", problems)

    nested_skills = [path for path in ROOT.rglob("SKILL.md") if path != ROOT / "SKILL.md"]
    ok("内置能力不会注册为独立 Codex Skill") if not nested_skills else fail(
        "内置能力中仍存在 SKILL.md: " + ", ".join(str(path.relative_to(ROOT)) for path in nested_skills[:8]),
        problems,
    )

    forbidden_dirs = {"openclaw"} if args.runtime else FORBIDDEN_DIRS
    bad_dirs = [path for path in ROOT.rglob("*") if path.is_dir() and path.name.lower() in forbidden_dirs]
    if bad_dirs:
        fail("包内存在禁止目录: " + ", ".join(str(p.relative_to(ROOT)) for p in bad_dirs[:8]), problems)
    else:
        ok("无旧运行目录、依赖缓存或测试缓存")

    if not args.runtime:
        sensitive = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path == RUNTIME / ".env.example":
                continue
            is_env = path.name.lower() == ".env"
            is_cookie_data = "cookie" in path.stem.lower() and path.suffix.lower() in COOKIE_DATA_SUFFIXES
            if is_env or is_cookie_data:
                sensitive.append(path)
        if sensitive:
            fail("包内存在配置或登录态文件: " + ", ".join(str(p.relative_to(ROOT)) for p in sensitive[:8]), problems)
        else:
            ok("包内不含 .env、Cookie 或登录态文件")

    missing_refs = []
    pattern = re.compile(r"\.\./bundled-skills/([A-Za-z0-9._-]+)")
    for path in [RUNTIME / "AGENTS.md", *BUNDLED.rglob("*.md")]:
        text = path.read_text(encoding="utf-8", errors="replace")
        for name in pattern.findall(text):
            if not (BUNDLED / name).is_dir():
                missing_refs.append(f"{path.relative_to(ROOT)} -> {name}")
    ok("内置能力文档路径均可解析") if not missing_refs else fail("无效能力路径: " + ", ".join(missing_refs[:8]), problems)

    portable_files = [
        path for path in ROOT.rglob("*")
        if not any(part in {".venv", "node_modules", "__pycache__", ".pytest_cache"} for part in path.relative_to(ROOT).parts)
    ]
    invalid_windows_paths: list[str] = []
    casefolded: dict[str, str] = {}
    case_collisions: list[str] = []
    for path in portable_files:
        relative = path.relative_to(ROOT)
        rel_text = str(relative)
        for part in relative.parts:
            stem = part.rstrip(" .").split(".")[0].upper()
            if any(char in part for char in '<>:"|?*') or part.endswith((" ", ".")) or stem in WINDOWS_RESERVED:
                invalid_windows_paths.append(rel_text)
                break
        folded = rel_text.casefold()
        if folded in casefolded and casefolded[folded] != rel_text:
            case_collisions.append(f"{casefolded[folded]} / {rel_text}")
        casefolded[folded] = rel_text
        if len(rel_text) > 220:
            invalid_windows_paths.append(f"路径过长({len(rel_text)}): {rel_text}")
    ok("Windows 文件名、路径长度与大小写均兼容") if not invalid_windows_paths and not case_collisions else fail(
        "Windows 路径不兼容: " + ", ".join((invalid_windows_paths + case_collisions)[:8]), problems,
    )

    stale_shared_paths = []
    stale_pattern = re.compile(r"parents\[3\]\s*/\s*[\"']shared[\"']\s*/\s*[\"']scripts[\"']")
    for path in BUNDLED.rglob("*.py"):
        if stale_pattern.search(path.read_text(encoding="utf-8", errors="replace")):
            stale_shared_paths.append(str(path.relative_to(ROOT)))
    ok("内置脚本均指向 V3 共享运行时") if not stale_shared_paths else fail(
        "仍有脚本指向旧共享目录: " + ", ".join(stale_shared_paths[:8]), problems,
    )

    if args.runtime:
        ffmpeg = runtime_which("ffmpeg")
        checks = {
            "Codex CLI": runtime_which("codex") is not None or Path(os.environ.get("EASEL_CODEX_BIN", "_")).is_file(),
            "Node.js": runtime_which("node") is not None,
            "npm": runtime_which("npm") is not None,
            "V3 bundled Bun": runtime_which("bun") is not None,
            "V3 bundled Redbook": runtime_which("redbook") is not None,
            "FFmpeg": ffmpeg is not None,
            "FFprobe": runtime_which("ffprobe") is not None,
            "FFmpeg drawtext/subtitles": ffmpeg_has_filters(ffmpeg, ("drawtext", "subtitles")),
            "Python fastapi": importlib.util.find_spec("fastapi") is not None,
            "Python playwright": importlib.util.find_spec("playwright") is not None,
            "Python requests": importlib.util.find_spec("requests") is not None,
            "Python BeautifulSoup": importlib.util.find_spec("bs4") is not None,
            "Python openpyxl": importlib.util.find_spec("openpyxl") is not None,
        }
        for label, ready in checks.items():
            ok(label) if ready else fail(f"运行依赖不可用: {label}", problems)

    if problems:
        print(f"\nSeal V3 校验失败：{len(problems)} 项")
        return 1
    print("\nSeal V3 校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
