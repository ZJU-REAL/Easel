#!/usr/bin/env python3
"""Generate scannable QR-code PNGs for a paper's links, captioned by destination.

Reads `paper_url` / `project_url` / `code_url` (and `arxiv_id`) from
`<outdir>/assets/meta/metadata.json` (written by `extract_pdf.py`), then:

  1. classifies each URL by what it POINTS TO — `Paper` (arXiv/doi/pdf/venue),
     `Code` (github/gitlab/HF), or `Project` (aka.ms, project pages, homepages);
  2. de-duplicates by URL so a one-link paper yields ONE QR, never two identical
     tiles (the #1 cause of "fake placeholder"-looking duplicate codes);
  3. renders at most two QRs into `<outdir>/assets/qr/{paper,code}.png` (stable
     template slots) and records each surviving tile's caption in the manifest.

The filenames `paper.png` / `code.png` are just the two template slots
(`{{QR_PAPER}}` / `{{QR_CODE}}`); the human-facing CAPTION is the manifest
`label`, so `qr/paper.png` may legitimately be captioned "Project". Either tile
(or both) may be absent — the poster templates auto-hide whichever doesn't
resolve. NEVER fabricates a URL.

Usage:
    python make_qr.py --outdir <outdir> --from-metadata <outdir>/assets/meta/metadata.json
    # or, explicit URLs:
    python make_qr.py --outdir <outdir> \
        --paper-url https://arxiv.org/pdf/1706.03762 \
        --code-url https://github.com/tensorflow/tensor2tensor

Prints a JSON summary on stdout AND writes it into metadata.json under `"qr"`:
    {"qr": [
       {"kind": "paper", "url": "https://...", "path": "assets/qr/paper.png", "label": "Paper"},
       {"kind": "code",  "url": "https://...", "path": "assets/qr/code.png",  "label": "Code"}
    ]}

Exit codes (match `fetch_logos.py`):
    0  at least one QR was written
    1  nothing resolved (no URLs present, or all renders failed)
    2  usage error (bad args)

Sourcing rules:
  - `paper_url` falls back to `https://arxiv.org/pdf/<arxiv_id>` only when empty
    AND `arxiv_id` is present (matches `{{VENUE_LINK}}` precedence).
  - No URL ever falls back to another's value; de-duplication is by identity, so
    when the extractor genuinely found only one link all three fields collapse to
    a single correctly-labelled QR.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Share the canonical bundle layout (utils/layout.py) when run directly.
_THIS_DIR = str(Path(__file__).resolve().parent)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
from utils import layout  # noqa: E402


def render_qr_png(url: str, out_path: Path) -> bool:
    """Render `url` as a QR PNG to `out_path`. Returns True on success.

    Uses medium error correction (ERROR_CORRECT_M, ~15% recovery) — robust
    enough to survive print artifacts, scuffs, and the white-tile padding
    in the poster template without inflating the symbol size unnecessarily.
    `box_size=12` + `border=2` renders the symbol at a resolution at/above the
    template's on-canvas QR tile (~360px at true 5760px canvas scale), so the
    tile never upscales-and-blurs the code. NOTE: a poster PNG exported below
    ~0.5x thumbnail scale shrinks the tile past the decode threshold — deliver
    the print PDF or a >=0.5x PNG for a scannable code.
    """
    try:
        import qrcode
    except ImportError as e:
        print(f"[make_qr] ERROR: `qrcode` package not installed: {e}", file=sys.stderr)
        return False
    try:
        qr = qrcode.QRCode(
            version=None,  # auto-pick the smallest version that fits
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=12,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path))
        return True
    except Exception as e:
        print(f"[make_qr] failed to render {url!r} -> {out_path}: {e}", file=sys.stderr)
        return False


def resolve_urls_from_metadata(meta: dict) -> tuple[str, str, str]:
    """Return (paper_url, project_url, code_url) honoring the arxiv_id fallback.

    `code_url` and `project_url` are taken verbatim. `paper_url` falls back to
    `https://arxiv.org/pdf/<arxiv_id>` only when empty AND an arxiv_id is present.
    """
    paper_url = (meta.get("paper_url") or "").strip()
    if not paper_url:
        arxiv_id = (meta.get("arxiv_id") or "").strip()
        if arxiv_id:
            paper_url = f"https://arxiv.org/pdf/{arxiv_id}"
    project_url = (meta.get("project_url") or "").strip()
    code_url = (meta.get("code_url") or "").strip()
    return paper_url, project_url, code_url


def classify_url(url: str) -> str:
    """Classify a URL by what it POINTS TO → 'Paper' | 'Code' | 'Project'.

    The QR caption must describe the destination, not the metadata field the URL
    happened to sit in. A paper whose only link is a project page must show a QR
    captioned 'Project', never 'Paper'.
    """
    u = (url or "").strip().lower()
    if not u:
        return "Project"
    if any(h in u for h in ("github.com", "gitlab.com", "bitbucket.org",
                            "huggingface.co", "codeberg.org")):
        return "Code"
    if any(h in u for h in ("arxiv.org", "doi.org", "aclanthology.org",
                            "openreview.net", "semanticscholar.org",
                            "dl.acm.org", "ieeexplore.ieee.org",
                            "/pdf/", "/abs/", ".pdf")):
        return "Paper"
    return "Project"


# Which label wins when the SAME url appears under more than one field.
_LABEL_PRIORITY = {"Paper": 0, "Code": 1, "Project": 2}


def build_qr_plan(paper_url: str, project_url: str, code_url: str) -> list[dict]:
    """De-duplicate the three URLs into an ordered, capped QR plan.

    Returns a list of ``{"url", "label"}`` dicts, ordered Paper -> Code -> Project,
    de-duplicated by normalized URL (so a one-link paper yields ONE QR, never two
    identical ones) and capped at 2 (the templates expose two QR slots).
    """
    seen: dict[str, dict] = {}
    for url in (paper_url, code_url, project_url):
        u = (url or "").strip()
        if not u:
            continue
        key = u.rstrip("/").lower()
        label = classify_url(u)
        prev = seen.get(key)
        if prev is None:
            seen[key] = {"url": u, "label": label}
        elif _LABEL_PRIORITY[label] < _LABEL_PRIORITY[prev["label"]]:
            # keep the more specific label for a shared URL (Paper > Code > Project)
            prev["label"] = label
    plan = sorted(seen.values(), key=lambda e: _LABEL_PRIORITY[e["label"]])
    return plan[:2]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--outdir", required=True, type=Path,
                    help="Poster outdir; qr/ is created inside it. (If you pass <outdir>/qr by mistake, the trailing /qr is auto-stripped with a warning — see Step 6 of paper2assets/SKILL.md.)")
    ap.add_argument("--from-metadata", "--metadata", dest="from_metadata", type=Path,
                    help="Read paper_url/code_url/arxiv_id from a metadata.json file. "
                         "(`--metadata` is a backward-compat alias; the canonical flag is "
                         "`--from-metadata` because that's what SKILL.md/help-output says.)")
    ap.add_argument("--paper-url", default="",
                    help="Explicit paper URL (overrides metadata.json when both given).")
    ap.add_argument("--code-url", default="",
                    help="Explicit code URL (overrides metadata.json when both given).")
    ap.add_argument("--project-url", default="",
                    help="Explicit project/website URL (overrides metadata.json when both given).")
    args = ap.parse_args()

    # Defensive: if caller passed `<outdir>/qr` (a common SKILL.md
    # misreading — script appends /qr itself, so passing it ends up
    # at <outdir>/qr/qr/{paper,code}.png and downstream paper2poster
    # finds nothing). Strip it once with a loud warning so the bug is
    # visible in batch logs. Same trap pattern as fetch_logos.py.
    if args.outdir.name == "qr":
        print(f"[make_qr] WARNING: --outdir ends in '/qr' "
              f"({args.outdir!s}); auto-stripping to {args.outdir.parent!s}. "
              f"Pass the POSTER OUTDIR (qr/ is created inside it).",
              file=sys.stderr)
        args.outdir = args.outdir.parent

    paper_url = (args.paper_url or "").strip()
    code_url = (args.code_url or "").strip()
    project_url = (args.project_url or "").strip()
    meta_path: Path | None = None

    if args.from_metadata:
        if not args.from_metadata.exists():
            print(f"[make_qr] --from-metadata path does not exist: {args.from_metadata}",
                  file=sys.stderr)
            return 2
        try:
            meta = json.loads(args.from_metadata.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[make_qr] failed to parse {args.from_metadata}: {e}", file=sys.stderr)
            return 2
        if not isinstance(meta, dict):
            print(f"[make_qr] metadata.json must be an object, got {type(meta).__name__}",
                  file=sys.stderr)
            return 2
        meta_path = args.from_metadata
        meta_paper, meta_project, meta_code = resolve_urls_from_metadata(meta)
        # Explicit CLI args win over metadata when both are present.
        if not paper_url:
            paper_url = meta_paper
        if not project_url:
            project_url = meta_project
        if not code_url:
            code_url = meta_code

    # De-duplicate + classify across all three URLs. Identical URLs collapse to
    # ONE QR; each surviving QR is captioned by what it actually points to.
    plan = build_qr_plan(paper_url, project_url, code_url)

    if not plan:
        print("[make_qr] no paper/project/code URL to render (nothing to do).",
              file=sys.stderr)
        # Still emit an empty manifest so callers can parse the output uniformly.
        print(json.dumps({"qr": []}, indent=2))
        return 1

    qr_dir = layout.qr_dir(args.outdir, create=True)
    # Slot 0 -> qr/paper.png, slot 1 -> qr/code.png. Filenames are just stable
    # slots for the two template QR placeholders ({{QR_PAPER}} / {{QR_CODE}});
    # the human-facing caption comes from the per-slot `label` in the manifest,
    # NOT from the filename.
    slot_names = ("paper", "code")
    results: list[dict] = []
    for i, entry in enumerate(plan):
        kind = slot_names[i]
        url, label = entry["url"], entry["label"]
        out_path = qr_dir / f"{kind}.png"
        if render_qr_png(url, out_path):
            rel = f"{layout.QR}/{kind}.png"
            print(f"[make_qr] {kind} -> {rel}  (label={label}, url={url})", file=sys.stderr)
            results.append({"kind": kind, "url": url, "path": rel, "label": label})

    # Remove any stale second-slot QR left from a previous (pre-dedup) run so a
    # one-link paper never keeps a leftover duplicate code.png on disk.
    for i in range(len(results), len(slot_names)):
        stale = qr_dir / f"{slot_names[i]}.png"
        if stale.exists():
            stale.unlink()

    # Persist the manifest into metadata.json so deterministic post-build steps
    # (paper2poster fit_logos.py) can caption each QR without re-deriving.
    if meta_path is not None and results:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["qr"] = results
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        except Exception as e:
            print(f"[make_qr] WARNING: could not write qr manifest into {meta_path}: {e}",
                  file=sys.stderr)

    print(json.dumps({"qr": results}, indent=2))
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
