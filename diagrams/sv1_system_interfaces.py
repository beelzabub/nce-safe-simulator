"""SV-1 — Systems Interface Description.

DoDAF Systems Viewpoint: internal components of the NCE Safe Simulator, its
system boundary, and every external interface with protocol and port. Rendered
at container build time alongside the other architecture diagrams.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Gitlab
from diagrams.programming.framework import FastAPI, Vue
from diagrams.programming.language import Python
from diagrams.aws.storage import S3, EFS
from diagrams.aws.management import (
    Cloudwatch,
    SystemsManagerParameterStore,
    AmazonManagedGrafana,
)


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "sv1-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "SV-1 — Systems Interface Description",
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
        browser = Users("Browser")

        with Cluster("NCE Safe Simulator — System Boundary"):
            spa = Vue("Vue 3 SPA\n(public/app)")

            with Cluster("FastAPI Server (uvicorn :80)"):
                gate   = FastAPI("Auth Gate\n(DoD banner, sessions,\nmethod: none|basic)")
                api    = FastAPI("REST API\n(/api/*)")
                ws     = FastAPI("Jobs WebSocket\n(/ws/run)")
                static = FastAPI("Static Mounts\n(/quarto /data\n/reports /architecture)")

            runner  = Python("Job Runner\n(threaded, stdout capture)")
            core    = Python("NceGitLab Core\n(12 mixins: epics, issues,\nreports, bootstrap, …)")
            quarto  = Python("Quarto + Marimo\nSite Builders")

            gate - Edge(style="dotted") - api
            api >> runner >> core
            ws >> Edge(label="stream logs") >> runner
            core >> quarto

        gitlab = Gitlab("GitLab\nREST v4 + GraphQL")
        ssm    = SystemsManagerParameterStore("SSM Parameter Store\n/nce/config (SecureString)\n/nce/grafana-api-key")
        s3     = S3("S3 staging\nnce-safe-sim-assets\n(login backgrounds)")
        efs    = EFS("EFS\n/config /reports\n/interactive /quarto-site")
        cw     = Cloudwatch("CloudWatch Logs")
        amg    = AmazonManagedGrafana("Amazon Managed\nGrafana (optional)")

        browser >> Edge(label="HTTPS 443") >> spa
        spa >> Edge(label="HTTP/WSS") >> gate

        core >> Edge(label="HTTPS 443\nPAT (api scope)") >> gitlab
        gate >> Edge(label="HTTPS 443 (boto3)\npresigned URLs", style="dashed") >> s3
        core >> Edge(label="NFS 2049\n(cloud deployments)") >> efs
        api  >> Edge(label="HTTPS 443 (boot)\nconfig pull", style="dashed") >> ssm
        core >> Edge(label="stdout → agent", style="dashed") >> cw
        amg  >> Edge(label="HTTPS 443\n/data/*.json via CloudFront", style="dashed") >> static


if __name__ == "__main__":
    main()
