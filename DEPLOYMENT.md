# Deployment Plan - moving Idaten off the Mac

Working document. The decision, the reasoning, and a step-by-step migration runbook.
Not done yet - captured so we can execute later without re-deriving it.
Written: 2026-07-21.

## Current local setup (the Mac, until the VPS move)

The app runs on Will's Mac behind a Cloudflare **named tunnel** (`idaten` -> `idaten.williamsu.me`).

`start.sh` and `stop.sh` now own that tunnel, so it is no longer started by hand.
This was the cause of repeated Cloudflare **Error 1033** (tunnel configured but no connector dialing in):
the old `start.sh` only started a throwaway `trycloudflare.com` quick tunnel, while the named tunnel that serves the real domain lived outside any script and only ran when someone launched `cloudflared` manually.
So it vanished on every sleep / logout / reboot.

`start.sh` supports two tunnel modes:

- `./start.sh` - **named** tunnel to `idaten.williamsu.me` (default). Host `cloudflared` binary + `~/.cloudflared/config.yml`, run in the background (`.cloudflared.pid` / `.cloudflared.log`).
- `./start.sh quick` - throwaway random `trycloudflare.com` URL via a `cloudflared` Docker container. For one-off testing.

`stop.sh` tears down whichever is running (container + host process).

Caveat still open: this does not survive a full **reboot or logout** on its own - you re-run `./start.sh`.
The `caffeinate` pin blocks idle-sleep, so in practice it stays up.
True auto-start-on-boot would need a `launchd` LaunchAgent; the real long-term fix is the VPS move below.

## The decision

Move the app off Will's Mac in Taiwan onto an always-on VPS in **Tokyo or Singapore**, keep the existing Cloudflare tunnel in front, and put a real domain on it.
Target cost: **~$15-25/month all in** (VPS ~$12-24/mo + domain ~$10-15/yr).

### Why move at all - reliability, not latency

The Mac is the wrong host for inviting friends for one reason, and it is not speed:

- **Reliability.** The Mac sleeps (we keep a `caffeinate` process pinned just to fight this), reboots for OS updates, and rides a home ISP dynamic IP and home power.
When it is 3am in Taiwan and the Mac is asleep, US friends are mid-day and the app is simply down.
- **Latency is a red herring for this app.** Idaten is a coaching dashboard, not a real-time game.
The slow operations (LLM calls, Garmin sync) take seconds regardless of where the box sits.
A US friend feels roughly 150ms extra per API call - "slightly less snappy," not "broken."

So the move is about uptime for a second timezone, not shaving milliseconds.

### Why Tokyo/Singapore and not Civo (or a US host)

Daily users (Will + gf) are in **Taiwan**; friends trying it out are in the **US**.
We cannot be physically near both, so we optimize for the people who use it every day and accept "acceptable" for occasional users.

| Server location | Will + gf (Taiwan) | US friends | Verdict |
|---|---|---|---|
| Mac in Taiwan | ~10ms | ~150-200ms | Fine for us, unreliable for everyone |
| **Tokyo / Singapore VPS** | **~40-70ms** | **~120-170ms** | **Fast for us, fine for friends** |
| Civo (NYC / London / Frankfurt) | ~180-250ms | ~20-80ms | Fast for friends, sluggish for us daily |

**Civo is the wrong pick here**, for two independent reasons:

1. **No Asia region** (as of 2026-07: London, Frankfurt, New York, India only), so it makes the daily-driver experience slower - backwards from what we want.
2. **Kubernetes-first.** Our app is a two-service `docker-compose`; Civo would mean either standing up K8s (overkill ops) or using plain compute in a far region.
It is not a cost problem (small instances are ~$5-10/mo) - it is wrong region + wrong abstraction.
Leftover FindLabs credits, if any, are better spent elsewhere.

Keeping **Cloudflare in front** (already in use via the tunnel) caches the Next.js static assets on its global edge, so US friends only pay the round-trip on real API calls, not on page loads.
That is most of the benefit of a fancy edge deploy, for free, with zero new moving parts, plus free HTTPS (which our `COOKIE_SECURE=true` / `secure=True` cookie requires).

## Migration runbook

Small, because the security prerequisites are already done (encrypted Garmin passwords, `Secure` cookie, login throttle, tenant isolation, gated `/admin`, `.gitignore`).

### 0. Pre-flight (before touching the new box)

- [ ] Pick provider + region: Vultr (Tokyo/Singapore), Linode/Akamai (Tokyo/Singapore), or DigitalOcean (Singapore).
Verify live pricing at checkout - promos shift often; the ranges above are not locked quotes.
- [ ] Buy the domain (Cloudflare Registrar sells at cost, ~$10-15/yr) so it is ready to point at the tunnel.
- [ ] Confirm the current `.env` on the Mac is complete and note which values must carry over verbatim (see the secrets checklist in step 4).

### 1. Provision the VPS

- [ ] Create a **2 vCPU / 4 GB** instance in Tokyo or Singapore, Ubuntu LTS.
The whole stack (FastAPI + Next.js + SQLite) fits comfortably at household + few-friends concurrency; SQLite is fine here (see ROADMAP security section - Postgres is not needed).
- [ ] Harden the box: non-root sudo user, SSH keys only (disable password auth), `ufw` allowing only SSH plus whatever the Cloudflare tunnel needs (the tunnel dials out, so ideally no inbound app ports are exposed publicly at all).
- [ ] Install Docker + the Compose plugin.
- [ ] Clone the repo (or copy the deploy files) onto the box.

### 2. Take a clean data snapshot from the Mac

- [ ] **Do NOT copy the live `data/garmin_bot.db` (or its `-wal`/`-shm`) off the host.**
Copying the WAL DB while the app is running corrupts the app's connections (learned rule).
Use the in-container SQLite backup API to produce a single consistent `.db` file, exactly as the ROADMAP predeploy backups do.
- [ ] Copy that backup file plus the Garmin token cache (`data/garmin_tokens/`) and the encryption key file (`data/.secret_key`, if `SECRET_KEY` is not set explicitly in `.env`) to the new box's `./data`.
- [ ] Treat every `.db` file as a secret in transit (scp over SSH, delete the intermediate copy afterward).

### 3. Bring the stack up on the VPS

- [ ] Place `data/` (restored DB + tokens + key) alongside the compose file.
- [ ] `docker compose up -d --build`.
- [ ] Smoke test locally on the box (curl `http://localhost:8000/docs` and `http://localhost:3000`) before exposing anything.

### 4. Secrets checklist (must be correct on the new box)

- [ ] `SECRET_KEY` - **set it explicitly and back it up**, OR carry over the `data/.secret_key` file.
If this value changes, existing encrypted Garmin passwords become undecryptable and every member must re-enter their Garmin credentials.
- [ ] `COOKIE_SECURE=true` - required now that we have real HTTPS via Cloudflare.
- [ ] `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, `LLM_PROVIDER`, model names - carry over.
- [ ] `TZ=Asia/Taipei` in compose - **keep it.** The daily job hour and all date logic assume the household is in Taiwan; a nearby region keeps that model clean.
- [ ] `GARMIN_*` / `INITIAL_*` - these only seed an empty DB; with a restored DB they are inert, but keep `.env` complete.

### 5. Domain + Cloudflare cutover

- [ ] Point the domain at the Cloudflare tunnel (the tunnel connector runs on the new VPS; the public hostname maps to the local frontend/backend).
- [ ] Verify HTTPS end to end and that the session cookie comes back with `Secure` set.
- [ ] Test **SSE streaming chat through the tunnel** specifically - we have two prior scars here (`compress:false` in Next must stay; chat SSE must go through a route handler, not a `rewrites()` proxy).
A plain page load passing is not enough; watch a chat reply stream token by token.
- [ ] Confirm the daily scheduler fires at `PLAN_HOUR` local time on the new box (check the next morning's eager review actually generated).

### 6. Verify the friend-invite path

- [ ] Log in as admin (Will): `/admin` renders, roster + usage cards present.
- [ ] Log in as a non-admin (gf): no Admin nav item, `/admin` redirects home, Settings is purely personal.
- [ ] Generate one real invite link and have a US friend complete signup + Garmin connect end to end from the US, on their phone.
- [ ] Confirm login throttle (429 after repeated bad passwords) still behaves on the new box.

### 7. Decommission the Mac

- [ ] Run both boxes in parallel for a few days if nervous; the Mac stays authoritative until the VPS is proven.
- [ ] Once confident, stop the Mac stack (`stop.sh`), kill the `caffeinate` pin, and keep one final Mac-side backup archived off-box as a cold copy.
- [ ] Set up a recurring off-box backup of the VPS `.db` (treated as a secret) so the single SQLite file is never the only copy.

## Alternatives considered (not chosen)

- **Frontend on Vercel (free, global edge) + API on the Tokyo VPS.**
Snappiest possible page loads for US friends, but it splits one clean `docker-compose` into two deploys and reopens cross-origin CORS/SSE - exactly the area with two prior scars.
Revisit only if friends complain after the Cloudflare-in-front setup.
- **US VPS instead of Tokyo.**
Only correct if the friend trial becomes the primary use and we two become secondary.
Not true today.

## Open items to confirm at execution time

- Live VPS pricing at checkout (Tokyo vs Singapore, provider promos).
- Whether to keep the Cloudflare **tunnel** or move to a Cloudflare-proxied A record to the VPS with the app ports firewalled (tunnel keeps zero inbound ports open, which is the safer default).
- Backup cadence + destination for the VPS `.db` (and whether to encrypt the backup files themselves, per the ROADMAP "backups as secrets" note).
