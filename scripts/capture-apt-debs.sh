#!/bin/bash
# Capture the .deb closures the Dockerfile installs from apt, per layer and per
# architecture, and upload them to this project's generic package registry as
# package `apt-debs` (issue #269) — so image builds resolve system packages
# from the project registry instead of deb.debian.org / deb.nodesource.com,
# and an enclave lift (scripts/enclave-export.sh) carries them automatically.
#
# Layers captured (must mirror the Dockerfile's apt layers and their flags):
#   graphviz    — diagram-builder stage: `graphviz` closure on fresh python:3.11-slim
#   weasyprint  — runtime stage: libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core
#                 closure on fresh python:3.11-slim
#   dev         — dev stage: make git jq graphviz curl ca-certificates + NodeSource
#                 nodejs 20.x, computed ON TOP of the runtime state (weasyprint
#                 closure installed), matching `FROM runtime AS dev`
#
# Each layer/arch yields a manifest-<layer>-<arch>.txt (sorted deb basenames);
# the Dockerfile fetches the manifest and installs exactly those files via
# scripts/fetch-apt-debs.py + an offline `apt-get install /tmp/debs/*.deb`
# (apt orders Pre-Depends; no indexes → no mirror). Refresh this package
# whenever the base
# image moves to a new Debian release or the dev toolchain list changes, then
# bump APT_DEBS_VERSION in the Dockerfile.
#
# Usage:
#   scripts/capture-apt-debs.sh [-v VERSION] [-a "amd64 arm64"] [-o DIR] [--no-upload]
#     -v VERSION    package version to publish (default: today, YYYY.MM.DD)
#     -a ARCHES     space-separated dpkg architectures (default: "amd64 arm64")
#     -o DIR        staging dir for the captured files (default: mktemp)
#     --no-upload   capture + manifests only; skip the registry upload
#
# Requirements: docker (for non-native arches: qemu binfmt —
#   docker run --privileged --rm tonistiigi/binfmt --install amd64), and
#   GITLAB_TOKEN with api scope for the upload step. The target project is
#   derived from this clone's origin remote via scripts/pkg-project-url.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE_MAJOR=20                       # matches the frontend-builder / dev stages
BASE_IMAGE=python:3.11-slim         # matches diagram-builder / runtime stages

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
[ -n "$OUTDIR" ] || OUTDIR="$(mktemp -d /tmp/apt-debs.XXXXXX)"
mkdir -p "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"
log() { echo "==> $*"; }

# The whole per-arch capture runs inside one container: --download-only does
# not change installed state, so the graphviz and weasyprint closures both see
# a pristine image; the weasyprint set is then actually installed so the dev
# closure is computed against the same state the dev stage builds FROM.
CAPTURE=$(cat <<'EOS'
set -eu
ARCH=$(dpkg --print-architecture)
grab() {  # grab <layer> <pkg...> — download closure, manifest, stash debs
  layer=$1; shift
  rm -f /var/cache/apt/archives/*.deb
  apt-get install -y -q --download-only --no-install-recommends "$@" >/dev/null
  # Epoch versions give filenames like git_1%3a2.47.3-..._amd64.deb; '%' is
  # rejected by GitLab's generic-package filename rules and would be treated
  # as percent-encoding in the fetch URL — rename to '__' (dpkg doesn't care).
  for d in /var/cache/apt/archives/*%3a*.deb; do
    [ -e "$d" ] && mv "$d" "${d//%3a/__}"
  done
  ls /var/cache/apt/archives/*.deb | xargs -n1 basename | sort \
    > "/out/manifest-$layer-$ARCH.txt"
  mv /var/cache/apt/archives/*.deb /out/
  echo "  $layer/$ARCH: $(wc -l < "/out/manifest-$layer-$ARCH.txt") debs"
}
apt-get update -q >/dev/null
grab graphviz graphviz
grab weasyprint libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core
# Reach the runtime state, then add NodeSource for the dev layer's nodejs.
apt-get install -y -q --no-install-recommends \
  libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core >/dev/null
mkdir -p /etc/apt/keyrings
python3 -c "import urllib.request as u; u.urlretrieve(
  'https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key',
  '/etc/apt/keyrings/nodesource.asc')"
echo "deb [signed-by=/etc/apt/keyrings/nodesource.asc] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" \
  > /etc/apt/sources.list.d/nodesource.list
echo "Package: nodejs
Pin: origin deb.nodesource.com
Pin-Priority: 600" > /etc/apt/preferences.d/nodesource
apt-get update -q >/dev/null
grab dev make git jq graphviz curl ca-certificates nodejs
EOS
)

for arch in $ARCHES; do
  log "Capturing $arch closures in $BASE_IMAGE (qemu if non-native)..."
  docker run --rm --platform "linux/$arch" -v "$OUTDIR:/out" \
    -e NODE_MAJOR="$NODE_MAJOR" "$BASE_IMAGE" bash -c "$CAPTURE"
done

log "Captured $(ls "$OUTDIR"/*.deb | wc -l) debs, $(du -sh "$OUTDIR" | cut -f1) total, manifests:"
ls "$OUTDIR"/manifest-*.txt

if [ "$UPLOAD" = 1 ]; then
  : "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope) to upload, or pass --no-upload}"
  API="$("$SCRIPT_DIR/pkg-project-url.sh")"
  log "Uploading to $API/packages/generic/apt-debs/$VERSION/ ..."
  for f in "$OUTDIR"/*; do
    name="$(basename "$f")"
    curl -fsS --header "PRIVATE-TOKEN: $GITLAB_TOKEN" --upload-file "$f" \
      "$API/packages/generic/apt-debs/$VERSION/$name" > /dev/null
    echo "  uploaded $name"
  done
  log "Done. Set APT_DEBS_VERSION=$VERSION in the Dockerfile."
else
  log "Skipped upload (--no-upload). Files staged in $OUTDIR"
fi
