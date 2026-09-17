import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPERS_DIR = ROOT / "data" / "papers"            # raw PDFs, gitignored, hand-populated
PAPER_INDEX_DIR = ROOT / "data" / "paper_index"  # .npz + .json, gitignored
FIGURES_DIR = ROOT / "frontend" / "papers"       # served via StaticFiles, gitignored
SCHEDULE_CSV = ROOT / "frontend" / "schedule.csv"


def read_schedule() -> list[dict]:
    """Every row of schedule.csv as a dict. Never raises — a missing/malformed
    file just means every downstream loop iterates zero times, not a crash."""
    try:
        with SCHEDULE_CSV.open(newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            return []
        header, body = rows[0], rows[1:]
        return [dict(zip(header, row)) for row in body]
    except Exception:
        return []


def session_key(row: dict) -> str:
    # A stable id assigned per schedule row (schedule.csv's session_key
    # column) — not derived from date/time, so a schedule reshuffle (a
    # talk's slot moving) doesn't silently change what already-submitted
    # questions or a session's paper_id point at. Session order and a
    # paper's real submission id are independent numbering spaces, only
    # linked via this row's own paper_id column.
    return row.get("session_key", "")


def read_papers() -> list[dict]:
    """Every schedule row with a paper_id attached, reshaped to the
    {paper_id, session_key, title, doi} shape the offline paper-processing
    scripts (extract_figures.py, build_paper_index.py) already expect.
    paper_id/doi used to live in a separate hand-maintained papers.json,
    keyed by session_key — now they're columns directly on the session row,
    since both are just "fill in whenever known" facts about that slot, no
    different from presenter. title/doi here are informational only (doi is
    independently re-read via doi_for_session_key when it matters, e.g. for
    a citation link — never trusted from this shape alone). Never raises,
    same reasoning as read_schedule()."""
    return [
        {
            "paper_id": row["paper_id"].strip(),
            "session_key": session_key(row),
            "title": row.get("session_fullname", ""),
            "doi": row.get("doi", "").strip() or None,
        }
        for row in read_schedule()
        if row.get("paper_id", "").strip()
    ]


def doi_for_session_key(key: str) -> str | None:
    """The authoritative DOI for a session, straight from schedule.csv — used
    for citation links, independent of whether that paper has been indexed."""
    for row in read_schedule():
        if session_key(row) == key and row.get("doi"):
            return row["doi"].strip()
    return None
