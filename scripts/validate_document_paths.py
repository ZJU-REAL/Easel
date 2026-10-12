#!/usr/bin/env python3
"""Validate concrete repository paths in documentation and Agent prompt material."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
FENCE_RE = re.compile(r"(?m)^([ \t]*)(`{3,}|~{3,})[^\n]*\n.*?^\1\2[ \t]*$", re.S)
INLINE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")
ROOT_PATH_RE = re.compile(r"(?<![\w/\\.-])(?:skills|agents)[/\\][^\s`\"'(),;，；。]+")
OLD_PATH_RE = re.compile(
    r"(?<![\w/~\\.-])(?:skills[/\\]openclaw(?:/|\\)"
    r"|openclaw[/\\](?:workspace|sync\.sh|openclaw\.json5))"
)
RESOURCE_PREFIXES = ("scripts/", "references/", "assets/", "tools/", "docs/", "themes/")
OPTIONAL_PATHS = {
    "skills/shared/scripts/models",
    "skills/shared/scripts/models/sh.rnnn",
    "skills/builtin/skill-wechat-publisher/wechat-publisher.yaml",
}


@dataclass(frozen=True)
class PathIssue:
    document: Path
    line: int
    reference: str
    reason: str


def documents(root: Path) -> list[Path]:
    found = list(root.glob("*.md"))
    for directory in ("docs", "agents", "skills", "profiles/_template", "web/frontend"):
        found.extend(
            path for path in (root / directory).rglob("*.md")
            if not set(path.relative_to(root).parts).intersection(
                {"node_modules", ".git", "__pycache__", "dist"}
            )
        )
    return sorted(set(found))


def resource_root(document: Path, root: Path) -> Path:
    for parent in document.parents:
        if parent == root:
            break
        if parent.parent.name == "vendor" or (parent / "SKILL.md").is_file():
            return parent
    return root


def literal_path(value: str) -> str | None:
    value = unquote(value.strip().strip('"').strip("'"))
    if not value or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
        return None
    value = value.split("#", 1)[0].split("?", 1)[0]
    if not value or any(marker in value for marker in ("$", "<", ">", "{", "}", "*", "...", "…")):
        return None
    if any(character.isspace() for character in value):
        return None
    return value.replace("\\", "/")


def resolve_reference(document: Path, root: Path, value: str, *, link: bool) -> Path | None:
    reference = literal_path(value)
    if reference is None or reference.startswith(("/", "~", "outputs/", "profiles/")):
        return None
    if reference in OPTIONAL_PATHS:
        return None
    if link or reference.startswith(("../", "./")):
        return document.parent / reference
    if reference.startswith(("skills/", "agents/")):
        return root / reference
    if reference.startswith(RESOURCE_PREFIXES):
        if reference in RESOURCE_PREFIXES:
            return None
        return resource_root(document, root) / reference
    return None


def without_fences(text: str) -> str:
    return FENCE_RE.sub(lambda match: "".join("\n" if character == "\n" else " " for character in match[0]), text)


def validate_document(document: Path, root: Path) -> tuple[list[PathIssue], int]:
    text = document.read_text(encoding="utf-8-sig")
    visible = without_fences(text)
    link_text = INLINE_RE.sub(
        lambda match: " " * len(match[0]), visible,
    )
    issues = []
    checked = 0
    seen = set()
    for match in OLD_PATH_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        issues.append(PathIssue(document, line, match[0], "obsolete repository path"))
    matches = (
        [(match, False) for match in INLINE_RE.finditer(visible)]
        + [(match, True) for match in LINK_RE.finditer(link_text)]
        + [(match, False) for match in ROOT_PATH_RE.finditer(text)]
    )
    for match, link in matches:
        reference = match[1] if match.lastindex else match[0]
        candidate = resolve_reference(document, root, reference, link=link)
        if candidate is None:
            continue
        line = text.count("\n", 0, match.start()) + 1
        if (line, candidate) in seen:
            continue
        seen.add((line, candidate))
        checked += 1
        if not candidate.exists():
            issues.append(PathIssue(document, line, reference, "path does not exist"))
    return issues, checked


def audit(root: Path = ROOT) -> tuple[list[PathIssue], int, int]:
    issues = []
    checked = 0
    sources = documents(root)
    for document in sources:
        failures, count = validate_document(document, root)
        issues.extend(failures)
        checked += count
    return issues, checked, len(sources)


def main() -> int:
    issues, checked, sources = audit()
    for issue in issues:
        print(f"{issue.document.relative_to(ROOT)}:{issue.line}: {issue.reason}: {issue.reference}")
    if issues:
        print(f"FAIL: {len(issues)} documentation path errors ({checked} references checked)", file=sys.stderr)
        return 1
    print(f"OK: {checked} repository paths checked across {sources} documentation and prompt files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
