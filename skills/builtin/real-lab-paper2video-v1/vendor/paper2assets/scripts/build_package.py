#!/usr/bin/env python3
"""Build the cross-skill canonical package for a paper2assets `<outdir>`.

paper2assets is the single source of truth for ALL paper-rendering skills
downstream — not just paper2poster. Skills like paper2blog, paper2video, and
paper2reel consume the same `<outdir>/` and rely on three additional
canonical files that paper2poster doesn't need but they do. This script
produces those three files so a single paper2assets run hands everything
downstream needs.

What this script adds on top of what paper2assets already produces (text.txt /
captions.json / figures.json / metadata.json / paper_spec.md / figures/):

  manifest.json   — package inventory + source PDF sha256 + file counts.
                    Lets downstream verify the package shape without
                    re-walking the directory.

  sections.json   — paper_spec.md parsed into structured per-section JSON
                    with stable ids (`problem`, `motivation`, `method`,
                    `key-result`, ...), each section's `necessary` /
                    `additional` / `audio_script` fields, and an empty
                    `figures: []` (downstream joins with figures.json by id).

  narration.json  — TTS clip list extracted from `**Audio script:**` markers
                    in document order. The title clip comes from the YAML
                    frontmatter's `title_audio_script` field. Will be empty
                    for posters that skip audio narration — that's expected
                    and downstream skills should handle it gracefully.

Use (from paper2assets SKILL.md Step 7, after Step 2 extraction is done):

  python skills/paper2assets/scripts/build_package.py <pdf> \\
      --outdir <outdir> \\
      --skip-extract \\
      --paper-spec <outdir>/paper_spec.md

The script is intentionally idempotent — re-running over an existing outdir
overwrites the 3 JSON outputs without touching extracted text/figures/spec.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Share the canonical bundle layout (utils/layout.py) when run directly.
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from utils import layout  # noqa: E402


# Schema strings written into the 3 JSON outputs. Downstream consumers
# may key on these to detect format changes — bump cautiously.
SCHEMA_VERSION = "paper2assets.v1"
SECTIONS_SCHEMA_VERSION = "paper_sections.v1"
NARRATION_SCHEMA_VERSION = "paper_narration.v1"

FIELD_RE = re.compile(
    r"^\s*\*\*(?P<name>Necessary|Additional|Audio script):\*\*\s*(?P<value>.*)\s*$",
    re.IGNORECASE,
)
IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)(?:\{(?P<attrs>[^}]*)\})?")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root() -> Path:
    # skills/paper2assets/scripts/build_package.py -> repo root
    return Path(__file__).resolve().parents[3]


def rel_to(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def normalize_section_id(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "section"


def parse_attrs(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    attrs: dict[str, str] = {}
    for token in raw.split():
        if "=" in token:
            k, v = token.split("=", 1)
            attrs[k.strip()] = v.strip().strip('"')
        else:
            attrs[token.strip()] = "true"
    return attrs


def extract_inline_value(lines: list[str], idx: int, initial: str) -> tuple[str, int]:
    parts: list[str] = []
    if initial:
        parts.append(initial.strip())
    i = idx + 1
    while i < len(lines):
        nxt = lines[i].strip()
        if not nxt:
            break
        if nxt.startswith("**") or nxt.startswith("## ") or nxt.startswith("# "):
            break
        parts.append(nxt)
        i += 1
    return " ".join(parts).strip(), i


def parse_spec(spec_path: Path) -> dict[str, Any]:
    text = spec_path.read_text()
    lines = text.splitlines()
    title = ""
    authors = ""
    institutes: list[str] = []
    title_audio_script = ""
    sections: list[dict[str, Any]] = []

    # First — if the file opens with a YAML frontmatter block (the
    # canonical paper2assets format), parse top-level metadata from
    # there. If the frontmatter is absent, fall through to the body-
    # section loop which also recognizes the older Markdown-header
    # metadata format (`# Title` / `**Authors:** ...` / `**Institutes:**
    # ...` / `**Title audio script:** ...`) as a backward-compatibility
    # shim. Both formats land in the same final shape.
    body_start = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                # Parse the lines between the two `---` fences as YAML-like
                # key: value pairs. We don't pull in a YAML lib (paper2assets
                # only writes a flat mapping with string scalars, not nested
                # structures or anchors); a line-by-line `key: value` split
                # is sufficient and avoids a runtime dep.
                for fm in lines[1:j]:
                    if ":" not in fm:
                        continue
                    k, v = fm.split(":", 1)
                    key = k.strip().lower()
                    val = v.strip()
                    if key == "title" and not title:
                        title = val
                    elif key == "authors" and not authors:
                        authors = val
                    elif key == "institutes" and not institutes:
                        institutes = [p.strip() for p in val.split(";") if p.strip()]
                    elif key == "title_audio_script" and not title_audio_script:
                        title_audio_script = val
                body_start = j + 1
                break

    current: dict[str, Any] | None = None

    def flush_current() -> None:
        nonlocal current
        if current is not None:
            sections.append(current)
            current = None

    i = body_start
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            i += 1
            continue

        if current is None:
            if stripped.startswith("**Authors:**"):
                authors = stripped.split("**Authors:**", 1)[1].strip()
                i += 1
                continue
            if stripped.startswith("**Institutes:**"):
                raw = stripped.split("**Institutes:**", 1)[1].strip()
                institutes = [p.strip() for p in raw.split(";") if p.strip()]
                i += 1
                continue
            if stripped.startswith("**Title audio script:**"):
                value = stripped.split("**Title audio script:**", 1)[1].strip()
                title_audio_script, i = extract_inline_value(lines, i, value)
                continue

        if stripped.startswith("## "):
            flush_current()
            heading = stripped[3:].strip()
            current = {
                "id": normalize_section_id(heading),
                "heading": heading,
                "necessary": "",
                "additional": "",
                "audio_script": "",
                "figures": [],
                "tables": [],
                "source": {
                    "type": "paper_spec",
                    "path": spec_path.as_posix(),
                },
            }
            i += 1
            continue

        if current is not None:
            img = IMAGE_RE.search(line)
            if img:
                current["figures"].append(
                    {
                        "path": img.group("path").strip(),
                        "alt": img.group("alt").strip(),
                        "attrs": parse_attrs(img.group("attrs")),
                    }
                )
                i += 1
                continue

            m = FIELD_RE.match(line)
            if m:
                field = m.group("name").lower()
                value, i = extract_inline_value(lines, i, m.group("value"))
                if field == "audio script":
                    current["audio_script"] = value
                else:
                    current[field] = value
                continue

        i += 1

    flush_current()

    return {
        "title": title,
        "authors": authors,
        "institutes": institutes,
        "title_audio_script": title_audio_script,
        "sections": sections,
    }


def build_sections_json(spec_path: Path | None, outdir: Path) -> dict[str, Any]:
    if spec_path is None:
        return {
            "schema_version": SECTIONS_SCHEMA_VERSION,
            "created_at": utc_now(),
            "source_spec": None,
            "title": "",
            "authors": "",
            "institutes": [],
            "title_audio_script": "",
            "sections": [],
            "status": "empty_until_spec_sync",
        }

    parsed = parse_spec(spec_path)
    source_spec = rel_to(spec_path, outdir)
    for section in parsed["sections"]:
        section["source"]["path"] = source_spec
    return {
        "schema_version": SECTIONS_SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_spec": source_spec,
        "title": parsed["title"],
        "authors": parsed["authors"],
        "institutes": parsed["institutes"],
        "title_audio_script": parsed["title_audio_script"],
        "sections": parsed["sections"],
        "status": "synced",
    }


def build_narration_json(sections_doc: dict[str, Any]) -> dict[str, Any]:
    narration_sections: list[dict[str, str]] = []
    title_audio = (sections_doc.get("title_audio_script") or "").strip()
    if title_audio:
        narration_sections.append(
            {
                "id": "title",
                "heading": "Title",
                "text": title_audio,
            }
        )
    for sec in sections_doc.get("sections", []):
        text = (sec.get("audio_script") or "").strip()
        if not text:
            continue
        narration_sections.append(
            {
                "id": sec.get("id", ""),
                "heading": sec.get("heading", ""),
                "text": text,
            }
        )
    return {
        "schema_version": NARRATION_SCHEMA_VERSION,
        "created_at": utc_now(),
        "provider": "edge",  # free Edge TTS default; generate_audio.py honors it
        "voice": None,
        "sections": narration_sections,
    }


def run_extractor(pdf: Path, outdir: Path, extractor: Path) -> list[str]:
    cmd = [sys.executable, str(extractor), str(pdf), "--outdir", str(outdir)]
    subprocess.run(cmd, check=True)
    return cmd


def build_manifest(
    *,
    pdf: Path,
    outdir: Path,
    extractor: Path,
    extractor_cmd: list[str] | None,
    paper_spec: Path | None,
    skipped_extract: bool,
) -> dict[str, Any]:
    previous_manifest = load_json(layout.manifest_path(outdir), {})
    previous_extractor = (
        previous_manifest.get("extractor", {})
        if isinstance(previous_manifest, dict)
        else {}
    )
    text_path = layout.meta_file(outdir, "text")
    captions = load_json(layout.meta_file(outdir, "captions"), {})
    figures = load_json(layout.meta_file(outdir, "figures"), [])
    metadata = load_json(layout.meta_file(outdir, "metadata"), {})
    source = {
        "pdf": pdf.as_posix(),
        "filename": pdf.name,
        "bytes": pdf.stat().st_size if pdf.exists() else None,
        "sha256": sha256_file(pdf) if pdf.exists() else "",
    }
    files = {
        "text": layout.META_FILES["text"],
        "metadata": layout.META_FILES["metadata"],
        "captions": layout.META_FILES["captions"],
        "figures": layout.META_FILES["figures"],
        "figures_dir": layout.FIGURES,
        "sections": layout.META_FILES["sections"],
        "narration": layout.META_FILES["narration"],
        "logos_dir": layout.LOGOS,
        "qr_dir": layout.QR,
        "audio_dir": layout.AUDIO,
    }
    if paper_spec is not None:
        files["paper_spec"] = rel_to(paper_spec, outdir)

    return {
        "schema_version": SCHEMA_VERSION,
        "layout": layout.LAYOUT_VERSION,
        "created_at": utc_now(),
        "source": source,
        "extractor": {
            "script": rel_to(extractor, repo_root()),
            "command": extractor_cmd
            if extractor_cmd is not None
            else previous_extractor.get("command"),
            "skipped": skipped_extract,
        },
        "files": files,
        "counts": {
            "text_chars": len(text_path.read_text(errors="replace")) if text_path.exists() else 0,
            "captions": len(captions) if isinstance(captions, dict) else 0,
            "figures": len(figures) if isinstance(figures, list) else 0,
            "metadata_populated_fields": len([k for k, v in metadata.items() if v])
            if isinstance(metadata, dict)
            else 0,
        },
    }


def parse_args() -> argparse.Namespace:
    root = repo_root()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="Source paper PDF")
    ap.add_argument("--outdir", required=True, help="Paper assets package root")
    ap.add_argument(
        "--extractor",
        default=str(root / "skills" / "paper2assets" / "scripts" / "extract_pdf.py"),
        help="PDF extractor script to reuse",
    )
    ap.add_argument(
        "--paper-spec",
        dest="paper_spec",
        help="Optional paper_spec.md to sync into sections.json and narration.json",
    )
    ap.add_argument(
        "--skip-extract",
        action="store_true",
        help="Do not run the extractor; only refresh manifest/sections/narration",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    pdf = Path(args.pdf).resolve()
    outdir = Path(args.outdir).resolve()
    extractor = Path(args.extractor).resolve()
    paper_spec = Path(args.paper_spec).resolve() if args.paper_spec else None

    if not pdf.exists() or pdf.suffix.lower() != ".pdf":
        sys.exit(f"PDF not found or not a .pdf: {pdf}")
    if not extractor.exists():
        sys.exit(f"Extractor not found: {extractor}")
    if paper_spec is not None and not paper_spec.exists():
        sys.exit(f"paper_spec not found: {paper_spec}")

    outdir.mkdir(parents=True, exist_ok=True)

    extractor_cmd = None
    if not args.skip_extract:
        print(f"[paper2assets/package] extracting PDF -> {outdir}", flush=True)
        extractor_cmd = run_extractor(pdf, outdir, extractor)
    else:
        print(f"[paper2assets/package] skip extract; refreshing package metadata in {outdir}")

    sections_doc = build_sections_json(paper_spec, outdir)
    narration_doc = build_narration_json(sections_doc)
    manifest = build_manifest(
        pdf=pdf,
        outdir=outdir,
        extractor=extractor,
        extractor_cmd=extractor_cmd,
        paper_spec=paper_spec,
        skipped_extract=args.skip_extract,
    )

    layout.meta_dir(outdir, create=True)
    write_json(layout.meta_file(outdir, "sections"), sections_doc)
    write_json(layout.meta_file(outdir, "narration"), narration_doc)
    write_json(layout.manifest_path(outdir), manifest)

    print("[paper2assets/package] wrote manifest.json")
    print(f"[paper2assets/package] wrote sections.json ({len(sections_doc.get('sections', []))} sections)")
    print(f"[paper2assets/package] wrote narration.json ({len(narration_doc.get('sections', []))} clips)")


if __name__ == "__main__":
    main()
