#!/usr/bin/env bash
#
# Start Garmin Bot for remote access (Cloudflare quick tunnel).
#
#   1. Keeps the Mac awake                (caffeinate)
#   2. Brings up the Docker stack         (docker compose up -d --build)
#   3. Starts a Cloudflare quick tunnel   (cloudflared container -> host :3000)
#      and prints the public https://<random>.trycloudflare.com URL
#
# The trycloudflare URL is RANDOM and changes every time you run this.
# Good for testing / temporary use. For a permanent bookmarkable URL,
# switch to a Cloudflare named tunnel with your own domain later.
#
# This is fully independent of Tailscale / the IslandByte network.
#
# Usage:  ./start.sh
# Stop:   ./stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

APP_PORT=3000
CF_NAME="garmin-bot-cloudflared"
PID_FILE="$ROOT/.caffeinate.pid"

DOCKER="$(command -v docker || echo /usr/local/bin/docker)"

log() { printf '\033[1;33m[start]\033[0m %s\n' "$*"; }

# 1. Keep the machine awake ---------------------------------------------------
# -d display, -i idle system, -m disk, -s while on AC power. Runs until killed.
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  log "caffeinate already running (pid $(cat "$PID_FILE"))"
else
  caffeinate -dims &
  echo $! > "$PID_FILE"
  log "caffeinate started (pid $(cat "$PID_FILE")) - Mac will not idle-sleep"
fi

# 2. Docker stack -------------------------------------------------------------
log "building + starting Docker stack..."
"$DOCKER" compose up -d --build

# 3. Cloudflare quick tunnel --------------------------------------------------
# host.docker.internal lets the cloudflared container reach the app that
# compose publishes on the host's port 3000.
log "starting Cloudflare quick tunnel..."
"$DOCKER" rm -f "$CF_NAME" >/dev/null 2>&1 || true
"$DOCKER" run -d --name "$CF_NAME" --restart unless-stopped \
  cloudflare/cloudflared:latest \
  tunnel --no-autoupdate --url "http://host.docker.internal:${APP_PORT}" >/dev/null

# Poll the container logs for the assigned public URL.
log "waiting for the public URL (a few seconds)..."
URL=""
for _ in $(seq 1 40); do
  URL="$("$DOCKER" logs "$CF_NAME" 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 || true)"
  [[ -n "$URL" ]] && break
  sleep 1
done

echo
if [[ -n "$URL" ]]; then
  log "Done. Public URL (changes every restart):"
  printf '\n    \033[1;36m%s\033[0m\n\n' "$URL"
  log "Send that link. Run ./stop.sh to tear it all down."
else
  log "Tunnel started but no URL appeared yet. Check logs:"
  log "  docker logs -f $CF_NAME"
fi
