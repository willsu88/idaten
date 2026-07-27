#!/usr/bin/env bash
#
# Stop Idaten: kills the Cloudflare tunnel (whichever mode is running), takes
# down the Docker stack, and lets the machine sleep again.
#
# Usage:  ./stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CF_NAME="garmin-bot-cloudflared"     # docker container (quick mode)
CF_CONFIG="$HOME/.cloudflared/config.yml"
# Named-tunnel name: CF_TUNNEL env override, else the config's `tunnel:` key.
CF_TUNNEL="${CF_TUNNEL:-$(grep -oE '^tunnel: *[^ ]+' "$CF_CONFIG" 2>/dev/null | awk '{print $2}' || true)}"
PID_FILE="$ROOT/.caffeinate.pid"
CF_PID_FILE="$ROOT/.cloudflared.pid" # named tunnel host process pid
DOCKER="$(command -v docker || echo /usr/local/bin/docker)"

log() { printf '\033[1;33m[stop]\033[0m %s\n' "$*"; }

log "stopping Cloudflare tunnel..."
# quick mode: the cloudflared container
"$DOCKER" rm -f "$CF_NAME" >/dev/null 2>&1 || true
# named mode: the host cloudflared background process (pid file, then any stray)
if [[ -f "$CF_PID_FILE" ]]; then
  kill "$(cat "$CF_PID_FILE")" 2>/dev/null || true
  rm -f "$CF_PID_FILE"
fi
if [[ -n "$CF_TUNNEL" ]]; then
  pkill -f "cloudflared.*run ${CF_TUNNEL}" 2>/dev/null || true
fi

log "stopping Docker stack..."
"$DOCKER" compose down

if [[ -f "$PID_FILE" ]]; then
  if kill "$(cat "$PID_FILE")" 2>/dev/null; then
    log "caffeinate stopped - machine can sleep again"
  fi
  rm -f "$PID_FILE"
fi

log "Done."
