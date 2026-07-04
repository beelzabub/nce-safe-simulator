"""Data Flow Diagram (SV-4 style) — sources, processing, stores, and outputs.

Shows what data enters the NCE Safe Simulator, where it rests, and every
egress path — the view an assessor walks through for a data-handling review.
Drawn as a strict left-to-right pipeline: sources → snapshot fetch → snapshot
store → report generation → published content → consumers. Solid edges are
mission data; dashed edges are secrets, telemetry, and supporting flows.
Rendered at container build time alongside the other architecture diagrams.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Gitlab
from diagrams.programming.language import Python
from diagrams.generic.storage import Storage
from diagrams.aws.storage import EFS
from diagrams.aws.management import (
    Cloudwatch,
    SystemsManagerParameterStore,
    AmazonManagedGrafana,
)


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "dataflow-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "Data Flow — sources, snapshot pipeline, stores, and egress",
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
        with Cluster("Data Sources"):
            gitlab_src = Gitlab("GitLab API\nepics, issues, labels,\nweights, groups")
            uploads    = Users("Browser uploads\nCSV / JSON imports\n(24 h retention)")
            ssm        = SystemsManagerParameterStore("SSM SecureString\n/nce/config\n(incl. GitLab PAT)")

        snapshot = Python("Snapshot fetch\n(one API pass per run)")

        with Cluster("Snapshot Store — reports/ (EFS on ECS/EKS; local disk otherwise)"):
            data_dir = Storage("reports/<date>/<time>/data\nepics, issues, blocking,\ngroups, projects (JSON)")

        with Cluster("Report Generation"):
            engine   = Python("Report generators\n(pandas / plotly)")
            builders = Python("Quarto + Marimo\nsite builders")

        with Cluster("Published Content", graph_attr={"margin": "30"}):
            sites = Storage("quarto-site/\npublic/interactive/\npublic/exports/")
            efs   = EFS("EFS (ECS/EKS)\nencrypted, TLS transit\nlocal disk otherwise")
            sites - Edge(style="dotted") - efs

        with Cluster("Egress / Consumers"):
            wiki    = Gitlab("GitLab Group Wiki\n(4-tier report pages)")
            viewer  = Users("Browser\n(reports, downloads)")
            grafana = AmazonManagedGrafana("Grafana\n(/data/*.json)")

        cw = Cloudwatch("CloudWatch Logs\n(cloud deployments;\njob output, no secrets)")

        gitlab_src >> Edge(label="HTTPS 443") >> snapshot >> data_dir
        uploads    >> Edge(label="POST /api/upload") >> engine
        ssm        >> Edge(style="dashed", label="boot-time pull") >> snapshot

        data_dir >> engine
        engine   >> Edge(label="wiki markdown\nHTTPS 443") >> wiki
        engine   >> builders >> sites
        sites    >> Edge(label="HTTP GET") >> viewer
        # Grafana initiates (Infinity datasource polls /data/*.json served from
        # the latest snapshot); << reverses the arrowhead while keeping the
        # data_dir→grafana ranking so the LR pipeline layout holds.
        data_dir << Edge(style="dashed",
                         label="pull: HTTP GET /data/*.json\n(via CloudFront)") << grafana

        engine >> Edge(style="dashed") >> cw


if __name__ == "__main__":
    main()
