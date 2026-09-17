# ConfCue

Lightweight conference Q&A. Attendees scan a QR code during a talk and submit questions from their phone; a locally running LLM clusters and summarizes them every 45s onto a live moderator dashboard, and drafts a grounded answer to each question from the speaker's own paper.

No external LLM APIs — summarization, answering, and retrieval all run on the host.

**Docs:** this file is how to *run and operate* it. `CONTEXT.md` is *why it's built this way*. `ROADMAP.md` is *what's done, missing, and next*.

---

# Part 1 — Getting started

## Requirements

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **[Ollama](https://ollama.com/)** running locally, with the summarization model pulled:
  ```bash
  ollama pull mistral-small3.2:24b
  ```
  The model name is a constant in `backend/llm.py`; change it there to use a different one.

## Run it

```bash
git clone git@github.com:Jaaaaabin/conf-cue.git
cd conf-cue
uv sync                                           # installs dependencies
uv run python scripts/build_sessions_index.py     # schedule.csv -> sessions.json
uv run uvicorn backend.main:app --reload
```

| | |
|---|---|
| Attendee (ask a question) | http://127.0.0.1:8000/ |
| Moderator dashboard | http://127.0.0.1:8000/dashboard.html |

The SQLite database and upload directory are created on first start — there is no migration or init step.

**`build_sessions_index.py` is not optional on a fresh clone.** `frontend/sessions.json` is generated *and* gitignored *and* fetched by every page; without it the schedule, the "Now" banner, and chat session routing are all silently empty.

## Moderator delete (optional)

Deleting questions and chat messages is gated by a shared secret. Without it the app runs fine, but those endpoints reject everything (it fails closed):

```bash
export MODERATOR_KEY="some-long-random-string"
```

See `.env.example`. The app reads the process environment directly — it does **not** auto-load a `.env` file.

---

# Part 2 — Conference papers

Optional. Attendee answers cite the speaker's paper, and the ask page shows that paper's figures. Both degrade gracefully — skip this and everything else still works.

These are offline batch scripts, not part of the running app. **Nothing needs restarting** — `backend/rag.py` reads `frontend/schedule.csv` and the index files fresh on every question.

1. Set `paper_id` (and `doi`, once assigned) on that paper's row in `frontend/schedule.csv`. There is no separate papers manifest — the link lives on the session row itself, like `presenter`.
2. Regenerate the session index. **A schedule edit is not visible until this runs:**
   ```bash
   uv run python scripts/build_sessions_index.py
   ```
3. Put the PDF at `data/papers/<paper_id>.pdf`. Try `uv run python scripts/fetch_papers.py` first, but don't count on it — publishers redirect DOIs to landing pages (0 of 5 real DOIs auto-fetched). Manual download is the reliable path.
4. Process it:
   ```bash
   uv run python scripts/extract_figures.py
   uv run python scripts/build_paper_index.py
   ```
   Both are **incremental** — already-processed papers are skipped unless the PDF changed (or `--force` is passed), so adding one more paper only costs time for that one.

---

# Part 3 — Operating the live server

Everything below is specific to the provisioned host. On any other machine, Part 1 is all you need.

## Current state

- Managed by **systemd** since 2026-09-03: unit `conf-cue.service` at `/etc/systemd/system/conf-cue.service`, **enabled** (survives reboot) and `Restart=always` (survives a crash).
- Runs as user `wu`, bound to `127.0.0.1:8000` only, reachable publicly through Tailscale Funnel at `https://wu.tailc772b5.ts.net`. **Binding to loopback is load-bearing**: rate limiting trusts `X-Forwarded-For`, which is only safe because nothing but the Funnel proxy can reach the port to set it.
- `MODERATOR_KEY` lives in `/etc/conf-cue.env` (root-owned, mode 600) — **not** in this repo. Never paste the real key into a file that lives here.
- `--reload` is still on in `ExecStart` (active development). See the pre-event checklist for when to turn it off.

## Golden rule

**Never run `uv run uvicorn backend.main:app` by hand on this host.** systemd already owns port 8000, so it just fails with `[Errno 98] Address already in use` — that's expected and correct, not a stray process to hunt down.

## Checking status

```bash
sudo systemctl status conf-cue.service   # up? since when? last log lines
curl -s http://127.0.0.1:8000/health     # {"status":"ok"} if actually serving
sudo journalctl -u conf-cue -f           # live log tail, Ctrl-C to stop
```

## Making a change

- **Frontend** (`frontend/*.html`, `style.css`, images): no restart, ever. `StaticFiles` re-reads from disk on every request, and the `no-cache` middleware stops browsers serving a stale copy. Save and reload.
- **Backend** (`backend/*.py`): with `--reload` on, saving auto-restarts the worker within seconds — watch it in `journalctl`. No `systemctl` command needed.
- If `--reload` has been turned off, a backend change needs `sudo systemctl restart conf-cue.service`.

## Pausing, stopping, disabling

```bash
sudo systemctl stop conf-cue.service      # stop now
sudo systemctl start conf-cue.service     # start again
sudo systemctl restart conf-cue.service   # both
```

`stop` only affects the current run — the unit stays `enabled`, so a reboot still brings it back. Boot-autostart (`enable`/`disable`) and run state (`start`/`stop`) are independent. To fully decommission after the event: `sudo systemctl disable --now conf-cue.service`.

## Rotating the moderator key

```bash
sudo nano /etc/conf-cue.env       # edit the MODERATOR_KEY= line
sudo systemctl restart conf-cue.service
```

Any dashboard browser holding the old key in `localStorage` gets a 401 on its next delete and is reprompted — expected, not a bug.

The file is root-only mode 600, so you can't `cat` it to confirm the edit. Verify instead by:
- `ls -la /etc/conf-cue.env` — fresh mtime, and a byte count matching `len("MODERATOR_KEY=") + len(key) + 1`.
- Functionally: `curl -X DELETE http://127.0.0.1:8000/questions/<id> -H "X-Moderator-Key: <new key>"`. A `200` (or `404` if that id is gone) means the new key is live; `401` means the restart didn't pick it up.

## Tailscale Funnel

Funnel just proxies to `127.0.0.1:8000`. Restarting uvicorn is picked up automatically with zero DNS or cert involvement.

- **Don't run `tailscale funnel reset` for routine restarts.** Only use it when actually changing Funnel config, and remember it removes public reachability until re-enabled.
- **First-time DNS propagation lag is real and expected.** The first time Funnel is enabled for a hostname, Tailscale issues a fresh TLS cert (ACME `dns-01`) and publishes new DNS records. For ~15–20 minutes, some devices and networks fail to resolve it (`DNS_PROBE_FINISHED_NXDOMAIN`) while others work fine. Confirmed here: two devices on the *identical* network showed opposite results, purely from each having queried at a different moment. It self-resolves as caches expire.
- **Re-enabling after a reset should be fast** — the cert for this hostname is already issued and cached (Let's Encrypt, ~90 days, auto-renewed). A fresh propagation cycle only happens on genuinely new issuance. Not empirically verified, so don't test it right before doors open.

## Emergency data reset

Wipes questions (answers + categories), reactions, chat messages, and uploaded images. **Not routine** — it's for the testing phase or a major mid-event problem.

```bash
uv run python scripts/reset_data.py        # --yes to skip the prompt
```

Safe to run with the server up; it picks up the empty state on its own (reactions and chat immediately, the summary within its normal 45s refresh). Host-only by design — there is deliberately no HTTP endpoint, since an exposed "wipe everything" route on a public URL would be the single biggest risk in the app. Does **not** touch paper data or the schedule.

## Before the event — pre-flight checklist

- [ ] Confirm the Funnel URL resolves from an off-network device: `dig @8.8.8.8 wu.tailc772b5.ts.net`, `dig @1.1.1.1 ...`, then an actual phone on cellular. Enable Funnel well ahead of time — the night before, not last-minute — and once confirmed, leave it running rather than touching it again.
- [ ] **Verify rate limiting separates two real, differently-networked phones** through the Funnel URL. A false negative here silently rate-limits every attendee as if they were one person. See `ROADMAP.md` — this is a hard gate.
- [ ] `sudo systemctl is-enabled conf-cue.service` → should say `enabled`.
- [ ] Decide whether to turn `--reload` off: edit `ExecStart=` in the unit, then `sudo systemctl daemon-reload && sudo systemctl restart conf-cue.service`. Trades instant backend edits for one less moving part.

---

## Reference

| What | Where |
|---|---|
| Unit file | `/etc/systemd/system/conf-cue.service` |
| Secret file | `/etc/conf-cue.env` (root:root, mode 600) |
| Env vars that exist | just `MODERATOR_KEY` — see `.env.example` |
| App code | `backend/`, `frontend/` |
| Public URL | `https://wu.tailc772b5.ts.net` |
| Local-only URL | `http://127.0.0.1:8000` |
| Session directory (source) | `frontend/schedule.csv` — tracked; date/time, names, presenter, paper_id, doi |
| Session directory (generated) | `frontend/sessions.json` — gitignored, rebuilt by `scripts/build_sessions_index.py` |
| Paper PDFs | `data/papers/<paper_id>.pdf` (gitignored) |
| Paper index | `data/paper_index/<paper_id>.{npz,json}` (gitignored) |
| Extracted figures | `frontend/papers/<paper_id>/` (gitignored) |
| Raw/unused icon sources | `icon_archive/` at repo root — **not** under `frontend/`, since anything there is publicly servable regardless of `.gitignore` |
