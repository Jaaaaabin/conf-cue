import time
from collections import defaultdict

from fastapi import HTTPException, Request

# In-process only — resets on restart, which is fine at this scale (a single
# uvicorn process, tens to a few hundred attendees for one event).
_hits: dict[tuple[str, str], list[float]] = defaultdict(list)


def client_ip(request: Request) -> str:
    # Trusting XFF unconditionally is normally unsafe, but is safe here only
    # because uvicorn binds 127.0.0.1 — nothing but the Funnel proxy (or a
    # process already on this host) can reach it to set this header.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request, bucket: str, limit: int, window_seconds: float) -> None:
    key = (bucket, client_ip(request))
    now = time.monotonic()
    hits = _hits[key]
    cutoff = now - window_seconds
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= limit:
        raise HTTPException(
            status_code=429,
            detail="Too many requests — slow down a moment.",
            headers={"Retry-After": str(int(window_seconds))},
        )
    hits.append(now)
