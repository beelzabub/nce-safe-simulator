#!/usr/bin/env bash
# Export EVERYTHING needed to recreate this project on a GitLab instance in a
# separate network (issue #263): the git repo (all branches + tags, as a
# git bundle), the project wiki (if any), every generic package in the
# package registry, and the container images. Output is ONE tar archive named
# <repo-name>-<YYYY-MM-DD>.txt (the .txt extension is the transfer-media
# convention; it is a plain gzipped tar) with a SHA256SUMS manifest inside,
# ready to carry across on approved media. The matching importer is
# scripts/enclave-import.sh — pass it the .txt file.
#
# Run it from any directory inside a clone of this git repo (the script
# locates the repo root from its own path), on a box connected to the source
# GitLab. Requirements: bash, git, curl, python3 (JSON parsing of API
# responses); docker only when exporting images.
#
# Usage:
#   scripts/enclave-export.sh [-o DIR] [--no-images] [--with-base-images]
#     -o DIR              where to write the final .txt archive (default: .)
#                         staging happens in DIR/<repo>-<date>-staging/
#     --no-images         skip container images (packages + repo only)
#     --with-base-images  also save the upstream base images the CI jobs and
#                         Docker builds pull (python:3.11, python:3.11-slim,
#                         node:20-slim, kaniko) for enclaves with no image proxy
#
# Env:
#   GITLAB_TOKEN  token with read_api — required to enumerate packages and
#                 resolve the container registry path (file downloads
#                 themselves are anonymous; the *listing* API is not).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

OUTDIR="."
WITH_IMAGES=1
WITH_BASES=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o) OUTDIR="$2"; shift 2 ;;
    --no-images) WITH_IMAGES=0; shift ;;
    --with-base-images) WITH_BASES=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required (API JSON parsing)" >&2; exit 1; }
: "${GITLAB_TOKEN:?Set GITLAB_TOKEN (read_api scope) — needed to enumerate packages}"
API="$("$SCRIPT_DIR/quarto-pkg-url.sh")"          # <scheme>://<host>/api/v4/projects/<encoded-path>
auth=(--header "PRIVATE-TOKEN: $GITLAB_TOKEN")

# Final artifact: <repo-name>-<YYYY-MM-DD>.txt in OUTDIR; staged in a sibling
# directory (same disk — image tars are large) that is removed on success.
REPO_NAME="$(basename -s .git "$(git remote get-url origin)")"
STAMP="$(date +%Y-%m-%d)"
mkdir -p "$OUTDIR"
OUTDIR="$(cd "$OUTDIR" && pwd)"
ARTIFACT="$OUTDIR/$REPO_NAME-$STAMP.txt"
OUT="$OUTDIR/$REPO_NAME-$STAMP-staging"
mkdir -p "$OUT"/repo "$OUT"/packages
log() { echo "==> $*"; }

# ── 1. Git repo: every branch + tag origin has, as one verified bundle ──────
log "Fetching all refs from origin..."
git fetch origin --prune --tags
log "Writing repo bundle..."
git bundle create "$OUT/repo/repo.bundle" --remotes=origin --tags
git bundle verify "$OUT/repo/repo.bundle" >/dev/null
log "repo.bundle OK ($(du -h "$OUT/repo/repo.bundle" | cut -f1))"

# ── 2. Project wiki (skipped silently if absent/empty). Fetched through this
#      clone so the repo's own git credentials apply (`git clone` of the wiki
#      URL would not see repo-local credential helpers). ────────────────────
WIKI_URL="$(git remote get-url origin)"; WIKI_URL="${WIKI_URL%.git}.wiki.git"
if git fetch "$WIKI_URL" '+refs/heads/*:refs/enclave-wiki/*' 2>/dev/null \
   && [ -n "$(git for-each-ref 'refs/enclave-wiki/')" ]; then
  log "Writing wiki bundle..."
  git bundle create "$OUT/repo/wiki.bundle" --glob='refs/enclave-wiki/*'
  git bundle verify "$OUT/repo/wiki.bundle" >/dev/null
  git for-each-ref --format='%(refname)' 'refs/enclave-wiki/' \
    | while read -r r; do git update-ref -d "$r"; done
  log "wiki.bundle OK"
else
  log "No project wiki content — skipping wiki bundle"
fi

# ── 3. Generic packages: enumerate via API so new packages/versions are
#      picked up automatically; download every file. ────────────────────────
log "Enumerating generic packages..."
curl -fsS "${auth[@]}" "$API/packages?package_type=generic&per_page=100" \
  | python3 -c 'import json,sys; [print(p["id"], p["name"], p["version"]) for p in json.load(sys.stdin)]' \
  | while read -r pid name version; do
      curl -fsS "${auth[@]}" "$API/packages/$pid/package_files?per_page=100" \
        | python3 -c 'import json,sys; [print(f["file_name"]) for f in json.load(sys.stdin)]' \
        | while read -r fname; do
            dest="$OUT/packages/$name/$version/$fname"
            mkdir -p "$(dirname "$dest")"
            log "  package $name/$version/$fname"
            curl -fsSL "${auth[@]}" -o "$dest" "$API/packages/generic/$name/$version/$fname"
          done
    done

# ── 4. Container images ─────────────────────────────────────────────────────
if [ "$WITH_IMAGES" = 1 ]; then
  command -v docker >/dev/null || { echo "docker not found — rerun with --no-images or install docker" >&2; exit 1; }
  mkdir -p "$OUT/images"
  PREFIX="$(curl -fsS "${auth[@]}" "$API" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["container_registry_image_prefix"])')"
  log "Container registry: $PREFIX (docker login may be required for private registries)"
  # amd64 explicitly: that is what CI built and what enclave runners will run.
  for pair in "runtime:$PREFIX:latest" "dev:$PREFIX/dev:latest"; do
    short="${pair%%:*}"; ref="${pair#*:}"
    log "  pulling $ref"
    docker pull --platform linux/amd64 "$ref" >/dev/null
    docker save "$ref" -o "$OUT/images/$short.tar"
    echo "$short.tar $ref" >> "$OUT/images/image-refs.txt"
  done
  if [ "$WITH_BASES" = 1 ]; then
    for base in python:3.11 python:3.11-slim node:20-slim gcr.io/kaniko-project/executor:debug; do
      fname="base-$(echo "$base" | tr '/:' '__').tar"
      log "  pulling base $base"
      docker pull --platform linux/amd64 "$base" >/dev/null
      docker save "$base" -o "$OUT/images/$fname"
      echo "$fname $base" >> "$OUT/images/image-refs.txt"
    done
  fi
fi

# ── 5. Manifest + checksums ─────────────────────────────────────────────────
{
  echo "source: $(git remote get-url origin)"
  echo "exported: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "head: $(git rev-parse origin/HEAD 2>/dev/null || git rev-parse origin/develop)"
  echo "contents:"
  (cd "$OUT" && find . -type f ! -name MANIFEST.txt ! -name SHA256SUMS | sort | sed 's/^/  /')
} > "$OUT/MANIFEST.txt"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

# ── 6. Single-file artifact: gzipped tar, .txt extension by transfer-media
#      convention. `tar -xf` auto-detects the compression on extract. ───────
log "Packing $ARTIFACT ..."
tar -czf "$ARTIFACT" -C "$OUT" .
rm -rf "$OUT"

log "Export complete: $ARTIFACT ($(du -h "$ARTIFACT" | cut -f1))"
log "Outer sha256 (note it down for the far side): $(sha256sum "$ARTIFACT" | cut -d' ' -f1)"
log "Then run: scripts/enclave-import.sh -d $REPO_NAME-$STAMP.txt -u https://<enclave-gitlab> -p <group/project>"
