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

# --ops (issue #231): build and swap in the ops image variant, which carries
# the CDK deploy toolchain (make, jq, node/cdk, AWS CLI, kubectl, helm) so the
# in-app ECS/EKS Deploy/Destroy buttons work from inside the container. The
# default stays the slim image — the same one that ships to ECR.
BUILD_TARGET=()
if [ "${1:-}" = "--ops" ]; then
  IMAGE="nce-safe-simulator:ops"
  BUILD_TARGET=(--target ops)
fi

# --image REF (issue #309): recreate the container from an image that already
# exists, skipping the build entirely. This is the rollback path — the weekly
# deck build tags the running image before it swaps, and restores it with this
# if the new container fails its health checks. Rebuilding would be useless
# there: the source is unchanged, so it would produce the same bad image.
SKIP_BUILD=""
if [ "${1:-}" = "--image" ]; then
  [ -n "${2:-}" ] || { echo "--image needs an image reference" >&2; exit 2; }
  IMAGE="$2"
  SKIP_BUILD=1
  docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || { echo "==> no such image: $IMAGE" >&2; exit 1; }
  echo "==> Recreating from existing image ($IMAGE) — no build."
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ -z "$SKIP_BUILD" ] && [ "$BRANCH" != "develop" ]; then
  echo "==> NOTE: building from '$BRANCH', not develop. The live site will run" >&2
  echo "          that branch's code — make sure that is intended." >&2
fi

if [ -z "$SKIP_BUILD" ]; then
echo "==> Building image ($IMAGE)..."
docker build "${BUILD_TARGET[@]}" \
  --build-arg VCS_REF="$(git rev-parse --short HEAD)" \
  --build-arg NCE_VERSION="$(git describe --tags --exact-match 2>/dev/null || true)" \
  --build-arg PKG_PROJECT="$(scripts/pkg-project-url.sh)" \
  -t "$IMAGE" .
fi

# Guard (issue #186): never swap the live container for an image that can't
# report its own version. This catches builds made from a branch that predates
# the version support (server/version.py / VERSION absent), which silently ship
# a UI with no version badge. Runs before the container swap, so a bad build
# aborts the deploy instead of going live.
echo "==> Verifying version stamp baked into image..."
# --entrypoint python3 bypasses the image's "NceGitLab.py --serve" entrypoint
# (which would demand a config and exit). tail -n1 keeps just the version line.
BAKED_VERSION="$(docker run --rm --entrypoint python3 "$IMAGE" -c \
  'from server.version import app_version; print(app_version())' 2>/dev/null \
  | tail -n1 | tr -d '[:space:]' || true)"
if [ -z "$BAKED_VERSION" ] || [ "$BAKED_VERSION" = "nce-unknown" ]; then
  echo "ERROR: built image has no resolvable version (got: '${BAKED_VERSION:-<server.version import failed>}')." >&2
  echo "       The source tree is likely missing server/version.py or VERSION —" >&2
  echo "       usually a build from a branch that predates version support." >&2
  echo "       Check out develop (or a branch based on it) and retry. Deploy aborted." >&2
  exit 1
fi
echo "    version: $BAKED_VERSION"

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"

echo "==> Recreating app container ($APP)..."
# Host dirs for the served/persistent volumes — created on first run so the
# bind mounts below survive container recreation (mirrors the cloud EFS layout:
# reports, public/interactive, public/exports, quarto-site, uploads). logs/ is
# box-only (the cloud ships logs to CloudWatch instead). Only individual public/
# subdirs are mounted so the image-baked public/app and public/architecture stay
# intact. uploads/ and public/exports hold UI import/export temp files (age-based
# retention handled in-app); mounting them keeps generated exports from being
# lost on every redeploy.
mkdir -p reports logs quarto-site public/interactive public/exports uploads

# The app container runs as uid 1000 (`USER app`, #304) — the bind-mounted
# dirs and the UI-writable config.json (PUT /api/config/full) must be
# writable by that uid, recursively, so existing root-created files can be
# rewritten in place.
if ! chown -R 1000:1000 reports logs quarto-site public/interactive \
      public/exports uploads config.json 2>/dev/null; then
  echo "    WARNING: could not chown mounts to uid 1000 — in-container writes" >&2
  echo "             (reports, logs, config edits) may fail. Re-run as root." >&2
fi

# AWS credentials for in-app deploys (S3/CloudFront, ECS, EKS — issue #225),
# mounted read-only rather than baked into the image (which would leave IAM
# keys in image layers, incl. anything pushed to ECR). Skipped when the host
# has no ~/.aws so the site still comes up for non-deploy use.
#   - ops variant runs as root: mount the host's ~/.aws at /root/.aws as-is.
#   - slim runs as uid 1000 (#304) and the host creds are typically 600
#     root-only, so stage a uid-1000-owned copy and mount that at
#     /home/app/.aws. Re-staged on every redeploy, so host cred rotations
#     propagate on the next deploy.
AWS_STAGE=/var/lib/nce-safe-sim/aws
AWS_MOUNT=()
if [ -d "${HOME}/.aws" ]; then
  if [ "${#BUILD_TARGET[@]}" -gt 0 ]; then
    AWS_MOUNT=(-v "${HOME}/.aws:/root/.aws:ro")
    echo "    mounting ${HOME}/.aws -> /root/.aws (read-only) for in-app AWS deploys"
  elif install -d -m 700 -o 1000 -g 1000 "$AWS_STAGE" 2>/dev/null; then
    for f in "${HOME}/.aws/config" "${HOME}/.aws/credentials"; do
      [ -f "$f" ] && install -m 600 -o 1000 -g 1000 "$f" "$AWS_STAGE/"
    done
    AWS_MOUNT=(-v "$AWS_STAGE:/home/app/.aws:ro")
    echo "    staged ${HOME}/.aws -> $AWS_STAGE (uid 1000) -> /home/app/.aws (read-only)"
  else
    echo "    WARNING: could not stage ${HOME}/.aws for uid 1000 (need root);" >&2
    echo "             in-app AWS deploys will be unavailable this run." >&2
  fi
fi

# Ops variant only (#231): hand the container the host docker daemon so the
# first-time ECS deploy can build+push the initial image (empty-repo branch:
# infra at desired_count=0 → push → scale up). The slim image has no docker
# CLI, so the socket is deliberately not offered to it.
DOCKER_MOUNT=()
if [ "${#BUILD_TARGET[@]}" -gt 0 ] && [ -S /var/run/docker.sock ]; then
  DOCKER_MOUNT=(-v /var/run/docker.sock:/var/run/docker.sock)
  echo "    mounting /var/run/docker.sock for in-app first-time image builds"
fi

# config.json mounts read-write: the web UI's settings editor saves through
# PUT /api/config/full, which writes the file in place. The bind mount means
# UI edits land in the host file too, so they survive redeploys.
docker rm -f "$APP" >/dev/null 2>&1 || true
docker run -d --name "$APP" --restart unless-stopped \
  --network "$NETWORK" \
  -e GITLAB_TOKEN="${GITLAB_TOKEN:-}" \
  "${AWS_MOUNT[@]}" \
  "${DOCKER_MOUNT[@]}" \
  -v "$PROJECT_ROOT/config.json:/app/config.json" \
  -v "$PROJECT_ROOT/reports:/app/reports" \
  -v "$PROJECT_ROOT/quarto-site:/app/quarto-site" \
  -v "$PROJECT_ROOT/public/interactive:/app/public/interactive" \
  -v "$PROJECT_ROOT/public/exports:/app/public/exports" \
  -v "$PROJECT_ROOT/uploads:/app/uploads" \
  -v "$PROJECT_ROOT/logs:/app/logs" \
  "$IMAGE"

docker image prune -f >/dev/null 2>&1 || true
echo "==> Done. Live at https://nce-safe-sim.com (Caddy untouched)."
