#!/usr/bin/env bash
# Survey deployed AWS resources for the NCE Safe Simulator stack.
# Usage: bash cdk/scripts/aws-survey.sh [--region us-east-1]

set -uo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-1}"
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

section() { echo; echo -e "${BOLD}${CYAN}━━━  $*  ━━━${RESET}"; }
row()     { printf "  %-28s %s\n" "$1" "$2"; }
ok()      { echo -e "  ${GREEN}✔${RESET}  $*"; }
warn()    { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()     { echo -e "  ${RED}✖${RESET}  $*"; }

# Safe AWS query: returns "null" on any error.
aws_q() { aws "$@" --region "$REGION" --output json 2>/dev/null || echo "null"; }

# Run a Python heredoc with JSON passed safely via env var NCE_JSON.
# Usage:  run_py "$json_var" <<'PYEOF'  ...  PYEOF
run_py() {
  NCE_JSON="${1:-null}" python3 - 2>/dev/null || true
}

# ── Header ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║     NCE Safe Simulator — AWS Resource Survey         ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════╝${RESET}"
echo -e "  Region : ${CYAN}${REGION}${RESET}"
echo -e "  Time   : $(date '+%Y-%m-%d %H:%M:%S %Z')"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
echo -e "  Account: ${CYAN}${ACCOUNT}${RESET}"

# ── ECS ───────────────────────────────────────────────────────────────────────
section "ECS — Cluster & Service"

CLUSTER="nce"
SVC="nce-safe-simulator"

SVC_JSON=$(aws_q ecs describe-services --cluster "$CLUSTER" --services "$SVC")
SVC_COUNT=$(NCE_JSON="$SVC_JSON" python3 -c "import json,os; print(len(json.loads(os.environ['NCE_JSON']).get('services',[])))" 2>/dev/null || echo "0")

if [[ "$SVC_COUNT" == "0" ]]; then
  err "Service $SVC not found in cluster $CLUSTER"
else
  run_py "$SVC_JSON" <<'PYEOF'
import json, os
d = json.loads(os.environ['NCE_JSON'])
s = d['services'][0]
status  = s['status']
running = s['runningCount']
desired = s['desiredCount']
pending = s['pendingCount']
tdef    = s['taskDefinition'].split('/')[-1]
created = str(s['createdAt'])[:19]
colour  = '\033[0;32m' if running == desired else '\033[1;33m'
sym     = '\033[0;32m✔\033[0m' if running == desired else '\033[1;33m⚠\033[0m'
reset   = '\033[0m'
print(f"  {sym}  {s['serviceName']}  — {colour}{status}{reset}")
print(f"  {'Tasks':<28} {running} running / {desired} desired / {pending} pending")
print(f"  {'Task definition':<28} {tdef}")
print(f"  {'Created':<28} {created}")
PYEOF

  TASK_ARNS=$(aws_q ecs list-tasks --cluster "$CLUSTER" --service-name "$SVC" --desired-status RUNNING \
    | NCE_JSON="$(cat)" python3 -c "import json,os; [print(a) for a in json.loads(os.environ.get('NCE_JSON','null') or 'null').get('taskArns',[])]" 2>/dev/null || true)

  if [[ -n "${TASK_ARNS:-}" ]]; then
    TASK_JSON=$(aws ecs describe-tasks --cluster "$CLUSTER" --tasks $TASK_ARNS --region "$REGION" --output json 2>/dev/null || echo "null")
    run_py "$TASK_JSON" <<'PYEOF'
import json, os
d = json.loads(os.environ['NCE_JSON'])
for t in d.get('tasks', []):
    tid     = t['taskArn'].split('/')[-1][:16]
    cpu     = t.get('cpu','?')
    mem     = t.get('memory','?')
    started = str(t.get('startedAt','?'))[:19]
    hc      = t.get('healthStatus','UNKNOWN')
    colour  = '\033[0;32m' if hc == 'HEALTHY' else '\033[1;33m'
    print(f"  {'  Task':<28} {tid}  health={colour}{hc}\033[0m  cpu={cpu}m  mem={mem}MB  started={started}")
PYEOF
  fi
fi

# ── ALB ───────────────────────────────────────────────────────────────────────
section "ALB — Load Balancer"

ALB_JSON=$(aws_q elbv2 describe-load-balancers --names "nce-alb")
ALB_COUNT=$(NCE_JSON="$ALB_JSON" python3 -c "import json,os; print(len(json.loads(os.environ['NCE_JSON']).get('LoadBalancers',[])))" 2>/dev/null || echo "0")

if [[ "$ALB_COUNT" == "0" ]]; then
  err "ALB nce-alb not found"
else
  ALB_ARN=$(NCE_JSON="$ALB_JSON" python3 -c "import json,os; print(json.loads(os.environ['NCE_JSON'])['LoadBalancers'][0]['LoadBalancerArn'])" 2>/dev/null)

  run_py "$ALB_JSON" <<'PYEOF'
import json, os
lb     = json.loads(os.environ['NCE_JSON'])['LoadBalancers'][0]
state  = lb['State']['Code']
colour = '\033[0;32m' if state == 'active' else '\033[1;33m'
sym    = '\033[0;32m✔\033[0m' if state == 'active' else '\033[1;33m⚠\033[0m'
print(f"  {sym}  {lb['LoadBalancerName']}  — {colour}{state}\033[0m  ({lb['Type']})")
print(f"  {'DNS':<28} {lb['DNSName']}")
print(f"  {'Created':<28} {str(lb.get('CreatedTime','?'))[:19]}")
PYEOF

  if [[ -n "${ALB_ARN:-}" ]]; then
    TG_JSON=$(aws_q elbv2 describe-target-groups --load-balancer-arn "$ALB_ARN")
    TG_ARNS=$(NCE_JSON="$TG_JSON" python3 -c "import json,os; [print(t['TargetGroupArn']) for t in json.loads(os.environ['NCE_JSON']).get('TargetGroups',[])]" 2>/dev/null || true)
    for TG_ARN in ${TG_ARNS:-}; do
      HEALTH_JSON=$(aws_q elbv2 describe-target-health --target-group-arn "$TG_ARN")
      run_py "$HEALTH_JSON" <<'PYEOF'
import json, os
targets = json.loads(os.environ['NCE_JSON']).get('TargetHealthDescriptions', [])
healthy = sum(1 for t in targets if t['TargetHealth']['State'] == 'healthy')
total   = len(targets)
colour  = '\033[0;32m' if healthy == total and total > 0 else '\033[1;33m'
print(f"  {'Target health':<28} {colour}{healthy}/{total} healthy\033[0m")
PYEOF
    done
  fi
fi

# ── CloudFront ────────────────────────────────────────────────────────────────
section "CloudFront — Distribution"

CF_JSON=$(aws cloudfront list-distributions --output json 2>/dev/null || echo "null")
if [[ "$CF_JSON" == "null" || -z "$CF_JSON" ]]; then
  err "Could not retrieve CloudFront distributions"
else
  run_py "$CF_JSON" <<'PYEOF'
import json, os
items = json.loads(os.environ['NCE_JSON']).get('DistributionList', {}).get('Items', [])
if not items:
    print("  (no distributions found)")
for d in items:
    status  = d['Status']
    state   = 'Enabled' if d.get('Enabled') else 'Disabled'
    aliases = ', '.join(d.get('Aliases', {}).get('Items', [])) or '(none)'
    colour  = '\033[0;32m' if status == 'Deployed' else '\033[1;33m'
    sym     = '\033[0;32m✔\033[0m' if status == 'Deployed' else '\033[1;33m⚠\033[0m'
    print(f"  {sym}  {d['Id']}  — {colour}{status}\033[0m  ({state})")
    print(f"  {'Domain':<28} {d['DomainName']}")
    print(f"  {'Aliases':<28} {aliases}")
PYEOF
fi

# ── EFS ───────────────────────────────────────────────────────────────────────
section "EFS — File Systems"

EFS_JSON=$(aws_q efs describe-file-systems)
run_py "$EFS_JSON" <<'PYEOF'
import json, os
fss = json.loads(os.environ['NCE_JSON']).get('FileSystems', [])
if not fss:
    print("  (no EFS file systems found)")
for fs in fss:
    fsid    = fs['FileSystemId']
    state   = fs['LifeCycleState']
    size_gb = fs['SizeInBytes']['Value'] / (1024**3)
    name    = next((t['Value'] for t in fs.get('Tags', []) if t['Key'] == 'Name'), fsid)
    colour  = '\033[0;32m' if state == 'available' else '\033[1;33m'
    print(f"  \033[0;32m✔\033[0m  {name} ({fsid})  — {colour}{state}\033[0m  {size_gb:.2f} GB used")
PYEOF

# ── AMG (Grafana) ─────────────────────────────────────────────────────────────
section "Grafana — AMG Workspace"

AMG_JSON=$(aws_q grafana list-workspaces)
run_py "$AMG_JSON" <<'PYEOF'
import json, os
wss = json.loads(os.environ['NCE_JSON']).get('workspaces', [])
if not wss:
    print("  (no AMG workspaces found)")
for ws in wss:
    status = ws.get('status', '?')
    ep     = ws.get('endpoint', '?')
    colour = '\033[0;32m' if status == 'ACTIVE' else '\033[1;33m'
    sym    = '\033[0;32m✔\033[0m' if status == 'ACTIVE' else '\033[1;33m⚠\033[0m'
    print(f"  {sym}  {ws.get('name', ws['id'])} ({ws['id']})  — {colour}{status}\033[0m")
    print(f"  {'Endpoint':<28} https://{ep}")
PYEOF

# ── CloudWatch Log Groups ─────────────────────────────────────────────────────
section "CloudWatch — Log Groups"

LOG_JSON=$(aws_q logs describe-log-groups --log-group-name-prefix "/ecs/nce")
run_py "$LOG_JSON" <<'PYEOF'
import json, os
groups = json.loads(os.environ['NCE_JSON']).get('logGroups', [])
if not groups:
    print("  (no /ecs/nce* log groups found)")
for g in groups:
    name      = g['logGroupName']
    retention = g.get('retentionInDays', 'never expires')
    size_mb   = g.get('storedBytes', 0) / (1024**2)
    print(f"  \033[0;32m✔\033[0m  {name}")
    print(f"  {'Stored':<28} {size_mb:.1f} MB   retention={retention} days")
PYEOF

# ── SSM Parameters ────────────────────────────────────────────────────────────
section "SSM — Parameters"

SSM_JSON=$(aws_q ssm describe-parameters --parameter-filters "Key=Name,Option=BeginsWith,Values=/nce/")
run_py "$SSM_JSON" <<'PYEOF'
import json, os
params = json.loads(os.environ['NCE_JSON']).get('Parameters', [])
if not params:
    print("  (no /nce/* parameters found)")
for p in params:
    raw = p.get('LastModifiedDate')
    if isinstance(raw, (int, float)):
        from datetime import datetime, timezone
        modified = datetime.fromtimestamp(raw, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
    else:
        modified = str(raw)[:16]
    print(f"  \033[0;32m✔\033[0m  {p['Name']}  \033[2m({p['Type']}, modified {modified})\033[0m")
PYEOF

# ── ECR — Container Repositories ─────────────────────────────────────────────
section "ECR — Container Repositories"

ECR_JSON=$(aws_q ecr describe-repositories)
run_py "$ECR_JSON" <<'PYEOF'
import json, os
repos = json.loads(os.environ['NCE_JSON']).get('repositories', [])
nce   = [r for r in repos if 'nce' in r['repositoryName']]
show  = nce if nce else repos
if not show:
    print("  (no repositories found)")
for r in show:
    raw = r.get('createdAt')
    if isinstance(raw, (int, float)):
        from datetime import datetime, timezone
        created = datetime.fromtimestamp(raw, tz=timezone.utc).strftime('%Y-%m-%d')
    else:
        created = str(raw)[:10]
    print(f"  \033[0;32m✔\033[0m  {r['repositoryName']}  \033[2m(created {created})\033[0m")
    print(f"  {'URI':<28} {r['repositoryUri']}")
PYEOF

# ── Cost Explorer ─────────────────────────────────────────────────────────────
section "Cost — Current Month (USD)"

START=$(date '+%Y-%m-01')
END=$(date '+%Y-%m-%d')

COST_JSON=$(aws ce get-cost-and-usage \
  --time-period "Start=${START},End=${END}" \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region us-east-1 \
  --output json 2>/dev/null || echo "null")

if [[ "$COST_JSON" == "null" ]]; then
  warn "Cost Explorer unavailable (requires ce:GetCostAndUsage permission)"
else
  run_py "$COST_JSON" <<'PYEOF'
import json, os
results = json.loads(os.environ['NCE_JSON']).get('ResultsByTime', [])
if not results:
    print("  (no cost data)")
else:
    rows = sorted(
        [(float(g['Metrics']['UnblendedCost']['Amount']), g['Keys'][0])
         for g in results[0].get('Groups', [])
         if float(g['Metrics']['UnblendedCost']['Amount']) > 0.001],
        reverse=True
    )
    total = sum(a for a, _ in rows)
    for amt, svc in rows:
        bar = '█' * max(1, int((amt / total) * 30)) if total else ''
        print(f"  {svc:<42}  ${amt:>8.2f}  \033[0;36m{bar}\033[0m")
    print(f"\n  {'─'*55}")
    print(f"  {'Total (month-to-date)':<42}  ${total:>8.2f}")
PYEOF
fi

# ── Footer ────────────────────────────────────────────────────────────────────
echo
echo -e "${DIM}────────────────────────────────────────────────────────${RESET}"
echo -e "${DIM}Survey complete — $(date '+%H:%M:%S')${RESET}"
echo
