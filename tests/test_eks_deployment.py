"""
Integration tests that validate a live EKS deployment of nce-safe-simulator.

Run:
    pytest tests/test_eks_deployment.py -v

Each test is independent and reports exactly what it found so failures
pinpoint which layer of the deployment stack broke.

Prerequisites:
    - AWS credentials in the environment
    - kubectl configured (run `make eks-kubeconfig` first, or let the
      eks_kubeconfig fixture do it)
    - boto3, requests installed (already in requirements.txt)
"""
import json
import subprocess
import time
from pathlib import Path

import boto3
import pytest
import requests

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CDK_JSON = Path(__file__).parent.parent / "cdk" / "cdk-eks.json"


def _ctx():
    """Return the CDK context dict."""
    return json.loads(CDK_JSON.read_text())["context"]


def _region():
    session = boto3.session.Session()
    return session.region_name or "us-east-1"


def _kubectl(*args, check=True):
    """Run kubectl and return stdout as a string."""
    result = subprocess.run(
        ["kubectl", *args],
        capture_output=True, text=True, check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"kubectl {' '.join(args)} failed:\n{result.stderr}"
        )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ctx():
    if not CDK_JSON.exists():
        pytest.skip(f"{CDK_JSON.name} not present — no deployed stack")
    return _ctx()


@pytest.fixture(scope="session", autouse=True)
def eks_kubeconfig(ctx):
    """Ensure kubectl is pointed at the right cluster before any test runs."""
    cluster = ctx.get("eks_cluster_name", "nce-eks")
    region = _region()
    try:
        result = subprocess.run(
            ["aws", "eks", "update-kubeconfig", "--name", cluster, "--region", region],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        pytest.skip("aws CLI not available — no deployed stack")
    if result.returncode != 0:
        pytest.skip(
            f"could not configure kubectl for cluster '{cluster}' — "
            "no AWS credentials or no deployed stack"
        )


# ---------------------------------------------------------------------------
# Layer 1 — CloudFormation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_cfn_stack_healthy(ctx):
    """NceEksStack must be in a terminal healthy state."""
    cf = boto3.client("cloudformation", region_name=_region())
    stacks = cf.describe_stacks(StackName="NceEksStack")["Stacks"]
    assert stacks, "NceEksStack not found"
    status = stacks[0]["StackStatus"]
    healthy = {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}
    assert status in healthy, (
        f"NceEksStack is in status '{status}' — expected one of {healthy}"
    )


@pytest.mark.integration
def test_cfn_stack_outputs_present(ctx):
    """NceEksStack must export the keys that downstream steps depend on."""
    cf = boto3.client("cloudformation", region_name=_region())
    outputs = cf.describe_stacks(StackName="NceEksStack")["Stacks"][0].get("Outputs", [])
    keys = {o["OutputKey"] for o in outputs}
    required = {"EksAppSaRoleArn", "EfsId", "EfsApConfig", "EfsApReports",
                "EfsApInteractive", "EfsApQuartoSite"}
    missing = required - keys
    assert not missing, f"Missing CloudFormation outputs: {missing}"


# ---------------------------------------------------------------------------
# Layer 2 — EKS cluster
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_eks_cluster_active(ctx):
    """EKS cluster must be ACTIVE."""
    eks = boto3.client("eks", region_name=_region())
    cluster = eks.describe_cluster(name=ctx["eks_cluster_name"])["cluster"]
    assert cluster["status"] == "ACTIVE", (
        f"Cluster status is '{cluster['status']}' — expected ACTIVE"
    )


@pytest.mark.integration
def test_eks_nodes_ready(ctx):
    """At least one node must be in Ready condition."""
    raw = _kubectl("get", "nodes", "-o", "json")
    nodes = json.loads(raw)["items"]
    assert nodes, "No nodes found in the cluster"
    ready_nodes = []
    for node in nodes:
        conditions = node.get("status", {}).get("conditions", [])
        for c in conditions:
            if c["type"] == "Ready" and c["status"] == "True":
                ready_nodes.append(node["metadata"]["name"])
    assert ready_nodes, (
        f"No nodes are Ready. Found nodes: {[n['metadata']['name'] for n in nodes]}"
    )


# ---------------------------------------------------------------------------
# Layer 3 — Kubernetes workload
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_app_pods_running(ctx):
    """All pods in the nce namespace must be Running."""
    ns = ctx["eks_namespace"]
    raw = _kubectl("get", "pods", "-n", ns, "-o", "json")
    pods = json.loads(raw)["items"]
    assert pods, f"No pods found in namespace '{ns}'"
    not_running = [
        f"{p['metadata']['name']}={p['status'].get('phase','unknown')}"
        for p in pods
        if p["status"].get("phase") != "Running"
    ]
    assert not not_running, f"Pods not Running: {not_running}"


@pytest.mark.integration
def test_deployment_available(ctx):
    """The app Deployment must have at least 1 available replica."""
    ns = ctx["eks_namespace"]
    app = ctx["app_name"]
    raw = _kubectl("get", "deployment", app, "-n", ns, "-o", "json")
    dep = json.loads(raw)
    available = dep["status"].get("availableReplicas", 0)
    desired = dep["spec"].get("replicas", 1)
    assert available >= 1, (
        f"Deployment '{app}' has {available}/{desired} available replicas"
    )


# ---------------------------------------------------------------------------
# Layer 4 — Persistent storage
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_pvcs_bound(ctx):
    """All four EFS PersistentVolumeClaims must be Bound."""
    ns = ctx["eks_namespace"]
    raw = _kubectl("get", "pvc", "-n", ns, "-o", "json")
    pvcs = json.loads(raw)["items"]
    assert pvcs, f"No PVCs found in namespace '{ns}'"
    unbound = [
        f"{p['metadata']['name']}={p['status'].get('phase','unknown')}"
        for p in pvcs
        if p["status"].get("phase") != "Bound"
    ]
    assert not unbound, f"PVCs not Bound: {unbound}"


# ---------------------------------------------------------------------------
# Layer 5 — Networking / ALB
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_ingress_has_alb(ctx):
    """The Ingress must have an ALB hostname assigned."""
    ns = ctx["eks_namespace"]
    app = ctx["app_name"]
    raw = _kubectl("get", "ingress", app, "-n", ns, "-o", "json")
    ingress = json.loads(raw)
    ingresses = ingress.get("status", {}).get("loadBalancer", {}).get("ingress", [])
    assert ingresses, (
        "Ingress has no loadBalancer.ingress entry — "
        "LB Controller may not have provisioned the ALB yet"
    )
    hostname = ingresses[0].get("hostname", "")
    assert hostname, "Ingress loadBalancer.ingress[0].hostname is empty"


@pytest.mark.integration
def test_alb_active(ctx):
    """The ALB named in cdk.json must exist and be active."""
    alb_dns = ctx.get("eks_alb_dns", "")
    if not alb_dns:
        pytest.skip("eks_alb_dns not set in cdk.json — run `make eks-set-alb`")
    elbv2 = boto3.client("elbv2", region_name=_region())
    lbs = elbv2.describe_load_balancers()["LoadBalancers"]
    matching = [lb for lb in lbs if lb["DNSName"] == alb_dns]
    assert matching, f"No ALB found with DNS '{alb_dns}'"
    state = matching[0]["State"]["Code"]
    assert state == "active", f"ALB state is '{state}' — expected 'active'"


# ---------------------------------------------------------------------------
# Layer 6 — CloudFront
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_cloudfront_deployed(ctx):
    """The EKS CloudFront distribution must exist and be Deployed."""
    dist_id = ctx.get("eks_cf_distribution_id", "")
    if not dist_id:
        pytest.skip(
            "eks_cf_distribution_id not set in cdk.json — "
            "run `make eks-cloudfront-deploy`"
        )
    cf = boto3.client("cloudfront", region_name="us-east-1")
    dist = cf.get_distribution(Id=dist_id)["Distribution"]
    status = dist["Status"]
    assert status == "Deployed", (
        f"CloudFront distribution {dist_id} has status '{status}' — expected 'Deployed'"
    )


# ---------------------------------------------------------------------------
# Layer 7 — Application HTTP
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_app_http_via_cloudfront(ctx):
    """GET / via the CloudFront URL must return HTTP 200."""
    cf_url = ctx.get("eks_cf_url", "")
    if not cf_url:
        pytest.skip(
            "eks_cf_url not set in cdk.json — run `make eks-cloudfront-deploy`"
        )
    resp = requests.get(cf_url, timeout=15, allow_redirects=True)
    assert resp.status_code == 200, (
        f"GET {cf_url} returned HTTP {resp.status_code}"
    )


@pytest.mark.integration
def test_app_http_via_alb(ctx):
    """GET / directly on the ALB must return HTTP 200 (bypasses CloudFront)."""
    alb_dns = ctx.get("eks_alb_dns", "")
    if not alb_dns:
        pytest.skip("eks_alb_dns not set in cdk.json — run `make eks-set-alb`")
    url = f"http://{alb_dns}"
    resp = requests.get(url, timeout=15, allow_redirects=True)
    assert resp.status_code == 200, (
        f"GET {url} returned HTTP {resp.status_code}"
    )


# ---------------------------------------------------------------------------
# Layer 8 — cdk.json completeness (checks the deploy wrote back all values)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_cdk_json_fully_populated(ctx):
    """All cdk.json EKS fields that eks-full-deploy should write must be non-empty."""
    required = {
        "eks_alb_dns": "run `make eks-set-alb`",
        "eks_cf_distribution_id": "run `make eks-cloudfront-deploy`",
        "eks_cf_url": "run `make eks-cloudfront-deploy`",
    }
    missing = {k: hint for k, hint in required.items() if not ctx.get(k)}
    if missing:
        details = "\n".join(f"  {k}: {hint}" for k, hint in missing.items())
        pytest.fail(f"cdk.json fields not populated:\n{details}")
