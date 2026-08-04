#!/bin/bash
# Capture the frontend's npm dependency cache per architecture and upload it to
# this project's generic package registry as package `npm-cache` (issue #271) —
# so the frontend-builder image stage installs with an OFFLINE
# `npm ci --offline`, never from registry.npmjs.org, and an enclave lift
# (scripts/enclave-export.sh) carries the cache automatically.
#
# npm's cache is content-addressed, so capturing `npm ci` on both arches into
# the SAME cache dir merges cleanly and picks up the per-arch optional platform
# binaries (@esbuild/*, @rollup/*). One gzipped cache (npm-cache.tar.gz) plus a
# manifest-npm.txt (sorted resolved tarball URLs from the lockfile, for
# capture<->fetch parity) and a capture-info.txt (source file, full sha256,
# capture date) go to the generic package npm-cache/<version>. The Dockerfile
# fetches the tarball, unpacks it, and runs:
#   npm ci --offline --cache /tmp/npm-cache --no-audit --no-fund
#
# The version is CONTENT-ADDRESSED (issue #296): the first 12 hex of
# sha256(frontend/package-lock.json) — derived identically by the Dockerfile
# at build time, so there is no version variable to bump and no way to drift.
# A lockfile committed without its capture 404s the very next image build;
# re-capturing an unchanged lockfile is a no-op (skipped unless --force). Run
# via `make capture-npm`, or directly:
#
# Usage:
#   scripts/capture-npm-cache.sh [-v VERSION] [-a "amd64 arm64"] [-o DIR] [--no-upload] [--force]
#     -v VERSION    package version to publish (default: content hash —
#                   sha256(frontend/package-lock.json) first 12 hex)
#     -a ARCHES     space-separated docker arches (default: "amd64 arm64")
#     -o DIR        staging dir for the captured files (default: mktemp)
#     --no-upload   capture only; skip the registry upload
#     --force       capture + upload even if the version is already published
#
# Requirements: docker (for non-native arches: qemu binfmt —
#   docker run --privileged --rm tonistiigi/binfmt --install arm64), and
#   GITLAB_TOKEN with api scope for the upload step. The target project is
#   derived from this clone's origin remote via scripts/pkg-project-url.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_DIR/frontend"
BASE_IMAGE=node:20-slim             # matches the frontend-builder / dev stages

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
[ -f "$FRONTEND_DIR/package-lock.json" ] || {
  echo "ERROR: frontend/package-lock.json not found" >&2; exit 1; }
# Content-addressed default: the same derivation the Dockerfile's
# frontend-builder stage runs at build time — the lockfile IS the version.
[ -n "$VERSION" ] || VERSION="$(sha256sum "$FRONTEND_DIR/package-lock.json" | cut -c1-12)"
[ -n "$OUTDIR" ] || OUTDIR="$(mktemp -d /tmp/npm-cache.XXXXXX)"
mkdir -p "$OUTDIR/npm-cache"
OUTDIR="$(cd "$OUTDIR" && pwd)"
log() { echo "==> $*"; }

# Idempotence: version == content hash, so an already-published version is
# guaranteed identical — skip the whole capture unless --force. (Anonymous
# pull is enabled on the registry, so the probe needs no token.)
API="$("$SCRIPT_DIR/pkg-project-url.sh")"
if [ "$FORCE" = 0 ] && [ "$UPLOAD" = 1 ]; then
  if curl -fsSo /dev/null "$API/packages/generic/npm-cache/$VERSION/npm-cache.tar.gz" --head; then
    log "npm-cache/$VERSION already published — nothing to do (--force to re-capture)"
    exit 0
  fi
fi

# One container per arch: copy the lockfile into a writable workdir, run
# `npm ci` pointed at the shared /out/npm-cache (content-addressed — both
# arches merge into it), and discard node_modules. The per-arch optional
# esbuild/rollup binaries only download when npm runs under that arch, which is
# why the capture runs on each arch (qemu for the non-native one).
CAPTURE=$(cat <<'EOS'
set -eu
ARCH=$(dpkg --print-architecture)
cp /src/package.json /src/package-lock.json /work/
cd /work
npm ci --cache /out/npm-cache --no-audit --no-fund >/dev/null 2>&1
echo "  $ARCH: cache populated ($(du -sh /out/npm-cache | cut -f1))"
EOS
)

for arch in $ARCHES; do
  log "Capturing $arch npm cache in $BASE_IMAGE (qemu if non-native)..."
  docker run --rm --platform "linux/$arch" \
    -v "$OUTDIR/npm-cache:/out/npm-cache" \
    -v "$FRONTEND_DIR:/src:ro" \
    --tmpfs /work:exec \
    "$BASE_IMAGE" bash -c "$CAPTURE"
done

# Manifest: the resolved registry tarball URLs the lockfile pins — a
# deterministic record of what the offline cache must be able to serve.
python3 - "$FRONTEND_DIR/package-lock.json" > "$OUTDIR/manifest-npm.txt" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))
urls = sorted(
    p["resolved"] for p in lock.get("packages", {}).values()
    if isinstance(p, dict) and p.get("resolved", "").startswith("http")
)
print("\n".join(urls))
PY

tar czf "$OUTDIR/npm-cache.tar.gz" -C "$OUTDIR/npm-cache" .
log "Captured npm-cache.tar.gz ($(du -sh "$OUTDIR/npm-cache.tar.gz" | cut -f1)), $(wc -l < "$OUTDIR/manifest-npm.txt") pinned tarballs in manifest"

# capture-info.txt: the registry UI shows only the opaque hash version — name
# the source file, its full sha256, and the capture date for humans.
{
  echo "source: frontend/package-lock.json"
  echo "sha256: $(sha256sum "$FRONTEND_DIR/package-lock.json" | cut -d' ' -f1)"
  echo "captured: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "arches: $ARCHES"
} > "$OUTDIR/capture-info.txt"

if [ "$UPLOAD" = 1 ]; then
  : "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope) to upload, or pass --no-upload}"
  log "Uploading to $API/packages/generic/npm-cache/$VERSION/ ..."
  for f in "$OUTDIR/npm-cache.tar.gz" "$OUTDIR/manifest-npm.txt" "$OUTDIR/capture-info.txt"; do
    name="$(basename "$f")"
    curl -fsS --header "PRIVATE-TOKEN: $GITLAB_TOKEN" --upload-file "$f" \
      "$API/packages/generic/npm-cache/$VERSION/$name" > /dev/null
    echo "  uploaded $name"
  done
  log "Done. npm-cache/$VERSION published — commit frontend/package-lock.json (the Dockerfile derives this version from its hash) and push AFTER this upload."
else
  log "Skipped upload (--no-upload). Files staged in $OUTDIR"
fi
