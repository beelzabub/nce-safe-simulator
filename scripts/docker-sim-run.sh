#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

if docker inspect nce &>/dev/null; then
  echo "Stopping and removing existing 'nce' container..."
  docker rm -f nce
fi

: "${GITLAB_TOKEN:?Set GITLAB_TOKEN before running (the mounted config.json no longer carries the token)}"

# AWS credentials for in-app deploys (S3/CloudFront, ECS, EKS — issue #225).
# The container runs as root, so boto3 reads /root/.aws; mount the host's creds
# read-only rather than baking them into the image. Skipped when the host has no
# ~/.aws so the sim still runs for non-deploy use.
AWS_MOUNT=()
if [ -d "${HOME}/.aws" ]; then
  AWS_MOUNT=(-v "${HOME}/.aws:/root/.aws:ro")
fi

echo "Starting nce-safe-simulator..."
docker run -d --rm \
  --name nce \
  -p 80:80 \
  -e GITLAB_TOKEN="$GITLAB_TOKEN" \
  "${AWS_MOUNT[@]}" \
  -v "$PROJECT_ROOT/config.json:/app/config.json" \
  -v "$PROJECT_ROOT/reports:/app/reports" \
  nce-safe-simulator

echo "Container started. Listening on http://localhost:80"
