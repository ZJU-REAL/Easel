#!/usr/bin/env python3
"""Check that Python commands documented by Skills match real CLI help."""

from __future__ import annotations

import re
import shlex
import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills" / "openclaw"
FENCE_RE = re.compile(r"```(?:bash|sh|shell)\s*\n(.*?)```", re.S)
OPTION_RE = re.compile(r"(?<!\S)(--[a-zA-Z][a-zA-Z0-9-]*|-[a-zA-Z])")


def commands(path: Path):
    text = path.read_text(encoding="utf-8")
    for block in FENCE_RE.findall(text):
        logical = re.sub(r"\\\s*\n\s*", " ", block)
        for raw in logical.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            for index, token in enumerate(tokens[:-1]):
                if token in {"python", "python3"} and tokens[index + 1].endswith(".py"):
                    yield line, tokens[index + 1 :]
                    break


def resolve_script(doc: Path, token: str) -> Path | None:
    if any(char in token for char in "$<>{}*"):
        return None
    candidate = Path(token)
    if candidate.is_absolute():
        return candidate
    if token.startswith(("skills/", "scripts/", "openclaw/")):
        return ROOT / candidate
    return doc.parent / candidate


def cli_schema(script: Path) -> tuple[set[str], set[str]]:
    """Collect argparse options and subcommand names without importing the script."""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set(), set()
    options, subcommands = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("-"):
                    options.add(arg.value)
        elif node.func.attr == "add_parser" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                subcommands.add(arg.value)
    return options, subcommands


def main() -> int:
    failures = []
    checked = 0
    docs = sorted(SKILLS.glob("*/SKILL.md")) + sorted(SKILLS.glob("*/references/*.md"))
    cache: dict[Path, tuple[set[str], set[str]]] = {}
    for doc in docs:
        for line, invocation in commands(doc):
            script = resolve_script(doc, invocation[0])
            if script is None:
                continue
            if not script.is_file():
                failures.append((doc, line, f"script does not exist: {script.relative_to(ROOT)}"))
                continue
            args = invocation[1:]
            if script not in cache:
                cache[script] = cli_schema(script)
            supported, subcommands = cache[script]
            checked += 1
            checked_line = line.split(" -- ", 1)[0]
            used = set(OPTION_RE.findall(checked_line)) - {"--help"}
            unknown = sorted(used - supported) if supported else []
            if unknown:
                failures.append((doc, line, "unknown options: " + ", ".join(unknown)))

    for doc, line, error in failures:
        print(f"{doc.relative_to(ROOT)}: {error}\n  {line}")
    if failures:
        print(f"FAIL: {len(failures)} documented command errors ({checked} checked)", file=sys.stderr)
        return 1
    print(f"OK: {checked} documented Python commands match their argparse schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
