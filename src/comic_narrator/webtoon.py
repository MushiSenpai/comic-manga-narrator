"""Webtoon ingestion — vertical-scroll strips → readable panel segments.

Webtoons (Solo Leveling, most Korean/Korean-style series) are not pages:
they are tall vertical strips (720px wide, thousands of px tall — some
40,000+). Two hard problems the page pipeline can't handle:

  1. Rendering a strip at 300 DPI explodes it to hundreds of megapixels and
     OOMs. We extract embedded images at NATIVE resolution instead.
  2. Feeding a 720x3000 strip to a vision model downscales the lettering into
     mush. We slice each strip into panel-height segments along the
     horizontal whitespace gutters webtoons use to separate beats, so each
     segment is roughly page-shaped and legible.

A gutterless action run (no whitespace for thousands of px) falls back to a
capped fixed-stride slice so no single segment is unreadable-tall.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# Slicing geometry (px, native webtoon scale ~720 wide)
MAX_SEGMENT_H = 1600      # hard cap — taller than this and the model can't read it
MIN_SEGMENT_H = 200       # don't emit slivers; merge upward
GUTTER_MIN_H = 18         # a whitespace band this tall counts as a gutter
GUTTER_STD_MAX = 8.0      # row is "background" if its pixel std is below this
SEARCH_FROM = 0.55        # only look for a cut in the lower part of the window


def extract_strips_native(pdf_path: Path, out_dir: Path) -> list[Path]:
    """Extract each PDF page's embedded image at native resolution.

    Resumable: existing page_NNNN.* are reused. Returns ordered paths.
    """
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with fitz.open(pdf_path) as doc:
        for i in range(len(doc)):
            # Most webtoon PDFs are one full-page image per page; grab it at
            # native res. Fall back to a modest-DPI render if there isn't one.
            existing = list(out_dir.glob(f"page_{i + 1:04d}.*"))
            if existing:
                paths.append(existing[0])
                continue
            page = doc[i]
            imgs = page.get_images(full=True)
            if len(imgs) == 1:
                xref = imgs[0][0]
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK etc.
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                out = out_dir / f"page_{i + 1:04d}.png"
                pix.save(str(out))
            else:
                # Zero or multiple images: render the page at a safe DPI,
                # clamped so a 40k-px strip can't explode.
                scale = min(2.0, 2000.0 / max(page.rect.height, 1))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                out = out_dir / f"page_{i + 1:04d}.png"
                pix.save(str(out))
            paths.append(out)
    return paths


def find_gutters(gray: np.ndarray) -> list[tuple[int, int]]:
    """Return (start, end) row ranges that are whitespace/background gutters.

    A row is background if its horizontal pixel std is low (flat color, light
    or dark). Consecutive background rows >= GUTTER_MIN_H form a gutter.
    """
    row_std = gray.std(axis=1)
    is_bg = row_std < GUTTER_STD_MAX
    gutters: list[tuple[int, int]] = []
    run_start = None
    for y, bg in enumerate(is_bg):
        if bg and run_start is None:
            run_start = y
        elif not bg and run_start is not None:
            if y - run_start >= GUTTER_MIN_H:
                gutters.append((run_start, y))
            run_start = None
    if run_start is not None and len(is_bg) - run_start >= GUTTER_MIN_H:
        gutters.append((run_start, len(is_bg)))
    return gutters


def slice_strip(strip_path: Path, out_dir: Path, stem: str) -> list[Path]:
    """Slice one tall strip into panel-height segments. Returns segment paths.

    Greedy from the top: extend a window up to MAX_SEGMENT_H, cut at the last
    gutter centre inside it; if none, hard-cut at MAX_SEGMENT_H (gutterless
    action). Background-only segments are dropped; runt tails merge upward.
    """
    from PIL import Image

    img = Image.open(strip_path).convert("RGB")
    w, h = img.size
    gray = np.asarray(img.convert("L"), dtype=np.float64)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Short strip → it's already a single panel.
    if h <= MAX_SEGMENT_H:
        out = out_dir / f"{stem}_p001.png"
        img.save(out)
        return [out]

    gutter_mids = [ (a + b) // 2 for a, b in find_gutters(gray) ]
    cuts = [0]
    y = 0
    while h - y > MAX_SEGMENT_H:
        window_lo = y + int(MAX_SEGMENT_H * SEARCH_FROM)
        window_hi = y + MAX_SEGMENT_H
        candidates = [g for g in gutter_mids if window_lo <= g <= window_hi]
        nxt = max(candidates) if candidates else window_hi
        cuts.append(nxt)
        y = nxt
    cuts.append(h)

    segments: list[Path] = []
    idx = 0
    for a, b in zip(cuts, cuts[1:]):
        if b - a < MIN_SEGMENT_H:
            continue  # runt — fold into the previous by skipping the cut
        seg = img.crop((0, a, w, b))
        # Drop a segment that is essentially blank (gutter-only)
        if np.asarray(seg.convert("L"), dtype=np.float64).std() < GUTTER_STD_MAX:
            continue
        idx += 1
        out = out_dir / f"{stem}_p{idx:03d}.png"
        seg.save(out)
        segments.append(out)
    return segments or [strip_path]


def webtoon_to_panels(
    pdf_path: Path,
    work_dir: Path,
    first_page: int = 1,
    last_page: int | None = None,
) -> list[Path]:
    """PDF webtoon → flat ordered list of panel images for [first,last] pages.

    Each PDF strip is extracted at native res then sliced; the panels are
    numbered globally so reading order is preserved across the whole run.
    """
    strips_dir = work_dir / "strips"
    panels_dir = work_dir / "panels"
    all_strips = extract_strips_native(Path(pdf_path), strips_dir)
    lo = max(first_page - 1, 0)
    hi = last_page if last_page is not None else len(all_strips)
    selected = all_strips[lo:hi]

    panels: list[Path] = []
    for n, strip in enumerate(selected, start=first_page):
        panels += slice_strip(strip, panels_dir, f"strip_{n:04d}")
    return panels
