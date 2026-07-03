"""SV-2 — Systems Resource Flow Description (EKS production deployment).

DoDAF Systems Viewpoint: the physical/deployment topology of the recommended
EKS deployment, drawn as nested trust zones (Internet → CloudFront edge → VPC
→ cluster) with security-group and port annotations. Labels are enriched from
live CloudFormation outputs when diagrams/cf-outputs-eks.json is populated
(see `make eks-diagram` in cdk/Makefile).
"""

import json, os, sys

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.network import CloudFront, ALB
from diagrams.aws.compute import EKS, EC2, ECR
from diagrams.aws.storage import EFS
from diagrams.aws.security import IAM
from diagrams.aws.management import (
    Cloudwatch,
    SystemsManagerParameterStore,
    AmazonManagedGrafana,
)
from diagrams.onprem.client import Users


def _load_cf(path):
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return {o["OutputKey"]: o["OutputValue"] for o in data}
    except Exception:
        pass
    return {}


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "sv2-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cf = _load_cf(os.path.join(script_dir, "cf-outputs-eks.json"))

    cf_domain    = cf.get("CloudFrontUrl", "").replace("https://", "") or "CloudFront distribution"
    cluster_name = cf.get("EksClusterName", "nce-eks")
    has_grafana  = bool(cf.get("GrafanaUrl"))

    if len(cf_domain) > 35:
        cf_domain = cf_domain[:32] + "..."

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "SV-2 — Deployment Topology (EKS, recommended production)",
    }
    node_attr = {"fontsize": "13"}

    with Diagram(
        "",
        filename=filename,
        direction="LR",
        show=False,
        outformat="png",
        graph_attr=graph_attr,
        node_attr=node_attr,
    ):
        browser = Users("Users\n(HTTPS only)")

        with Cluster("AWS Account 881490118830 — us-east-1"):
            cdn = CloudFront(f"CloudFront\n{cf_domain}\nTLS termination, WebSocket\nupgrade forwarded")

            with Cluster("VPC vpc-06c1d6ba7f71a217f (172.31.0.0/16)"):
                with Cluster("Public subnets (AZ a–d, f)"):
                    alb = ALB("ALB nce-eks-alb\nSG: CloudFront origin-facing\nprefix list only, tcp/80")

                    with Cluster(f"EKS {cluster_name} (v1.31) — namespace nce"):
                        node = EC2("Managed node group\nt4g.small ARM64\n(min 1 / max 3)")
                        pod  = EKS("App pod :80\nFastAPI + Vue\nServiceAccount nce-app")
                        node - Edge(style="dotted") - pod

                efs = EFS("EFS (encrypted)\naccess points: /config /reports\n/interactive /quarto-site\nSG: tcp/2049 from cluster")

            ecr  = ECR("ECR\nnce-safe-simulator:latest\n(ARM64)")
            ssm  = SystemsManagerParameterStore("SSM Parameter Store\n/nce/config (SecureString)")
            irsa = IAM("IRSA role (nce-app)\nssm:GetParameter + EFS RW")
            cw   = Cloudwatch("CloudWatch Logs\n/eks/nce-eks (1-month retention)")

        browser >> Edge(label="HTTPS 443") >> cdn
        cdn >> Edge(label="HTTP 80 (origin)") >> alb
        alb >> Edge(label="HTTP 80\ntarget-type ip") >> pod
        pod >> Edge(label="NFS 2049") >> efs

        ecr  >> Edge(style="dashed", label="image pull") >> node
        pod  >> Edge(style="dashed", label="config pull (boot)") >> ssm
        irsa >> Edge(style="dashed") >> pod
        pod  >> Edge(style="dashed", label="stdout") >> cw

        if has_grafana:
            amg = AmazonManagedGrafana("Amazon Managed Grafana\n(AWS IAM Identity Center)")
            amg >> Edge(style="dashed", label="/data/*.json via CloudFront") >> cdn


if __name__ == "__main__":
    main()
