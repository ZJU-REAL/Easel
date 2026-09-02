#!/usr/bin/env python3
"""Validate Easel Skill metadata, links, layout, and execution contracts."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "skills" / "openclaw"
ALLOWED_KEYS = {"name", "description", "layer", "metadata"}
LAYERS = {"discover", "plan", "produce", "publish", "attribute", "general"}
INTENTIONAL_NAME_MISMATCHES = {"skill-xhs-analyzer": "redbook"}
KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):(?:\s*(.*))?$")
TRIGGER_RE = re.compile(r"当用户|触发|使用时机|适用场景|用户说|用户问|用户需要|用于")
LEGACY_OUTPUT_DIRS = {
    "ai-image", "ai-music", "ai-video", "audio-denoise", "audio-editing",
    "audio-mix", "audio-visualizer", "auto-short-video", "auto-subtitle",
    "beat-sync-video", "comment-insights", "doc-convert", "green-screen",
    "image-enhance", "meme-generator", "mindmap", "novels", "paper",
    "remove-bg", "reviews", "rss", "short-drama", "slideshow-video",
    "subtitle-translate", "tts-voiceover", "video-chapters", "video-highlights",
    "video-intro-outro", "video-reframe", "video-to-article", "voice-clone",
}
PUBLISH_SCRIPT_CONTRACTS = {
    "skills/openclaw/skill-bilibili-upload/scripts/bili_upload.py": (
        "content_guard.guard_or_die", 'add_argument("--exec"',
    ),
    "skills/openclaw/skill-wechat-publisher/scripts/publish.py": (
        "content_guard.guard_or_die", '"--exec"',
    ),
    "skills/openclaw/skill-wechat-publisher/scripts/multi_publish.py": (
        "content_guard.guard_or_die", '"--exec"',
    ),
    "skills/shared/scripts/xhs_publish.py": (
        "content_guard.guard_or_die", 'add_argument("--exec"',
    ),
    "skills/shared/scripts/douyin_publish.py": (
        "content_guard.guard_or_die", 'add_argument("--exec"',
    ),
    "skills/shared/scripts/web_publisher.py": (
        "content_guard.guard_or_die", 'add_argument("--exec"',
    ),
    "skills/shared/scripts/zhihu_answer.py": (
        "content_guard.guard_or_die", 'add_argument("--exec"',
    ),
}
OUTPUT_SCAN_SUFFIXES = {".md", ".py", ".sh"}
GENERIC_OUTPUT_DIRS = {"xhs", "test", "tmp", "temp", "demo", "output", "outputs", "result", "results"}
ROOT_OUTPUT_FILE_RE = re.compile(
    r"outputs/([^/\s`\"']+\.(?:md|json|jsonl|csv|txt|html|pdf|png|jpe?g|webp|gif|mp3|wav|mp4|mov|srt|vtt))"
)


def parse_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["missing opening frontmatter delimiter"]
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, ["missing closing frontmatter delimiter"]

    fields: dict[str, str] = {}
    errors: list[str] = []
    for line in lines[1:end]:
        if not line or line[0].isspace() or line.lstrip().startswith("#"):
            continue
        match = KEY_RE.match(line)
        if not match:
            errors.append(f"invalid top-level frontmatter line: {line!r}")
            continue
        key, value = match.groups()
        if key in fields:
            errors.append(f"duplicate frontmatter key: {key}")
        fields[key] = (value or "").strip().strip('"\'')
    return fields, errors


def read_description(path: Path) -> str:
    """Return the resolved scalar text for inline or block descriptions."""
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value not in {"", ">", ">-", "|", "|-"}:
            return value.strip('"\'')
        parts = []
        for child in lines[index + 1 :]:
            if child and not child[0].isspace():
                break
            parts.append(child.strip())
        return " ".join(part for part in parts if part)
    return ""


def validate(path: Path) -> list[str]:
    fields, errors = parse_frontmatter(path)
    missing = {"name", "description", "layer"} - fields.keys()
    if missing:
        errors.append(f"missing required keys: {', '.join(sorted(missing))}")
    extras = fields.keys() - ALLOWED_KEYS
    if extras:
        errors.append(f"unsupported keys: {', '.join(sorted(extras))}")
    if fields.get("layer") not in LAYERS:
        errors.append(f"invalid layer: {fields.get('layer')!r}")

    description = read_description(path)
    if not 80 <= len(description) <= 300:
        errors.append(f"description length must be 80..300 characters, got {len(description)}")
    if not TRIGGER_RE.search(description):
        errors.append("description must state when the skill should trigger")

    folder = path.parent.name
    expected_name = INTENTIONAL_NAME_MISMATCHES.get(folder, folder)
    if fields.get("name") != expected_name:
        errors.append(f"name {fields.get('name')!r} does not match expected {expected_name!r}")

    text = path.read_text(encoding="utf-8")
    if "metadata" in fields and not re.search(
        r"(?m)^metadata:\s*$\n(?:[ \t]+.*\n)*?[ \t]+openclaw:\s*$", text
    ):
        errors.append("metadata is allowed only as a metadata.openclaw runtime manifest")
    line_count = len(text.splitlines())
    if line_count > 200:
        errors.append(f"SKILL.md must stay within 200 lines, got {line_count}")
    for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        clean = target.split("#", 1)[0].strip()
        if not clean or clean in {"URL", "url", "{URL}"} or "://" in clean:
            continue
        if not (path.parent / clean).resolve().exists():
            errors.append(f"broken relative Markdown link: {target}")
    # Code-span references are common in OpenClaw Skills; validate those too.
    inline_resources = set(re.findall(
        r"`((?:scripts|references)/[^`\s]+)`", text
    ))
    for target in sorted(inline_resources):
        clean = target.rstrip(".,;:，。；：、）)").split("#", 1)[0]
        if not any(char in clean for char in "*{}<>") and not (path.parent / clean).exists():
            errors.append(f"missing inline resource: {target}")
    legacy_outputs = {
        value for value in re.findall(r"outputs/([A-Za-z0-9_-]+)/", text)
        if value in LEGACY_OUTPUT_DIRS
    }
    if legacy_outputs:
        errors.append(
            "legacy skill-named output directories: " + ", ".join(sorted(legacy_outputs))
        )
    if "outputs/analytics" in text:
        errors.append("analytics state must use outputs/_analytics")
    if re.search(r"outputs/主题名/(?:<主题>|主题名)/", text):
        errors.append("duplicated topic output directory")
    return errors


def validate_execution_contracts() -> list[str]:
    errors = []
    for relative_path, required_markers in PUBLISH_SCRIPT_CONTRACTS.items():
        path = ROOT / relative_path
        if not path.is_file():
            errors.append(f"missing publisher script: {relative_path}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in required_markers:
            if marker not in text:
                errors.append(f"{relative_path}: missing safety marker {marker!r}")

    analyzer_docs = [
        ROOT / "skills/openclaw/skill-xhs-analyzer/SKILL.md",
        ROOT / "skills/openclaw/skill-xhs-analyzer/references/commands.md",
        ROOT / "skills/openclaw/skill-xhs-analyzer/references/modules.md",
    ]
    forbidden = re.compile(r"redbook\s+(?:post|comment|reply|batch-reply|like|collect)\b")
    for path in analyzer_docs:
        if match := forbidden.search(path.read_text(encoding="utf-8")):
            errors.append(
                f"{path.relative_to(ROOT)}: analyzer must stay read-only; found {match.group()!r}"
            )
    return errors


def validate_output_layout_references() -> list[str]:
    """Reject examples that teach agents to create root files or generic projects."""
    errors: list[str] = []
    roots = (ROOT / "skills/openclaw", ROOT / "skills/shared/scripts")
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in OUTPUT_SCAN_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in ROOT_OUTPUT_FILE_RE.finditer(text):
                name = match.group(1)
                if not name.startswith("_"):
                    errors.append(
                        f"{path.relative_to(ROOT)}: root-level content output {match.group(0)!r}"
                    )
            for name in sorted(GENERIC_OUTPUT_DIRS):
                if re.search(rf"outputs/{re.escape(name)}/", text, re.I):
                    errors.append(
                        f"{path.relative_to(ROOT)}: generic output project directory 'outputs/{name}/'"
                    )
    return sorted(set(errors))


def main() -> int:
    skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
    failures = 0
    for path in skill_files:
        errors = validate(path)
        if not errors:
            continue
        failures += 1
        print(path.relative_to(ROOT))
        for error in errors:
            print(f"  - {error}")
    contract_errors = validate_execution_contracts()
    contract_errors.extend(validate_output_layout_references())
    if contract_errors:
        failures += 1
        print("execution contracts")
        for error in contract_errors:
            print(f"  - {error}")
    if failures:
        print(f"FAIL: {failures}/{len(skill_files)} skills invalid", file=sys.stderr)
        return 1
    print(f"OK: {len(skill_files)} skills and publisher execution contracts conform")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
