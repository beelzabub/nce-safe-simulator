#!/usr/bin/env bash
# Import a transfer artifact produced by scripts/enclave-export.sh into a
# GitLab instance on this network (issue #263): verifies checksums, creates
# the project if it does not exist, pushes every branch + tag (and the wiki),
# uploads all generic packages, enables anonymous package-registry pull (what
# lets Docker builds fetch Quarto with no token), and loads + pushes the
# container images. Each phase is idempotent — safe to rerun after a partial
# failure.
#
# Requirements (preflight-checked): bash, git, curl, python3, tar, sha256sum;
# docker only for the images phase.
#
# Usage:
#   scripts/enclave-import.sh -d TRANSFER -u GITLAB_URL -p GROUP/PROJECT \
#       [--default-branch main] [--skip-repo] [--skip-packages] [--skip-images]
#   TRANSFER is the <repo>-<date>.txt archive the exporter produced (it is a
#   gzipped tar; extracted next to itself), or an already-extracted directory.
#   e.g. scripts/enclave-import.sh -d nce-safe-simulator-2026-07-21.txt \
#          -u https://gitlab.enclave.mil -p tools/nce-safe-simulator
#
# Bootstrap: the artifact carries a copy of this script at its top level —
# on a box that has ONLY the .txt file (the repo is still inside the bundle):
#   tar -xf <repo>-<date>.txt ./enclave-import.sh
#   GITLAB_TOKEN=<token> ./enclave-import.sh -d <repo>-<date>.txt -u ... -p ...
#
# Env:
#   GITLAB_TOKEN  token with api scope on the target instance — required.
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
  echo "Install them and rerun. (docker is additionally needed unless --skip-images.)" >&2
  exit 1
fi

DIR="" URL="" PROJ="" DEFAULT_BRANCH="main"
DO_REPO=1 DO_PACKAGES=1 DO_IMAGES=1
while [ $# -gt 0 ]; do
  case "$1" in
    -d) DIR="$2"; shift 2 ;;
    -u) URL="${2%/}"; shift 2 ;;
    -p) PROJ="$2"; shift 2 ;;
    --default-branch) DEFAULT_BRANCH="$2"; shift 2 ;;
    --skip-repo) DO_REPO=0; shift ;;
    --skip-packages) DO_PACKAGES=0; shift ;;
    --skip-images) DO_IMAGES=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] && [ -n "$URL" ] && [ -n "$PROJ" ] || {
  echo "usage: enclave-import.sh -d TRANSFER_DIR -u GITLAB_URL -p GROUP/PROJECT" >&2; exit 2; }
: "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope on the target instance)}"

log() { echo "==> $*"; }

# Accept the single-file .txt artifact (a gzipped tar) or an extracted dir.
if [ -f "$DIR" ]; then
  ARCHIVE="$(cd "$(dirname "$DIR")" && pwd)/$(basename "$DIR")"
  EXTRACT="${ARCHIVE%.txt}-extracted"
  log "Extracting $(basename "$ARCHIVE") to $EXTRACT ..."
  mkdir -p "$EXTRACT"
  tar -xf "$ARCHIVE" -C "$EXTRACT"
  DIR="$EXTRACT"
fi
DIR="$(cd "$DIR" && pwd)"
API="$URL/api/v4"
ENC="$(printf '%s' "$PROJ" | sed 's#/#%2F#g')"
auth=(--header "PRIVATE-TOKEN: $GITLAB_TOKEN")

# ── 0. Integrity ────────────────────────────────────────────────────────────
log "Verifying checksums..."
(cd "$DIR" && sha256sum --quiet -c SHA256SUMS)
log "Checksums OK"

# ── 1. Project (create if absent) ───────────────────────────────────────────
if curl -fsS "${auth[@]}" "$API/projects/$ENC" >/dev/null 2>&1; then
  log "Project $PROJ exists"
else
  GROUP="${PROJ%/*}"; NAME="${PROJ##*/}"
  log "Creating project $NAME in group $GROUP..."
  NS_ID="$(curl -fsS "${auth[@]}" "$API/groups/$(printf '%s' "$GROUP" | sed 's#/#%2F#g')" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  curl -fsS "${auth[@]}" --request POST "$API/projects" \
    --data-urlencode "name=$NAME" --data-urlencode "path=$NAME" \
    --data-urlencode "namespace_id=$NS_ID" \
    --data-urlencode "visibility=private" >/dev/null
  log "Created"
fi

# ── 2. Repo: push every branch + tag from the bundle ────────────────────────
# The bundle carries origin's refs as refs/remotes/origin/*; the push refspec
# maps them back to refs/heads/* on the target.
PUSH_URL="${URL%%://*}://oauth2:$GITLAB_TOKEN@${URL#*://}/$PROJ.git"
if [ "$DO_REPO" = 1 ]; then
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  log "Pushing repo (all branches + tags)..."
  git clone --quiet --mirror "$DIR/repo/repo.bundle" "$TMP/repo.git"
  git -C "$TMP/repo.git" push --quiet "$PUSH_URL" \
    '+refs/remotes/origin/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
  curl -fsS "${auth[@]}" --request PUT "$API/projects/$ENC" \
    --data-urlencode "default_branch=$DEFAULT_BRANCH" >/dev/null
  log "Repo pushed; default branch = $DEFAULT_BRANCH"
  if [ -f "$DIR/repo/wiki.bundle" ]; then
    log "Pushing wiki..."
    git clone --quiet --mirror "$DIR/repo/wiki.bundle" "$TMP/wiki.git"
    git -C "$TMP/wiki.git" push --quiet "${PUSH_URL%.git}.wiki.git" \
      '+refs/enclave-wiki/*:refs/heads/*'
    log "Wiki pushed"
  fi
fi

# ── 3. Generic packages (layout: packages/<name>/<version>/<file>) ──────────
if [ "$DO_PACKAGES" = 1 ]; then
  find "$DIR/packages" -type f | while read -r f; do
    rel="${f#"$DIR/packages/"}"                       # name/version/file
    log "  package $rel"
    curl -fsS "${auth[@]}" --upload-file "$f" \
      "$API/projects/$ENC/packages/generic/$rel" >/dev/null
  done
  # Anonymous pull from the package registry (project stays private) — this
  # is what lets Docker builds fetch Quarto with no token in build args.
  curl -fsS "${auth[@]}" --request PUT "$API/projects/$ENC" \
    --data-urlencode "package_registry_access_level=public" >/dev/null
  log "Packages uploaded; anonymous package-registry pull enabled"
fi

# ── 4. Container images ─────────────────────────────────────────────────────
if [ "$DO_IMAGES" = 1 ] && [ -d "$DIR/images" ]; then
  command -v docker >/dev/null || { echo "docker not found — rerun with --skip-images or install docker" >&2; exit 1; }
  PREFIX="$(curl -fsS "${auth[@]}" "$API/projects/$ENC" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["container_registry_image_prefix"])')"
  REG_HOST="${PREFIX%%/*}"
  log "Logging in to $REG_HOST..."
  printf '%s' "$GITLAB_TOKEN" | docker login "$REG_HOST" --username oauth2 --password-stdin >/dev/null
  while read -r tarname origref; do
    case "$tarname" in
      runtime.tar) newref="$PREFIX:latest" ;;
      dev.tar)     newref="$PREFIX/dev:latest" ;;
      base-*)      log "  loading base image $origref (not pushed — hand to your registry/proxy admin)"
                   docker load -i "$DIR/images/$tarname" >/dev/null; continue ;;
      *)           echo "  unknown image entry: $tarname — skipping" >&2; continue ;;
    esac
    log "  $tarname → $newref"
    docker load -i "$DIR/images/$tarname" >/dev/null
    docker tag "$origref" "$newref"
    docker push "$newref" >/dev/null
  done < "$DIR/images/image-refs.txt"
  log "Images pushed"
fi

log "Import complete. Post-import checklist:"
cat <<'EOF'
  1. Runners: ensure the instance has runners that can pull the imported
     images (and the CI base images python:3.11 / kaniko, via proxy or
     registry import).
  2. CI/CD variables: create GITLAB_API_TOKEN (masked) if the report/deck
     recipes will run here.
  3. config.json: copy config.example.json and fill url/token/parent_group
     for THIS instance.
  4. Protect the default branch (Settings → Repository) to match your flow.
  5. First green pipeline proves the lift: test fetches Pango debs and a
     default-branch merge rebuilds images — both from THIS instance's
     registries (README → Enclave Transfer, Verify section).
EOF
