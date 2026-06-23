#!/usr/bin/env bash
# Full stack teardown and redeploy — designed for unattended nohup runs.
# Usage (from cdk/ or anywhere):
#   nohup bash cdk/scripts/redeploy.sh > redeploy.log 2>&1 &
#   tail -f redeploy.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$(dirname "$SCRIPT_DIR")"
cd "$CDK_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*"; exit 1; }

log "========================================="
log " NCE Safe Simulator — Teardown + Redeploy"
log "========================================="
log "Working directory: $(pwd)"

# ── Step 1: Destroy ──────────────────────────────────────────────────────────
log ""
log "--- [1/5] Destroying existing stack ---"
if cdk destroy NceStack --force; then
  log "Stack destroyed."
else
  # Stack may not exist on first run — that's fine
  log "Destroy returned non-zero (stack may not have existed). Continuing."
fi

# ── Step 2: Fresh deploy ──────────────────────────────────────────────────────
log ""
log "--- [2/5] Deploying stack (fresh) ---"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region 2>/dev/null || \
         aws ec2 describe-availability-zones \
           --query 'AvailabilityZones[0].RegionName' --output text)
APP_NAME=$(jq -r '.context.app_name' cdk.json)
CLUSTER=$(jq -r '.context.cluster_name' cdk.json)
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${APP_NAME}"

log "Account: ${ACCOUNT}, Region: ${REGION}, App: ${APP_NAME}"

log "==> Deploying infra with service scaled to 0 tasks..."
cdk deploy NceStack --require-approval never --context desired_count=0

log "==> Building Docker image for linux/arm64..."
docker build --platform linux/arm64 -t "${APP_NAME}" ../

log "==> Pushing image to ECR..."
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin \
    "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
docker tag "${APP_NAME}:latest" "${REPO}:latest"
docker push "${REPO}:latest"
log "==> Image pushed."

log "==> Scaling service up to 1 task..."
cdk deploy NceStack --require-approval never

# ── Step 3: Seed config ───────────────────────────────────────────────────────
log ""
log "--- [3/5] Seeding config into SSM ---"
CONFIG_PARAM=$(jq -r '.context.config_param' cdk.json)
[ -f ../config.json ] || fail "config.json not found at $(realpath ../config.json)"
aws ssm put-parameter \
  --name "${CONFIG_PARAM}" \
  --type SecureString \
  --overwrite \
  --value "$(cat ../config.json)" \
  --region "${REGION}"
log "Config stored at ${CONFIG_PARAM}."

# ── Step 4: Wait for ECS to stabilize ────────────────────────────────────────
log ""
log "--- [4/5] Waiting for ECS service to stabilize ---"
log "Cluster: ${CLUSTER}, Service: ${APP_NAME}"
# Force a new deployment so the task picks up the freshly seeded config
SERVICE_ARN=$(aws ecs update-service \
  --cluster "${CLUSTER}" \
  --service "${APP_NAME}" \
  --force-new-deployment \
  --region "${REGION}" \
  --output text --query 'service.serviceArn')
log "Service ARN: ${SERVICE_ARN}"

log "Waiting for running count to reach desired (this can take a few minutes)..."
aws ecs wait services-stable \
  --cluster "${CLUSTER}" \
  --services "${APP_NAME}" \
  --region "${REGION}"
log "ECS service is stable."

# ── Step 5: Grafana ───────────────────────────────────────────────────────────
log ""
log "--- [5/5] Setting up Grafana ---"
WORKSPACE_ID=$(aws grafana list-workspaces --region "${REGION}" \
  --query "workspaces[?name=='${APP_NAME}'].id" --output text)
[ -n "${WORKSPACE_ID}" ] || fail "Grafana workspace not found — CDK deploy may have failed."
log "Workspace: ${WORKSPACE_ID}"

GRAFANA_API_KEY_PARAM=$(jq -r '.context.grafana_api_key_param' cdk.json)

log "==> Creating Grafana Admin API key..."
KEY=$(aws grafana create-workspace-api-key \
  --key-name "nce-deploy" \
  --key-role "ADMIN" \
  --seconds-to-live 2592000 \
  --workspace-id "${WORKSPACE_ID}" \
  --region "${REGION}" \
  --query 'key' --output text)
aws ssm put-parameter \
  --name "${GRAFANA_API_KEY_PARAM}" \
  --type SecureString \
  --overwrite \
  --value "${KEY}" \
  --region "${REGION}"
log "API key stored at ${GRAFANA_API_KEY_PARAM}."

log "==> Deploying dashboards..."
GRAFANA_URL="https://${WORKSPACE_ID}.grafana-workspace.${REGION}.amazonaws.com"
DATA_URL=$(aws cloudformation describe-stacks \
  --stack-name NceStack \
  --region "${REGION}" \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontUrl`].OutputValue' \
  --output text)
[ -n "${DATA_URL}" ] || fail "CloudFrontUrl not found in NceStack outputs."

log "Grafana URL: ${GRAFANA_URL}"
log "Data URL:    ${DATA_URL}"

# Install Infinity plugin
PLUGIN_VER=$(curl -sf "${GRAFANA_URL}/api/plugins/yesoreyeram-infinity-datasource/settings" \
  -H "Authorization: Bearer ${KEY}" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('info',{}).get('version',''))" 2>/dev/null || echo "")
if [ -n "${PLUGIN_VER}" ]; then
  log "  Infinity plugin already installed (v${PLUGIN_VER})"
else
  INSTALL_CODE=$(curl -sf -o /dev/null -w "%{http_code}" -X POST \
    "${GRAFANA_URL}/api/plugins/yesoreyeram-infinity-datasource/install" \
    -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \
    -d '{"version":"2.11.0"}')
  [ "${INSTALL_CODE}" = "200" ] || fail "Plugin install returned HTTP ${INSTALL_CODE}"
  log "  Installed yesoreyeram-infinity-datasource 2.11.0"
fi

# Configure datasource (access: direct — browser fetches CloudFront directly)
DS_PAYLOAD="{\"uid\":\"ffon28bht91c0b\",\"name\":\"Infinity\",\"type\":\"yesoreyeram-infinity-datasource\",\"access\":\"direct\",\"isDefault\":true,\"url\":\"${DATA_URL}\",\"jsonData\":{}}"
EXISTING_DS=$(curl -sf "${GRAFANA_URL}/api/datasources/name/Infinity" \
  -H "Authorization: Bearer ${KEY}" 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")
if [ -n "${EXISTING_DS}" ]; then
  curl -sf -X PUT "${GRAFANA_URL}/api/datasources/${EXISTING_DS}" \
    -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \
    -d "${DS_PAYLOAD}" > /dev/null
  log "  Updated datasource (id=${EXISTING_DS})"
else
  curl -sf -X POST "${GRAFANA_URL}/api/datasources" \
    -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \
    -d "${DS_PAYLOAD}" > /dev/null
  log "  Created datasource"
fi

# Deploy dashboards
find ../grafana -name '*.json' | sort | while read -r DASH; do
  PATCHED=$(sed "s|__BASE_URL__|${DATA_URL}|g" "${DASH}")
  TITLE=$(echo "${PATCHED}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('title','unknown'))")
  RESULT=$(echo "{\"dashboard\":${PATCHED},\"overwrite\":true,\"folderId\":0}" | \
    curl -sf -X POST "${GRAFANA_URL}/api/dashboards/import" \
      -H "Authorization: Bearer ${KEY}" -H "Content-Type: application/json" \
      -d @- 2>&1) && \
    log "  ✓ ${TITLE}" || log "  ✗ ${TITLE}: ${RESULT}"
done

log "==> Assigning Grafana Admin to SSO user..."
bash "${SCRIPT_DIR}/add-grafana-user.sh"

log ""
log "========================================="
log " Redeploy complete."
log " App:     https://$(aws cloudformation describe-stacks --stack-name NceStack --region "${REGION}" --query 'Stacks[0].Outputs[?OutputKey==`AlbDnsName`].OutputValue' --output text 2>/dev/null || echo '<see ALB in console>')"
log " Grafana: ${GRAFANA_URL}"
log "========================================="
