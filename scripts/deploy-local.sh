#!/usr/bin/env bash
# Full single-box bring-up for nce-safe-sim.com:
#
#   internet :443/:80  ->  caddy (Let's Encrypt TLS)  ->  nce-safe-sim :80 (uvicorn)
#
# Both containers run with --restart unless-stopped, so they come back after a
# reboot (the instance is on an EventBridge start/stop schedule to control cost;
# while it is stopped the site is simply down — by design).
#
# Idempotent: safe to re-run. For code-only updates use redeploy.sh, which
# leaves Caddy (and its issued certs) untouched.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

NETWORK="nce-net"

# Ensure the shared Docker network exists (idempotent — created on first run).
docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"

# 1. Build the image and (re)create the internal app container on nce-net.
"$SCRIPT_DIR/redeploy.sh"

# 2. Caddy — TLS terminator / reverse proxy on 80+443.
#    caddy_data persists issued certs across restarts (no needless re-issue).
echo "==> (Re)starting Caddy..."
docker rm -f caddy >/dev/null 2>&1 || true
docker run -d --name caddy --restart unless-stopped \
  --network "$NETWORK" \
  -p 80:80 -p 443:443 \
  -v "$PROJECT_ROOT/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  -v caddy_data:/data \
  -v caddy_config:/config \
  caddy:2-alpine

echo "==> Stack up. https://nce-safe-sim.com"
