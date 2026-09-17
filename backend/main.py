import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator, model_validator

from backend import db, llm, rag
from backend.ratelimit import check_rate_limit

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"

MAX_IMAGE_BYTES = 6 * 1024 * 1024
# Sniff the actual bytes — a client-supplied content-type proves nothing.
# Raster only: SVG is a script-execution vector, so it is deliberately excluded.
IMAGE_MAGIC = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG\r\n\x1a\n": ".png",
}


def _sniff_image(head: bytes) -> str | None:
    for magic, ext in IMAGE_MAGIC.items():
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None
SUMMARY_INTERVAL_SECONDS = 45
ANSWER_INTERVAL_SECONDS = 20

Category = Literal["Just Curious", "Check Paper", "To Moderator"]

REACTIONS = ["🔥", "❤️", "👏", "🤔", "😄", "🎉"]
Reaction = Literal["🔥", "❤️", "👏", "🤔", "😄", "🎉"]
REACTION_WINDOW_SECONDS = 300

# (requests, seconds) per client IP. Reactions stay generous — repeat taps
# are an intentional "applause meter", not abuse.
RATE_LIMITS: dict[str, tuple[int, float]] = {
    "questions": (1, 10),
    "category": (1, 3),
    "reactions": (20, 60),
    "messages": (1, 3),
    "messages_image": (1, 15),
}

MODERATOR_KEY = os.environ.get("MODERATOR_KEY")


def require_moderator(x_moderator_key: str | None = Header(default=None)) -> None:
    # Fails closed: an unset MODERATOR_KEY rejects every delete, never leaves
    # the endpoint silently unprotected.
    if not MODERATOR_KEY or not x_moderator_key or not secrets.compare_digest(x_moderator_key, MODERATOR_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing moderator key")


_latest_summary = {"summary": llm.NO_QUESTIONS_SUMMARY}


async def _refresh_summary_loop():
    while True:
        try:
            questions = await db.list_questions()
            texts = [q["text"] for q in questions]
            _latest_summary["summary"] = await asyncio.to_thread(llm.summarize_questions, texts)
        except Exception:
            pass  # keep serving the last known good summary if the LLM call fails
        await asyncio.sleep(SUMMARY_INTERVAL_SECONDS)


async def _answer_questions_loop():
    while True:
        try:
            unanswered = await db.list_unanswered_questions()
        except Exception:
            unanswered = []
        for question in unanswered:
            try:
                context, citation = await asyncio.to_thread(rag.retrieve, question.get("session_key"), question["text"])
                answer = await asyncio.to_thread(llm.answer_question, question["text"], context)
                await db.save_answer(question["id"], answer, citation)
            except Exception:
                pass  # this one stays unanswered and is retried next cycle
        await asyncio.sleep(ANSWER_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    await db.init_db()
    tasks = [
        asyncio.create_task(_refresh_summary_loop()),
        asyncio.create_task(_answer_questions_loop()),
    ]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request, call_next):
    # StaticFiles sends ETag/Last-Modified but no Cache-Control, so browsers
    # (mobile especially) fall back to heuristic caching and keep serving a
    # stale file after an edit. Forcing revalidation means every load checks
    # with the server — unchanged files still get a cheap 304, changed ones
    # show up immediately, with no manual cache-busting needed.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


class QuestionIn(BaseModel):
    text: str
    category: Category | None = None
    # Client-resolved "what talk is on now" key, same format and source as
    # MessageIn.session_key — but kept None (not defaulted to "lobby") when
    # unknown, since retrieval already treats "no key" and "key with no doi"
    # identically, and there's no reason to invent a value that isn't true.
    session_key: str | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped

    @field_validator("session_key")
    @classmethod
    def session_key_sane(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped[:64] if stripped else None


@app.get("/health")
def get_health():
    return {"status": "ok"}


@app.post("/questions")
async def post_question(question: QuestionIn, request: Request):
    check_rate_limit(request, "questions", *RATE_LIMITS["questions"])
    return await db.insert_question(question.text, question.category, question.session_key)


@app.get("/questions")
async def get_questions():
    return await db.list_questions()


@app.delete("/questions/{question_id}")
async def delete_question(question_id: int, _: None = Depends(require_moderator)):
    if not await db.delete_question(question_id):
        raise HTTPException(status_code=404, detail="question not found")
    return {"id": question_id, "deleted": True}


class CategoryIn(BaseModel):
    category: Category | None = None


@app.post("/questions/{question_id}/category")
async def set_question_category(question_id: int, body: CategoryIn, request: Request):
    check_rate_limit(request, "category", *RATE_LIMITS["category"])
    await db.set_question_category(question_id, body.category)
    return {"id": question_id, "category": body.category}


class ReactionIn(BaseModel):
    emoji: Reaction


async def _reaction_payload() -> dict:
    """Always includes every emoji so the client renders a stable row."""
    counts = await db.reaction_counts(REACTION_WINDOW_SECONDS)
    return {
        "emojis": REACTIONS,
        "window_seconds": REACTION_WINDOW_SECONDS,
        "recent": {e: counts["recent"].get(e, 0) for e in REACTIONS},
        "total": {e: counts["total"].get(e, 0) for e in REACTIONS},
    }


@app.post("/reactions")
async def post_reaction(body: ReactionIn, request: Request):
    check_rate_limit(request, "reactions", *RATE_LIMITS["reactions"])
    await db.add_reaction(body.emoji)
    return await _reaction_payload()


@app.get("/reactions")
async def get_reactions():
    return await _reaction_payload()


class MessageIn(BaseModel):
    text: str = ""
    # Client-resolved session key ("lobby" outside session hours). It owns
    # schedule.csv parsing, so it scopes the thread; trivially spoofable, which
    # is acceptable for an anonymous public chat at this scale.
    session_key: str = "lobby"
    image_url: str | None = None

    @field_validator("text")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()[:500]

    @field_validator("session_key")
    @classmethod
    def session_key_sane(cls, value: str) -> str:
        stripped = value.strip()
        return stripped[:64] if stripped else "lobby"

    @field_validator("image_url")
    @classmethod
    def image_url_must_be_ours(cls, value: str | None) -> str | None:
        # Only accept paths this server minted, so a message can't embed a
        # remote (or javascript:) URL that every attendee's browser would load.
        if value is None:
            return None
        if not value.startswith("/uploads/") or "/" in value[len("/uploads/"):]:
            raise ValueError("image_url must be an upload path from this server")
        return value

    @model_validator(mode="after")
    def needs_text_or_image(self):
        if not self.text and not self.image_url:
            raise ValueError("message must have text or an image")
        return self


@app.post("/messages/image")
async def post_message_image(file: UploadFile, request: Request):
    check_rate_limit(request, "messages_image", *RATE_LIMITS["messages_image"])
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="image too large")

    ext = _sniff_image(data[:16])
    if ext is None:
        raise HTTPException(status_code=415, detail="only JPEG, PNG or WebP images are accepted")

    # Server-generated name: never trust a client-supplied filename.
    name = f"{secrets.token_hex(16)}{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    return {"image_url": f"/uploads/{name}", "bytes": len(data)}


@app.post("/messages")
async def post_message(body: MessageIn, request: Request):
    check_rate_limit(request, "messages", *RATE_LIMITS["messages"])
    return await db.insert_message(body.text, body.session_key, body.image_url)


@app.get("/messages")
async def get_messages(session: str = "lobby"):
    return await db.list_messages(session)


@app.get("/messages/recent")
async def get_recent_messages(limit: int = 100):
    # Same "viewing is open, deleting is gated" split as the question feed —
    # for the moderator dashboard's chat panel, across every session at once.
    return await db.list_recent_messages(min(limit, 200))


@app.delete("/messages/{message_id}")
async def delete_message(message_id: int, _: None = Depends(require_moderator)):
    if not await db.delete_message(message_id):
        raise HTTPException(status_code=404, detail="message not found")
    return {"id": message_id, "deleted": True}


@app.get("/summary")
def get_summary():
    return {"summary": _latest_summary["summary"]}


UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Mounted before the catch-all frontend mount so /uploads/* resolves here.
# Kept out of frontend/ on purpose: this is user-generated content, not source.
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
