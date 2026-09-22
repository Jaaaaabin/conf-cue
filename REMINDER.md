# REMINDER.md — open items from the 2026-09-18 verification

> **Temporary, same deal as `REDIRECT.md`.** It carries state between working sessions. When the
> event config is settled, fold the outcome into `README.md` / `CONTEXT.md` / `ROADMAP.md` and
> **delete this file** — the project deliberately keeps only three docs.

`app.dbpc26.de` is live and serving ConfCue. It was wired as a **reverse proxy**, not the 302
redirect `REDIRECT.md` specifies, and that broke rate limiting for every attendee.

---

## STATUS — update as you go

- [ ] **A** · Two-device cellular test against the Funnel URL 🚦 *gate: closes `CONTEXT.md:112`*
- [ ] **B** · Decide: proxy or redirect (A informs it, but does not decide it)
- [ ] **C** · COLLEAGUE — swap `reverse_proxy` for `redir … 302`, reload
- [ ] **D** · Re-verify the chain (expect 302, not 200 + `via: Caddy`)
- [ ] **E** · IPv6 — add `AAAA` for `app.dbpc26.de`, or consciously accept NAT64
- [ ] **F** · Late Oct — confirm the Funnel cert renewed past 2026-11-25
- [ ] **G** · Only then resume `REDIRECT.md` steps 7–9 (pin machine name, QR, print test)

**Currently at: A.** Event is **2026-11-25**.

---

## Verified 2026-09-18 — do not re-research

| | |
|---|---|
| `app.dbpc26.de` | `A 91.98.165.157`, no CNAME, consistent on 8.8.8.8 / 1.1.1.1 / 9.9.9.9 |
| Cert | Let's Encrypt, `CN=app.dbpc26.de`, `notAfter Dec 17 2026` — clears the event |
| `http://` | 308 → `https://`. OK |
| Pages | `/`, `/schedule.html`, `/dashboard.html`, `?query` all 200 |
| Funnel | still directly reachable, 200 |
| Funnel cert | `notAfter Nov 19 2026` — **6 days before the event**, not yet renewed |
| Colleague's box | **not** on the tailnet — so Caddy proxies to the public Funnel URL |
| Transport | no WebSocket/SSE anywhere; all `setInterval` polling. A proxy hop cannot break it |

---

## Finding 1 — it is a reverse proxy, not a redirect

```
HTTP/2 200          ← no Location header
server: uvicorn     ← ConfCue itself
via: 2.0 Caddy      ← only on this path, absent on direct-Funnel
```

Real chain: `phone → Caddy 91.98.165.157 (TLS terminates HERE) → Funnel → tailscaled → uvicorn`.

Contradicts `REDIRECT.md`'s premise — *"a redirect is not a proxy… attendee traffic never crosses
the colleague's server."* It does now, and **uploads are in scope**: `post_message_image` takes an
`UploadFile` on this origin and `image_url_must_be_ours()` forces `/uploads/` on our server, so
attendee photo bytes transit their box in plaintext. Their server is also now a single point of
failure for the event.

## Finding 2 — rate limiting collapsed to one global bucket 🔴 showstopper

`ratelimit.py` keys on `(bucket, X-Forwarded-For[0])`. Same client, **same second**:

| request | result |
|---|---|
| via `app.dbpc26.de` | `200` |
| direct to Funnel | `200` ← *different bucket* |
| via `app.dbpc26.de` again | `429` ← limiter live |

One client in two buckets ⇒ the Caddy path is not keying on the attendee IP. Nothing else varies
per attendee, so the key is constant for everyone. Limits become room-wide:

- **questions: 6 per minute for the entire audience**
- messages 20/min · photos 4/min · reactions 20/min — all totals, not per person

Spoofed XFF was ignored on **both** paths, so there is no spoofing risk.

`ratelimit.py`'s comment — *"nothing but the Funnel proxy… can reach it to set this header"* — no
longer describes the real topology, whichever way B is decided.

## CORRECTION — the 302 is not verified for rate limiting either

An earlier note in this session called the redirect "known good" for per-attendee bucketing. **It
is not.** The test above shows only that the two paths differ. That is equally consistent with:

1. direct path keys on the real client IP → per-attendee works, **or**
2. *both* paths key on constants that merely differ → both collapse.

The spoofing probe cannot separate these — it showed tailscaled **replaces** the header, never what
it replaces it *with*. So `CONTEXT.md:112` is closed **negatively for the proxy path** and **still
open for the direct path**, exactly as originally written.

Switching to the 302 is still right for the plaintext / IPv6 / single-point-of-failure reasons —
just do not assume it fixes rate limiting until step A passes.

## Finding 3 — IPv6 silently dropped (`REDIRECT.md` trap #3, now real)

`app.dbpc26.de` has an `A` record only. Funnel was dual-stack (`2a00:dd80:20::…`). IPv6-only
cellular attendees now depend on carrier NAT64 for the whole session, not just one hop.

## Finding 4 — the Funnel cert is still on the critical path

Moving to a proxy did **not** make it moot: Caddy's *upstream* is the Funnel. `notAfter Nov 19`,
event Nov 25. tailscaled should auto-renew, but only if `wu` stays online with Funnel enabled
through early November. (If the colleague set `tls_insecure_skip_verify`, this stops mattering and
a different problem starts.)

---

## "Deploy it properly later?" — assessed 2026-09-18

**Yes, by design** — that is what the domain indirection buys. `REDIRECT.md`'s goal is that the QR
survives hosting changes; deploy anywhere later, repoint `app.dbpc26.de`, no reprint.

**But it is blocked by hardware, not effort.** `backend/llm.py` pins
`MODEL = "mistral-small3.2:24b"` (15 GB) on this host's RTX 4090. Needs **≥16 GB VRAM or a smaller
model**, and `CONTEXT.md:14` rules out external LLM APIs deliberately — that is the constraint that
would have to give. A CPU-only box cannot serve the 45s summarization loop. (`fastembed` + `pymupdf`
are CPU-fine; the LLM is the whole blocker.) This is *why* the Funnel setup exists.

**It does not relieve fixing the Caddy config now** — otherwise it is two months of a known
showstopper.

---

## Probes (reusable, both harmless)

**A · the two-device test that closes `CONTEXT.md:112`.** Limit is 1 per 10s for questions; use the
no-op probe below instead of posting real questions. Two clients **on different networks** (phone on
**cellular**, not WiFi) hit the Funnel URL inside the window — both should get `200`. A `429` on the
second means the limiter collapses on the direct path too.

**Rate-limit probe — writes nothing.** `UPDATE … WHERE id = 999999999` matches zero rows, and
`check_rate_limit` runs before it:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -X POST https://wu.tailc772b5.ts.net/questions/999999999/category \
  -H 'Content-Type: application/json' -d '{"category":null}'
```

**Is it a proxy or a redirect?** `via:` + `server:` are the tell; a real redirect returns 302 with a
`Location` and no `via:`:

```bash
curl -sSI https://app.dbpc26.de/ | grep -iE '^(HTTP|location|server|via)'
```

**Funnel cert expiry:**

```bash
openssl s_client -connect 185.40.234.37:443 -servername wu.tailc772b5.ts.net </dev/null 2>/dev/null \
  | openssl x509 -noout -dates
```

**Never verify DNS from this host** — MagicDNS returns the tailnet IP. Always `@8.8.8.8` / `@1.1.1.1`.
Likewise a plain `curl -L` from here follows the redirect over the tailnet and looks like success
without testing the public path; pin it with
`--resolve wu.tailc772b5.ts.net:443:185.40.234.37`.

---

## Blocked — needs a decision from you

Determining what `X-Forwarded-For` value actually reaches uvicorn needs one observation I could not
make. **Only matters if B keeps the proxy**; if B takes the 302, test A replaces it.

- `tailscale serve --set-path /__hdrdebug 8099` + echo server — denied (exposes a local service).
- `tcpdump -i lo 'tcp port 8000'` — needs `CAP_NET_RAW`; run as `! sudo tcpdump -i lo -A -s0 'tcp port 8000'`.
- Temporary route returning `dict(request.headers)` — uvicorn runs with `--reload` so it hot-loads,
  but it edits a tracked file and briefly exposes a debug endpoint on the live app. Not done unprompted.
