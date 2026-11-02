#!/usr/bin/env python3
"""Re-crop an extracted figure PNG in place, with a safety backup.

The figure extractor (extract_pdf.py) is heuristic and usually right, but a few
failure modes slip through: a uniform white margin that makes the figure paint
as a tiny stamp on the poster, an orphaned caption strip or page-footer line
left inside the image, or a neighboring sub-figure bleeding in from the side.
This script is the corrective tool the figure-review step reaches for after it
has *looked* at a figure and named a specific defect.

Two modes, matched to the two defect classes:

  autotrim  — strip uniform near-white border margins. Use when the figure
              content is correct but floats in whitespace. Safe and reversible;
              it only ever removes border rows/cols that are within `--tol` of
              white, so it cannot eat into real content.

  box       — crop to an explicit pixel rectangle. Use when there is *content*
              to cut: an orphaned caption line, a bled-in neighbor panel, a
              footer/page number. You pass the box you read off the image.

  decaption — auto-detect and strip a baked-in caption band along the BOTTOM of
              the figure. The extractor's figure bbox often over-reaches into the
              paper's own "Figure N: ..." caption text, which then collides with
              the poster's HTML <figcaption> and gets half-clipped by the figure
              box. This mode finds a short text band separated from the figure
              content by a clear horizontal whitespace gap and (with --apply)
              cuts it off. Report-only by default — pass --apply to crop.

  top-check — auto-detect and strip a thin chrome residue band along the TOP of
              the figure (page running title, conference banner remnant, the
              bottom 1-3 px of a horizontal rule line, etc.). The extractor's
              upper boundary is set by the column-aware "prev_y" logic but on
              dense pages it can leave a 1-6 px dark band stuck to the top edge
              with a small whitespace gutter to the figure content. Visual
              verification systematically misses these 1-3 px residues — they
              don't disturb the figure body, so the eye smooths over them. This
              detector pattern-matches the chrome signature (dense band → clean
              gutter → figure content) and reports the exact cut Y. Report-only
              by default — pass --apply to crop.

The first three modes (and top-check with --apply) write `_debug/<file>.bak` (once — re-runs don't clobber the original) and,
if a figures.json is found alongside the image, update that entry's width/height
so downstream layout math stays consistent. Print the before/after dimensions so
the caller can sanity-check the result without re-opening the file.

Usage:
  crop_figure.py autotrim <image.png> [--tol 8] [--pad 4]
  crop_figure.py box <image.png> --box X0 Y0 X1 Y1
  crop_figure.py decaption <image.png> [--apply]   # detect/strip bottom caption band
  crop_figure.py top-check <image.png> [--apply]   # detect/strip top chrome residue band
  crop_figure.py inspect <image.png>          # print size + border-whitespace report

Coordinates are pixels in the saved PNG (origin top-left), the same frame you
see when you open the file. Use `inspect` first if you need the dimensions.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def _load(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _debug_dir(path: Path) -> Path:
    """Ensure and return the per-figures-dir `_debug/` subdir.

    All non-deliverable artifacts (one-shot raw-extract `.bak` backups and
    per-iteration `marked-<NN>.png` overlays) live under this hidden subdir
    so that the parent `figures/` listing contains ONLY clean final files
    that downstream renderers consume. The `_debug/` artifacts are kept as
    auditable breadcrumbs of the crop decision process — pruning them is
    a manual cleanup, not something the agent should do mid-workflow.
    """
    d = path.parent / "_debug"
    d.mkdir(exist_ok=True)
    return d


def _bak_path(path: Path) -> Path:
    """One-shot raw-extract backup path for a figure, under `_debug/`.

    The backup captures the figure's first state (i.e. straight from
    `extract_pdf.py`) before any 5a-5d processing modifies it. `_backup()`
    only writes once — re-runs of the cleanup chain never clobber the
    original raw extract.
    """
    return _debug_dir(path) / (path.name + ".bak")


def _next_marked_path(path: Path) -> Path:
    """Return the next `marked-<NN>.png` path under `_debug/`.

    Each call to `mark` rotates to a fresh filename (`<stem>.marked-01.png`,
    `marked-02.png`, ...) so iterative mark-then-tweak cycles preserve the
    full bbox-decision history for later review. Two-digit zero-padded so
    file listings sort lexicographically.
    """
    d = _debug_dir(path)
    stem = path.stem
    n = 1
    while (d / f"{stem}.marked-{n:02d}.png").exists():
        n += 1
    return d / f"{stem}.marked-{n:02d}.png"


def _next_preview_path(path: Path) -> Path:
    """Return the next `preview-<NN>.png` path under `_debug/`.

    Preview rotates in parallel with `marked-<NN>.png` — round N's mark
    and round N's preview pair together (`marked-01.png` shows the bbox
    on the original raster; `preview-01.png` shows what the figure would
    look like AFTER applying that bbox crop). The verifier sub-agent
    judges the preview directly (no red-line geometry to interpret),
    while the mark is kept for auditability.
    """
    d = _debug_dir(path)
    stem = path.stem
    n = 1
    while (d / f"{stem}.preview-{n:02d}.png").exists():
        n += 1
    return d / f"{stem}.preview-{n:02d}.png"


def _backup(path: Path) -> None:
    """Write `_debug/<name>.bak` once (re-runs don't clobber the original).

    The first time any destructive crop-mode (`box`, `autotrim`, `decaption`,
    `top-check --apply`, `split`) touches a figure, it captures the
    raw-extract state here. Recovery from a bad crop is then `cp
    figures/_debug/<name>.png.bak figures/<name>.png`.
    """
    bak = _bak_path(path)
    if not bak.exists():
        bak.write_bytes(path.read_bytes())


def _update_manifest(path: Path, w: int, h: int) -> bool:
    """If a sibling figures.json references this image, update its w/h.

    Returns True if an entry was updated. Searches both legacy colocated
    manifests and the v2 bundle layout (`assets/meta/figures.json`).
    """
    rel_names = {path.name, f"figures/{path.name}", str(path)}
    for cand in (
        path.parent / "figures.json",
        path.parent.parent / "figures.json",
        path.parent.parent / "meta" / "figures.json",
    ):
        if not cand.exists():
            continue
        try:
            data = json.loads(cand.read_text())
        except Exception:
            continue
        changed = False
        for entry in data if isinstance(data, list) else []:
            f = entry.get("file", "")
            if f in rel_names or Path(f).name == path.name:
                entry["width"], entry["height"] = w, h
                changed = True
        if changed:
            cand.write_text(json.dumps(data, indent=2))
            return True
    return False


def _split_manifest(orig_path: Path, child_specs: list[tuple[Path, int, int]]) -> bool:
    """Replace a single figure entry in figures.json with multiple child entries.

    Used by the `split` mode when a single extracted raster actually contains
    two (or more) independent side-by-side figures that should each be their
    own asset. Each child inherits the original's `page` and `layout` fields;
    only `file`, `width`, `height` differ.

    Returns True if a manifest entry was replaced. Children are inserted in
    the same position as the original (so document order in figures.json
    follows page order).
    """
    rel_names = {orig_path.name, f"figures/{orig_path.name}", str(orig_path)}
    for cand in (
        orig_path.parent / "figures.json",
        orig_path.parent.parent / "figures.json",
        orig_path.parent.parent / "meta" / "figures.json",
    ):
        if not cand.exists():
            continue
        try:
            data = json.loads(cand.read_text())
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for i, entry in enumerate(data):
            f = entry.get("file", "")
            if f in rel_names or Path(f).name == orig_path.name:
                template = dict(entry)  # keep page, layout, any other extras
                new_entries = []
                for child_path, cw, ch in child_specs:
                    rel = f"assets/figures/{child_path.name}" if "figures" in str(child_path.parent) else child_path.name
                    new = dict(template)
                    new["file"] = rel
                    new["width"], new["height"] = cw, ch
                    new_entries.append(new)
                data[i:i + 1] = new_entries
                cand.write_text(json.dumps(data, indent=2))
                return True
    return False


def _whitespace_report(arr: np.ndarray, tol: int):
    """Return how many border rows/cols (top, bottom, left, right) are near-white."""
    near_white = (arr >= 255 - tol).all(axis=2)  # H x W bool
    h, w = near_white.shape

    def count_leading(mask_1d):
        c = 0
        for v in mask_1d:
            if v:
                c += 1
            else:
                break
        return c

    row_white = near_white.all(axis=1)  # each row fully white?
    col_white = near_white.all(axis=0)
    top = count_leading(row_white)
    bottom = count_leading(row_white[::-1])
    left = count_leading(col_white)
    right = count_leading(col_white[::-1])
    return top, bottom, left, right


def cmd_inspect(path: Path, tol: int) -> int:
    img = _load(path)
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    top, bottom, left, right = _whitespace_report(arr, tol)
    print(f"{path.name}: {w}x{h} px")
    print(f"  near-white border (tol={tol}): "
          f"top={top} bottom={bottom} left={left} right={right}")
    total_margin = top + bottom + left + right
    if total_margin == 0:
        print("  no trimmable border whitespace — crop looks tight")
    else:
        print(f"  autotrim would remove ~{top+bottom}px vertical, "
              f"{left+right}px horizontal")
    return 0


def cmd_autotrim(path: Path, tol: int, pad: int) -> int:
    img = _load(path)
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    top, bottom, left, right = _whitespace_report(arr, tol)
    if top + bottom + left + right == 0:
        print(f"{path.name}: no border whitespace to trim ({w}x{h}) — left untouched")
        return 0

    x0 = max(0, left - pad)
    y0 = max(0, top - pad)
    x1 = min(w, w - right + pad)
    y1 = min(h, h - bottom + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        print(f"{path.name}: autotrim would erase the image — refusing", file=sys.stderr)
        return 1

    _backup(path)
    cropped = img.crop((x0, y0, x1, y1))
    cropped.save(path)
    nw, nh = cropped.size
    upd = _update_manifest(path, nw, nh)
    print(f"{path.name}: autotrim {w}x{h} -> {nw}x{nh} "
          f"(removed L{left} R{right} T{top} B{bottom}, pad={pad})"
          + ("  [figures.json updated]" if upd else ""))
    return 0


def cmd_box(path: Path, box) -> int:
    img = _load(path)
    w, h = img.size
    x0, y0, x1, y1 = box
    # Clamp into bounds and sanity-check ordering.
    x0, x1 = sorted((max(0, min(x0, w)), max(0, min(x1, w))))
    y0, y1 = sorted((max(0, min(y0, h)), max(0, min(y1, h))))
    if x1 - x0 < 8 or y1 - y0 < 8:
        print(f"{path.name}: box {box} is too small after clamping — refusing",
              file=sys.stderr)
        return 1

    _backup(path)
    cropped = img.crop((x0, y0, x1, y1))
    cropped.save(path)
    nw, nh = cropped.size
    upd = _update_manifest(path, nw, nh)
    print(f"{path.name}: box crop {w}x{h} -> {nw}x{nh} "
          f"(kept x[{x0}:{x1}] y[{y0}:{y1}])"
          + ("  [figures.json updated]" if upd else ""))
    return 0


def _row_ink(arr: np.ndarray, tol: int) -> np.ndarray:
    """Per-row count of non-near-white pixels (the row's 'ink')."""
    non_white = (arr.min(axis=2) < 255 - tol)  # H x W bool
    return non_white.sum(axis=1)


def _detect_bottom_caption(arr: np.ndarray, tol: int):
    """Find a baked-in caption band along the figure's bottom edge.

    The signature we look for: the main figure content ends, then a band of
    near-blank rows (a clear horizontal gutter), then one or more short text
    bands (the 'Figure N: ...' caption, sometimes plus a page-footer line)
    before the image ends. We return the y at which to cut (keep rows [0:cut])
    plus a human-readable reason, or (None, reason) when no confident caption
    band is found.

    Approach: segment the image into vertical ink-blocks separated by blank
    gutters, take the tallest block as the figure body, and treat every block
    *below* the body that is short (caption-like) as caption/footer. Cut just
    above the topmost such trailing block. Conservative by design — it only
    fires when the trailing material is clearly shorter than the figure body,
    so a multi-panel figure or an in-figure legend is never mistaken for a
    caption.
    """
    h, w = arr.shape[:2]
    ink = _row_ink(arr, tol)
    # A row is a "gutter" (blank) row when almost nothing is drawn across it.
    # Use a LOW ABSOLUTE cutoff, not a fraction of the figure's own peak density:
    # a caption line spans most of the width and so carries a lot of ink even when
    # it renders faint (e.g. a 2px sliver at 12-16% coverage), whereas the margin
    # between the figure body and its caption is genuinely white (~0 ink). A
    # density-relative threshold scales with the figure and silently swallows a
    # faint caption on a low-density plot (the bug this replaces). The small
    # width-proportional term lets a faintly speckled gutter (stray anti-aliased
    # dots) still count as blank without ever masking a real text line.
    blank_thresh = max(3, int(0.02 * w))
    blank = ink <= blank_thresh

    gap_run_needed = max(6, int(0.012 * h))  # blank-row run that counts as a gutter

    # Segment into [start, end] ink-blocks separated by gutters of >= gap_run_needed.
    blocks = []
    y = 0
    while y < h:
        if blank[y]:
            y += 1
            continue
        start = y
        run = 0
        while y < h:
            if blank[y]:
                run += 1
                if run >= gap_run_needed:
                    break
            else:
                run = 0
            y += 1
        end = y - run  # last ink row of this block
        blocks.append((start, end))
    if len(blocks) < 2:
        return None, "single ink block — no caption band to separate"

    # Figure body = the tallest block.
    heights = [e - s + 1 for s, e in blocks]
    body_idx = max(range(len(blocks)), key=lambda i: heights[i])
    body_h = heights[body_idx]
    trailing = blocks[body_idx + 1:]
    if not trailing:
        return None, "no ink blocks below the figure body — bottom is clean"

    # High-precision guardrails. We would rather miss a caption (the agent still
    # eyeballs the figure in Step 5.6) than amputate real figure content, so we
    # only fire when the trailing material is unmistakably a caption:
    #   - the body is the dominant block (a real figure, not a stack of thin
    #     chart strips that got mis-segmented into many small blocks);
    #   - there are at most 3 trailing bands (a caption is 1-3 text lines);
    #   - the trailing bands are collectively thin vs the body and the image.
    # On any of these failing we leave the image untouched and say why.
    total_trailing = sum(heights[body_idx + 1:])
    if body_h < 0.40 * h:
        return None, (f"tallest block is only {body_h / h:.0%} of height — figure looks "
                      f"like stacked strips (e.g. a chart), not figure+caption (left intact)")
    if len(trailing) > 3:
        return None, (f"{len(trailing)} blocks below the body — too many to be a 1-3 line "
                      f"caption (likely chart/legend content, left intact)")
    if total_trailing > 0.15 * body_h or total_trailing > 0.15 * h:
        return None, (f"trailing blocks total {total_trailing}px "
                      f"({total_trailing / h:.0%} of height) — too tall to be a caption "
                      f"(left intact)")

    first_trailing_top = trailing[0][0]
    last_body_bottom = blocks[body_idx][1]
    # Cut at the middle of the gutter between the body and the first caption band.
    cut = (last_body_bottom + first_trailing_top) // 2 + 1
    reason = (f"{len(trailing)} trailing band(s) totalling {total_trailing}px below a "
              f"{first_trailing_top - last_body_bottom}px gutter "
              f"(figure body {body_h}px); cut at y={cut}")
    return cut, reason


def cmd_decaption(path: Path, tol: int, apply: bool) -> int:
    img = _load(path)
    arr = np.asarray(img)
    w, h = img.size
    cut, reason = _detect_bottom_caption(arr, tol)
    if cut is None:
        print(f"{path.name}: no bottom caption band detected — {reason}")
        return 0
    if not apply:
        print(f"{path.name}: DETECTED bottom caption band — {reason}")
        print(f"  re-run with --apply to crop to {w}x{cut} "
              f"(or use `box {path.name} --box 0 0 {w} <y>` for a custom cut)")
        return 0
    if cut < 8:
        print(f"{path.name}: caption cut would erase the figure — refusing",
              file=sys.stderr)
        return 1
    _backup(path)
    cropped = img.crop((0, 0, w, cut))
    cropped.save(path)
    nw, nh = cropped.size
    upd = _update_manifest(path, nw, nh)
    print(f"{path.name}: decaption {w}x{h} -> {nw}x{nh}  ({reason})"
          + ("  [figures.json updated]" if upd else ""))
    return 0


def _detect_top_chrome(arr: np.ndarray, tol: int):
    """Find a chrome residue band along the figure's TOP edge.

    The signature we look for, working from the top down:
      - (optional) leading near-white margin — skipped (autotrim's job).
      - A "chrome" prefix of non-clean rows. Most chrome has mixed density:
        e.g. a 1 px rule line (dense) followed by 5-10 px of sparse text
        remnants from a banner above. So we accept any first stretch of
        non-clean rows as candidate chrome, as long as it contains at
        least one dense row (to rule out stray noise).
      - A "clean gutter" of >=3 consecutive near-blank rows separating the
        chrome from the figure body.
      - Sustained ink below the gutter (the figure itself).

    Returns (cut_y, reason) when chrome detected (cut keeps rows [cut:H])
    or (None, reason) when the top is clean / pattern ambiguous.

    Why a separate detector from autotrim/decaption: those two assume the
    "noise" is *uniform near-white* (autotrim) or a *thick bottom caption
    block* (decaption). Chrome residue is neither — it's a thin mixed-
    density strip right at the top edge with a small whitespace gutter to
    the figure. autotrim leaves it (not pure white); decaption ignores
    the top entirely. Hence this dedicated check.

    Thresholds (intentionally conservative — would rather miss a faint
    chrome and let the visual second-pass catch it, than amputate a real
    top axis frame):
      - "dense" row: >= max(5% width, 5 px) non-near-white pixels.
        Catches full-width rule lines and banner residues; misses lone
        axis ticks (density well under 1%).
      - "clean" row: <= max(1% width, 1 px).
      - Gutter: >= 3 consecutive clean rows.
      - Chrome prefix max thickness: 15 px. A genuine chrome residue at
        zoom=6 sits in 1-12 px; anything thicker is probably a top legend
        or a figure header strip and we leave it alone.
    """
    h, w = arr.shape[:2]
    if h < 60:
        return None, "image too short to scan reliably (< 60 px tall)"
    ink = _row_ink(arr, tol)

    dense_floor = max(int(0.05 * w), 5)
    clean_floor = max(int(0.01 * w), 1)
    scan_height = min(50, h // 4)

    # Skip any leading near-white margin (autotrim's job).
    chrome_start = 0
    while chrome_start < scan_height and ink[chrome_start] <= clean_floor:
        chrome_start += 1
    if chrome_start >= scan_height:
        return None, (f"top {scan_height} px is clean white margin "
                      f"(run autotrim to strip it)")

    # Walk down the candidate chrome prefix until we hit a clean gutter
    # (>=3 consecutive clean rows). Track whether the prefix contains at
    # least one dense row — pure-sparse strips are stray noise, not chrome.
    has_dense = False
    gutter_start = None
    y = chrome_start
    while y < scan_height:
        if ink[y] >= dense_floor:
            has_dense = True
        if ink[y] <= clean_floor:
            # Could be the start of the gutter. Confirm 3 consecutive clean.
            window = min(3, h - y)
            if all(ink[y + k] <= clean_floor for k in range(window)):
                gutter_start = y
                break
        y += 1

    if gutter_start is None:
        return None, (f"top non-clean band starting at y={chrome_start} runs "
                      f"past {scan_height} px without a clean gutter — likely "
                      f"continuous figure content (top axis / legend / panel "
                      f"frame), leaving intact")

    chrome_thickness = gutter_start - chrome_start
    if not has_dense:
        return None, (f"top non-clean band ({chrome_thickness} px at y="
                      f"{chrome_start}..{gutter_start-1}) has no dense row — "
                      f"probably anti-aliased speckle, not chrome")
    if chrome_thickness > 15:
        return None, (f"top non-clean band is {chrome_thickness} px (>15) at "
                      f"y={chrome_start}..{gutter_start-1} — too thick for "
                      f"chrome residue, probably figure header / legend "
                      f"strip, leaving intact")

    # Confirm gutter height (already known >=3; measure how big).
    gutter_end = gutter_start
    while (gutter_end < h
           and gutter_end - gutter_start < 20
           and ink[gutter_end] <= clean_floor):
        gutter_end += 1
    gutter_height = gutter_end - gutter_start

    # Cut in the middle of the gutter — drops the chrome, keeps the
    # figure with a reasonable top margin.
    cut_y = gutter_start + (gutter_height // 2)
    reason = (f"chrome residue {chrome_thickness} px at y="
              f"{chrome_start}..{gutter_start-1}, gutter {gutter_height} px, "
              f"cut at y={cut_y}")
    return cut_y, reason


def cmd_top_check(path: Path, tol: int, apply: bool) -> int:
    img = _load(path)
    arr = np.asarray(img)
    w, h = img.size
    cut, reason = _detect_top_chrome(arr, tol)
    if cut is None:
        print(f"{path.name}: TOP clean — {reason}")
        return 0
    if not apply:
        print(f"{path.name}: TOP-CHROME DETECTED — {reason}")
        print(f"  re-run with --apply to crop to {w}x{h - cut}, "
              f"or use `box {path.name} --box 0 <y> {w} {h}` "
              f"for a custom cut.")
        return 0
    if cut > h - 50:
        print(f"{path.name}: cut at y={cut} would leave less than 50 px "
              f"— refusing", file=sys.stderr)
        return 1
    _backup(path)
    cropped = img.crop((0, cut, w, h))
    cropped.save(path)
    nw, nh = cropped.size
    upd = _update_manifest(path, nw, nh)
    print(f"{path.name}: top-check {w}x{h} -> {nw}x{nh}  ({reason})"
          + ("  [figures.json updated]" if upd else ""))
    return 0


def _col_ink(arr: np.ndarray, tol: int) -> np.ndarray:
    """Per-column count of non-near-white pixels (the column's 'ink')."""
    non_white = (arr.min(axis=2) < 255 - tol)
    return non_white.sum(axis=0)


def _find_ink_blocks_1d(ink: np.ndarray, length: int, w: int,
                        dense_pct: float = 0.05, gap_min: int = 5):
    """Segment a 1-D ink profile into 'dense' blocks separated by clean gutters.

    A *block* is a contiguous run of rows (or columns) whose ink count exceeds
    `dense_pct * w` pixels. Two blocks are split only when `gap_min` or more
    consecutive low-ink lines separate them. This is the same algorithm the
    Step 5d agent workflow relies on to enumerate the figure's structural
    parts (legend / chart body / axis labels / sub-caption / etc.) so the
    bbox decision can ground itself in real pixel boundaries instead of
    eyeballed estimates.

    Returns a list of ``(start, end)`` inclusive index pairs.
    """
    dense_floor = max(int(dense_pct * w), 5)
    clean_floor = max(int(0.005 * w), 1)
    blocks: list[tuple[int, int]] = []
    in_block = False
    start = 0
    gap_run = 0
    for i in range(length):
        v = ink[i]
        if v >= dense_floor:
            if not in_block:
                start = i; in_block = True
            gap_run = 0
        else:
            if in_block:
                if v <= clean_floor:
                    gap_run += 1
                else:
                    gap_run = 0
                if gap_run >= gap_min:
                    blocks.append((start, i - gap_run + 1))
                    in_block = False
                    gap_run = 0
    if in_block:
        blocks.append((start, length - 1))
    return blocks


def cmd_blocks(path: Path, tol: int) -> int:
    """Print the figure's ink-block structure (row-wise + column-wise).

    Use this BEFORE deciding a bbox in Step 5d. The output names every
    dense band in the figure and the gap between bands — which lets you
    distinguish 'narrow column adjacent to figure body' (= axis labels /
    legend, KEEP) from 'wide gap separates body-text column from figure'
    (= paper prose, CUT).
    """
    img = _load(path)
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    ri = _row_ink(arr, tol)
    ci = _col_ink(arr, tol)
    rb = _find_ink_blocks_1d(ri, h, w)
    cb = _find_ink_blocks_1d(ci, w, h)

    print(f"{path.name}: {w}x{h} px  (tol={tol})")
    print(f"  ROW blocks (top→bottom):")
    for i, (s, e) in enumerate(rb):
        gap_below = (rb[i + 1][0] - e - 1) if i + 1 < len(rb) else None
        gap_str = f"  ↓ gap {gap_below} px" if gap_below is not None else ""
        print(f"    y={s:>5}..{e:<5}  h={e - s + 1:>4}{gap_str}")
    if not rb:
        print(f"    (no dense row blocks at dense_pct=0.05)")
    print(f"  COL blocks (left→right):")
    for i, (s, e) in enumerate(cb):
        gap_right = (cb[i + 1][0] - e - 1) if i + 1 < len(cb) else None
        gap_str = f"  → gap {gap_right} px" if gap_right is not None else ""
        print(f"    x={s:>5}..{e:<5}  w={e - s + 1:>4}{gap_str}")
    if not cb:
        print(f"    (no dense col blocks)")

    # Heuristic hint: spot column blocks adjacent to a wider neighbor — those
    # are most likely axis labels / legend / rotated y-titles that should be
    # KEPT in any crop. Wide gaps (>30 px) typically signal a separate
    # element (body-text column from the paper, OR adjacent figure bleed).
    print("  hint:")
    if cb:
        widest = max(cb, key=lambda b: b[1] - b[0] + 1)
        wi = widest[1] - widest[0] + 1
        for s, e in cb:
            if (s, e) == widest:
                continue
            w_b = e - s + 1
            if e < widest[0]:
                gap = widest[0] - e - 1
                side = "LEFT"
            else:
                gap = s - widest[1] - 1
                side = "RIGHT"
            if w_b < wi * 0.4 and gap < 30:
                print(f"    {side} narrow block (w={w_b}) is {gap} px from main body "
                      f"(w={wi}) → likely axis labels / legend / rotated title; "
                      f"INCLUDE in bbox")
            elif gap >= 50:
                print(f"    {side} block (w={w_b}) is {gap} px away from main body "
                      f"(w={wi}) → likely paper text column or adjacent figure; "
                      f"EXCLUDE from bbox unless visual recheck says it's figure content")
    return 0


def cmd_mark(path: Path, box, stroke: int, outside: int) -> int:
    """Draw a red rectangle OUTSIDE the proposed bbox and save to
    ``<file>.marked.png`` (never overwrites the original PNG).

    The mark step is the verification gate: after deciding a bbox from the
    `blocks` analysis, draw it, Re-Read the marked image, and confirm the
    box encloses the figure's panels + axis labels + sub-captions while
    excluding paper-text / banner / main caption. Only after this
    verification does Step 5d call `box` to commit the crop.

    Stroke is drawn OFFSET OUTWARD from the bbox edges (clamped to image
    bounds), so the line never paints over content right at the bbox
    boundary — important because panel titles, sub-captions, and axis
    labels often sit a few pixels inside the proposed bbox.
    """
    img = _load(path)
    w, h = img.size
    x0, y0, x1, y1 = box
    x0, x1 = sorted((max(0, min(x0, w)), max(0, min(x1, w))))
    y0, y1 = sorted((max(0, min(y0, h)), max(0, min(y1, h))))
    if x1 - x0 < 8 or y1 - y0 < 8:
        print(f"{path.name}: box {box} too small after clamping — refusing",
              file=sys.stderr)
        return 1
    import PIL.ImageDraw as ImageDraw
    draw = ImageDraw.Draw(img)
    for off in range(stroke):
        ox = -outside - off
        oy = -outside - off
        rx0 = max(0, x0 + ox)
        ry0 = max(0, y0 + oy)
        rx1 = min(w - 1, x1 - 1 - ox)
        ry1 = min(h - 1, y1 - 1 - oy)
        draw.rectangle([rx0, ry0, rx1, ry1], outline=(220, 30, 30))
    out_path = _next_marked_path(path)
    img.save(out_path)
    pct_w = 100 * (x1 - x0) / w
    pct_h = 100 * (y1 - y0) / h
    print(f"{path.name}: marked bbox ({x0},{y0},{x1},{y1}) "
          f"[{pct_w:.0f}% w × {pct_h:.0f}% h]  →  _debug/{out_path.name}")
    return 0


def cmd_preview(path: Path, box) -> int:
    """Produce a non-destructive preview of what the bbox crop would yield.

    Writes ``_debug/<stem>.preview-<NN>.png`` next to (but never touching)
    the original. Pairs round-by-round with `mark`: round N's mark shows
    the bbox overlaid on the original with a red rectangle; round N's
    preview shows what the cropped figure would actually look like.

    The preview removes the geometric-polarity confusion of the marked
    PNG (verifier confused about which side of the red line is kept):
    the preview IS the kept side, period. Sub-agent verifiers can judge
    'is this a complete clean figure?' directly without translating any
    red-line geometry.
    """
    img = _load(path)
    w, h = img.size
    x0, y0, x1, y1 = box
    x0, x1 = sorted((max(0, min(x0, w)), max(0, min(x1, w))))
    y0, y1 = sorted((max(0, min(y0, h)), max(0, min(y1, h))))
    if x1 - x0 < 8 or y1 - y0 < 8:
        print(f"{path.name}: box {box} too small after clamping — refusing",
              file=sys.stderr)
        return 1
    out_path = _next_preview_path(path)
    img.crop((x0, y0, x1, y1)).save(out_path)
    print(f"{path.name}: preview bbox ({x0},{y0},{x1},{y1}) "
          f"→  _debug/{out_path.name}  ({x1 - x0}x{y1 - y0})")
    return 0


def cmd_split(path: Path, boxes: list[tuple[int, int, int, int]],
              suffixes: list[str]) -> int:
    """Split one extracted raster into multiple independent figures.

    Used when a single PDF extraction packed two (or more) side-by-side
    figures into one raster because they shared a page row in the source
    paper. The signature pattern: figures A and B sit side-by-side; A has
    its own caption below it that does NOT extend under B (so B is taller
    than A+caption, OR they have separate sub-captions). They are NOT one
    figure — they are two, and downstream renderers should be able to pick
    either independently.

    For each provided bbox, writes a new file ``<stem><suffix>.png`` next to
    the original (e.g. ``page5_figure4.png`` -> ``page5_figure4_a.png`` +
    ``page5_figure4_b.png``). Then:
      - removes the original PNG from disk
      - replaces the original entry in figures.json with one entry per child
        (inheriting page + layout from the original; new file/width/height)
      - PRESERVES the ``.bak`` from 5a-5c (so the raw extract is still
        recoverable if the split was misjudged)

    Each child file does NOT get its own ``.bak`` — the shared ``.bak`` of
    the original raster (under ``_debug/``) is the recovery source for both.
    To undo a bad split: ``cp _debug/<stem>.png.bak <stem>.png && rm
    <stem>_*.png`` then re-run a regular box crop.
    """
    if len(boxes) != len(suffixes):
        print(f"{path.name}: --boxes count ({len(boxes)}) != --suffixes count "
              f"({len(suffixes)}) — refusing", file=sys.stderr)
        return 1
    if len(boxes) < 2:
        print(f"{path.name}: split needs >=2 boxes — use `box` for single crop",
              file=sys.stderr)
        return 1
    img = _load(path)
    w, h = img.size
    children: list[tuple[Path, int, int]] = []
    for (x0, y0, x1, y1), sfx in zip(boxes, suffixes):
        x0, x1 = sorted((max(0, min(x0, w)), max(0, min(x1, w))))
        y0, y1 = sorted((max(0, min(y0, h)), max(0, min(y1, h))))
        if x1 - x0 < 8 or y1 - y0 < 8:
            print(f"{path.name}: child box ({x0},{y0},{x1},{y1}) too small after "
                  f"clamping — refusing", file=sys.stderr)
            return 1
        cropped = img.crop((x0, y0, x1, y1))
        sfx = sfx if sfx.startswith("_") else f"_{sfx}"
        out = path.with_name(path.stem + sfx + path.suffix)
        cropped.save(out)
        cw, ch = cropped.size
        children.append((out, cw, ch))
        print(f"{path.name}: split child → {out.name}  ({cw}x{ch} from bbox "
              f"({x0},{y0},{x1},{y1}))")

    upd = _split_manifest(path, children)
    # Remove the original PNG — it's been replaced by the children. The .bak
    # is preserved (provides recovery for both children if either was wrong).
    try:
        path.unlink()
    except Exception as e:
        print(f"{path.name}: failed to remove original after split: {e}",
              file=sys.stderr)
    print(f"{path.name}: split into {len(children)} children "
          + ("[figures.json updated]" if upd else "[figures.json NOT updated — "
             "no matching entry found; manifest may be stale]"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="report size + border whitespace")
    p_ins.add_argument("image")
    p_ins.add_argument("--tol", type=int, default=8)

    p_at = sub.add_parser("autotrim", help="strip near-white border margins")
    p_at.add_argument("image")
    p_at.add_argument("--tol", type=int, default=8,
                      help="how close to white (0-255) counts as background")
    p_at.add_argument("--pad", type=int, default=4,
                      help="px of margin to keep around trimmed content")

    p_box = sub.add_parser("box", help="crop to explicit pixel rectangle")
    p_box.add_argument("image")
    p_box.add_argument("--box", type=int, nargs=4, required=True,
                       metavar=("X0", "Y0", "X1", "Y1"))

    p_dc = sub.add_parser("decaption",
                          help="detect/strip a baked-in caption band at the bottom")
    p_dc.add_argument("image")
    p_dc.add_argument("--tol", type=int, default=8,
                      help="how close to white (0-255) counts as background")
    p_dc.add_argument("--apply", action="store_true",
                      help="actually crop (default: report only)")

    p_tc = sub.add_parser("top-check",
                          help="detect/strip a thin chrome residue band at the TOP edge "
                               "(page rule lines, banner remnants, running-title strips)")
    p_tc.add_argument("image")
    p_tc.add_argument("--tol", type=int, default=8,
                      help="how close to white (0-255) counts as background")
    p_tc.add_argument("--apply", action="store_true",
                      help="actually crop (default: report only)")

    p_bl = sub.add_parser("blocks",
                          help="pixel-level ink-block analysis (use BEFORE deciding a bbox)")
    p_bl.add_argument("image")
    p_bl.add_argument("--tol", type=int, default=8,
                      help="how close to white (0-255) counts as background")

    p_mk = sub.add_parser("mark",
                          help="draw a red bbox on a copy of the image (verification gate "
                               "before committing a `box` crop). Writes <file>.marked.png.")
    p_mk.add_argument("image")
    p_mk.add_argument("--box", type=int, nargs=4, required=True,
                      metavar=("X0", "Y0", "X1", "Y1"))
    p_mk.add_argument("--stroke", type=int, default=3,
                      help="red outline thickness in pixels (default 3)")
    p_mk.add_argument("--outside", type=int, default=2,
                      help="px offset of the stroke OUTSIDE the bbox so it never "
                           "obscures content right at the bbox boundary (default 2)")

    p_pv = sub.add_parser("preview",
                          help="non-destructive crop preview — writes the cropped figure "
                               "to _debug/<stem>.preview-<NN>.png without touching the "
                               "original. Pairs with `mark` for the verifier sub-agent "
                               "(verifier judges the preview directly, no red-line "
                               "geometry to interpret).")
    p_pv.add_argument("image")
    p_pv.add_argument("--box", type=int, nargs=4, required=True,
                      metavar=("X0", "Y0", "X1", "Y1"))

    p_sp = sub.add_parser("split",
                          help="split one raster into multiple independent figures "
                               "(side-by-side packed figures with their own captions). "
                               "Writes <stem>_<suffix>.png per child, replaces the original "
                               "entry in figures.json with one per child.")
    p_sp.add_argument("image")
    p_sp.add_argument("--box", type=int, nargs=4, action="append", required=True,
                      metavar=("X0", "Y0", "X1", "Y1"),
                      help="bbox for one child; pass --box twice (or more) for "
                           "multiple children")
    p_sp.add_argument("--suffix", action="append", required=True,
                      help="filename suffix per child (e.g. 'a', 'b'); pass once "
                           "per --box. The child filename is <stem>_<suffix>.png.")

    args = ap.parse_args()
    path = Path(args.image).resolve()
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1

    if args.cmd == "inspect":
        return cmd_inspect(path, args.tol)
    if args.cmd == "autotrim":
        return cmd_autotrim(path, args.tol, args.pad)
    if args.cmd == "box":
        return cmd_box(path, args.box)
    if args.cmd == "decaption":
        return cmd_decaption(path, args.tol, args.apply)
    if args.cmd == "top-check":
        return cmd_top_check(path, args.tol, args.apply)
    if args.cmd == "blocks":
        return cmd_blocks(path, args.tol)
    if args.cmd == "mark":
        return cmd_mark(path, args.box, args.stroke, args.outside)
    if args.cmd == "preview":
        return cmd_preview(path, args.box)
    if args.cmd == "split":
        boxes = [tuple(b) for b in args.box]
        return cmd_split(path, boxes, args.suffix)
    return 1


if __name__ == "__main__":
    sys.exit(main())
