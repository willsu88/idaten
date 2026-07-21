#!/usr/bin/env bash
#
# Start Garmin Bot for remote access via a Cloudflare tunnel.
#
#   1. Keeps the Mac awake            (caffeinate)
#   2. Brings up the Docker stack     (docker compose up -d --build)
#   3. Starts a Cloudflare tunnel     (see the two modes below)
#
# Two tunnel modes:
#
#   named  (default) - the permanent, bookmarkable domain (idaten.williamsu.me).
#                      Uses the host `cloudflared` binary + ~/.cloudflared/config.yml.
#                      Runs in the background; ./stop.sh tears it down.
#
#   quick            - a throwaway random https://<random>.trycloudflare.com URL.
#                      Uses a cloudflared Docker container. No domain/config needed.
#                      Good for one-off testing. The URL changes every run.
#
# Pick a mode with the TUNNEL env var or the first argument:
#
#   ./start.sh              # named tunnel (the real domain)
#   ./start.sh quick        # random trycloudflare URL
#   TUNNEL=quick ./start.sh # same as above
#
# This is fully independent of Tailscale / the IslandByte network.
#
# Stop:   ./stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

APP_PORT=3000
CF_NAME="garmin-bot-cloudflared"          # docker container name (quick mode)
CF_TUNNEL="idaten"                        # named tunnel name (named mode)
CF_CONFIG="$HOME/.cloudflared/config.yml" # named tunnel config (host binary)
PID_FILE="$ROOT/.caffeinate.pid"
CF_PID_FILE="$ROOT/.cloudflared.pid"      # named tunnel host process pid
CF_LOG="$ROOT/.cloudflared.log"           # named tunnel host process log

# Mode: first arg wins, then TUNNEL env var, else "named".
TUNNEL="${1:-${TUNNEL:-named}}"

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

# 3. Cloudflare tunnel --------------------------------------------------------
case "$TUNNEL" in

  named)
    # Permanent domain via the host cloudflared binary + ~/.cloudflared/config.yml.
    # config.yml maps hostname -> http://localhost:3000, so nothing else to wire.
    if ! command -v cloudflared >/dev/null 2>&1; then
      log "ERROR: 'cloudflared' not found on PATH. Install it (brew install cloudflared)"
      log "or run the throwaway tunnel instead: ./start.sh quick"
      exit 1
    fi
    if [[ ! -f "$CF_CONFIG" ]]; then
      log "ERROR: missing $CF_CONFIG (the named tunnel config)."
      log "Run ./start.sh quick for a throwaway URL, or restore the config."
      exit 1
    fi

    HOSTNAME_="$(grep -oE 'hostname: *[^ ]+' "$CF_CONFIG" | head -1 | awk '{print $2}')"

    # Skip if this named tunnel is already connected (avoid duplicate connectors).
    if pgrep -f "cloudflared.*run ${CF_TUNNEL}" >/dev/null 2>&1; then
      log "named tunnel '${CF_TUNNEL}' already running"
    else
      log "starting Cloudflare named tunnel '${CF_TUNNEL}' in the background..."
      nohup cloudflared tunnel --config "$CF_CONFIG" run "$CF_TUNNEL" \
        >"$CF_LOG" 2>&1 &
      echo $! > "$CF_PID_FILE"
      # Wait for at least one edge connection to register.
      for _ in $(seq 1 30); do
        grep -q "Registered tunnel connection" "$CF_LOG" 2>/dev/null && break
        sleep 1
      done
    fi

    echo
    if grep -q "Registered tunnel connection" "$CF_LOG" 2>/dev/null; then
      log "Done. Permanent URL:"
      printf '\n    \033[1;36mhttps://%s\033[0m\n\n' "${HOSTNAME_:-idaten.williamsu.me}"
      log "Run ./stop.sh to tear it all down. Tunnel logs: $CF_LOG"
    else
      log "Tunnel started but no edge connection registered yet. Check logs:"
      log "  tail -f $CF_LOG"
    fi
    ;;

  quick)
    # Throwaway random trycloudflare URL via a cloudflared Docker container.
    # host.docker.internal lets the container reach the app on the host's :3000.
    log "starting Cloudflare quick tunnel (throwaway URL)..."
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
    ;;

  *)
    log "ERROR: unknown tunnel mode '$TUNNEL' (use 'named' or 'quick')"
    exit 1
    ;;
esac
