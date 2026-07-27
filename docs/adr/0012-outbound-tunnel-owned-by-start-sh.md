# Public access is an outbound Cloudflare tunnel, owned by start.sh

The app is reachable at its domain through a Cloudflare named tunnel: a connector on the host dials out to Cloudflare, and no inbound port is ever opened.
The tunnel process is started and stopped by `start.sh`/`stop.sh`, never by hand.
Full reasoning, the VPS migration decision, and the runbook live in `DEPLOYMENT.md`; this ADR records only the two decisions that outlast it.

## Considered Options

- **Router port-forwarding + dynamic DNS** - rejected: open inbound ports on a home network and no TLS story (the `Secure` session cookie requires real HTTPS).
- **Tailscale / private mesh** - rejected: private-only; friends can't be invited by URL.
- **ngrok-style quick tunnels** - kept only as `./start.sh quick` for one-off testing; a throwaway URL is wrong for a permanent domain.
- **Cloudflare named tunnel** - chosen: zero inbound ports, free HTTPS, and edge caching of static assets for far-away users.

## The ownership lesson

The recurring Cloudflare Error 1033 outages were never a Cloudflare problem: the named tunnel serving the real domain lived outside any script, only ran when someone launched `cloudflared` manually, and vanished on every sleep, logout, and reboot.
The fix was ownership, not configuration: **any process the deployment depends on must be owned by the deploy scripts.**
`start.sh` is the single owner of the deployment lifecycle - tests (ADR 0001), containers, and the tunnel - and `stop.sh` tears down whichever tunnel mode is running.

## Consequences

- The host advertises nothing: the connector dials out, so hardening reduces to SSH plus the tunnel.
- SSE streaming has two recorded scars that any transport change must re-verify: Next.js `compress: false` must stay, and chat SSE must go through a route handler, not a `rewrites()` proxy (see DEPLOYMENT.md step 5).
- Reboot/logout still requires re-running `./start.sh`; the accepted interim is the `caffeinate` pin, and the real fix is the VPS move planned in DEPLOYMENT.md.
