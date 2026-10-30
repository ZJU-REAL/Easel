"""Canonical output-bundle layout — the cross-skill contract.

Every paper2* skill writes one bundle directory named after the paper. The
bundle's top level holds ONLY the skill's deliverable FILES; everything else
(runtime dependencies + build intermediates) lives under a single ``assets/``
container:

    <bundle>/
      <deliverables>          # poster.{html,pdf,png,pptx} | blog_*.docx | *.mp4 | reel.html
      manifest.json           # package index (the paths below are root-relative)
      assets/
        figures/  logos/  qr/  audio/  fonts/   # runtime deps the deliverables reference
        meta/                                    # build intermediates
          paper_spec.md  sections.json  narration.json
          captions.json   figures.json  metadata.json  text.txt

This module is the single source of truth for those subpaths, so relocating the
layout later is a one-file edit. The string constants are POSIX-relative to the
bundle root — exactly what ``manifest.json`` records and what ``poster.html``
emits in ``<img src>`` (the deliverable resolves them relative to its own
location, so no absolute paths leak into the bundle).
"""
from __future__ import annotations

from pathlib import Path

# Schema marker stamped into manifest.json so a consumer can tell a new
# assets/ bundle from a legacy flat one.
LAYOUT_VERSION = "v2-assets"

# Root-relative POSIX directory paths (used in manifest.json + poster.html src).
ASSETS = "assets"
FIGURES = "assets/figures"
LOGOS = "assets/logos"
QR = "assets/qr"
AUDIO = "assets/audio"
FONTS = "assets/fonts"
META = "assets/meta"

# Root-relative POSIX paths for the build-intermediate files under meta/.
META_FILES: dict[str, str] = {
    "text": "assets/meta/text.txt",
    "captions": "assets/meta/captions.json",
    "metadata": "assets/meta/metadata.json",
    "figures": "assets/meta/figures.json",
    "sections": "assets/meta/sections.json",
    "narration": "assets/meta/narration.json",
    "paper_spec": "assets/meta/paper_spec.md",
}

# The one index file allowed at the bundle root.
MANIFEST = "manifest.json"


def _sub(outdir: Path | str, rel: str, *, create: bool = False) -> Path:
    p = Path(outdir) / rel
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def figures_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, FIGURES, create=create)


def logos_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, LOGOS, create=create)


def qr_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, QR, create=create)


def audio_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, AUDIO, create=create)


def fonts_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, FONTS, create=create)


def meta_dir(outdir: Path | str, *, create: bool = False) -> Path:
    return _sub(outdir, META, create=create)


def meta_file(outdir: Path | str, key: str, *, create_parent: bool = False) -> Path:
    """Absolute path to a build-intermediate file (key from META_FILES)."""
    p = Path(outdir) / META_FILES[key]
    if create_parent:
        p.parent.mkdir(parents=True, exist_ok=True)
    return p


def manifest_path(outdir: Path | str) -> Path:
    return Path(outdir) / MANIFEST


def ensure_dirs(outdir: Path | str) -> None:
    """Create the standard assets/ subtree under a bundle root."""
    for fn in (figures_dir, logos_dir, qr_dir, audio_dir, meta_dir):
        fn(outdir, create=True)
