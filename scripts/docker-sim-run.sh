#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if docker inspect nce &>/dev/null; then
  echo "Stopping and removing existing 'nce' container..."
  docker rm -f nce
fi

echo "Starting nce-safe-simulator..."
docker run -d --rm \
  --name nce \
  -p 80:80 \
  -v "$PROJECT_ROOT/config.json:/app/config.json" \
  -v "$PROJECT_ROOT/reports:/app/reports" \
  nce-safe-simulator

echo "Container started. Listening on http://localhost:80"
