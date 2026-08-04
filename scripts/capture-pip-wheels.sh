#!/bin/bash
# Capture the full pip wheel closure (requirements.lock) per architecture and
# upload it to this project's generic package registry as package `pip-wheels`
# (issue #271) — so the runtime and diagram-builder image stages resolve Python
# packages with an OFFLINE `pip install --no-index`, never from pypi.org /
# files.pythonhosted.org, and an enclave lift (scripts/enclave-export.sh)
# carries the wheelhouse automatically.
#
# The whole requirements.txt tree resolves to a pure-wheel closure
# (`--only-binary=:all:` succeeds end-to-end; no sdists), so capture is a plain
# download-and-upload — nothing is ever built, on either side of the boundary.
# One gzipped wheelhouse per arch (pip-wheels-<arch>.tar.gz) plus a
# manifest-<arch>.txt (sorted wheel basenames, for capture<->fetch parity) go
# to the generic package pip-wheels/<version>. The Dockerfile fetches the arch
# tarball, unpacks it, and runs:
#   pip install --no-index --find-links /tmp/wheels -r requirements.lock
# Refresh whenever requirements.lock changes, then bump PIP_WHEELS_VERSION in
# the Dockerfile.
#
# Usage:
#   scripts/capture-pip-wheels.sh [-v VERSION] [-a "amd64 arm64"] [-o DIR] [--no-upload]
#     -v VERSION    package version to publish (default: today, YYYY.MM.DD)
#     -a ARCHES     space-separated docker arches (default: "amd64 arm64")
#     -o DIR        staging dir for the captured files (default: mktemp)
#     --no-upload   capture + manifests only; skip the registry upload
#
# Requirements: docker (for non-native arches: qemu binfmt —
#   docker run --privileged --rm tonistiigi/binfmt --install arm64), and
#   GITLAB_TOKEN with api scope for the upload step. The target project is
#   derived from this clone's origin remote via scripts/pkg-project-url.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_IMAGE=python:3.11-slim         # matches runtime / diagram-builder stages

VERSION="$(date +%Y.%m.%d)"
ARCHES="amd64 arm64"
OUTDIR=""
UPLOAD=1
while [ $# -gt 0 ]; do
  case "$1" in
    -v) VERSION="$2"; shift 2 ;;
    -a) ARCHES="$2"; shift 2 ;;
    -o) OUTDIR="$2"; shift 2 ;;
    --no-upload) UPLOAD=0; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -f "$REPO_DIR/requirements.lock" ] || {
  echo "ERROR: requirements.lock not found — compile it first" >&2
  echo "  (pip-compile requirements.txt -o requirements.lock, in python:3.11)" >&2
  exit 1; }
[ -n "$OUTDIR" ] || OUTDIR="$(mktemp -d /tmp/pip-wheels.XXXXXX)"
mkdir -p "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"
log() { echo "==> $*"; }

# One container per arch: download the full locked closure as wheels only, emit
# a sorted manifest, and tar the wheelhouse. --only-binary=:all: is a hard gate
# — if any package lacks a wheel for this arch it fails loudly here rather than
# silently building from an sdist at image-build time.
CAPTURE=$(cat <<'EOS'
set -eu
export PIP_DISABLE_PIP_VERSION_CHECK=1
ARCH=$(dpkg --print-architecture)
mkdir -p /wheels
pip download --only-binary=:all: --no-cache-dir \
  -r /lock/requirements.lock -d /wheels >/dev/null
ls /wheels | sort > "/out/manifest-$ARCH.txt"
tar czf "/out/pip-wheels-$ARCH.tar.gz" -C /wheels .
echo "  $ARCH: $(wc -l < "/out/manifest-$ARCH.txt") wheels, $(du -sh /wheels | cut -f1)"
EOS
)

for arch in $ARCHES; do
  log "Capturing $arch wheel closure in $BASE_IMAGE (qemu if non-native)..."
  docker run --rm --platform "linux/$arch" \
    -v "$OUTDIR:/out" \
    -v "$REPO_DIR/requirements.lock:/lock/requirements.lock:ro" \
    "$BASE_IMAGE" bash -c "$CAPTURE"
done

log "Captured $(ls "$OUTDIR"/*.tar.gz | wc -l) wheelhouse tarball(s), $(du -sh "$OUTDIR" | cut -f1) total:"
ls "$OUTDIR"/pip-wheels-*.tar.gz "$OUTDIR"/manifest-*.txt

if [ "$UPLOAD" = 1 ]; then
  : "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope) to upload, or pass --no-upload}"
  API="$("$SCRIPT_DIR/pkg-project-url.sh")"
  log "Uploading to $API/packages/generic/pip-wheels/$VERSION/ ..."
  for f in "$OUTDIR"/pip-wheels-*.tar.gz "$OUTDIR"/manifest-*.txt; do
    name="$(basename "$f")"
    curl -fsS --header "PRIVATE-TOKEN: $GITLAB_TOKEN" --upload-file "$f" \
      "$API/packages/generic/pip-wheels/$VERSION/$name" > /dev/null
    echo "  uploaded $name"
  done
  log "Done. Set PIP_WHEELS_VERSION=$VERSION in the Dockerfile."
else
  log "Skipped upload (--no-upload). Files staged in $OUTDIR"
fi
