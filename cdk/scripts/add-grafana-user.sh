#!/usr/bin/env bash
set -euo pipefail

REGION=$(aws configure get region 2>/dev/null \
  || aws ec2 describe-availability-zones \
       --query 'AvailabilityZones[0].RegionName' --output text)
APP_NAME=$(jq -r '.context.app_name' "$(dirname "$0")/../cdk.json")

WORKSPACE_ID=$(aws grafana list-workspaces --region "$REGION" \
  --query "workspaces[?name=='$APP_NAME'].id" --output text)
[ -n "$WORKSPACE_ID" ] || { echo "ERROR: Grafana workspace not found — run make deploy first"; exit 1; }

SSO_USER_ID=$(jq -r '.context.grafana_admin_sso_user_id' "$(dirname "$0")/../cdk.json")

echo "==> Adding Admin permissions for $SSO_USER_ID in workspace $WORKSPACE_ID..."
aws grafana update-permissions \
  --workspace-id "$WORKSPACE_ID" \
  --region "$REGION" \
  --update-instruction-batch "[{\"action\":\"ADD\",\"role\":\"ADMIN\",\"users\":[{\"id\":\"$SSO_USER_ID\",\"type\":\"SSO_USER\"}]}]"
echo "==> Done."
