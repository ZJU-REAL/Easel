#!/usr/bin/env python3
"""Apply Seal's required redbook fixes without running unrelated hooks."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "runtime/tools/node_modules/@lucasygu/redbook"
TOOLS_MODULES = ROOT / "runtime/tools/node_modules"


def replace_once(target: Path, old: str, new: str) -> None:
    if not target.is_file():
        raise SystemExit(f"redbook 依赖文件不存在: {target}")
    source = target.read_text(encoding="utf-8")
    if new in source:
        return
    if old not in source:
        raise SystemExit(f"redbook 上游结构已变化，无法应用兼容补丁: {target.relative_to(ROOT)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


def dependency_file(package: str, relative: str) -> Path:
    """Resolve both npm nested and hoisted dependency layouts."""
    candidates = (
        PACKAGE / "node_modules" / package / relative,
        TOOLS_MODULES / package / relative,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("redbook 依赖文件不存在: " + " 或 ".join(str(path) for path in candidates))


def main() -> int:
    replace_once(
        PACKAGE / "dist/cli.js",
        'const REDBOOK_DIR = join(homedir(), ".redbook");',
        'const REDBOOK_DIR = process.env.REDBOOK_STATE_DIR || join(homedir(), ".redbook");',
    )
    replace_once(
        PACKAGE / "dist/lib/detect.js",
        'const CACHE_DIR = join(homedir(), ".redbook");',
        'const CACHE_DIR = process.env.REDBOOK_STATE_DIR || join(homedir(), ".redbook");',
    )
    replace_once(
        dependency_file("@steipete/sweet-cookie", "dist/providers/chromeSqliteMac.js"),
        "timeoutMs: 3_000,",
        "timeoutMs: options.timeoutMs ?? 30_000,",
    )
    replace_once(
        dependency_file("@steipete/sweet-cookie", "dist/providers/chromeSqlite/shared.js"),
        "SELECT name, value, host_key, path, expires_utc, samesite, encrypted_value,",
        "SELECT name, value, host_key, path, CAST(expires_utc AS TEXT) AS expires_utc, samesite, encrypted_value,",
    )
    replace_once(
        PACKAGE / "dist/lib/render.js",
        'import { existsSync, readFileSync, mkdirSync } from "node:fs";\nimport { dirname, join, resolve } from "node:path";',
        'import { existsSync, readFileSync, mkdirSync, readdirSync } from "node:fs";\nimport { homedir } from "node:os";\nimport { dirname, join, resolve } from "node:path";',
    )
    replace_once(
        PACKAGE / "dist/lib/render.js",
        '''function findChromeExecutable() {
    // Allow override via environment variable
    if (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH)) {
        return process.env.CHROME_PATH;
    }
    if (process.platform === "darwin") {
        const candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ];
        for (const p of candidates) {
            if (existsSync(p))
                return p;
        }
    }
    throw new Error("Chrome not found. Install Google Chrome or set CHROME_PATH environment variable.\\n" +
        "Expected: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome");
}''',
        '''function findChromeExecutable() {
    const candidates = [];
    if (process.env.CHROME_PATH)
        candidates.push(process.env.CHROME_PATH);
    if (process.platform === "darwin") {
        candidates.push(
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        );
    }
    else if (process.platform === "win32") {
        for (const base of [process.env.PROGRAMFILES, process.env["PROGRAMFILES(X86)"], process.env.LOCALAPPDATA]) {
            if (!base)
                continue;
            candidates.push(
                join(base, "Google", "Chrome", "Application", "chrome.exe"),
                join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
            );
        }
    }
    const cacheRoot = process.env.PLAYWRIGHT_BROWSERS_PATH || (process.platform === "darwin"
        ? join(homedir(), "Library", "Caches", "ms-playwright")
        : process.platform === "win32"
            ? join(process.env.LOCALAPPDATA || join(homedir(), "AppData", "Local"), "ms-playwright")
            : join(homedir(), ".cache", "ms-playwright"));
    if (existsSync(cacheRoot)) {
        for (const entry of readdirSync(cacheRoot, { withFileTypes: true })) {
            if (!entry.isDirectory() || !entry.name.startsWith("chromium-"))
                continue;
            const versionRoot = join(cacheRoot, entry.name);
            candidates.push(
                join(versionRoot, "chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
                join(versionRoot, "chrome-mac", "Google Chrome for Testing.app", "Contents", "MacOS", "Google Chrome for Testing"),
                join(versionRoot, "chrome-win64", "chrome.exe"),
                join(versionRoot, "chrome-win", "chrome.exe"),
                join(versionRoot, "chrome-linux", "chrome"),
            );
        }
    }
    for (const candidate of candidates) {
        if (candidate && existsSync(candidate))
            return candidate;
    }
    throw new Error("Chrome/Chromium not found. Run the Seal V3 installer or set CHROME_PATH.");
}''',
    )

    # 上游 npm 包携带的安装钩子只用于创建其他 Agent 环境链接，V3 不需要。
    for hook in (PACKAGE / "scripts/postinstall.js", PACKAGE / "scripts/preuninstall.js"):
        hook.unlink(missing_ok=True)

    # Codex recursively discovers every SKILL.md under ~/.codex/skills.
    # Dependency package metadata is not a Seal entrypoint and is unused at runtime.
    for dependency_root in (
        ROOT / "runtime/.venv",
        ROOT / "runtime/tools/node_modules",
        ROOT / "runtime/web/frontend/node_modules",
    ):
        if dependency_root.is_dir():
            for marker in dependency_root.rglob("SKILL.md"):
                marker.unlink()
    print("redbook 运行时兼容补丁已应用；未执行无关的 Agent 环境安装钩子")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
