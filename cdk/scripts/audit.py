#!/usr/bin/env python3
"""
Audit AWS resources for NceStack (ECS) and NceEksStack (EKS).
Reads resource names from cdk-ecs.json and cdk-eks.json.
Usage: python3 scripts/audit.py   (or: make audit)
"""

import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ── Load context from the two CDK config files ──────────────────────────────
_root = Path(__file__).parent.parent
_ecs_ctx = json.loads((_root / "cdk-ecs.json").read_text())["context"]
_eks_ctx = json.loads((_root / "cdk-eks.json").read_text())["context"]

APP_NAME         = _ecs_ctx["app_name"]           # nce-safe-simulator
VPC_ID           = _ecs_ctx["vpc_id"]
CLUSTER_NAME     = _ecs_ctx["cluster_name"]        # nce
ALB_NAME         = _ecs_ctx["alb_name"]            # nce-alb
LOG_GROUP_ECS    = _ecs_ctx["log_group"]           # /ecs/nce-safe-simulator
SSM_PARAM        = _ecs_ctx["config_param"]        # /nce/config
ECS_STACK        = "NceStack"

EKS_CLUSTER_NAME = _eks_ctx["eks_cluster_name"]   # nce-eks
LOG_GROUP_EKS    = f"/eks/{EKS_CLUSTER_NAME}"
EKS_CF_ID        = _eks_ctx.get("eks_cf_distribution_id", "")
EKS_ALB_DNS      = _eks_ctx.get("eks_alb_dns", "")
EKS_STACK        = "NceEksStack"

ENABLE_GRAFANA   = str(_ecs_ctx.get("enable_grafana", False)).lower() in ("true", "1")

# ── Colour helpers ───────────────────────────────────────────────────────────
_tty = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if _tty else text

GREEN  = lambda t: _c("32", t)
RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

def _row(icon, label, status, note=""):
    note_str = f"  {DIM('(' + note + ')')}" if note else ""
    print(f"  {icon}  {label:<48} {status}{note_str}")

def ok(label, note=""):
    _row(GREEN("✓"), label, GREEN("deployed"), note)

def missing(label, note=""):
    _row(RED("✗"), label, RED("not found"), note)

def warn(label, note=""):
    _row(YELLOW("!"), label, YELLOW("orphaned / retained"), note)

def section(title):
    print(f"\n{BOLD(title)}")
    print("─" * 62)

# ── AWS clients ──────────────────────────────────────────────────────────────
session  = boto3.Session()
REGION   = session.region_name or "us-east-1"
ACCOUNT  = session.client("sts").get_caller_identity()["Account"]

cf_client  = session.client("cloudformation")
ecs_client = session.client("ecs")
eks_client = session.client("eks")
ecr_client = session.client("ecr")
efs_client = session.client("efs")
elb_client = session.client("elbv2")
logs_client= session.client("logs")
ssm_client = session.client("ssm")
cf_dist    = session.client("cloudfront")
ec2_client = session.client("ec2")
amg_client = session.client("grafana")

# ── Check helpers ────────────────────────────────────────────────────────────

def cf_stack_status(stack_name):
    try:
        r = cf_client.describe_stacks(StackName=stack_name)
        return r["Stacks"][0]["StackStatus"]
    except ClientError:
        return None

def ecs_cluster_active(name):
    r = ecs_client.describe_clusters(clusters=[name])
    return any(c["status"] == "ACTIVE" for c in r.get("clusters", []))

def eks_cluster_status(name):
    try:
        return eks_client.describe_cluster(name=name)["cluster"]["status"]
    except eks_client.exceptions.ResourceNotFoundException:
        return None

def ecr_repo_exists(name):
    try:
        ecr_client.describe_repositories(repositoryNames=[name])
        return True
    except ecr_client.exceptions.RepositoryNotFoundException:
        return False

def alb_by_name(name):
    try:
        r = elb_client.describe_load_balancers(Names=[name])
        lbs = r.get("LoadBalancers", [])
        return lbs[0] if lbs else None
    except elb_client.exceptions.LoadBalancerNotFoundException:
        return None

def albs_by_tag(tag_key, tag_value):
    """Return ALBs that carry a specific tag (used for K8s-provisioned ALBs)."""
    try:
        paginator = elb_client.get_paginator("describe_load_balancers")
        matches = []
        for page in paginator.paginate():
            arns = [lb["LoadBalancerArn"] for lb in page["LoadBalancers"]]
            if not arns:
                continue
            tags_resp = elb_client.describe_tags(ResourceArns=arns)
            for desc in tags_resp["TagDescriptions"]:
                tags = {t["Key"]: t["Value"] for t in desc["Tags"]}
                if tags.get(tag_key) == tag_value:
                    arn = desc["ResourceArn"]
                    lb = next(lb for lb in page["LoadBalancers"]
                              if lb["LoadBalancerArn"] == arn)
                    matches.append(lb)
        return matches
    except Exception:
        return []

def log_group_exists(name):
    r = logs_client.describe_log_groups(logGroupNamePrefix=name)
    return any(g["logGroupName"] == name for g in r.get("logGroups", []))

def ssm_param_exists(name):
    try:
        ssm_client.get_parameter(Name=name)
        return True
    except ssm_client.exceptions.ParameterNotFound:
        return False

def efs_for_stack(stack_name):
    """Return EFS file systems tagged with the given CF stack name."""
    r = efs_client.describe_file_systems()
    out = []
    for fs in r.get("FileSystems", []):
        tags = {t["Key"]: t["Value"] for t in fs.get("Tags", [])}
        if tags.get("aws:cloudformation:stack-name") == stack_name:
            out.append((fs, tags))
    return out

def efs_named(name):
    """Return EFS file systems with a Name tag matching name."""
    r = efs_client.describe_file_systems()
    out = []
    for fs in r.get("FileSystems", []):
        tags = {t["Key"]: t["Value"] for t in fs.get("Tags", [])}
        if tags.get("Name") == name:
            out.append((fs, tags))
    return out

def cloudfront_by_origin(origin_substr):
    """Find a CloudFront distribution whose first origin contains origin_substr."""
    paginator = cf_dist.get_paginator("list_distributions")
    for page in paginator.paginate():
        for dist in page.get("DistributionList", {}).get("Items", []):
            for origin in dist.get("Origins", {}).get("Items", []):
                if origin_substr in origin.get("DomainName", ""):
                    return dist
    return None

def cloudfront_by_id(dist_id):
    try:
        return cf_dist.get_distribution(Id=dist_id)["Distribution"]
    except Exception:
        return None

def ec2_nodes_for_eks(cluster_name):
    r = ec2_client.describe_instances(Filters=[
        {"Name": f"tag:kubernetes.io/cluster/{cluster_name}", "Values": ["owned"]},
        {"Name": "instance-state-name", "Values": ["running", "pending", "stopped"]},
    ])
    return sum(len(res["Instances"]) for res in r.get("Reservations", []))

def amg_workspaces():
    try:
        return amg_client.list_workspaces().get("workspaces", [])
    except Exception:
        return []

# ── Main audit ───────────────────────────────────────────────────────────────

def main():
    print()
    print(BOLD("=" * 62))
    print(BOLD("  NCE Safe Simulator — AWS Resource Audit"))
    print(f"  Account : {ACCOUNT}   Region : {REGION}")
    print(BOLD("=" * 62))

    # ── CloudFormation stacks ─────────────────────────────────────────────
    section("CloudFormation Stacks")
    for stack, label in [(ECS_STACK, "ECS stack (NceStack)"),
                         (EKS_STACK, "EKS stack (NceEksStack)")]:
        status = cf_stack_status(stack)
        if status:
            ok(label, status)
        else:
            missing(label)

    # ── ECS resources ────────────────────────────────────────────────────
    section(f"ECS / Fargate  ({ECS_STACK})")

    if ecs_cluster_active(CLUSTER_NAME):
        ok(f"ECS cluster: {CLUSTER_NAME}")
    else:
        missing(f"ECS cluster: {CLUSTER_NAME}")

    if ecr_repo_exists(APP_NAME):
        ok(f"ECR repository: {APP_NAME}")
    else:
        missing(f"ECR repository: {APP_NAME}")

    alb = alb_by_name(ALB_NAME)
    if alb:
        state = alb["State"]["Code"]
        ok(f"ALB: {ALB_NAME}", state)
    else:
        missing(f"ALB: {ALB_NAME}")

    if log_group_exists(LOG_GROUP_ECS):
        ok(f"CW log group: {LOG_GROUP_ECS}")
    else:
        missing(f"CW log group: {LOG_GROUP_ECS}")

    if ssm_param_exists(SSM_PARAM):
        ok(f"SSM parameter: {SSM_PARAM}")
    else:
        missing(f"SSM parameter: {SSM_PARAM}")

    # ECS EFS — tagged Name=nce-safe-simulator (file_system_name=app_name in stack)
    ecs_efs = efs_named(APP_NAME)
    if ecs_efs:
        for fs, tags in ecs_efs:
            fid   = fs["FileSystemId"]
            state = fs["LifeCycleState"]
            size  = fs["SizeInBytes"]["Value"] // (1024 ** 3)
            ok(f"EFS (ECS): {fid}", f"{state}, {size} GB")
    else:
        missing(f"EFS (ECS): (Name={APP_NAME})")

    # ECS CloudFront — find by ALB origin
    alb_dns = alb["DNSName"] if alb else ""
    cf_ecs = cloudfront_by_origin(ALB_NAME) if alb_dns else None
    if cf_ecs:
        ok(f"CloudFront (ECS): {cf_ecs['Id']}", cf_ecs.get("Status", ""))
    else:
        missing(f"CloudFront (ECS): (origin: {ALB_NAME})")

    # ── EKS resources ────────────────────────────────────────────────────
    section(f"EKS / Kubernetes  ({EKS_STACK})")

    eks_status = eks_cluster_status(EKS_CLUSTER_NAME)
    if eks_status:
        ok(f"EKS cluster: {EKS_CLUSTER_NAME}", eks_status)
    else:
        missing(f"EKS cluster: {EKS_CLUSTER_NAME}")

    if log_group_exists(LOG_GROUP_EKS):
        ok(f"CW log group: {LOG_GROUP_EKS}")
    else:
        missing(f"CW log group: {LOG_GROUP_EKS}")

    # EKS ALB — provisioned by K8s LBC, tagged with cluster name
    eks_albs = albs_by_tag(f"kubernetes.io/cluster/{EKS_CLUSTER_NAME}", "owned")
    if eks_albs:
        for lb in eks_albs:
            ok(f"ALB (EKS): {lb['DNSName'][:48]}", lb["State"]["Code"])
    else:
        missing(f"ALB (EKS): (tag: kubernetes.io/cluster/{EKS_CLUSTER_NAME})")

    # EKS EC2 node group
    node_count = ec2_nodes_for_eks(EKS_CLUSTER_NAME)
    if node_count > 0:
        ok(f"EC2 nodes (EKS): {EKS_CLUSTER_NAME}", f"{node_count} instance(s)")
    else:
        missing(f"EC2 nodes (EKS): {EKS_CLUSTER_NAME}")

    # EKS CloudFront — by ID stored in cdk-eks.json, else search by EKS ALB DNS
    if EKS_CF_ID:
        dist = cloudfront_by_id(EKS_CF_ID)
        if dist:
            ok(f"CloudFront (EKS): {EKS_CF_ID}", dist.get("Status", ""))
        else:
            missing(f"CloudFront (EKS): {EKS_CF_ID}")
    elif EKS_ALB_DNS:
        dist = cloudfront_by_origin(EKS_ALB_DNS)
        if dist:
            ok(f"CloudFront (EKS): {dist['Id']}", dist.get("Status", ""))
        else:
            missing(f"CloudFront (EKS): (origin: {EKS_ALB_DNS[:40]})")
    else:
        missing("CloudFront (EKS):", "eks_alb_dns not set in cdk-eks.json")

    # EKS EFS (RETAIN — survives stack destroy)
    eks_efs = efs_for_stack(EKS_STACK)
    if eks_efs:
        for fs, tags in eks_efs:
            fid   = fs["FileSystemId"]
            state = fs["LifeCycleState"]
            size  = fs["SizeInBytes"]["Value"] // (1024 ** 3)
            warn(f"EFS (EKS, RETAIN): {fid}",
                 f"{state}, {size} GB — delete manually when no longer needed")
    else:
        ok("EFS (EKS retained): none found", "clean")

    # ── Grafana (AMG) ────────────────────────────────────────────────────
    if ENABLE_GRAFANA:
        section("Grafana (AMG)")
        workspaces = amg_workspaces()
        nce_ws = [w for w in workspaces if w.get("name") == APP_NAME]
        if nce_ws:
            for ws in nce_ws:
                status = ws.get("status", "?")
                ep     = ws.get("endpoint", "?")
                ok(f"AMG workspace: {ws['id']}", f"{status}  https://{ep}")
        else:
            missing(f"AMG workspace: (name={APP_NAME})")

    print(f"\n{BOLD('=' * 62)}\n")


if __name__ == "__main__":
    main()
