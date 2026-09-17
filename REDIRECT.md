# REDIRECT.md — working runbook: `app.dbpc26.de` → Funnel

> **Temporary file with a defined end of life.** It exists to carry state across working
> sessions while this is executed. When the QR code is printed and verified, fold the
> outcome into `README.md` / `CONTEXT.md` / `ROADMAP.md` and **delete this file** — the
> project deliberately keeps only three docs.

---

## STATUS — update as you go

- [ ] **0** · Ask colleague: does the server have IPv6? (this decides the DNS record type)
- [ ] **1** · YOU — change the `app` DNS record at STRATO
- [ ] **2** · YOU — verify DNS moved 🚦 *gate: script must print `[2/3]`*
- [ ] **3** · YOU — give colleague the go-ahead
- [ ] **4** · COLLEAGUE — add Caddy block, reload
- [ ] **5** · YOU — verify full chain (302 → 200)
- [ ] **6** · YOU — test on a phone **on cellular** 🚦 *gate: nothing prints until this passes*
- [ ] **7** · YOU — pin the Tailscale machine name
- [ ] **8** · YOU — generate the QR code
- [ ] **9** · YOU — print test at final size

**Currently at: step 0.**

---

## Goal

The QR code must survive hosting changes made between now and the event (**2026-11-25**).
So it encodes a domain we control, which redirects to whatever is actually serving:

```
phone scans QR
  → https://app.dbpc26.de/            Caddy on the colleague's box, 302
  → https://wu.tailc772b5.ts.net/     Funnel, unchanged   ← address bar lands here
  → 127.0.0.1:8000                    ConfCue, unchanged
```

**A redirect is not a proxy.** After the 302 the phone talks straight to Funnel, so attendee
traffic (questions, chat, uploaded photos) never crosses the colleague's server, TLS keeps
terminating on our own node, and `backend/ratelimit.py` needs no change.

Accepted trade-off: the address bar ends on the `.ts.net` URL, so shared links carry that,
not the branded name. The domain is for printed and spoken material.

---

## Verified facts — do not re-research these

Measured 2026-09-17.

| | |
|---|---|
| Zone `dbpc26.de` | STRATO nameservers (`shades11` / `docks10.rzone.de`) |
| `dbpc26.de`, `www` | Hetzner `91.98.165.157`, **server: Caddy**, Let's Encrypt, no HSTS |
| `www.dbpc26.de` | `CNAME → dbpc26.de.` — the pattern `app` should copy |
| `app.dbpc26.de` | `CNAME → wu.tailc772b5.ts.net.`, TTL **150s** — must change |
| Funnel | 443, `/ → 127.0.0.1:8000`, machine `wu`, tailnet `tailc772b5.ts.net` |
| Event date | 2026-11-25 |

**`app.dbpc26.de` is broken right now** — and cannot be fixed by pointing it at Funnel:

```
curl https://app.dbpc26.de/      → curl: (35) unexpected eof   (no HTTP response at all)
openssl SNI=app.dbpc26.de        → "no peer certificate available", connection dropped
openssl SNI=wu.tailc772b5.ts.net → valid Let's Encrypt cert, same IPs   ← works
```

Funnel routes by SNI and only holds a `*.ts.net` cert, so it drops connections asking for any
other name. Documented limitation (tailscale.com/kb/1223/funnel; open FR tailscale#11563).
No config fixes it — **the CNAME must be replaced, not kept.**

---

## Traps

1. **Order matters: DNS before Caddy.** Caddy gets its cert via ACME HTTP-01, which only
   succeeds once `app.dbpc26.de` resolves to its box. Configure it first and it fails in a
   loop, which can trip Let's Encrypt's failed-validation limit (5/hour/hostname).

2. **Never verify DNS from this host — MagicDNS lies.**
   ```
   dig wu.tailc772b5.ts.net           → 100.67.73.0     ← tailnet IP, misleading
   dig @8.8.8.8 wu.tailc772b5.ts.net  → 185.40.234.x    ← what attendees actually get
   ```
   Every public check must use `@8.8.8.8` / `@1.1.1.1` or an off-tailnet device.

3. **Repointing `app` silently drops IPv6.** Funnel is dual-stack, the Caddy box is not:
   ```
   wu.tailc772b5.ts.net   A 185.40.234.x    AAAA 2a00:dd80:20::...   ← dual-stack
   dbpc26.de              A 91.98.165.157   AAAA (none)              ← v4 only
   ```
   Attendees on IPv6-only mobile networks would then depend on carrier NAT64 for the redirect
   hop. Hence step 0 — if the box has IPv6, add an `AAAA` and the gap closes.

4. **302, not 301.** A permanent redirect is cached hard by browsers; if the target is ever
   repointed, already-scanned phones keep hitting the stale one — defeating the whole point.

5. **In the STRATO panel, touch only the `app` row.** The zone also carries `MX`, `_dmarc`
   with `p=reject`, and a Google verification TXT. With `p=reject`, damaged mail records fail
   *silently* rather than visibly.

---

## Steps

### 0 · YOU → colleague, ask first

> Does the `dbpc26.de` server have an IPv6 address? And can you add a small Caddy block when
> I give you the go-ahead?

Ask before touching DNS: a `CNAME` cannot coexist with an `AAAA` at the same name, so the
answer decides the record type and avoids editing twice.

### 1 · YOU — DNS at STRATO, zone `dbpc26.de`, row `app` only

```
delete:  app   CNAME   wu.tailc772b5.ts.net.

no IPv6 on the box:                 has IPv6:
  add:   app   CNAME   dbpc26.de.     add:  app  A     91.98.165.157
                                            app  AAAA  <their v6>
```

### 2 · YOU — verify DNS moved 🚦

Wait ~3 min (TTL 150s), then run the script in **Verification** below.

**Gate:** proceed only when it prints `[2/3] CADDY answering, no cert yet`.

`https://app.dbpc26.de/` is still broken at this point — that is correct, Caddy has no site
block for the name yet. Judge by the script's verdict line, not by whether the page loads.

### 3–4 · COLLEAGUE — Caddy

Send verbatim:

> DNS for `app.dbpc26.de` now points at this server. Could you add this block and reload?
> Caddy will obtain the certificate automatically — nothing else is needed, and no traffic
> beyond the redirect itself touches this box.
>
> ```caddyfile
> app.dbpc26.de {
>     redir https://wu.tailc772b5.ts.net{uri} 302
> }
> ```
>
> `systemctl reload caddy`
>
> Please keep it **302, not 301** — a permanent redirect gets cached hard by browsers and we
> need to be able to repoint this later. `{uri}` preserves the path.

### 5–6 · YOU — verify the chain 🚦

Run the script below (expect `[3/3] CADDY + cert for app.dbpc26.de`), then:

```bash
curl -sSI https://app.dbpc26.de/                 # 302 → Location: https://wu.tailc772b5.ts.net/
curl -sSL -o /dev/null -w '%{http_code} %{url_effective}\n' https://app.dbpc26.de/   # 200
curl -sSI https://app.dbpc26.de/schedule.html    # path preserved
```

Then **from a phone on cellular, not WiFi** — the only test that reflects a real attendee,
and the one that catches an IPv6/NAT64 problem.

**Gate: nothing gets printed until this passes.**

### 7 · YOU — pin the Tailscale machine name

Admin console → Machines → `wu` → **Edit machine name** → re-enter `wu`.

The machine name currently matches the OS hostname, meaning it is still auto-tracking it. Any
`hostnamectl` or reimage would silently change the URL and kill every printed QR code. Also:
never rename the tailnet, and if the host is rebuilt, delete the old node *first* (a colliding
re-enrollment becomes `wu-1` permanently).

### 8 · YOU — generate the QR

- `scripts/make_qr.py` using **segno** (pure Python, no image libs).
- **Do not add segno to `pyproject.toml`** — offline tool, not a runtime dep; this project
  refuses unjustified deps (see the slowapi/redis reasoning in `CONTEXT.md`).
  Run: `uv run --with segno python scripts/make_qr.py`
- Encode `https://app.dbpc26.de/` — the root, never a sub-page, so frontend restructuring can
  never invalidate printed material.
- Output **SVG** (print) + PNG (slides), error correction **level H** (~30% recoverable),
  quiet zone 4 modules, dark-on-light. Write to a gitignored `qr/`, not `frontend/`.
- Sizing: printed width ≈ scan distance ÷ 10. Poster at 1.5 m → ~15 cm; table tent at 30 cm → ~3 cm.
- **Always print the URL as text underneath** — the fallback when a camera app fails.

### 9 · YOU — print test

Final size, both iOS and Android, under venue lighting.

---

## Verification script

Self-contained — paste into a shell. (Do not rely on a scratchpad copy; those are session-scoped.)

**Do not judge progress by TLS error strings.** Funnel and Caddy-without-a-site-block *both*
report `no peer certificate available`, and both surface as a `curl: (35)`. The reliable
discriminator is the resolved IP, which is what this script keys on. (An earlier version of
this script matched on error text and misreported a successful step 1 as a failure.)

```bash
cat > /tmp/verify_redirect.sh << 'SCRIPT'
#!/usr/bin/env bash
# Verdict keys on the resolved IP, not TLS error strings.
CADDY_IP=91.98.165.157
echo "===== app.dbpc26.de check  $(date '+%F %T') ====="
for r in 8.8.8.8 1.1.1.1 9.9.9.9; do
  printf "   %-8s A: %s\n" "$r" "$(dig +short @$r app.dbpc26.de A | grep -E '^[0-9]' | tr '\n' ' ')"
done
IP=$(dig +short @8.8.8.8 app.dbpc26.de A | grep -E '^[0-9]' | head -1)
CERT=$(timeout 15 openssl s_client -connect app.dbpc26.de:443 -servername app.dbpc26.de </dev/null 2>/dev/null \
       | openssl x509 -noout -subject 2>/dev/null)
echo
if [ -z "$IP" ]; then
  echo "   ?? no A record — check the STRATO panel"
elif [ "$IP" = "$CADDY_IP" ]; then
  if grep -q "app.dbpc26.de" <<<"$CERT"; then
    echo "   [3/3] CADDY + cert for app.dbpc26.de  -> Caddy block LIVE, verify the 302 below"
  else
    echo "   [2/3] CADDY answering, no cert yet    -> STEP 1 DONE. Tell the colleague to go."
  fi
else
  echo "   [1/3] Still FUNNEL ($IP)      -> DNS not moved or not propagated yet"
fi
echo
echo "-- HTTP (expect 302 -> wu.tailc772b5.ts.net once Caddy is live)"
curl -sSI --max-time 15 https://app.dbpc26.de/ 2>&1 | head -3 | sed 's/^/   /'
SCRIPT
bash /tmp/verify_redirect.sh
```

Expected progression: `[1/3]` now → `[2/3]` after your DNS change → `[3/3]` after the Caddy
reload. Both the `[1/3]` and `[2/3]` branches have been tested against the real hosts.

---

## Rollback

Everything through step 6 reverts within one TTL (~3 min). **The one-way door is the printer,
not the DNS.**

- **Undo step 1:** set `app CNAME wu.tailc772b5.ts.net.` again.
- **Undo step 4:** colleague deletes the block and reloads. A leftover cert is harmless.
- **Untouched throughout:** `https://wu.tailc772b5.ts.net/`, the Funnel config, systemd, the
  database, the app code, and the `dbpc26.de` / `www` website.

Note that "revert" restores a **broken** `app.dbpc26.de` — it does not work today either. The
worst case is an unused subdomain, not a regression.

### DNS snapshot taken before any change (external view, 2026-09-17)

```
SOA    dbpc26.de        docks10.rzone.de. hostmaster.strato-rz.de. 2026020534 86400 7200 604800 300
NS     dbpc26.de        shades11.rzone.de. | docks10.rzone.de.
A      dbpc26.de        91.98.165.157
MX     dbpc26.de        5 smtpin.rzone.de.
TXT    dbpc26.de        "google-site-verification=ydTmuUGgAOS-elSWblQXa6fRa7oQc2b3L1pVT8YlCIA"
CNAME  www.dbpc26.de    dbpc26.de.
CNAME  app.dbpc26.de    wu.tailc772b5.ts.net.        <- THE ONLY ROW TO TOUCH
TXT    _dmarc           "v=DMARC1;p=reject;"
```

---

## Fallback if the colleague is unavailable

The redirect host does not have to be theirs. Anything that can obtain a cert for
`app.dbpc26.de` works — Netlify or Cloudflare Pages with a one-line `_redirects` file, or
STRATO's own HTTPS domain forwarding. Only the DNS target changes; every other step is
identical. Use this rather than letting the QR slip.

## When this is done

1. `README.md` — add `app.dbpc26.de` as the public entry point (Part 3 + reference table)
2. `CONTEXT.md` — record the SNI finding and why a redirect beat a proxy, under
   "Networking — Tailscale Funnel"
3. `ROADMAP.md` — tick the QR item (4.6) and the blocking checklist
4. **Delete this file.**
