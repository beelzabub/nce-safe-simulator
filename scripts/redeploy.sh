#!/usr/bin/env bash
# Iterative redeploy: rebuild the simulator image and swap the running app
# container in place. Caddy (TLS + domain) keeps running untouched — only the
# app container is recreated, so the live site at https://nce-safe-sim.com
# reflects the latest code within ~1 minute.
#
# Use this for code changes. For a first-time / full bring-up (including Caddy)
# use deploy-local.sh instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

IMAGE="nce-safe-simulator:latest"
NETWORK="nce-net"
APP="nce-safe-sim"

echo "==> Building image ($IMAGE)..."
docker build -t "$IMAGE" .

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"

echo "==> Recreating app container ($APP)..."
docker rm -f "$APP" >/dev/null 2>&1 || true
docker run -d --name "$APP" --restart unless-stopped \
  --network "$NETWORK" \
  -e GITLAB_TOKEN="${GITLAB_TOKEN:-}" \
  -v "$PROJECT_ROOT/config.json:/app/config.json:ro" \
  -v "$PROJECT_ROOT/reports:/app/reports" \
  "$IMAGE"

docker image prune -f >/dev/null 2>&1 || true
echo "==> Done. Live at https://nce-safe-sim.com (Caddy untouched)."
