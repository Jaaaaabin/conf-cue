#!/usr/bin/env python3
"""Host-only reset: wipes all shared ConfCue data.

Deletes every question (with its AI answer/category), every reaction, every
chat message, and every uploaded chat image. Run this by hand on the host
when you want a clean slate (testing, or a major-issue reset mid-event) —
there is no HTTP endpoint for this on purpose, since the app is reachable by
anyone with the public Funnel URL.

Row IDs are NOT reset (autoincrement keeps climbing past whatever was there
before). This is deliberate: an emergency mid-event reset can happen while
the server still has live traffic, and reusing IDs risks an in-flight AI
answer landing on the wrong (new) question, or an attendee's local "my
questions"/chat cache merging with an unrelated new item that reused their
old ID.

Usage:
    uv run python scripts/reset_data.py [--yes]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.db import DB_PATH

UPLOAD_DIR = DB_PATH.parent / "uploads"
TABLES = ("questions", "reactions", "messages")


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"No database at {DB_PATH} — nothing to reset.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        before = table_counts(conn)
        upload_files = [p for p in UPLOAD_DIR.glob("*") if p.is_file()] if UPLOAD_DIR.exists() else []

        if sum(before.values()) == 0 and not upload_files:
            print("Already empty — nothing to do.")
            return

        print("This will permanently delete:")
        print(f"  {before['questions']} question(s) — including AI answers and categories")
        print(f"  {before['reactions']} reaction(s)")
        print(f"  {before['messages']} chat message(s)")
        print(f"  {len(upload_files)} uploaded chat image(s)")

        if not args.yes:
            reply = input("Type 'yes' to continue: ").strip().lower()
            if reply != "yes":
                print("Aborted — nothing was deleted.")
                return

        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

        for path in upload_files:
            path.unlink()

        print("Done. Row IDs keep climbing (not reset) — see the module docstring for why.")
        print(
            "A running server picks this up on its own — reactions and chat "
            "immediately, the moderator summary panel within 45s (its normal "
            "refresh cycle). No restart needed."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
