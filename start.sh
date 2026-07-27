#!/usr/bin/env bash
#
# Start Idaten: test gate -> Docker stack -> optional public tunnel.
#
#   1. Keeps the machine awake        (caffeinate; macOS only, skipped elsewhere)
#   2. Runs the test gate             (backend pytest + frontend vitest; SKIP_TESTS=1 to bypass)
#   3. Brings up the Docker stack     (docker compose up -d --build)
#   4. Starts a Cloudflare tunnel     (see the three modes below)
#
# Three tunnel modes:
#
#   named  (default) - a permanent, bookmarkable domain on YOUR Cloudflare zone.
#                      Uses the host `cloudflared` binary + ~/.cloudflared/config.yml;
#                      the tunnel name is read from that config's `tunnel:` key
#                      (override with the CF_TUNNEL env var).
#                      One-time setup on a fresh machine:
#                        1. install cloudflared (brew install cloudflared / apt)
#                        2. cloudflared tunnel login
#                        3. cloudflared tunnel create <name>
#                        4. cloudflared tunnel route dns <name> app.your-domain.com
#                        5. write ~/.cloudflared/config.yml:
#                             tunnel: <name>
#                             credentials-file: /path/to/<tunnel-id>.json
#                             ingress:
#                               - hostname: app.your-domain.com
#                                 service: http://localhost:3000
#                               - service: http_status:404
#
#   quick            - a throwaway random https://<random>.trycloudflare.com URL.
#                      Uses a cloudflared Docker container. No domain, config, or
#                      Cloudflare account needed. Good for one-off testing; the
#                      URL changes every run.
#
#   none             - no tunnel: localhost / LAN only. The right mode for a
#                      self-hosted box that is never exposed to the internet.
#
# Pick a mode with the TUNNEL env var or the first argument:
#
#   ./start.sh              # named tunnel (your permanent domain)
#   ./start.sh quick        # random trycloudflare URL
#   ./start.sh none         # no tunnel
#
# Stop:   ./stop.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

APP_PORT=3000
CF_NAME="garmin-bot-cloudflared"          # docker container name (quick mode)
CF_CONFIG="$HOME/.cloudflared/config.yml" # named tunnel config (host binary)
# Named-tunnel name: CF_TUNNEL env override, else the config's `tunnel:` key.
CF_TUNNEL="${CF_TUNNEL:-$(grep -oE '^tunnel: *[^ ]+' "$CF_CONFIG" 2>/dev/null | awk '{print $2}' || true)}"
PID_FILE="$ROOT/.caffeinate.pid"
CF_PID_FILE="$ROOT/.cloudflared.pid"      # named tunnel host process pid
CF_LOG="$ROOT/.cloudflared.log"           # named tunnel host process log

# Mode: first arg wins, then TUNNEL env var, else "named".
TUNNEL="${1:-${TUNNEL:-named}}"

DOCKER="$(command -v docker || echo /usr/local/bin/docker)"

log() { printf '\033[1;33m[start]\033[0m %s\n' "$*"; }

# 1. Keep the machine awake (macOS only) --------------------------------------
# -d display, -i idle system, -m disk, -s while on AC power. Runs until killed.
if ! command -v caffeinate >/dev/null 2>&1; then
  log "no caffeinate on this OS - skipping keep-awake (a server stays up anyway)"
elif [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  log "caffeinate already running (pid $(cat "$PID_FILE"))"
else
  caffeinate -dims &
  echo $! > "$PID_FILE"
  log "caffeinate started (pid $(cat "$PID_FILE")) - machine will not idle-sleep"
fi

# 2. Test gate ----------------------------------------------------------------
# This script is the one chokepoint every change passes through, so it is this
# repo's CI: a red test can never reach the live app. Rationale + trade-offs:
# docs/adr/0001-start-sh-is-the-test-gate.md. Skip only for a deliberate
# hotfix with SKIP_TESTS=1 ./start.sh.
if [[ "${SKIP_TESTS:-0}" == "1" ]]; then
  log "SKIP_TESTS=1 - skipping the test gate (hotfix mode)"
else
  log "test gate: backend pytest..."
  # `python -m pytest`, not `.venv/bin/pytest`: console-script shebangs bake
  # the venv's absolute path and break if the repo directory is ever renamed.
  (cd "$ROOT/backend" && .venv/bin/python -m pytest -q)
  log "test gate: frontend vitest..."
  (cd "$ROOT/frontend" && npm test --silent)
  log "test gate passed"
fi

# 3. Docker stack -------------------------------------------------------------
log "building + starting Docker stack..."
"$DOCKER" compose up -d --build

# 4. Cloudflare tunnel --------------------------------------------------------
case "$TUNNEL" in

  named)
    # Permanent domain via the host cloudflared binary + ~/.cloudflared/config.yml.
    # config.yml maps hostname -> http://localhost:3000, so nothing else to wire.
    if ! command -v cloudflared >/dev/null 2>&1; then
      log "ERROR: 'cloudflared' not found on PATH. Install it (brew install cloudflared),"
      log "or use './start.sh quick' (throwaway URL) / './start.sh none' (no tunnel)."
      exit 1
    fi
    if [[ ! -f "$CF_CONFIG" ]]; then
      log "ERROR: missing $CF_CONFIG (the named tunnel config)."
      log "One-time setup is documented in this script's header. Meanwhile:"
      log "'./start.sh quick' (throwaway URL) or './start.sh none' (no tunnel)."
      exit 1
    fi
    if [[ -z "$CF_TUNNEL" ]]; then
      log "ERROR: no tunnel name - add a 'tunnel:' key to $CF_CONFIG or set CF_TUNNEL."
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
      printf '\n    \033[1;36mhttps://%s\033[0m\n\n' "${HOSTNAME_:-<hostname in $CF_CONFIG>}"
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

  none)
    echo
    log "Done (no tunnel). App: http://localhost:${APP_PORT}"
    log "Run ./stop.sh to tear it all down."
    ;;

  *)
    log "ERROR: unknown tunnel mode '$TUNNEL' (use 'named', 'quick', or 'none')"
    exit 1
    ;;
esac
