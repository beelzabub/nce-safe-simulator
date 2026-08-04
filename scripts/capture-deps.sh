#!/usr/bin/env bash
# Vendored-dependency refresh orchestrator (issue #296) — the engine behind
# `make capture-deps` / `capture-pip` / `capture-npm` / `capture-apt`.
#
# The developer loop: edit a dependency input (requirements.txt, `npm
# install` in frontend/, or the layer lists in capture-apt-debs.sh), run the
# matching make target, commit. For pip/npm the closures are
# CONTENT-ADDRESSED — the registry version is the first 12 hex of sha256
# over the lock file, derived identically here and by the Dockerfile at
# build time — so the commit is just the lock diff: no version to bump, and
# a lock pushed without its capture 404s the MR pipeline's image build (the
# drift guard is the pipeline itself). Capture BEFORE pushing.
#
# Modes:
#   pip   recompile requirements.lock (python:3.11-slim, pinned pip-tools),
#         then publish its wheel closure if the hash version is not yet in
#         the registry (capture-pip-wheels.sh self-skips otherwise)
#   npm   publish the npm cache for frontend/package-lock.json if new
#   apt   re-capture the dated apt-debs closure, then print the
#         APT_DEBS_VERSION + capture-input stamp values to set in the
#         Dockerfile (apt has no lock file to content-address)
#   all   pip + npm (the common inner loop; apt changes are rare and need
#         the Dockerfile edit anyway)
#
# Requirements (preflighted): docker; qemu binfmt for the non-native arch;
# GITLAB_TOKEN with api scope (uploads). The target project is derived from
# this clone's origin remote via scripts/pkg-project-url.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MODE="${1:-all}"
case "$MODE" in pip|npm|apt|all) ;; *)
  echo "usage: capture-deps.sh [pip|npm|apt|all]" >&2; exit 2 ;;
esac
log() { echo "==> $*"; }

# Recompiles reproduce the lock only if pip-tools itself is held still; bump
# deliberately (a new pin may reformat the lock -> new hash -> re-capture).
PIP_TOOLS_PIN='pip-tools==7.5.1'

# ── Preflight: report every gap up front, with the fix ──────────────────────
gaps=""
command -v docker >/dev/null 2>&1 || gaps="$gaps
  - docker is required (all captures run in containers)"
[ -n "${GITLAB_TOKEN:-}" ] || gaps="$gaps
  - GITLAB_TOKEN (api scope) is required to upload to the package registry"
NATIVE="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$NATIVE" in x86_64) NATIVE=amd64 ;; aarch64) NATIVE=arm64 ;; esac
for arch in amd64 arm64; do
  [ "$arch" = "$NATIVE" ] && continue
  case "$arch" in amd64) q=qemu-x86_64 ;; arm64) q=qemu-aarch64 ;; esac
  [ -f "/proc/sys/fs/binfmt_misc/$q" ] || gaps="$gaps
  - cross-arch capture needs qemu binfmt for $arch — run:
      docker run --privileged --rm tonistiigi/binfmt --install $arch"
done
if [ -n "$gaps" ]; then
  echo "capture-deps preflight failed:$gaps" >&2
  exit 1
fi

# ── pip: recompile the lock, then capture if its hash is unpublished ────────
if [ "$MODE" = pip ] || [ "$MODE" = all ]; then
  log "Recompiling requirements.lock in python:3.11-slim ($PIP_TOOLS_PIN)..."
  # Compile to a scratch name SEEDED with the current lock, adopt only on
  # change: pip-compile preserves pins already present in its output file,
  # so an untouched requirements.txt reproduces the lock byte-for-byte and
  # nothing recaptures — new/changed requirements resolve, everything else
  # stays put. (Deliberate wholesale upgrades: pip-compile --upgrade by
  # hand, then rerun this.) --strip-extras matches the committed lock and
  # pip-tools 8's default.
  docker run --rm -v "$REPO_DIR:/work" -w /work python:3.11-slim bash -c \
    "pip install -q $PIP_TOOLS_PIN >/dev/null 2>&1 && \
     cp /work/requirements.lock /tmp/new.lock 2>/dev/null || true && \
     pip-compile -q --no-header --strip-extras -o /tmp/new.lock requirements.txt && \
     cp /tmp/new.lock /work/.capture-new.lock"
  if cmp -s "$REPO_DIR/requirements.lock" "$REPO_DIR/.capture-new.lock"; then
    rm -f "$REPO_DIR/.capture-new.lock"
    log "requirements.lock unchanged"
  else
    mv "$REPO_DIR/.capture-new.lock" "$REPO_DIR/requirements.lock"
    log "requirements.lock UPDATED — commit it with your requirements.txt change"
  fi
  bash "$SCRIPT_DIR/capture-pip-wheels.sh"
fi

# ── npm: capture if the lockfile's hash is unpublished ──────────────────────
if [ "$MODE" = npm ] || [ "$MODE" = all ]; then
  bash "$SCRIPT_DIR/capture-npm-cache.sh"
fi

# ── apt: dated capture + the two Dockerfile values to set ───────────────────
if [ "$MODE" = apt ]; then
  bash "$SCRIPT_DIR/capture-apt-debs.sh"
  STAMP="$(sha256sum "$SCRIPT_DIR/capture-apt-debs.sh" | cut -c1-12)"
  log "Now set BOTH in the Dockerfile (tests/test_apt_debs.py pins the stamp):"
  echo "  ARG APT_DEBS_VERSION=$(date +%Y.%m.%d)"
  echo "  # apt-debs capture-input: $STAMP"
fi

log "capture-deps ($MODE) done. Commit the lock/Dockerfile changes and push — uploads are already live, so the MR pipeline will resolve them."
