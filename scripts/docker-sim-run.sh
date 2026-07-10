#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# --ops (issue #231): build and run the ops image variant, which carries the
# CDK deploy toolchain (make, jq, node/cdk, AWS CLI, kubectl, helm) so the
# in-app ECS/EKS Deploy/Destroy buttons work from inside the container.
# Default remains the slim image — the one that ships to ECR.
IMAGE=nce-safe-simulator
BUILD_TARGET=""
if [ "${1:-}" = "--ops" ]; then
  IMAGE=nce-safe-simulator:ops
  BUILD_TARGET="--target ops"
  shift
fi

if [ "${1:-}" = "--build" ] || [ -n "$BUILD_TARGET" ]; then
  echo "Building $IMAGE..."
  # shellcheck disable=SC2086  # BUILD_TARGET is intentionally word-split
  docker build $BUILD_TARGET \
    --build-arg VCS_REF="$(git rev-parse --short HEAD)" \
    --build-arg NCE_VERSION="$(git describe --tags --exact-match 2>/dev/null || true)" \
    -t "$IMAGE" .
fi

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

echo "Starting $IMAGE..."
docker run -d --rm \
  --name nce \
  -p 80:80 \
  -e GITLAB_TOKEN="$GITLAB_TOKEN" \
  "${AWS_MOUNT[@]}" \
  -v "$PROJECT_ROOT/config.json:/app/config.json" \
  -v "$PROJECT_ROOT/reports:/app/reports" \
  "$IMAGE"

echo "Container started. Listening on http://localhost:80"
