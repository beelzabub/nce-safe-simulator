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
# manifest-<arch>.txt (sorted wheel basenames, for capture<->fetch parity) and
# a capture-info.txt (source file, full sha256, capture date — the registry UI
# shows only the opaque hash version) go to the generic package
# pip-wheels/<version>. The Dockerfile fetches the arch tarball, unpacks it,
# and runs:
#   pip install --no-index --find-links /tmp/wheels -r requirements.lock
#
# The version is CONTENT-ADDRESSED (issue #296): the first 12 hex of
# sha256(requirements.lock) — derived identically by the Dockerfile at build
# time, so there is no version variable to bump and no way to drift. A lock
# committed without its capture 404s the very next image build; re-capturing
# an unchanged lock is a no-op (the version already exists — skipped unless
# --force). Run via `make capture-pip` (which also recompiles the lock), or
# directly:
#
# Usage:
#   scripts/capture-pip-wheels.sh [-v VERSION] [-a "amd64 arm64"] [-o DIR] [--no-upload] [--force]
#     -v VERSION    package version to publish (default: content hash —
#                   sha256(requirements.lock) first 12 hex; override only to
#                   re-publish for a historical scheme)
#     -a ARCHES     space-separated docker arches (default: "amd64 arm64")
#     -o DIR        staging dir for the captured files (default: mktemp)
#     --no-upload   capture + manifests only; skip the registry upload
#     --force       capture + upload even if the version is already published
#
# Requirements: docker (for non-native arches: qemu binfmt —
#   docker run --privileged --rm tonistiigi/binfmt --install arm64), and
#   GITLAB_TOKEN with api scope for the upload step. The target project is
#   derived from this clone's origin remote via scripts/pkg-project-url.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_IMAGE=python:3.11-slim         # matches runtime / diagram-builder stages

VERSION=""
ARCHES="amd64 arm64"
OUTDIR=""
UPLOAD=1
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    -v) VERSION="$2"; shift 2 ;;
    -a) ARCHES="$2"; shift 2 ;;
    -o) OUTDIR="$2"; shift 2 ;;
    --no-upload) UPLOAD=0; shift ;;
    --force) FORCE=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
[ -f "$REPO_DIR/requirements.lock" ] || {
  echo "ERROR: requirements.lock not found — compile it first" >&2
  echo "  (make capture-pip recompiles it; or pip-compile in python:3.11-slim)" >&2
  exit 1; }
# Content-addressed default: the same derivation the Dockerfile install sites
# run at build time — the lock file IS the version.
[ -n "$VERSION" ] || VERSION="$(sha256sum "$REPO_DIR/requirements.lock" | cut -c1-12)"
[ -n "$OUTDIR" ] || OUTDIR="$(mktemp -d /tmp/pip-wheels.XXXXXX)"
mkdir -p "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"
log() { echo "==> $*"; }

# Idempotence: version == content hash, so an already-published version is
# guaranteed identical — skip the whole capture unless --force. (Anonymous
# pull is enabled on the registry, so the probe needs no token.)
API="$("$SCRIPT_DIR/pkg-project-url.sh")"
if [ "$FORCE" = 0 ] && [ "$UPLOAD" = 1 ]; then
  published=1
  for arch in $ARCHES; do
    curl -fsSo /dev/null "$API/packages/generic/pip-wheels/$VERSION/pip-wheels-$arch.tar.gz" \
      --head || { published=0; break; }
  done
  if [ "$published" = 1 ]; then
    log "pip-wheels/$VERSION already published for: $ARCHES — nothing to do (--force to re-capture)"
    exit 0
  fi
fi

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

# capture-info.txt: the registry UI shows only the opaque hash version — name
# the source file, its full sha256, and the capture date for humans.
{
  echo "source: requirements.lock"
  echo "sha256: $(sha256sum "$REPO_DIR/requirements.lock" | cut -d' ' -f1)"
  echo "captured: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "arches: $ARCHES"
} > "$OUTDIR/capture-info.txt"

if [ "$UPLOAD" = 1 ]; then
  : "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope) to upload, or pass --no-upload}"
  log "Uploading to $API/packages/generic/pip-wheels/$VERSION/ ..."
  for f in "$OUTDIR"/pip-wheels-*.tar.gz "$OUTDIR"/manifest-*.txt "$OUTDIR/capture-info.txt"; do
    name="$(basename "$f")"
    curl -fsS --header "PRIVATE-TOKEN: $GITLAB_TOKEN" --upload-file "$f" \
      "$API/packages/generic/pip-wheels/$VERSION/$name" > /dev/null
    echo "  uploaded $name"
  done
  log "Done. pip-wheels/$VERSION published — commit requirements.lock (the Dockerfile derives this version from its hash) and push AFTER this upload."
else
  log "Skipped upload (--no-upload). Files staged in $OUTDIR"
fi
