#!/usr/bin/env bash
#
# Stop Garmin Bot remote access: kills the Cloudflare tunnel, takes down the
# Docker stack, and lets the Mac sleep again.
#
# Usage:  ./stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

CF_NAME="garmin-bot-cloudflared"
PID_FILE="$ROOT/.caffeinate.pid"
DOCKER="$(command -v docker || echo /usr/local/bin/docker)"

log() { printf '\033[1;33m[stop]\033[0m %s\n' "$*"; }

log "stopping Cloudflare tunnel..."
"$DOCKER" rm -f "$CF_NAME" >/dev/null 2>&1 || true

log "stopping Docker stack..."
"$DOCKER" compose down

if [[ -f "$PID_FILE" ]]; then
  if kill "$(cat "$PID_FILE")" 2>/dev/null; then
    log "caffeinate stopped - Mac can sleep again"
  fi
  rm -f "$PID_FILE"
fi

log "Done."
