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
# GitLab. Requirements (preflight-checked): bash, git, curl, python3, tar,
# sha256sum; docker only when exporting images.
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
# ── Preflight: check every required tool up front and report ALL gaps in one
#    message. The bash check runs before `set -o pipefail`, which plain sh
#    would reject with a far less helpful error. ─────────────────────────────
if [ -z "${BASH_VERSION:-}" ]; then
  echo "This script requires bash (arrays, pipefail) — run it directly, not via 'sh'" >&2
  exit 1
fi
set -euo pipefail
missing=""
for tool in git curl python3 tar sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
done
if [ -n "$missing" ]; then
  echo "Missing required tools:$missing" >&2
  echo "Install them and rerun. (docker is additionally needed unless --no-images.)" >&2
  exit 1
fi

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
# --exclude origin/HEAD: some gits (e.g. Git for Windows builds) write the
# symref into the bundle DEREFERENCED — a second entry under its target name —
# and any clone of that bundle dies with "multiple updates for ref
# 'refs/remotes/origin/<default>' not allowed". The importer never needs it.
git bundle create "$OUT/repo/repo.bundle" --exclude=refs/remotes/origin/HEAD --remotes=origin --tags
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
# One transient TLS reset mid-file must not abort a whole export: retry each
# download with backoff, discarding partials so nothing corrupt gets staged
# (SHA256SUMS is computed FROM staged files, so a partial would otherwise
# checksum as "valid"). A bash loop, not curl --retry: plain --retry skips
# mid-stream resets and --retry-all-errors needs curl >= 7.71.
fetch_with_retry() {
  local url=$1 dest=$2 try
  for try in 1 2 3 4; do
    curl -fsSL "${auth[@]}" -o "$dest" "$url" && return 0
    rm -f "$dest"
    [ "$try" = 4 ] && break
    log "  transient download failure - retry $try/3 in $((2 * try))s"
    sleep $((2 * try))
  done
  echo "download failed after 4 attempts: $url" >&2
  return 1
}
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
            fetch_with_retry "$API/packages/generic/$name/$version/$fname" "$dest"
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

# ── 5. Ship both importers inside the artifact: the enclave box has ONLY the
#      .txt file, and the import scripts' canonical home (this repo) is
#      locked inside repo.bundle — so copies ride along at the top level,
#      extractable with a single tar command (see the final hint). The .ps1
#      variant (issue #264) covers Windows transfer boxes. ──────────────────
cp -p "$SCRIPT_DIR/enclave-import.sh" "$OUT/enclave-import.sh"
cp -p "$SCRIPT_DIR/enclave-import.ps1" "$OUT/enclave-import.ps1"

# ── 6. Manifest + checksums ─────────────────────────────────────────────────
{
  echo "source: $(git remote get-url origin)"
  echo "exported: $(date -u '+%Y-%m-%d %H:%M UTC')"
  echo "head: $(git rev-parse origin/HEAD 2>/dev/null || git rev-parse origin/develop)"
  echo "contents:"
  (cd "$OUT" && find . -type f ! -name MANIFEST.txt ! -name SHA256SUMS | sort | sed 's/^/  /')
} > "$OUT/MANIFEST.txt"
(cd "$OUT" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)

# ── 7. Single-file artifact: gzipped tar, .txt extension by transfer-media
#      convention. `tar -xf` auto-detects the compression on extract. ───────
log "Packing $ARTIFACT ..."
tar -czf "$ARTIFACT" -C "$OUT" .
rm -rf "$OUT"

log "Export complete: $ARTIFACT ($(du -h "$ARTIFACT" | cut -f1))"
log "Outer sha256 (note it down for the far side): $(sha256sum "$ARTIFACT" | cut -d' ' -f1)"
log "On the enclave box (importers ship inside the artifact; use .ps1 on Windows):"
log "  tar -xf $REPO_NAME-$STAMP.txt ./enclave-import.sh"
log "  GITLAB_TOKEN=<token> ./enclave-import.sh -d $REPO_NAME-$STAMP.txt -u https://<enclave-gitlab> -p <group/project>"
