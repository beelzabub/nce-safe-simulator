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

echo "--- sync $REF ---"
git checkout "$REF"  || fail "git checkout $REF"
git pull --ff-only   || fail "git pull $REF"

# --- port agreement pre-flight (issue #309) --------------------------------
# The image and the reverse proxy come from *different checkouts*: the image is
# built here from $REF, while Caddy's config is bind-mounted from the live tree,
# which may sit on any branch. On 2026-08-07 develop's image listened on 80
# while Caddy dialled 8080, so the swap put up a container the proxy could not
# reach and the public site stayed down for five hours.
#
# Checked *before* the swap: on disagreement the run aborts with the running
# container untouched, so a mismatch costs a deck and never the site.
LIVE_TREE="/root/.venv/nce-safe-simulator"
CADDYFILE="$LIVE_TREE/deploy/Caddyfile"

image_port() {   # the port this ref's image will listen on, read from its Dockerfile
  grep -oE '^EXPOSE[[:space:]]+[0-9]+' Dockerfile 2>/dev/null | tail -1 | grep -oE '[0-9]+'
}
proxy_port() {   # the port Caddy is configured to dial
  grep -oE 'nce-safe-sim:[0-9]+' "$CADDYFILE" 2>/dev/null | head -1 | cut -d: -f2
}

# Read from the Dockerfile rather than a built image on purpose: this has to be
# answerable *before* anything is built or swapped, and EXPOSE is what the build
# would produce anyway.
IMG_PORT="$(image_port)"
PRX_PORT="$(proxy_port)"
echo "    image listens on ${IMG_PORT:-?}; proxy dials ${PRX_PORT:-?}"
if [ -n "$IMG_PORT" ] && [ -n "$PRX_PORT" ] && [ "$IMG_PORT" != "$PRX_PORT" ]; then
  fail "port mismatch — the $REF image listens on $IMG_PORT but the live Caddy config
($CADDYFILE, from $(git -C "$LIVE_TREE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?'))
dials $PRX_PORT. Deploying would take the public site down, so nothing was swapped.
Reconcile the two checkouts, then re-run."
fi

# Tag whatever is running now so a failed deploy can be undone.
PREV_IMAGE="$(docker inspect -f '{{.Image}}' "$APP_NAME" 2>/dev/null || true)"
if [ -n "$PREV_IMAGE" ]; then
  docker tag "$PREV_IMAGE" "$IMAGE_ROLLBACK" && echo "    rollback point: $IMAGE_ROLLBACK"
fi

echo "--- rebuild + redeploy container ---"
make redeploy || fail "make redeploy"

# --- health checks ---------------------------------------------------------
# Two distinct checks, reported separately. The container check proves the app
# itself came up; the public check proves the proxy can reach it. The deck build
# used to depend on the public URL alone, which let reverse-proxy config hold
# the whole run hostage without saying so.
container_url() {
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

rollback() {  # restore the previous container, then fail with $1
  if [ -n "$PREV_IMAGE" ]; then
    echo "==> rolling back to $IMAGE_ROLLBACK"
    if bash scripts/redeploy.sh --image "$IMAGE_ROLLBACK"; then
      local cu; cu="$(container_url)"
      if [ -n "$cu" ] && poll "$cu" 24; then
        echo "==> rollback healthy — the site is serving the previous image"
      else
        echo "==> WARNING: rollback container is not answering" >&2
      fi
    else
      echo "==> WARNING: rollback failed — the app container may be down" >&2
    fi
  else
    echo "==> no previous image recorded; nothing to roll back to" >&2
  fi
  fail "$1"
}

echo "--- app health check (container) ---"
CURL_TARGET="$(container_url)"
[ -n "$CURL_TARGET" ] || rollback "app container has no address after redeploy"
poll "$CURL_TARGET" 30 || rollback "app container health check ($CURL_TARGET)"
echo "    container OK: $CURL_TARGET"

echo "--- app health check (public URL) ---"
poll "$APP_URL" 12 || rollback "public URL health check ($APP_URL) — the container is up,
so this is the reverse proxy, not the app."
echo "    public OK: $APP_URL"

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
[ -f "$GEN_SPOTLIGHTS" ] && SPOT="$GEN_SPOTLIGHTS" \
  || { echo "WARN: no authored spotlights — auto-deriving from labels"; SPOT="/nonexistent.yaml"; }

echo "--- build deck ---"
python3 deck/build_deck.py --spotlights "$SPOT" || fail "build_deck"
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
notify "NCE Safe Simulator - Weekly Status Deck ready" "The weekly status deck built successfully.

Deck:  $(basename "$DECK")  ($SLIDES slides)
Built: $(TZ=America/Los_Angeles date '+%A %F %H:%M %Z')
$CAPS_NOTE

Download (link valid 7 days):
$URL

Or pull via CLI:
aws s3 cp s3://$BUCKET/$KEY ."
echo "=== done @ $(TZ=America/Los_Angeles date '+%F %T %Z') ==="
