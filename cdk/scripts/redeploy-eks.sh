#!/usr/bin/env bash
# Full EKS teardown and redeploy — designed for unattended nohup runs.
# Usage (from cdk/ or anywhere):
#   nohup bash cdk/scripts/redeploy-eks.sh > redeploy-eks.log 2>&1 &
#   tail -f redeploy-eks.log

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$(dirname "$SCRIPT_DIR")"
cd "$CDK_DIR"

log()  { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*"; exit 1; }

log "=============================================="
log " NCE Safe Simulator — EKS Teardown + Redeploy"
log "=============================================="
log "Working directory: $(pwd)"

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region 2>/dev/null || \
         aws ec2 describe-availability-zones \
           --query 'AvailabilityZones[0].RegionName' --output text)
APP_NAME=$(jq -r '.context.app_name' cdk.json)
NAMESPACE=$(jq -r '.context.eks_namespace' cdk.json)
CLUSTER=$(jq -r '.context.eks_cluster_name' cdk.json)
REPO="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${APP_NAME}"

log "Account: ${ACCOUNT}, Region: ${REGION}, App: ${APP_NAME}"

# ── Step 1: Destroy ────────────────────────────────────────────────────────────
log ""
log "--- [1/7] Tearing down existing EKS stack ---"
if helm uninstall "${APP_NAME}" --namespace "${NAMESPACE}" 2>/dev/null; then
  log "Helm release uninstalled."
else
  log "No helm release found — continuing."
fi
if CDK_DEFAULT_ACCOUNT="${ACCOUNT}" CDK_DEFAULT_REGION="${REGION}" \
   cdk destroy NceEksStack --force; then
  log "NceEksStack destroyed."
else
  log "Destroy returned non-zero (stack may not have existed). Continuing."
fi

# ── Step 2: Deploy CDK EKS stack ──────────────────────────────────────────────
log ""
log "--- [2/7] Deploying EKS CDK stack ---"
log "Note: EKS cluster creation typically takes 15-20 minutes."
CDK_DEFAULT_ACCOUNT="${ACCOUNT}" CDK_DEFAULT_REGION="${REGION}" \
  cdk deploy NceEksStack --require-approval never
log "NceEksStack deployed."

# ── Step 3: Configure kubectl ──────────────────────────────────────────────────
log ""
log "--- [3/7] Configuring kubectl ---"
aws eks update-kubeconfig --name "${CLUSTER}" --region "${REGION}"
log "kubectl configured for cluster ${CLUSTER}."

# ── Step 4: Build and push Docker image ───────────────────────────────────────
log ""
log "--- [4/7] Building and pushing Docker image ---"
aws ecr get-login-password --region "${REGION}" | \
  docker login --username AWS --password-stdin \
    "${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"
log "==> Building Docker image for linux/arm64..."
docker build --platform linux/arm64 -t "${APP_NAME}" ../
docker tag "${APP_NAME}:latest" "${REPO}:latest"
docker push "${REPO}:latest"
log "==> Image pushed to ${REPO}:latest"

# ── Step 5: Seed config and install Helm chart ────────────────────────────────
log ""
log "--- [5/7] Seeding config and installing Helm chart ---"
CONFIG_PARAM=$(jq -r '.context.config_param' cdk.json)
if [ -f ../config.json ]; then
  aws ssm put-parameter \
    --name "${CONFIG_PARAM}" \
    --type SecureString \
    --overwrite \
    --value "$(cat ../config.json)" \
    --region "${REGION}"
  log "Config stored at ${CONFIG_PARAM}."
else
  log "WARNING: config.json not found — skipping SSM seed (pod will read existing SSM value on boot)."
fi

EFS_ID=$(jq -r '.context.efs_id // empty' cdk.json)
[ -n "${EFS_ID}" ] || fail "efs_id not set in cdk.json — run 'make set-efs' first and re-run this script."

AP_CONFIG=$(jq -r '.context.efs_ap_config' cdk.json)
AP_REPORTS=$(jq -r '.context.efs_ap_reports' cdk.json)
AP_INTERACTIVE=$(jq -r '.context.efs_ap_interactive' cdk.json)
AP_QUARTO=$(jq -r '.context.efs_ap_quarto' cdk.json)
SA_ROLE_ARN=$(aws cloudformation describe-stacks --stack-name NceEksStack --region "${REGION}" \
  --query 'Stacks[0].Outputs[?OutputKey==`EksAppSaRoleArn`].OutputValue' --output text)
[ -n "${SA_ROLE_ARN}" ] || fail "EksAppSaRoleArn not found in NceEksStack outputs."

helm upgrade --install "${APP_NAME}" ../helm/nce-safe-simulator \
  --namespace "${NAMESPACE}" --create-namespace \
  --set image.repository="${REPO}" \
  --set serviceAccount.roleArn="${SA_ROLE_ARN}" \
  --set efs.fileSystemId="${EFS_ID}" \
  --set efs.accessPoints.config="${AP_CONFIG}" \
  --set efs.accessPoints.reports="${AP_REPORTS}" \
  --set efs.accessPoints.interactive="${AP_INTERACTIVE}" \
  --set efs.accessPoints.quartoSite="${AP_QUARTO}"
log "Helm release installed in namespace ${NAMESPACE}."

# ── Step 6: Wait for pod and capture ALB DNS ──────────────────────────────────
log ""
log "--- [6/7] Waiting for pod and ALB ---"
log "Waiting for deployment rollout..."
kubectl rollout status deployment/"${APP_NAME}" -n "${NAMESPACE}" --timeout=300s
log "Pod is running."

log "Waiting for ALB DNS to be assigned (up to 3 min)..."
ALB_DNS=""
for i in $(seq 1 18); do
  ALB_DNS=$(kubectl get ingress -n "${NAMESPACE}" "${APP_NAME}" \
    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
  if [ -n "${ALB_DNS}" ]; then break; fi
  printf "  [%02d/18] ALB not ready yet — waiting 10s...\n" "${i}"
  sleep 10
done
[ -n "${ALB_DNS}" ] || fail "ALB DNS never became available — check LB controller logs."
jq --arg v "${ALB_DNS}" '.context.eks_alb_dns = $v' cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json
log "ALB DNS: ${ALB_DNS}"

# ── CloudFront: create or update ──────────────────────────────────────────────
EXISTING_CF_ID=$(jq -r '.context.eks_cf_distribution_id // empty' cdk.json)
DIST_CONFIG=$(python3 - <<PYEOF
import json
alb_dns = "${ALB_DNS}"
config = {
    "CallerReference": "nce-eks-alb",
    "Comment": "NCE Safe Simulator EKS",
    "DefaultCacheBehavior": {
        "TargetOriginId": "nce-eks-alb",
        "ViewerProtocolPolicy": "https-only",
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",
        "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",
        "AllowedMethods": {
            "Quantity": 7,
            "Items": ["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"],
            "CachedMethods": {"Quantity": 2, "Items": ["GET","HEAD"]},
        },
        "Compress": True,
    },
    "Origins": {"Quantity": 1, "Items": [{
        "Id": "nce-eks-alb",
        "DomainName": alb_dns,
        "CustomOriginConfig": {
            "HTTPPort": 80, "HTTPSPort": 443,
            "OriginProtocolPolicy": "http-only",
        },
    }]},
    "Enabled": True,
    "HttpVersion": "http2",
}
print(json.dumps(config))
PYEOF
)

if [ -n "${EXISTING_CF_ID}" ]; then
  log "Updating existing CloudFront distribution ${EXISTING_CF_ID}..."
  ETAG=$(aws cloudfront get-distribution-config --id "${EXISTING_CF_ID}" \
    --query 'ETag' --output text)
  aws cloudfront update-distribution --id "${EXISTING_CF_ID}" --if-match "${ETAG}" \
    --distribution-config "${DIST_CONFIG}" > /dev/null
  DATA_URL=$(jq -r '.context.eks_cf_url' cdk.json)
  log "CloudFront distribution updated. URL: ${DATA_URL}"
else
  log "Creating CloudFront distribution for EKS ALB..."
  RESULT=$(aws cloudfront create-distribution --distribution-config "${DIST_CONFIG}")
  CF_ID=$(echo "${RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['Id'])")
  CF_DOMAIN=$(echo "${RESULT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['Distribution']['DomainName'])")
  DATA_URL="https://${CF_DOMAIN}"
  jq --arg id "${CF_ID}" --arg url "${DATA_URL}" \
    '.context.eks_cf_distribution_id = $id | .context.eks_cf_url = $url' \
    cdk.json > cdk.json.tmp && mv cdk.json.tmp cdk.json
  log "CloudFront distribution created: ${DATA_URL} (may take ~5 min to become active)"
fi

# ── Step 7: Grafana ────────────────────────────────────────────────────────────
log ""
log "--- [7/7] Setting up Grafana ---"
WORKSPACE_ID=$(aws grafana list-workspaces --region "${REGION}" \
  --query "workspaces[?name=='${APP_NAME}'].id" --output text)
[ -n "${WORKSPACE_ID}" ] || fail "Grafana workspace not found — ensure NceStack is deployed."
log "Workspace: ${WORKSPACE_ID}"

GRAFANA_URL="https://${WORKSPACE_ID}.grafana-workspace.${REGION}.amazonaws.com"
GRAFANA_API_KEY_PARAM=$(jq -r '.context.grafana_api_key_param' cdk.json)

log "==> Rotating Grafana Admin API key..."
aws grafana delete-workspace-api-key --key-name "nce-deploy" \
  --workspace-id "${WORKSPACE_ID}" --region "${REGION}" 2>/dev/null || true
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

log "==> Installing Infinity plugin (if needed)..."
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

log "==> Configuring Infinity datasource → ${DATA_URL}..."
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

log "==> Deploying dashboards..."
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
log "=============================================="
log " EKS Redeploy complete."
log " App:     http://${ALB_DNS}"
log " HTTPS:   ${DATA_URL}"
log " Grafana: ${GRAFANA_URL}"
log "=============================================="
