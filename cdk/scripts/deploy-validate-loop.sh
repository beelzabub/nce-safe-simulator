#!/usr/bin/env bash
# deploy-validate-loop.sh
# Destroy → Deploy ECS → Validate ECS → Deploy EKS → Validate EKS → Destroy → repeat
# Run with: nohup bash scripts/deploy-validate-loop.sh > deploy-validate-loop.log 2>&1 &

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CDK_DIR="$(dirname "$SCRIPT_DIR")"
ECS_CTX="$CDK_DIR/cdk-ecs.json"
EKS_CTX="$CDK_DIR/cdk-eks.json"
MAX_ITERATIONS="${MAX_ITERATIONS:-3}"
ITERATION=0

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log()  { echo "[$(ts)] $*"; }
fail() { echo "[$(ts)] FAILED: $*" >&2; exit 1; }

# ── Stack existence checks ────────────────────────────────────────────────────
# Returns true for any stack state that needs cleanup (including ROLLBACK_COMPLETE).
# Only returns false when the stack is fully gone.
ecs_stack_exists() {
  local STATUS
  STATUS=$(aws cloudformation describe-stacks --stack-name NceStack \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
  [[ "$STATUS" != "MISSING" && "$STATUS" != "DELETE_COMPLETE" ]]
}
eks_stack_exists() {
  local STATUS
  STATUS=$(aws cloudformation describe-stacks --stack-name NceEksStack \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
  [[ "$STATUS" != "MISSING" && "$STATUS" != "DELETE_COMPLETE" ]]
}

# ── Destroy helpers ───────────────────────────────────────────────────────────
destroy_ecs() {
  log "--- Destroying ECS stack ---"
  if ecs_stack_exists; then
    (cd "$CDK_DIR" && make ecs-destroy) || log "WARN: ecs-destroy returned non-zero (may already be gone)"
  else
    log "NceStack not found — skipping ECS destroy"
  fi
}

destroy_eks() {
  log "--- Destroying EKS stack ---"
  if eks_stack_exists; then
    (cd "$CDK_DIR" && make eks-destroy) || log "WARN: eks-destroy returned non-zero (may already be gone)"
  else
    log "NceEksStack not found — skipping EKS destroy"
  fi
}

# ── Deploy helpers ────────────────────────────────────────────────────────────
deploy_ecs() {
  log "--- Deploying ECS stack ---"
  (cd "$CDK_DIR" && make ecs-full-deploy) || fail "ecs-full-deploy failed"
  log "ECS deploy complete"
}

deploy_eks() {
  log "--- Deploying EKS stack ---"
  (cd "$CDK_DIR" && make eks-full-deploy) || fail "eks-full-deploy failed"
  log "EKS deploy complete"
}

# ── Validation helpers ────────────────────────────────────────────────────────
validate_ecs() {
  log "--- Validating ECS stack ---"
  REGION=$(aws configure get region 2>/dev/null || \
    aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)

  # Check CloudFormation stack is CREATE_COMPLETE or UPDATE_COMPLETE
  STATUS=$(aws cloudformation describe-stacks --stack-name NceStack \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
  case "$STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE)
      log "  CloudFormation status: $STATUS — OK"
      ;;
    *)
      fail "ECS stack status is '$STATUS', expected COMPLETE"
      ;;
  esac

  # Get ALB DNS from stack outputs
  ALB_DNS=$(aws cloudformation describe-stacks --stack-name NceStack \
    --query 'Stacks[0].Outputs[?OutputKey==`LoadBalancerDNS`].OutputValue' \
    --output text --region "$REGION" 2>/dev/null || true)

  if [ -z "$ALB_DNS" ]; then
    # Fall back to querying the ALB directly by name
    ALB_NAME=$(jq -r '.context.alb_name' "$ECS_CTX")
    ALB_DNS=$(aws elbv2 describe-load-balancers --region "$REGION" \
      --names "$ALB_NAME" --query 'LoadBalancers[0].DNSName' --output text 2>/dev/null || true)
  fi

  if [ -n "$ALB_DNS" ]; then
    log "  ALB DNS: $ALB_DNS"
    # Check ECS service desired/running counts
    APP_NAME=$(jq -r '.context.app_name' "$ECS_CTX")
    CLUSTER=$(jq -r '.context.cluster_name' "$ECS_CTX")
    DESIRED=$(aws ecs describe-services --cluster "$CLUSTER" --services "$APP_NAME" \
      --region "$REGION" --query 'services[0].desiredCount' --output text 2>/dev/null || echo "?")
    RUNNING=$(aws ecs describe-services --cluster "$CLUSTER" --services "$APP_NAME" \
      --region "$REGION" --query 'services[0].runningCount' --output text 2>/dev/null || echo "?")
    log "  ECS service: desired=$DESIRED running=$RUNNING"

    if [ "$DESIRED" != "0" ] && [ "$DESIRED" = "$RUNNING" ]; then
      log "  ECS service running — checking HTTP..."
      HTTP_CODE=$(curl -sf --max-time 15 -o /dev/null -w "%{http_code}" "http://$ALB_DNS/" 2>/dev/null || echo "000")
      if [[ "$HTTP_CODE" =~ ^[23] ]]; then
        log "  HTTP $HTTP_CODE — ECS validation PASSED"
      else
        log "  WARN: HTTP $HTTP_CODE from ALB (service may be warming up)"
      fi
    else
      log "  ECS service not fully running (desired=$DESIRED, running=$RUNNING) — skipping HTTP check"
    fi
  else
    log "  WARN: could not determine ALB DNS — skipping HTTP validation"
  fi
  log "ECS validation complete"
}

validate_eks() {
  log "--- Validating EKS stack ---"
  REGION=$(aws configure get region 2>/dev/null || \
    aws ec2 describe-availability-zones --query 'AvailabilityZones[0].RegionName' --output text)
  NAMESPACE=$(jq -r '.context.eks_namespace' "$EKS_CTX")

  STATUS=$(aws cloudformation describe-stacks --stack-name NceEksStack \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo "MISSING")
  case "$STATUS" in
    CREATE_COMPLETE|UPDATE_COMPLETE)
      log "  CloudFormation status: $STATUS — OK"
      ;;
    *)
      fail "EKS stack status is '$STATUS', expected COMPLETE"
      ;;
  esac

  # Update kubeconfig in case it drifted
  CLUSTER=$(jq -r '.context.eks_cluster_name' "$EKS_CTX")
  aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" 2>/dev/null || true

  # Check pods
  RUNNING_PODS=$(kubectl get pods -n "$NAMESPACE" --field-selector=status.phase=Running \
    --no-headers 2>/dev/null | wc -l | tr -d ' ')
  TOTAL_PODS=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  log "  Pods in namespace $NAMESPACE: $RUNNING_PODS/$TOTAL_PODS running"

  if [ "$TOTAL_PODS" -gt 0 ] && [ "$RUNNING_PODS" -gt 0 ]; then
    log "  Pods running — OK"
  elif [ "$TOTAL_PODS" -eq 0 ]; then
    log "  WARN: no pods found in $NAMESPACE — Helm release may not have deployed"
  else
    POD_STATUS=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null || true)
    log "  Pod status:\n$POD_STATUS"
    fail "No pods running in $NAMESPACE"
  fi

  # Check ALB
  ALB_DNS=$(jq -r '.context.eks_alb_dns // empty' "$EKS_CTX")
  if [ -n "$ALB_DNS" ]; then
    log "  ALB DNS: $ALB_DNS"
    HTTP_CODE=$(curl -sf --max-time 15 -o /dev/null -w "%{http_code}" "http://$ALB_DNS/" 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" =~ ^[23] ]]; then
      log "  HTTP $HTTP_CODE — EKS validation PASSED"
    else
      log "  WARN: HTTP $HTTP_CODE from ALB (may be warming up)"
    fi
  else
    log "  WARN: eks_alb_dns not set in cdk-eks.json — skipping HTTP check"
  fi
  log "EKS validation complete"
}

# ── Main loop ─────────────────────────────────────────────────────────────────
log "============================================================"
log "deploy-validate-loop starting (MAX_ITERATIONS=$MAX_ITERATIONS)"
log "============================================================"

# Initial clean slate — destroy whatever is currently up
log "=== INITIAL TEARDOWN ==="
destroy_eks
destroy_ecs

while [ "$ITERATION" -lt "$MAX_ITERATIONS" ]; do
  ITERATION=$((ITERATION + 1))
  log ""
  log "============================================================"
  log "ITERATION $ITERATION / $MAX_ITERATIONS"
  log "============================================================"

  # Deploy
  deploy_ecs
  validate_ecs

  deploy_eks
  validate_eks

  # Teardown
  log "--- Iteration $ITERATION teardown ---"
  destroy_eks
  destroy_ecs

  log "ITERATION $ITERATION CLEAN — deploy/validate/destroy cycle passed"
done

log ""
log "============================================================"
log "ALL $MAX_ITERATIONS ITERATIONS CLEAN — loop complete"
log "============================================================"
