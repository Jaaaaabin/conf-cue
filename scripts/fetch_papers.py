#!/usr/bin/env python3
"""Best-effort paper PDF fetcher — a convenience, not a reliable pipeline step.

DOI resolution (doi.org/<doi>) is designed for bibliographic metadata, not
full text — it almost always redirects to a publisher landing page, not a
PDF. This works for some DOIs (repository-hosted ones especially) and
silently no-ops for the rest. Anything it can't get, drop in by hand as
data/papers/<paper_id>.pdf — that manual path is the reliable one, this
script just saves you the trouble for the DOIs where it happens to work.

Only session rows in frontend/schedule.csv that have both a paper_id and a
doi can be attempted here at all — one with no doi yet needs a manual
drop-in regardless.

Verifies success by sniffing the response body for the %PDF- magic bytes,
never by trusting Content-Type (same distrust _sniff_image already applies
to client-supplied content-types in backend/main.py).

Usage:
    uv run python scripts/fetch_papers.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.papers import PAPERS_DIR, read_papers

TIMEOUT_SECONDS = 20


def main() -> None:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)

    entries = [e for e in read_papers() if e.get("paper_id")]
    if not entries:
        print("No paper_id entries in frontend/schedule.csv — nothing to fetch.")
        return

    fetched, skipped, no_doi, failed = [], [], [], []

    with httpx.Client(follow_redirects=True, timeout=TIMEOUT_SECONDS) as client:
        for entry in entries:
            paper_id = entry["paper_id"]
            doi = (entry.get("doi") or "").strip()
            dest = PAPERS_DIR / f"{paper_id}.pdf"

            if dest.exists():
                skipped.append(paper_id)
                continue
            if not doi:
                no_doi.append(paper_id)
                continue

            try:
                resp = client.get(f"https://doi.org/{doi}", headers={"Accept": "application/pdf"})
                if resp.status_code == 200 and resp.content[:5] == b"%PDF-":
                    dest.write_bytes(resp.content)
                    fetched.append(paper_id)
                else:
                    failed.append((paper_id, doi))
            except httpx.HTTPError:
                failed.append((paper_id, doi))

    print(f"Fetched: {len(fetched)}")
    for paper_id in fetched:
        print(f"  {paper_id}")
    print(f"Already had: {len(skipped)}")
    print(f"No doi yet (needs a manual drop-in): {len(no_doi)}")
    for paper_id in no_doi:
        print(f"  {paper_id}  ->  data/papers/{paper_id}.pdf")
    print(f"doi didn't resolve to a PDF (needs a manual drop-in): {len(failed)}")
    for paper_id, doi in failed:
        print(f"  {paper_id} ({doi})  ->  data/papers/{paper_id}.pdf")


if __name__ == "__main__":
    main()
