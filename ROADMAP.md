# ROADMAP.md — ConfCue status, gaps & backlog

What is built, what is missing, and what could come next. Companion to `README.md` (how to run and operate it) and `CONTEXT.md` (why it is built the way it is).

**Organized bottom-up.** Layer 1 is the data everything else reads; each layer above depends only on the ones below it. A gap low in the stack is worth more attention than a gap high in it, because more sits on top of it. Within each entry: what it is, then **Gap —** bullets for what is still open.

Status marks: ✅ built · ◐ built with a known hole · ○ not built

---

## Status at a glance

| Layer | State | What's still open |
|---|---|---|
| 1 · Data foundation | ◐ | Staleness and validation on the session index; figure captions unindexed |
| 2 · Platform & delivery | ◐ | Two-device rate-limit check; nothing committed yet |
| 3 · Intelligence | ◐ | Summary prompt grows without bound |
| 4 · Functional modules | ◐ | QR code; placeholder contact addresses |

**Git reality check:** only two commits exist (`Initial Commit`, `Track empty dirs`). Everything from Block 2 onward — `backend/`, all of `frontend/` — is still staged or untracked. The marks above track working-tree completeness, not what has been committed. Repo: `git@github.com:Jaaaaabin/conf-cue.git`

### Blocking before the event

Detail lives in the layer each belongs to; these are the hard gates.

- [ ] **Two-device rate-limit verification** through the real Funnel URL (2.4) — the highest-risk item on this page
- [ ] **QR code** pointing at the Funnel URL (4.6) — the last original Block 6 item
- [ ] **Real contact addresses** replacing the placeholders (4.5)
- [ ] **Funnel pre-flight** well ahead of doors opening (2.3)
- [ ] **Commit everything** (2.5)

---

## Layer 1 · Data foundation

Everything above reads from here. All of it is hand-maintained or offline-generated — none of it is written by the running app except the database.

### 1.1 Session directory ✅
`frontend/schedule.csv` (hand-maintained, tracked) → `scripts/build_sessions_index.py` → `frontend/sessions.json` (generated, gitignored, fetched by every page). Carries the stable IDs the whole system keys on: `session_key` for scoping, `paper_id` for paper files. Replaced an earlier `schedule.csv` + `papers.json` split.

- **Gap —** regeneration after a CSV edit is manual and unenforced; forget it and the site serves the old JSON with no error. Computing it per request would close this at negligible cost given the row count.
- **Gap —** no input validation: a malformed row (wrong column count, duplicate `session_key`, unparseable date/time) fails silently. Only bites once real data replaces the 11-row mock schedule — worth adding before that, not after.
- **Gap —** `session_shortname` is hand-written per row. For a ~50-paper lineup that's real work; an LLM-suggested shortname is plausible (Ollama is already wired up) but wasn't built speculatively.
- **Gap —** no convention for multiple presenters/co-authors; every row assumes one name.

### 1.2 Persistent store ✅
SQLite, created by the FastAPI lifespan on first start — no migration step, no init script. Holds questions (with answer, category, `session_key`, citation), reactions, and chat messages. Schema additions land via guarded `ALTER TABLE`, so an existing dev database upgrades in place.

### 1.3 Paper corpus ◐
Per paper: `data/papers/<paper_id>.pdf` → `data/paper_index/<paper_id>.{npz,json}` (embeddings) and `frontend/papers/<paper_id>/` (figures). Both pipelines are offline, incremental, and skip papers whose output is newer than the PDF. Verified against all 5 real conference papers.

- **Gap —** figure captions are not in the RAG index; the two pipelines are disconnected, so *"what's the first figure about"* won't be well served even with correct session routing. Each caption would need indexing as its own small chunk.
- **Note —** PDF sourcing is manual-primary by necessity: 0 of 5 real DOIs auto-fetched, because publishers redirect DOIs to landing pages. `scripts/fetch_papers.py` is a convenience, not a dependency.

### 1.4 Static assets ✅
Logos in `frontend/icon/`, all cropped to content bounds and suffixed `_final`. Raw and unused sources live in `icon_archive/` at the repo root — deliberately outside `frontend/`, which is mounted wholesale by `StaticFiles` and therefore public regardless of `.gitignore`.

- **Gap —** partner logo filenames encode grid position rather than identity (`par_11`…`par_33` = row·col), so reordering the 3×3 grid requires renaming files to keep the encoding meaningful.
- **Gap —** DigiB's logo color (`#001f3d`) is baked into the PNG rather than applied via CSS, so a palette change won't reach it. The white-on-transparent original is kept at `icon_archive/org/save_org_5.png` for a re-tint.

---

## Layer 2 · Platform & delivery

Getting the data foundation served, supervised, reachable, and protected.

### 2.1 App server & static serving ✅
FastAPI + uvicorn, with `frontend/` mounted wholesale via `StaticFiles` and a `no-cache` middleware so frontend edits need no restart. Live updates are polling (3–5s), which is simpler than websockets and sufficient at this scale.

### 2.2 Supervision ✅
systemd unit `conf-cue.service`, system-scope, `enabled` and `Restart=always`. Survives crashes, reboots, and the developer's SSH session ending. Docker was considered and never needed.

### 2.3 Public exposure ◐
Tailscale Funnel at `https://wu.tailc772b5.ts.net` → `127.0.0.1:8000`, verified end-to-end from an off-network phone on cellular. Attendees need no account, app, or VPN.

- **Gap —** a pre-flight check is required before relying on it again: enable well ahead of doors, then confirm from off-network resolvers and a real phone. First-time DNS propagation lag is real (~15–20 min) and has already produced two devices on one network disagreeing.

### 2.4 Abuse control ◐
Per-IP sliding-window rate limiter (`backend/ratelimit.py`), no new dependency, covering all five POST endpoints. A 429 needed no frontend changes — both existing client error paths already degrade gracefully. Client IP comes from `X-Forwarded-For`, which is only safe because uvicorn binds loopback.

- **Gap — the single highest-risk open item.** Not yet verified from two real, differently-networked phones through the actual Funnel URL. If `X-Forwarded-For` isn't coming through, every attendee collapses into one `127.0.0.1` bucket and one person's question blocks everyone else's. A hard gate, not optional.

### 2.5 Repo reproducibility ◐
A fresh clone runs: real `README.md`, populated `.env.example`, `.gitignore` grouped by why-excluded with the rebuild script named per generated path, no dead scaffolding, `[tool.uv] package = false`. Verified by copying the would-be-committed file set into a clean directory and running it there.

- **Gap —** none of it is committed yet. See the git reality check above.

---

## Layer 3 · Intelligence

Local LLM work on top of Layers 1–2. Everything here runs on the host; there are no external LLM API calls.

### 3.1 Summarization ◐
`mistral-small3.2:24b` via Ollama. A background loop reclusters and summarizes every 45s and caches the result, so `/summary` serves the cache rather than hammering Ollama at the dashboard's 4s poll. An LLM failure keeps serving the last good summary instead of erroring.

- **Gap —** the prompt grows without bound: it feeds every question ever recorded to the model, so by day 3 it would be summarising day 1. Wants scoping to the current session or last N.

### 3.2 Per-question answers ✅
A separate 20s loop drafts an answer per question, labeled **ConfCue ✦** so it reads as a bot. Answers persist to the database, so they survive restarts and appear identically on every device. The prompt instructs the model to decline event specifics it cannot know rather than invent them.

### 3.3 Retrieval (RAG) ✅
`fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim, CPU, no server) over fixed-window chunks, filtered to the current session before searching, with citations anchored to the top-ranked chunk's page. Every failure mode — no session, no paper, no PDF, no index, retrieval error — falls through to the plain-answer path.

Two measured results worth keeping, because they justify *future* decisions:

**Why there is no vector database.** Sized for the real ~50-paper corpus (~10pp each, 600-token chunks, 15% overlap):

| | |
|---|---|
| Chunks | 14/paper → **700 total** |
| Index on disk | **3.7 MB** (2.2 MB vectors + 1.5 MB text) |
| Brute-force top-4, whole corpus | **0.022 ms** measured |
| Brute-force top-4, session-scoped | **0.004 ms** measured |

At 700 chunks a NumPy dot product isn't a compromise, it's the correct answer — roughly 2,000× faster than a single network hop. Revisit only past ~100k chunks, i.e. ~7,000 papers.

**Why embeddings don't go through Ollama.** Ollama on this host rejects embeddings at the server level (`/api/embeddings` and `/api/embed` both return *"This server does not support embeddings"*), and index-building is an offline batch job with no reason to depend on a running server:

| | |
|---|---|
| Model load | 3.1 s |
| Embedding 702 chunks (the full 50-paper corpus) | **13.7 s**, CPU only |
| Resulting index | 1.1 MB |

The whole corpus indexes in about fifteen seconds with no server and no GPU, so embedding never competes with the summary and answer loops.

### 3.4 Figure extraction ✅
Renders the page region around each `Figure N` caption rather than pulling embedded images — which fixed a tiled-figure false positive and a colorspace crash at once, and picks up vector-drawn figures for free. A caption match is required, which is what filters out header/footer logos.

- **Note —** vision models are blocked on this host: the only one pulled, `llama3.2-vision:11b`, fails with `unknown model architecture: 'mllama'` (a private Ollama fork patch dropped at the engine rewrite, never upstreamed). This blocks only optional garnish — captioning uncaptioned figures, or "find the figure showing X" — not the feature itself, which uses no model at all.

> ⚖️ **Check redistribution rights before figures go live publicly.** Re-serving extracted figures from a public Funnel URL republishes copyrighted material. Fine for open-access papers, probably fine for a closed room, but it is a publishing decision, not a technical one.

---

## Layer 4 · Functional modules

What people actually touch. Everything here rides the layers below.

### Attendee

**4.1 Ask + classification ✅** — a single Submit button splits into Just Curious / Check Paper / To Moderator; tapping one is what sends. Native `required` validation gates stage one, so an empty question never reaches the split. The category can be changed afterwards from My Questions.

**4.2 My Questions ✅** — its own page, polling every 5s and merging fresh server data so a ConfCue ✦ answer appears without a manual refresh.

**4.3 Reaction stamps ✅** — six one-tap stamps under the "Now:" banner on a rolling 5-minute window, not a running total. Taps are optimistic and repeat taps are intended; it's an applause meter, not a poll. No per-person rate limiting by design.

**4.4 Public session chat ✅** — scoped per session, public and anonymous, full-screen on phones with `100dvh` so the composer survives the keyboard. Images are resized in-browser before upload, which also strips EXIF including GPS; SVG is rejected and uploads land outside `frontend/`.

**4.5 Info pages ✅** — Schedule, Sponsors & Partners, Venues, Contact, plus the fold-out nav on all six attendee pages. Mobile layout runs off `clamp()`-ramped spacing tokens, verified across 7 pages × 11 viewports.
- **Gap —** contact addresses are placeholders (`hello@`/`support@`/`program@confcue-demo.org`). The page says so itself, but swapping in real ones isn't tracked anywhere else.
- **Gap —** the venue floor plan and confirmed dinner time are still "coming soon".

**4.6 Entry point ○** — **no QR code yet**; attendees currently need the URL typed or pasted. The last original Block 6 item.

### Moderator

**4.7 Dashboard feeds ◐** — "On the floor" summary panel, questions grouped by category and chat grouped by session, both foldable with fold state in `localStorage`. Chat groups resolve to the real `session_shortname`.
- **Gap —** the Questions panel shows no session context: each question's `session_key` is captured and used for RAG scoping, but never surfaced on the card or offered as a grouping, unlike the Chat panel.

**4.8 Moderation ✅** — `DELETE /questions/{id}` and `/messages/{id}` behind a shared secret, compared with `secrets.compare_digest` and **failing closed** if unset. Viewing stays as open as before; only deleting is gated. `GET /messages/recent` backs a cross-session chat moderation panel usable from a phone.

---

## Cross-cutting

- **`/questions` returns everything to every client on each poll** — measured ~2 MB/s at 300 questions × 100 attendees. Wants a `?since=<id>` incremental fetch. This is the ceiling every new feature pushes against.
- **Every new counter adds polling traffic.** Fold new signals into an existing poll response rather than adding an endpoint per feature, and keep payloads small enough to stay noise next to the question list.

---

## Candidate features (not scheduled)

Grouped by the layer each would extend. **Free** = no new backend. **Cheap** = one table + one endpoint on existing polling. **Medium** = real build, new UI and/or extra LLM traffic.

**Extending Layer 3 (intelligence)**
- **Jargon translator** — *nearly free*. Tap a term, get it explained *in the context of this talk*: `llm.answer_question()` with a different prompt and the session topic as `context`. Genuinely valuable at a conference where half the audience is technical and half regulatory.
- **Mood of the room** — *free*. A second, wittier prompt over the question set the summarizer already collects; one dry one-liner on the dashboard instead of the neutral summary. Prompt variant only.
- **Buzzword bingo** — *medium*. Ollama generates nine terms per session (cached), attendee gets a 3×3 grid, first bingo pops on the dashboard. Highest fun-per-unit-of-work here, but it competes with Ollama during talks; the QR code is the remaining blocker before it's worth scheduling.

**Extending Layer 4 (attendee modules)**
- **Pace dial** — *cheap*. "Lost me" / "got it, move on", shown as a needle. The one item here that reliably changes speaker behaviour mid-talk. Must be a **rolling ~60s window**, not a cumulative counter — same reasoning as reaction stamps.
- **Room temperature** — *cheap*. "Too cold" / "too hot." Trivially silly, and reliably the most-complained-about thing at any venue. Same shape as the pace dial; could share one generic `signals` table.
- **Upvoting questions** — *medium*. Let attendees "+1" an existing question instead of piling up duplicates, surfacing what the room actually wants answered. Needs backend work (upvote counts per question) — larger than anything else here.

**Extending Layer 4 (moderator)**
- **Time remaining** — *free*. "12 min left in this session," computed from the schedule the same way the "Now:" banner already is. Keeps the projector screen feeling live even when nobody is interacting.

**Removed:** ~~punch card~~ — built (pure `localStorage`, no backend), then dropped by product decision. Not a technical failure.

---

## Appendix — build order

The layers above are the current shape; this is the order it was actually built in.

| Block | Delivered | Lands in |
|---|---|---|
| 1 · Structure & environment | `uv` project, folder layout, `.gitignore`, GitHub repo | 2.5 |
| 2 · Communication test | Stub `/health`, `/questions`, `/summary`, curl-verified | 2.1 |
| 3 · Simple UI | Bare form + polling dashboard; `StaticFiles` chosen | 2.1, 4.1 |
| 4 · Real storage | SQLite via lifespan startup | 1.2 |
| 5 · Remote network test | Funnel verified off-LAN; systemd supervision | 2.2, 2.3 |
| 6 · Real LLM + polish | Ollama, styling, and everything below | 3.x, 4.x |

Block 6 grew well past its original checklist. Added live, none of it originally planned: rate limiting (2.4), moderator delete (4.8), grouped/foldable dashboard feeds (4.7), the session-directory consolidation (1.1), Paper RAG and figures (3.3, 3.4, 1.3), the logo cleanup (1.4), the mobile layout pass (4.5), and repo hygiene (2.5). See `CONTEXT.md` for the as-built account of each.
