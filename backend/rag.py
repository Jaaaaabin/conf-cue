import json

import numpy as np
from fastembed import TextEmbedding

from backend.papers import PAPER_INDEX_DIR, doi_for_session_key, read_papers

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
TOP_K = 4

_embedder = None  # lazily loaded on first real use, not at import time or per-question


def _get_embedder() -> TextEmbedding:
    global _embedder
    if _embedder is None:
        _embedder = TextEmbedding(model_name=EMBED_MODEL)
    return _embedder


def paper_id_for_session_key(key: str | None) -> str | None:
    if not key:
        return None
    for entry in read_papers():
        if entry.get("session_key") == key and entry.get("paper_id"):
            return entry["paper_id"]
    return None


def load_index(paper_id: str) -> tuple[np.ndarray, list[dict]] | None:
    npz_path = PAPER_INDEX_DIR / f"{paper_id}.npz"
    json_path = PAPER_INDEX_DIR / f"{paper_id}.json"
    if not npz_path.exists() or not json_path.exists():
        return None
    try:
        vectors = np.load(npz_path)["vectors"]
        metadata = json.loads(json_path.read_text())
        return vectors, metadata
    except Exception:
        return None


def search(index: tuple[np.ndarray, list[dict]], question: str, k: int = TOP_K) -> list[dict]:
    vectors, metadata = index
    query = np.array(list(_get_embedder().embed([question]))[0], dtype=np.float32)
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm
    scores = vectors @ query
    top_indices = np.argsort(scores)[::-1][:k]
    return [metadata[i] for i in top_indices]


def format_context(chunks: list[dict]) -> str:
    return "\n\n".join(c["text"] for c in chunks)


def format_citation(chunks: list[dict], doi: str | None) -> str:
    # Anchor to the single top-ranked chunk, not the span across all k
    # retrieved — the context sent to the model is enriched by all k, but
    # the citation should point at where the answer most likely came from,
    # not a broad range that includes lower-relevance filler chunks.
    top = chunks[0]
    if top["page_start"] == top["page_end"]:
        page_label = f"p. {top['page_start']}"
    else:
        page_label = f"pp. {top['page_start']}–{top['page_end']}"
    # A paper can be indexed (paper_id known) before its DOI is assigned —
    # citation still shows the page, just without a doi.org link.
    return f"{page_label} — doi.org/{doi}" if doi else page_label


def retrieve(key: str | None, question_text: str) -> tuple[str, str | None]:
    """Every failure mode returns ("", None) — no session_key, no paper_id
    matched for that session, no index built yet, or a retrieval error all
    fall through to exactly today's context-free answer. This is deliberate:
    partial progress on indexing the real paper lineup should never break a
    question, just leave it unenriched."""
    if not key:
        return "", None
    paper_id = paper_id_for_session_key(key)
    if not paper_id:
        return "", None
    index = load_index(paper_id)
    if index is None:
        return "", None
    try:
        hits = search(index, question_text)
    except Exception:
        return "", None
    if not hits:
        return "", None
    doi = doi_for_session_key(key)  # informational only — citation still works without one
    return format_context(hits), format_citation(hits, doi)
