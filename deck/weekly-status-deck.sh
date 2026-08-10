#!/usr/bin/env bash
#
# Weekly status-deck build + email (issue #213). Invoked by nce-status-deck.service
# via the nce-status-deck.timer (Fri 15:00 America/Los_Angeles) on the box that
# hosts the app. Pulls develop, rebuilds/redeploys the app container so the
# screenshots are current, builds the deck (spotlights authored headless from the
# `slides`-labeled issues closed this week), uploads to S3, and emails via SNS.
# Any failure emails a failure notice; the authored-spotlights step degrades to
# deterministic auto-derived spotlights rather than failing the whole run.
set -uo pipefail

REPO="/root/.venv/nce-safe-simulator-2"
TOPIC_ARN="arn:aws:sns:us-east-1:881490118830:nce-status-deck"
BUCKET="workflow-bootstrap-20260626-055227-881490118830"
S3_PREFIX="nce-safe-simulator/status"
APP_URL="https://nce-safe-sim.com/app/"
# Container name must match scripts/redeploy.sh; the rollback tag is what the
# pre-swap image gets stamped with so a failed deploy can be undone (#309).
APP_NAME="nce-safe-sim"
IMAGE_ROLLBACK="nce-safe-simulator:rollback"
GEN_SPOTLIGHTS="$REPO/deck/dist/latest-work-spotlights.gen.yaml"
GEN_CAPS="$REPO/deck/dist/capabilities-updates.gen.yaml"
LOGDIR="$REPO/deck/dist/weekly-logs"

export HOME=/root
# The deck's Python deps (playwright, python-pptx, Pillow, segno, …) live in the
# /root/.venv virtualenv, not system Python — put it first so `python3` and the
# playwright browsers resolve there. git/make/aws/glab/docker/claude come from /usr/bin.
export PATH="/root/.venv/bin:/usr/local/bin:/usr/bin:/bin"
export AWS_DEFAULT_REGION=us-east-1
# Which ref to build from. Production is develop; a validation run can point this
# at a feature branch (WEEKLY_REF=feature/...) before the automation is merged.
REF="${WEEKLY_REF:-develop}"

mkdir -p "$LOGDIR"
STAMP="$(TZ=America/Los_Angeles date '+%Y%m%d-%H%M%S')"
LOG="$LOGDIR/weekly-$STAMP.log"
exec > >(tee -a "$LOG") 2>&1

notify() { aws sns publish --topic-arn "$TOPIC_ARN" --subject "$1" --message "$2" >/dev/null 2>&1 || true; }
fail() {
  echo "FAILED at: $1"
  notify "NCE Status Deck - BUILD FAILED" "The weekly status-deck build failed at: $1

Host: $(hostname)   Time: $(TZ=America/Los_Angeles date '+%F %T %Z')
Log on the box: $LOG"
  exit 1
}

echo "=== weekly status deck @ $(TZ=America/Los_Angeles date '+%F %T %Z') ==="
cd "$REPO" || fail "cd repo"

# --- credentials pre-flight (issue #258) ------------------------------------
# The 2026-07-31 run died at `git pull` on an expired GitLab token — a silent
# step-1 death after the timer had already fired. Check auth up front and fail
# with a clear, actionable message instead of deep in the run. Tokens expire
# again, so this stays.
echo "--- credentials pre-flight ---"
git ls-remote origin HEAD >/dev/null 2>&1 \
  || fail "git auth pre-flight — cannot reach origin over HTTPS. The GitLab token in
the cron's git credentials has most likely expired (this is what broke the
2026-07-31 run). Rotate it (update ~/.git-credentials / the glab token), then re-run."

echo "--- sync $REF ---"
git checkout "$REF"  || fail "git checkout $REF"
git pull --ff-only   || fail "git pull $REF"

# --- port agreement pre-flight (issue #309, degrade #258) -------------------
# The image and the reverse proxy come from *different checkouts*: the image is
# built here from $REF, while Caddy's config is bind-mounted from the live tree,
# which may sit on any branch. On 2026-08-07 develop's image listened on 80
# while Caddy dialled 8080, so a swap would have put up a container the proxy
# could not reach — and the run aborted with no deck.
#
# Checked *before* the swap. A mismatch no longer aborts: if a healthy container
# is already serving, we SKIP the deploy and build the deck against it (degraded,
# see #258), so a config drift costs a fresh app image — not the deck, and never
# the site.
LIVE_TREE="/root/.venv/nce-safe-simulator"
CADDYFILE="$LIVE_TREE/deploy/Caddyfile"

image_port() {   # the port this ref's image will listen on, read from its Dockerfile
  grep -oE '^EXPOSE[[:space:]]+[0-9]+' Dockerfile 2>/dev/null | tail -1 | grep -oE '[0-9]+'
}
proxy_port() {   # the port Caddy is configured to dial
  grep -oE 'nce-safe-sim:[0-9]+' "$CADDYFILE" 2>/dev/null | head -1 | cut -d: -f2
}

container_url() {  # the running container's own address — a proxy-independent check
  local ip
  ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$APP_NAME" 2>/dev/null)"
  [ -n "$ip" ] && echo "http://$ip:${IMG_PORT:-8080}/app/"
}

poll() {  # poll <url> <attempts> -> 0 when it answers 200
  local url="$1" n="$2"
  for _ in $(seq 1 "$n"); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$url" || true)" = "200" ] && return 0
    sleep 5
  done
  return 1
}

# Degrade-don't-abort (issue #258): a failed redeploy/health check used to end
# the whole run, so a deploy hiccup cost the weekly deck entirely (2026-08-07,
# 2026-08-01). Instead we fall back to the last-healthy container and keep going;
# the deck is still built, against the previous image. Only a case where *no*
# healthy container can be reached is fatal — then there is genuinely no app to
# screenshot.
DEGRADED=""
degrade_note() {  # record a degraded reason (accumulates) and log it
  [ -n "$DEGRADED" ] && DEGRADED="$DEGRADED  |  $1" || DEGRADED="$1"
  echo "==> DEGRADING: $1"
}

degrade_to_rollback() {  # degrade_to_rollback <reason> — restore prev image and continue
  local reason="$1"
  [ -n "$PREV_IMAGE" ] || fail "$reason — and no previous image to fall back to, so there is no app to screenshot."
  degrade_note "$reason; deck built against the previous container ($IMAGE_ROLLBACK), so app screenshots may lag the latest $REF."
  echo "==> rolling back to $IMAGE_ROLLBACK"
  bash scripts/redeploy.sh --image "$IMAGE_ROLLBACK" \
    || fail "$reason — and the rollback redeploy failed, so the app is down; no deck."
  local cu; cu="$(container_url)"
  { [ -n "$cu" ] && poll "$cu" 24; } \
    || fail "$reason — the rollback container is not answering either; no app to screenshot, so no deck."
  echo "==> rollback healthy — continuing against the previous container"
}

# Tag whatever is running now so a failed deploy can be undone / fallen back to.
PREV_IMAGE="$(docker inspect -f '{{.Image}}' "$APP_NAME" 2>/dev/null || true)"
if [ -n "$PREV_IMAGE" ]; then
  docker tag "$PREV_IMAGE" "$IMAGE_ROLLBACK" && echo "    rollback point: $IMAGE_ROLLBACK"
fi

# Read from the Dockerfile rather than a built image on purpose: this has to be
# answerable *before* anything is built or swapped, and EXPOSE is what the build
# would produce anyway.
IMG_PORT="$(image_port)"
PRX_PORT="$(proxy_port)"
echo "    image listens on ${IMG_PORT:-?}; proxy dials ${PRX_PORT:-?}"

SKIP_DEPLOY=""
if [ -n "$IMG_PORT" ] && [ -n "$PRX_PORT" ] && [ "$IMG_PORT" != "$PRX_PORT" ]; then
  MISMATCH="port mismatch — the $REF image listens on $IMG_PORT but the live Caddy config ($CADDYFILE, from $(git -C "$LIVE_TREE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')) dials $PRX_PORT; deploying would take the site down"
  if [ -n "$PREV_IMAGE" ]; then
    SKIP_DEPLOY=1
    degrade_note "$MISMATCH — kept the running container and built against it. Reconcile the two checkouts."
  else
    fail "$MISMATCH — and nothing is running to fall back to. Reconcile the two checkouts, then re-run."
  fi
fi

if [ -z "$SKIP_DEPLOY" ]; then
  echo "--- rebuild + redeploy container ---"
  make redeploy || degrade_to_rollback "make redeploy failed"

  # Two distinct checks, reported separately. The container check proves the app
  # itself came up; the public check proves the proxy can reach it. Depending on
  # the public URL alone let reverse-proxy config hold the whole run hostage.
  if [ -z "$DEGRADED" ]; then
    echo "--- app health check (container) ---"
    CURL_TARGET="$(container_url)"
    if [ -z "$CURL_TARGET" ]; then
      degrade_to_rollback "app container has no address after redeploy"
    elif ! poll "$CURL_TARGET" 30; then
      degrade_to_rollback "app container health check ($CURL_TARGET)"
    else
      echo "    container OK: $CURL_TARGET"
      echo "--- app health check (public URL) ---"
      if poll "$APP_URL" 12; then
        echo "    public OK: $APP_URL"
      else
        degrade_to_rollback "public URL health check ($APP_URL) — container up, so this is the reverse proxy, not the app"
      fi
    fi
  fi
else
  # Deploy skipped on a port mismatch: confirm the existing container really
  # serves before we spend time screenshotting it.
  echo "--- app health check (existing container, deploy skipped) ---"
  CURL_TARGET="$(container_url)"
  { [ -n "$CURL_TARGET" ] && poll "$CURL_TARGET" 6; } \
    || fail "deploy was skipped on a port mismatch, but the running container is not answering either; no app to screenshot."
  echo "    existing container OK: $CURL_TARGET"
fi

echo "--- capture screenshots ---"
python3 deck/capture_screenshots.py || fail "capture_screenshots"
python3 deck/capture_diagrams.py     || true
python3 deck/capture_cli_menu.py     || true
python3 deck/capture_test_log.py     || true
python3 deck/capture_git_workflow.py || true
python3 deck/capture_ci_router.py     || true

echo "--- fetch metrics ---"
python3 deck/fetch_metrics.py || fail "fetch_metrics"

echo "--- author spotlights (headless) ---"
rm -f "$GEN_SPOTLIGHTS" "$GEN_CAPS"
claude -p "$(cat "$REPO/deck/weekly-authoring-prompt.md")" \
  --allowedTools "Bash(python3 *),Bash(ls *),Bash(glab *),Read,Write,Edit" 2>&1 | tail -25 \
  || echo "WARN: authoring step returned non-zero"
# Spotlights source (issue #258, Gap D). Prefer a freshly-curated committed set
# over headless authoring: if deck/latest-work-spotlights.yaml was committed
# AFTER this window opened (the previous Friday), a human curated it for THIS
# deck — use it. Otherwise use the headless-authored set; only if that is
# missing too fall back to auto-derive from labels. The date guard fails safe:
# if the window start can't be computed, the proven headless path is used.
CURATED="$REPO/deck/latest-work-spotlights.yaml"
WINDOW_START_EPOCH="$(date -d 'last friday 15:00' +%s 2>/dev/null || echo 0)"
CURATED_EPOCH="$(git -C "$REPO" log -1 --format=%ct -- deck/latest-work-spotlights.yaml 2>/dev/null || echo 0)"
if [ -f "$CURATED" ] && [ "$WINDOW_START_EPOCH" -gt 0 ] && [ "$CURATED_EPOCH" -gt "$WINDOW_START_EPOCH" ]; then
  echo "spotlights: using curated $CURATED (committed $(date -d "@$CURATED_EPOCH" +%F), newer than the window start)"
  SPOT="$CURATED"
elif [ -f "$GEN_SPOTLIGHTS" ]; then
  echo "spotlights: using headless-authored $GEN_SPOTLIGHTS"
  SPOT="$GEN_SPOTLIGHTS"
else
  echo "WARN: no curated or authored spotlights — auto-deriving from labels"
  SPOT="/nonexistent.yaml"
fi

echo "--- build deck ---"
BUILD_ARGS=(--spotlights "$SPOT")
[ -n "$DEGRADED" ] && BUILD_ARGS+=(--degraded "$DEGRADED")
python3 deck/build_deck.py "${BUILD_ARGS[@]}" || fail "build_deck"
DECK="$(ls -t deck/dist/NCE-Safe-Simulator-Status-*.pptx 2>/dev/null | head -1)"
[ -n "$DECK" ] || fail "no deck produced"
KEY="$S3_PREFIX/$(basename "$DECK")"

echo "--- upload to S3 ---"
aws s3 cp "$DECK" "s3://$BUCKET/$KEY" --only-show-errors || fail "s3 upload"
URL="$(aws s3 presign "s3://$BUCKET/$KEY" --expires-in 604800)"
SLIDES="$(python3 -c "from pptx import Presentation;print(len(Presentation('$DECK').slides))" 2>/dev/null || echo '?')"

# Capability updates proposed by the authoring step render in this week's deck
# but still need review + committing into capabilities.yaml — call that out.
CAPS_NOTE=""
[ -f "$GEN_CAPS" ] && CAPS_NOTE="
Capability-area updates were proposed (already rendered in this deck):
review $GEN_CAPS and fold accepted changes into deck/capabilities.yaml.
"

echo "--- notify success ---"
# A degraded run still ships a deck (that is the point of #258) — but say so
# loudly so nobody mistakes a fallback build for a clean one.
SUBJECT="NCE Safe Simulator - Weekly Status Deck ready"
DEGRADED_NOTE=""
if [ -n "$DEGRADED" ]; then
  SUBJECT="NCE Safe Simulator - Weekly Status Deck ready (DEGRADED)"
  DEGRADED_NOTE="
*** DEGRADED BUILD — a deck was produced, but not a clean run ***
$DEGRADED
"
fi
notify "$SUBJECT" "The weekly status deck built successfully.
$DEGRADED_NOTE
Deck:  $(basename "$DECK")  ($SLIDES slides)
Built: $(TZ=America/Los_Angeles date '+%A %F %H:%M %Z')
$CAPS_NOTE

Download (link valid 7 days):
$URL

Or pull via CLI:
aws s3 cp s3://$BUCKET/$KEY ."
echo "=== done @ $(TZ=America/Los_Angeles date '+%F %T %Z') ==="
