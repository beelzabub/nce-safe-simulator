#!/usr/bin/env bash
#
# Weekly status-deck build + email (issue #213). Invoked by nce-status-deck.service
# via the nce-status-deck.timer (Fri 14:00 America/Los_Angeles) on the box that
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

echo "--- rebuild + redeploy container ---"
make redeploy || fail "make redeploy"

echo "--- app health check ---"
ok=0
for _ in $(seq 1 30); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$APP_URL" || true)" = "200" ] && { ok=1; break; }
  sleep 5
done
[ "$ok" = "1" ] || fail "app health check ($APP_URL)"

echo "--- capture screenshots ---"
python3 deck/capture_screenshots.py || fail "capture_screenshots"
python3 deck/capture_diagrams.py     || true
python3 deck/capture_cli_menu.py     || true
python3 deck/capture_test_log.py     || true
python3 deck/capture_git_workflow.py || true

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
