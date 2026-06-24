import json, os, sys

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.network import CloudFront, ALB
from diagrams.aws.compute import Fargate, ECR
from diagrams.aws.storage import EFS
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
    output_path = sys.argv[1] if len(sys.argv) > 1 else "ecs-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cf = _load_cf(os.path.join(script_dir, "cf-outputs-ecs.json"))

    cf_domain   = cf.get("CloudFrontUrl", "").replace("https://", "") or "CloudFront CDN"
    has_grafana = bool(cf.get("GrafanaUrl"))

    if len(cf_domain) > 35:
        cf_domain = cf_domain[:32] + "..."

    efs_label = (
        '<<B>EFS</B>'
        '<BR/><FONT POINT-SIZE="10">- /config</FONT>'
        '<BR/><FONT POINT-SIZE="10">- /reports</FONT>'
        '<BR/><FONT POINT-SIZE="10">- /interactive</FONT>'
        '<BR/><FONT POINT-SIZE="10">- /quarto</FONT>>'
    )

    graph_attr = {"fontsize": "14", "bgcolor": "white", "pad": "0.75", "rankdir": "LR", "labelloc": "t"}
    node_attr  = {"fontsize": "13"}

    with Diagram(
        "NCE Safe Simulator — ECS on Fargate",
        filename=filename,
        direction="LR",
        show=False,
        outformat="png",
        graph_attr=graph_attr,
        node_attr=node_attr,
    ):
        browser  = Users("Browser")
        cdn      = CloudFront(cf_domain)
        alb      = ALB("ALB")
        task     = Fargate("Fargate Task\n(ECS Service)")
        fs       = EFS(efs_label, height="3.5")

        ecr_node = ECR("ECR\n(container image)")
        ssm      = SystemsManagerParameterStore("SSM\n(/nce/config)")
        cw       = Cloudwatch("CloudWatch\nLogs")

        browser >> cdn >> alb >> task >> fs

        ecr_node >> Edge(style="dashed") >> task
        ssm      >> Edge(style="dashed") >> task
        task     >> Edge(style="dashed") >> cw

        if has_grafana:
            amg = AmazonManagedGrafana("Amazon\nManaged Grafana")
            fs >> Edge(style="dashed", label="report data") >> amg


if __name__ == "__main__":
    main()
