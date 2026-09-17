#!/usr/bin/env python3
"""Build a retrieval index (chunks + embeddings) for each paper PDF present.

Same skip-gracefully shape as extract_figures.py: loops over every session
row in frontend/schedule.csv that has a paper_id, indexes whatever PDF is
present at data/papers/<paper_id>.pdf, and leaves anything missing for a
later run.
Re-running after dropping in more PDFs just picks up what's newly there —
nothing here assumes a fixed paper count. Matching is by paper_id, not
DOI — a paper can be indexed before its DOI is even assigned.

Chunking is fixed-window over words (not a real tokenizer — see the
word/token approximation below), not section-aware. True section detection
(abstract/method/results) is a formatting heuristic that would vary
unpredictably across publishers for papers not seen yet; a wrong guess
would produce worse chunks than simple windowing, so citations use page
numbers only, not section labels.

No vector database — at the scale this produces (a few hundred to ~1000
chunks total even at the real ~50-paper lineup), a NumPy dot product over
an in-memory array is faster than a network hop to any vector DB would be.

Incremental: a paper whose index is already newer than its PDF is skipped,
not reprocessed — dropping in a handful more papers the night before the
event and re-running only costs time (and an embedding pass) for the new
ones. Pass --force to reprocess everything regardless (e.g. after changing
the chunking logic itself).

Usage:
    uv run python scripts/build_paper_index.py [--force]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from fastembed import TextEmbedding

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.papers import PAPER_INDEX_DIR, PAPERS_DIR, read_papers

# ~600 tokens / 15% overlap per ROADMAP.md, converted to words via the
# standard ~0.75 words-per-token approximation for English prose — no
# tokenizer dependency needed at this scale.
CHUNK_WORDS = 450
OVERLAP_WORDS = 68
EMBED_MODEL = "BAAI/bge-small-en-v1.5"


def extract_pages(doc: pymupdf.Document) -> list[str]:
    return [page.get_text() for page in doc]


def chunk_pages(pages: list[str]) -> list[dict]:
    """Word-window chunks with overlap, each tagged with the page range it spans."""
    words_with_page = []
    for page_num, text in enumerate(pages, start=1):
        for word in text.split():
            words_with_page.append((word, page_num))

    chunks = []
    step = CHUNK_WORDS - OVERLAP_WORDS
    i = 0
    while i < len(words_with_page):
        window = words_with_page[i:i + CHUNK_WORDS]
        if not window:
            break
        text = " ".join(w for w, _ in window)
        pages_in_chunk = [p for _, p in window]
        chunks.append({
            "text": text,
            "page_start": pages_in_chunk[0],
            "page_end": pages_in_chunk[-1],
        })
        i += step
    return chunks


def _up_to_date(paper_id: str, pdf_path: Path) -> bool:
    npz_path = PAPER_INDEX_DIR / f"{paper_id}.npz"
    json_path = PAPER_INDEX_DIR / f"{paper_id}.json"
    if not npz_path.exists() or not json_path.exists():
        return False
    pdf_mtime = pdf_path.stat().st_mtime
    return npz_path.stat().st_mtime >= pdf_mtime and json_path.stat().st_mtime >= pdf_mtime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="reprocess every paper, even if already up to date")
    args = parser.parse_args()

    entries = [e for e in read_papers() if e.get("paper_id")]
    if not entries:
        print("No paper_id entries in frontend/schedule.csv — nothing to do.")
        return

    found = []
    for entry in entries:
        paper_id = entry["paper_id"]
        pdf_path = PAPERS_DIR / f"{paper_id}.pdf"
        if pdf_path.exists():
            found.append((paper_id, entry.get("title", paper_id), pdf_path))

    if not found:
        print(f"No PDFs found in {PAPERS_DIR} yet — run scripts/fetch_papers.py or drop them in by hand.")
        return

    to_process = found if args.force else [
        (paper_id, title, pdf_path) for paper_id, title, pdf_path in found if not _up_to_date(paper_id, pdf_path)
    ]
    skipped_up_to_date = len(found) - len(to_process)

    if not to_process:
        print(f"All {len(found)} paper(s) already indexed and up to date. Pass --force to rebuild anyway.")
        return

    # Loaded lazily, only once we know there's actually something to embed —
    # a no-op run shouldn't pay the ~3s model load cost.
    print(f"Loading embedding model ({EMBED_MODEL})...")
    embedder = TextEmbedding(model_name=EMBED_MODEL)

    PAPER_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    indexed = 0

    for paper_id, title, pdf_path in to_process:
        print(f"{paper_id} ({title})")
        try:
            doc = pymupdf.open(pdf_path)
            pages = extract_pages(doc)
            doc.close()
        except Exception as exc:
            print(f"    could not open PDF: {exc}")
            continue

        chunks = chunk_pages(pages)
        if not chunks:
            print("    no extractable text — skipped")
            continue

        vectors = np.array(list(embedder.embed([c["text"] for c in chunks])), dtype=np.float32)
        # Explicit L2 normalization — cheap insurance so a plain dot product
        # at query time is guaranteed to equal cosine similarity, regardless
        # of whether the embedder's own output is already normalized.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1  # guard against a degenerate all-zero embedding
        vectors = vectors / norms

        np.savez(PAPER_INDEX_DIR / f"{paper_id}.npz", vectors=vectors)
        metadata = [{"text": c["text"], "page_start": c["page_start"], "page_end": c["page_end"]} for c in chunks]
        (PAPER_INDEX_DIR / f"{paper_id}.json").write_text(json.dumps(metadata))

        print(f"    {len(chunks)} chunk(s) indexed")
        indexed += 1

    print(f"\nIndexed {indexed}/{len(to_process)} paper(s). {skipped_up_to_date} already up to date, skipped.")


if __name__ == "__main__":
    main()
