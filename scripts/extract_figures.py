#!/usr/bin/env python3
"""Extract figures from paper PDFs by rendering the page region near each
caption, rather than pulling out individual embedded images.

Loops over every session row in frontend/schedule.csv that has a paper_id — zero, five, or
fifty entries all work the same way — and skips gracefully wherever a PDF
hasn't been dropped into data/papers/<paper_id>.pdf yet (see
scripts/fetch_papers.py). Re-running after adding more entries/PDFs just
picks up whatever's newly present. Matching is by paper_id, not DOI — a
paper can be indexed before its DOI is even assigned.

Incremental: a paper whose figures.json is already newer than its PDF is
skipped, not reprocessed — dropping in a handful more papers the night
before the event and re-running only costs time for the new ones. Pass
--force to reprocess everything regardless (e.g. after changing this
script's extraction logic itself).

Why a region-render instead of extracting each embedded image (page.
get_images()): real academic PDFs broke that approach outright — a single
figure is often composed of many separate embedded XObjects (observed: one
figure tiled across 12 embedded images, each a small mosaic cell but with a
*high native pixel resolution*, so a native-resolution size filter let all
12 through as if they were 12 separate real figures), and some embedded
images use colorspaces (Separation/spot-color, seen in practice) that
crash a naive PNG save. Rendering the clipped page region instead sidesteps
both problems — it doesn't care how many XObjects or what colorspace
compose the artwork, it just rasterizes whatever's actually drawn there —
and picks up vector-drawn figures for free, which raw image extraction
never could.

A caption match ("Figure N" / "Fig. N" text nearby) is required for a
region to be captured at all — this is what anchors each region and avoids
capturing headers, footers, or arbitrary page content.

Usage:
    uv run python scripts/extract_figures.py [--force]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.papers import FIGURES_DIR, PAPERS_DIR, read_papers

RENDER_DPI = 150
COLUMN_MARGIN = 15  # points — widen the caption's own column width slightly
BOTTOM_PADDING = 6  # points — a sliver of slack so a figure's own bottom edge
                     # (e.g. embedded label text) isn't clipped by the caption's
                     # block boundary sitting a few points tighter than the art
MAX_FIGURE_HEIGHT = 380  # points — safety cap when nothing bounds the region above
MIN_FIGURE_HEIGHT = 30  # points — thinner than this isn't a real figure, skip it
CAPTION_RE = re.compile(r"^\s*fig(?:ure)?\.?\s*(\d+)", re.IGNORECASE)


def page_blocks(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str]]:
    return [(pymupdf.Rect(b[0], b[1], b[2], b[3]), b[4].strip()) for b in page.get_text("blocks")]


def find_captions(blocks: list[tuple[pymupdf.Rect, str]]) -> list[tuple[int, pymupdf.Rect, str, int]]:
    captions = []
    for i, (rect, text) in enumerate(blocks):
        m = CAPTION_RE.match(text)
        if m:
            captions.append((i, rect, text, int(m.group(1))))
    return captions


def figure_region(page: pymupdf.Page, caption_index: int, caption_rect: pymupdf.Rect,
                   blocks: list[tuple[pymupdf.Rect, str]]) -> pymupdf.Rect | None:
    left = max(0, caption_rect.x0 - COLUMN_MARGIN)
    right = min(page.rect.width, caption_rect.x1 + COLUMN_MARGIN)
    bottom = min(page.rect.height, caption_rect.y0 + BOTTOM_PADDING)

    top = max(0, bottom - MAX_FIGURE_HEIGHT)
    for i, (rect, _text) in enumerate(blocks):
        if i == caption_index:
            continue
        # Same column as the caption (horizontal overlap), and ends above it —
        # the closest such block's bottom edge is the figure's top boundary.
        overlap = min(rect.x1, right) - max(rect.x0, left)
        if overlap > 0 and rect.y1 <= bottom + 1:
            top = max(top, rect.y1)

    if bottom - top < MIN_FIGURE_HEIGHT:
        return None
    return pymupdf.Rect(left, top, right, bottom)


def extract_one(doc: pymupdf.Document, paper_id: str) -> list[dict]:
    out_dir = FIGURES_DIR / paper_id
    figures = []
    fig_index = 0
    dropped_no_region = 0
    dropped_errors = 0

    for page_num, page in enumerate(doc, start=1):
        blocks = page_blocks(page)
        captions = find_captions(blocks)

        for caption_index, caption_rect, caption_text, number in captions:
            region = figure_region(page, caption_index, caption_rect, blocks)
            if region is None:
                dropped_no_region += 1
                continue

            filename = f"fig-{fig_index + 1:02d}.png"
            try:
                pix = page.get_pixmap(clip=region, dpi=RENDER_DPI)
                out_dir.mkdir(parents=True, exist_ok=True)
                pix.save(out_dir / filename)
            except Exception:
                # Real academic PDFs turn up edge cases this script hasn't
                # seen — one bad region shouldn't take down the whole
                # paper's extraction, let alone the whole batch.
                dropped_errors += 1
                continue

            fig_index += 1
            figures.append({
                "number": number,
                "caption": caption_text,
                "page": page_num,
                "file": filename,
            })

    if not figures:
        print(f"    0 figures — no captions with a usable region above them")
    else:
        notes = []
        if dropped_no_region:
            notes.append(f"{dropped_no_region} caption(s) had no usable region above them")
        if dropped_errors:
            notes.append(f"{dropped_errors} dropped for a render error")
        note = f" ({', '.join(notes)})" if notes else ""
        print(f"    {len(figures)} figure(s) extracted{note}")

    return figures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="reprocess every paper, even if already up to date")
    args = parser.parse_args()

    entries = [e for e in read_papers() if e.get("paper_id") and e.get("session_key")]
    if not entries:
        print("No paper_id entries in frontend/schedule.csv — nothing to do.")
        return

    manifest = {}
    found = 0
    reprocessed = 0
    skipped_up_to_date = 0

    for entry in entries:
        paper_id = entry["paper_id"]
        session_key = entry["session_key"]
        pdf_path = PAPERS_DIR / f"{paper_id}.pdf"

        if not pdf_path.exists():
            continue
        found += 1

        figures_json = FIGURES_DIR / paper_id / "figures.json"
        up_to_date = figures_json.exists() and figures_json.stat().st_mtime >= pdf_path.stat().st_mtime

        if up_to_date and not args.force:
            skipped_up_to_date += 1
            manifest[session_key] = {"paper_id": paper_id, "figures": json.loads(figures_json.read_text())}
            continue

        print(f"{paper_id} ({entry.get('title', session_key)})")
        try:
            doc = pymupdf.open(pdf_path)
        except Exception as exc:
            print(f"    could not open PDF: {exc}")
            continue

        figures = extract_one(doc, paper_id)
        doc.close()
        reprocessed += 1

        if figures:
            (FIGURES_DIR / paper_id).mkdir(parents=True, exist_ok=True)
            figures_json.write_text(json.dumps(figures, indent=2))
            manifest[session_key] = {"paper_id": paper_id, "figures": figures}
        elif figures_json.exists():
            # PDF was replaced and no longer yields any figures — drop the stale output.
            figures_json.unlink()

    if found == 0:
        print(f"No PDFs found in {PAPERS_DIR} yet — run scripts/fetch_papers.py or drop them in by hand.")
        return

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIGURES_DIR / "index.json").write_text(json.dumps(manifest, indent=2))
    print(
        f"\n{reprocessed} processed, {skipped_up_to_date} already up to date, "
        f"{len(manifest)}/{found} paper(s) with a PDF present have figures. "
        f"Wrote manifest to {FIGURES_DIR / 'index.json'}"
    )


if __name__ == "__main__":
    main()
