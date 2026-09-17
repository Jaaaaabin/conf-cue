"""Converts frontend/schedule.csv (the hand-maintained session directory) into
frontend/sessions.json — the one thing the frontend actually fetches.

Why this exists: frontend/nav.js used to parse schedule.csv in the browser
with a naive `line.split(",")` — correct only as long as no field (a paper
title, most likely) ever contains a literal comma. Python's csv module
handles quoting correctly, so doing that parsing once, offline, and shipping
plain JSON removes the whole class of bug instead of hardening the JS parser.

CSV headers are exactly the JSON keys on purpose — this script is close to a
straight csv.DictReader -> json.dump, not a real transformation. Rerun it
after every schedule.csv edit (see README.md); nothing needs restarting, the
frontend just fetches whatever's on disk.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE_CSV = ROOT / "frontend" / "schedule.csv"
SESSIONS_JSON = ROOT / "frontend" / "sessions.json"

# Columns carried through as-is; blank -> null so the frontend can use plain
# truthiness checks instead of comparing against a placeholder string.
OPTIONAL_COLUMNS = ("presenter", "paper_id", "doi")


def build() -> list[dict]:
    with SCHEDULE_CSV.open(newline="") as f:
        rows = list(csv.DictReader(f))

    sessions = []
    for row in rows:
        session = {key: value.strip() for key, value in row.items()}
        for key in OPTIONAL_COLUMNS:
            session[key] = session.get(key) or None
        sessions.append(session)
    return sessions


def main() -> None:
    sessions = build()
    SESSIONS_JSON.write_text(json.dumps(sessions, indent=2) + "\n")
    print(f"Wrote {len(sessions)} sessions to {SESSIONS_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
