#!/usr/bin/env bash
# Import a transfer artifact produced by scripts/enclave-export.sh into a
# GitLab instance on this network (issue #263): verifies checksums, creates
# the project if it does not exist, pushes every branch + tag (and the wiki),
# syncs all generic packages (sha256-driven — see the packages phase, issue
# #295), enables anonymous package-registry pull (what lets Docker builds
# fetch Quarto with no token), and loads + pushes the container images. Each
# phase is idempotent — safe to rerun after a partial failure, and a rerun
# with an unchanged artifact uploads nothing.
#
# Requirements (preflight-checked): bash, git, curl, python3, tar, sha256sum;
# docker only for the images phase.
#
# Usage:
#   scripts/enclave-import.sh -d TRANSFER -u GITLAB_URL -p GROUP/PROJECT \
#       [--default-branch main] [--rewrite-committer 'Full Name <email@domain>'] \
#       [--sign-commits] [--skip-repo] [--skip-packages] [--skip-images] \
#       [--no-prune]
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

DIR="" URL="" PROJ="" DEFAULT_BRANCH="main" REWRITE_COMMITTER="" SIGN_COMMITS=0
DO_REPO=1 DO_PACKAGES=1 DO_IMAGES=1 PRUNE=1
while [ $# -gt 0 ]; do
  case "$1" in
    -d) DIR="$2"; shift 2 ;;
    -u) URL="${2%/}"; shift 2 ;;
    -p) PROJ="$2"; shift 2 ;;
    --default-branch) DEFAULT_BRANCH="$2"; shift 2 ;;
    --rewrite-committer) REWRITE_COMMITTER="$2"; shift 2 ;;
    --sign-commits) SIGN_COMMITS=1; shift ;;
    --skip-repo) DO_REPO=0; shift ;;
    --skip-packages) DO_PACKAGES=0; shift ;;
    --skip-images) DO_IMAGES=0; shift ;;
    --no-prune) PRUNE=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] && [ -n "$URL" ] && [ -n "$PROJ" ] || {
  echo "usage: enclave-import.sh -d TRANSFER_DIR -u GITLAB_URL -p GROUP/PROJECT [--rewrite-committer 'Full Name <email@domain>'] [--sign-commits]" >&2; exit 2; }
: "${GITLAB_TOKEN:?Set GITLAB_TOKEN (api scope on the target instance)}"

log() { echo "==> $*"; }

# --rewrite-committer: for targets enforcing the "committer restriction" push
# rule (only commits whose committer email is a verified email of the pushing
# account are accepted), which rejects any transferred history wholesale.
# Rewrites author AND committer on every commit of the repo and wiki mirrors
# before pushing. Deterministic — reruns yield identical hashes, so imports
# stay idempotent.
RW_NAME="" RW_EMAIL=""
if [ -n "$REWRITE_COMMITTER" ]; then
  case "$REWRITE_COMMITTER" in
    *"<"*"@"*">"*)
      RW_NAME="$(printf '%s' "${REWRITE_COMMITTER%%<*}" | sed 's/ *$//')"
      RW_EMAIL="${REWRITE_COMMITTER#*<}"; RW_EMAIL="${RW_EMAIL%%>*}" ;;
    *) echo "--rewrite-committer must look like 'Full Name <email@domain>'" >&2; exit 2 ;;
  esac
fi
# --sign-commits: for targets enforcing the "reject unsigned commits" push
# rule. GPG-signs every commit during the same history pass; needs gpg set up
# for git on THIS box (gpg.program/user.signingkey in the global git config,
# or a secret key matching the committer email). Composes with
# --rewrite-committer: the rewritten identity chooses the signing key. NOT
# deterministic — every run yields new hashes; a rerun force-pushes over the
# previous history.
history_filter() {
  # filter-branch rather than git-filter-repo because it ships inside git —
  # nothing to install on an enclave box. Its refs/original/* backups never
  # match the push refspecs, so only rewritten history leaves the mirror.
  local repo=$1 what=""
  if [ -n "$REWRITE_COMMITTER" ]; then what="authorship -> $RW_NAME <$RW_EMAIL>"; fi
  if [ "$SIGN_COMMITS" = 1 ]; then what="${what:+$what + }gpg signing"; fi
  log "  rewriting history ($what) - large histories take a while..."
  set --
  if [ -n "$REWRITE_COMMITTER" ]; then
    set -- "$@" --env-filter "export GIT_AUTHOR_NAME='$RW_NAME' GIT_AUTHOR_EMAIL='$RW_EMAIL' GIT_COMMITTER_NAME='$RW_NAME' GIT_COMMITTER_EMAIL='$RW_EMAIL'"
  fi
  if [ "$SIGN_COMMITS" = 1 ]; then
    # --commit-filter replaces the stock commit-tree call; -S signs with the
    # key matching the (possibly rewritten) committer identity.
    set -- "$@" --commit-filter 'git commit-tree -S "$@"'
  fi
  FILTER_BRANCH_SQUELCH_WARNING=1 git -C "$repo" filter-branch -f "$@" \
    --tag-name-filter cat -- --all
}

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
PRE_EXISTING=0
if curl -fsS "${auth[@]}" "$API/projects/$ENC" >/dev/null 2>&1; then
  PRE_EXISTING=1
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
  # Scratch clone lives beside the transfer contents, NOT in the system
  # temp — /tmp is often a small tmpfs while the transfer dir is on a disk
  # already proven big enough to hold the artifact.
  TMP="$(mktemp -d "$DIR/.import-XXXXXX")"; trap 'rm -rf "$TMP"' EXIT
  log "Pushing repo (all branches + tags)..."
  git clone --quiet --mirror "$DIR/repo/repo.bundle" "$TMP/repo.git"
  if [ -n "$REWRITE_COMMITTER" ] || [ "$SIGN_COMMITS" = 1 ]; then history_filter "$TMP/repo.git"; fi
  # A pre-existing target can hold a protected branch whose tip is not in the
  # bundle's history — classic cause: the project was pre-created in the UI
  # with "Initialize repository with a README", so its main has a stray root
  # commit. The push below force-updates every branch, protection rejects
  # forced updates unless allow_force_push is set, and a pre-receive
  # rejection fails the ENTIRE push — a wall of rejected refs with no hint.
  # Detect the collision up front (after the history filter, so the check
  # sees the refs that will actually be pushed) and say how to fix it.
  if [ "$PRE_EXISTING" = 1 ]; then
    curl -fsS "${auth[@]}" "$API/projects/$ENC/protected_branches?per_page=100" \
      | python3 -c 'import json,sys; [print("%s\t%s" % (b["name"], str(bool(b.get("allow_force_push"))).lower())) for b in json.load(sys.stdin)]' \
      | while IFS=$'\t' read -r bname allow; do
          [ "$allow" = "false" ] || continue
          sha="$(curl -fsS "${auth[@]}" "$API/projects/$ENC/repository/branches/$(printf '%s' "$bname" | sed 's#/#%2F#g')" 2>/dev/null \
            | python3 -c 'import json,sys; print(json.load(sys.stdin)["commit"]["id"])' 2>/dev/null || true)"
          [ -n "$sha" ] || continue    # wildcard rule or branch absent — push creates, no force needed
          git -C "$TMP/repo.git" show-ref --verify --quiet "refs/remotes/origin/$bname" || continue
          div=1
          if git -C "$TMP/repo.git" rev-parse --quiet --verify "$sha^{commit}" >/dev/null; then
            if git -C "$TMP/repo.git" merge-base --is-ancestor "$sha" "refs/remotes/origin/$bname"; then div=0; fi
          fi
          if [ "$div" = 1 ]; then
            cat >&2 <<EOF
ERROR: protected branch '$bname' on $PROJ has history the bundle does not
build on, and its protection disallows force push — GitLab would reject the
forced update, and one rejected ref fails the ENTIRE push. Common cause: the
project was pre-created in the UI with 'Initialize repository with a README'.
Fix ONE of these, then rerun:
  - allow force push on the branch:
      curl -X PATCH -H "PRIVATE-TOKEN: \$GITLAB_TOKEN" \\
        "$API/projects/$ENC/protected_branches/$bname?allow_force_push=true"
  - or delete the pre-created project and let this importer create it
EOF
            exit 1
          fi
        done
  fi
  git -C "$TMP/repo.git" push --quiet "$PUSH_URL" \
    '+refs/remotes/origin/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
  curl -fsS "${auth[@]}" --request PUT "$API/projects/$ENC" \
    --data-urlencode "default_branch=$DEFAULT_BRANCH" >/dev/null
  log "Repo pushed; default branch = $DEFAULT_BRANCH"
  if [ -f "$DIR/repo/wiki.bundle" ]; then
    log "Pushing wiki..."
    git clone --quiet --mirror "$DIR/repo/wiki.bundle" "$TMP/wiki.git"
    if [ -n "$REWRITE_COMMITTER" ] || [ "$SIGN_COMMITS" = 1 ]; then history_filter "$TMP/wiki.git"; fi
    git -C "$TMP/wiki.git" push --quiet "${PUSH_URL%.git}.wiki.git" \
      '+refs/enclave-wiki/*:refs/heads/*'
    log "Wiki pushed"
  fi
fi

# ── 3. Generic packages (layout: packages/<name>/<version>/<file>) ──────────
# Sync, not blind upload (issue #295). GitLab's generic registry APPENDS on
# re-publish of an existing name/version/file — downloads resolve to the
# newest entry, every older copy is kept — so unconditional re-uploads stack
# a full duplicate set per rerun, and files removed at the source lived on
# at the destination forever. The archive is a complete snapshot of the
# source registry, so the destination converges to it BY CONTENT: per file,
# the sha256 from the archive's own SHA256SUMS (phase 0 verified it against
# disk) is compared to the newest destination entry — identical skips,
# different or absent uploads and then deletes the superseded entries
# (upload FIRST, so there is no window where the file is unserved); older
# duplicates are swept; anything the archive does not carry is pruned unless
# --no-prune. A name-only skip-if-exists would be wrong: bytes can change
# under an unchanged version (same-day re-capture), and the destination
# would silently serve stale content forever.
#
# One transient TLS reset mid-file must not abort a whole import: retry each
# upload with backoff (uploads are idempotent, so a half-sent file is safe to
# resend). A bash loop, not curl --retry: plain --retry skips mid-stream
# resets and --retry-all-errors needs curl >= 7.71.
upload_with_retry() {
  local src=$1 url=$2 try
  for try in 1 2 3 4; do
    curl -fsS "${auth[@]}" --upload-file "$src" "$url" >/dev/null && return 0
    [ "$try" = 4 ] && break
    log "  transient upload failure - retry $try/3 in $((2 * try))s"
    sleep $((2 * try))
  done
  echo "upload failed after 4 attempts: $url" >&2
  return 1
}
api_delete_with_retry() {
  local url=$1 try
  for try in 1 2 3 4; do
    curl -fsS "${auth[@]}" --request DELETE "$url" >/dev/null && return 0
    [ "$try" = 4 ] && break
    log "  transient delete failure - retry $try/3 in $((2 * try))s"
    sleep $((2 * try))
  done
  echo "delete failed after 4 attempts: $url" >&2
  return 1
}
# Paged listing — GitLab caps per_page at 100 and a one-shot request silently
# truncates larger sets (the 225-file apt-debs package, #273). Same pager as
# the exporter's; context for the parse program rides in exported CUR_* vars.
list_paged() {
  local url=$1 parse=$2 page=1 sep batch count
  case "$url" in *\?*) sep='&' ;; *) sep='?' ;; esac
  while :; do
    batch="$(curl -fsS "${auth[@]}" "$url${sep}per_page=100&page=$page" \
      | python3 -c "$parse")"
    [ -n "$batch" ] && printf '%s\n' "$batch"
    count=$(printf '%s\n' "$batch" | grep -c . || true)
    [ "$count" -lt 100 ] && return 0
    page=$((page + 1))
  done
}
if [ "$DO_PACKAGES" = 1 ]; then
  SYNC="$(mktemp -d "$DIR/.pkg-sync-XXXXXX")"
  trap 'rm -rf ${TMP:+"$TMP"} "$SYNC"' EXIT
  log "Enumerating destination packages..."
  list_paged "$API/projects/$ENC/packages?package_type=generic" \
      'import json,sys; [print("%d\t%s\t%s" % (p["id"], p["name"], p["version"])) for p in json.load(sys.stdin)]' \
    > "$SYNC/pkgs.tsv"
  : > "$SYNC/dest.tsv"
  while IFS=$'\t' read -r pid name version; do
    export CUR_PID="$pid" CUR_NAME="$name" CUR_VER="$version"
    list_paged "$API/projects/$ENC/packages/$pid/package_files" \
        'import json,sys,os; [print("\t".join([os.environ["CUR_PID"],os.environ["CUR_NAME"],os.environ["CUR_VER"],f["file_name"],str(f["id"]),(f.get("file_sha256") or ""),f["created_at"]])) for f in json.load(sys.stdin)]' \
      >> "$SYNC/dest.tsv"
  done < "$SYNC/pkgs.tsv"
  # Build the action plan: compare archive content hashes against the
  # destination state and emit one tab-separated action per line —
  #   SKIP        <name/ver/file> identical
  #   UPLOAD      <name/ver/file> new|changed
  #   DELETE_FILE <pkg_id> <file_id> <name/ver/file> duplicate|superseded|pruned
  #   DELETE_PKG  <pkg_id> <name/ver>
  python3 - "$DIR" "$SYNC/dest.tsv" "$SYNC/pkgs.tsv" "$PRUNE" > "$SYNC/plan.tsv" <<'PLAN_PY'
import hashlib, os, sys
from collections import defaultdict

root, dest_tsv, pkgs_tsv, prune = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"

sums = {}
with open(os.path.join(root, "SHA256SUMS")) as fh:
    for line in fh:
        line = line.rstrip("\n")
        if len(line) > 66 and line[64:66] == "  ":
            path = line[66:].lstrip("*")
            if path.startswith("./"):
                path = path[2:]
            sums[path] = line[:64]

def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

archive = {}                       # name/version/file -> sha256
pkgroot = os.path.join(root, "packages")
for dirpath, _, files in os.walk(pkgroot):
    for fn in files:
        full = os.path.join(dirpath, fn)
        rel = os.path.relpath(full, root).replace(os.sep, "/")
        key = os.path.relpath(full, pkgroot).replace(os.sep, "/")
        archive[key] = sums.get(rel) or file_sha(full)

dest = defaultdict(list)           # key -> [(created_at, file_id, sha, pkg_id)]
pkg_keys = defaultdict(set)
pkg_label = {}
with open(pkgs_tsv) as fh:
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            pkg_keys[int(parts[0])]                 # zero-file packages prune too
            pkg_label[int(parts[0])] = "%s/%s" % (parts[1], parts[2])
with open(dest_tsv) as fh:
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 7:
            continue
        pid, name, ver, fname, fid, sha, created = parts
        key = "%s/%s/%s" % (name, ver, fname)
        dest[key].append((created, int(fid), sha, int(pid)))
        pkg_keys[int(pid)].add(key)

out = []
for key in sorted(archive):
    entries = sorted(dest.get(key, []), reverse=True)          # newest first
    if not entries:
        out.append(("UPLOAD", key, "new"))
    elif entries[0][2] == archive[key]:
        out.append(("SKIP", key, "identical"))
        for _created, fid, _sha, pid in entries[1:]:
            out.append(("DELETE_FILE", str(pid), str(fid), key, "duplicate"))
    else:
        out.append(("UPLOAD", key, "changed"))
        for _created, fid, _sha, pid in entries:
            out.append(("DELETE_FILE", str(pid), str(fid), key, "superseded"))

if prune:
    for pid in sorted(pkg_keys):
        keys = pkg_keys[pid]
        stale = sorted(k for k in keys if k not in archive)
        if keys and not stale:
            continue
        if len(stale) == len(keys):                            # covers zero-file packages
            out.append(("DELETE_PKG", str(pid), pkg_label.get(pid, str(pid))))
        else:
            for k in stale:
                for _created, fid, _sha, p in sorted(dest[k], reverse=True):
                    out.append(("DELETE_FILE", str(p), str(fid), k, "pruned"))

for row in out:
    print("\t".join(row))
PLAN_PY
  # Uploads first — a replaced file's new bytes must be live before its old
  # entries are deleted — then every delete (dupes, superseded, prune).
  UP_NEW=0 UP_CHG=0 SKIPPED=0 STALE=0 PRUNED_FILES=0 PRUNED_PKGS=0
  while IFS=$'\t' read -r op a1 a2 a3 a4; do
    case "$op" in
      UPLOAD)
        log "  upload ($a2): $a1"
        upload_with_retry "$DIR/packages/$a1" "$API/projects/$ENC/packages/generic/$a1"
        if [ "$a2" = "new" ]; then UP_NEW=$((UP_NEW + 1)); else UP_CHG=$((UP_CHG + 1)); fi ;;
      SKIP) SKIPPED=$((SKIPPED + 1)) ;;
    esac
  done < "$SYNC/plan.tsv"
  while IFS=$'\t' read -r op a1 a2 a3 a4; do
    case "$op" in
      DELETE_FILE)
        log "  delete ($a4): $a3"
        api_delete_with_retry "$API/projects/$ENC/packages/$a1/package_files/$a2"
        if [ "$a4" = "pruned" ]; then PRUNED_FILES=$((PRUNED_FILES + 1)); else STALE=$((STALE + 1)); fi ;;
      DELETE_PKG)
        log "  delete (pruned package): $a2"
        api_delete_with_retry "$API/projects/$ENC/packages/$a1"
        PRUNED_PKGS=$((PRUNED_PKGS + 1)) ;;
    esac
  done < "$SYNC/plan.tsv"
  # Anonymous pull from the package registry (project stays private) — this
  # is what lets Docker builds fetch Quarto with no token in build args.
  curl -fsS "${auth[@]}" --request PUT "$API/projects/$ENC" \
    --data-urlencode "package_registry_access_level=public" >/dev/null
  PRUNE_NOTE="$PRUNED_FILES files + $PRUNED_PKGS packages pruned"
  [ "$PRUNE" = 1 ] || PRUNE_NOTE="prune skipped (--no-prune)"
  log "Package sync: $((UP_NEW + UP_CHG)) uploaded ($UP_NEW new, $UP_CHG replaced), $SKIPPED skipped identical, $STALE stale entries removed, $PRUNE_NOTE; anonymous package-registry pull enabled"
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
