from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "conf_cue.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                answer TEXT,
                answered_at TEXT,
                category TEXT
            )
            """
        )
        # Guarded ALTERs patch a pre-existing dev DB that predates these columns.
        # SQLite has no "ADD COLUMN IF NOT EXISTS" — catch the duplicate-column error instead.
        for column in ("answer TEXT", "answered_at TEXT", "category TEXT", "session_key TEXT", "citation TEXT"):
            try:
                await db.execute(f"ALTER TABLE questions ADD COLUMN {column}")
            except aiosqlite.OperationalError:
                pass

        # Append-only so counts can be windowed to "recent" rather than
        # accumulating all day — a running total says nothing about right now.
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emoji TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_reactions_created_at ON reactions (created_at)"
        )

        # Public chat, scoped per session so each talk starts a fresh thread
        # (also keeps any single fetch small).
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                session_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                image_url TEXT
            )
            """
        )
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN image_url TEXT")
        except aiosqlite.OperationalError:
            pass
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_key, id)"
        )
        await db.commit()


async def insert_question(text: str, category: str | None = None, session_key: str | None = None) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO questions (text, created_at, category, session_key) VALUES (?, ?, ?, ?)",
            (text, created_at, category, session_key),
        )
        await db.commit()
        return {"id": cursor.lastrowid, "text": text, "created_at": created_at, "answer": None, "category": category}


async def list_questions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, text, created_at, answer, category, citation FROM questions ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def list_unanswered_questions() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, text, session_key FROM questions WHERE answer IS NULL ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def save_answer(question_id: int, answer: str, citation: str | None = None) -> None:
    answered_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE questions SET answer = ?, answered_at = ?, citation = ? WHERE id = ?",
            (answer, answered_at, citation, question_id),
        )
        await db.commit()


async def add_reaction(emoji: str) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reactions (emoji, created_at) VALUES (?, ?)",
            (emoji, created_at),
        )
        await db.commit()


async def reaction_counts(window_seconds: int) -> dict:
    """Counts within the recent window (what the room feels *now*), plus all-time totals."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT emoji, COUNT(*) FROM reactions WHERE created_at >= ? GROUP BY emoji",
            (cutoff,),
        ) as cursor:
            recent = {row[0]: row[1] for row in await cursor.fetchall()}
        async with db.execute(
            "SELECT emoji, COUNT(*) FROM reactions GROUP BY emoji"
        ) as cursor:
            total = {row[0]: row[1] for row in await cursor.fetchall()}
    return {"recent": recent, "total": total}


async def insert_message(text: str, session_key: str, image_url: str | None = None) -> dict:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO messages (text, session_key, created_at, image_url) VALUES (?, ?, ?, ?)",
            (text, session_key, created_at, image_url),
        )
        await db.commit()
        return {
            "id": cursor.lastrowid,
            "text": text,
            "session_key": session_key,
            "created_at": created_at,
            "image_url": image_url,
        }


async def list_messages(session_key: str, limit: int = 200) -> list[dict]:
    """Newest `limit` messages for one session, returned oldest-first for display."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, text, session_key, created_at, image_url FROM messages
            WHERE session_key = ? ORDER BY id DESC LIMIT ?
            """,
            (session_key, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]


async def list_recent_messages(limit: int = 100) -> list[dict]:
    """Most recent messages across every session, newest-first — for moderation."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, text, session_key, created_at, image_url FROM messages
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def set_question_category(question_id: int, category: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE questions SET category = ? WHERE id = ?",
            (category, question_id),
        )
        await db.commit()


async def delete_question(question_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM questions WHERE id = ?", (question_id,))
        await db.commit()
        return cursor.rowcount > 0


async def delete_message(message_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await db.commit()
        return cursor.rowcount > 0
