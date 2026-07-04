"""OV-1 — High-Level Operational Concept.

DoDAF Operational Viewpoint: who uses the NCE Safe Simulator, what mission it
supports, and how information flows between stakeholders, the system, and the
GitLab system of record. Rendered at container build time alongside the other
architecture diagrams (see Dockerfile stage 2).
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.generic.blank import Blank
from diagrams.onprem.client import Users, Client
from diagrams.onprem.vcs import Gitlab
from diagrams.programming.framework import FastAPI, Vue
from diagrams.aws.management import AmazonManagedGrafana

LEGEND = (
    '<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="2" CELLPADDING="2">'
    '<TR><TD ALIGN="LEFT"><B>RTE</B> — Release Train Engineer: facilitates an Agile Release Train'
    '<BR ALIGN="LEFT"/>(PI Planning, cross-team dependencies, flow); SAFe program-level scrum master</TD></TR>'
    '<TR><TD ALIGN="LEFT"><B>PM</B> — Program/Project Manager: owns scope, budget, and stakeholder accountability</TD></TR>'
    '<TR><TD ALIGN="LEFT"><B>Tiers</B> mirror the wiki portfolio home and its cadence:</TD></TR>'
    '<TR><TD ALIGN="LEFT">  T1 Executive Pulse (daily) · T2 Program Management (weekly)'
    '<BR ALIGN="LEFT"/>  T3 Operational Detail (on demand) · T4 Data Quality (as needed)</TD></TR>'
    '</TABLE>>'
)


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "ov1-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": (
            "OV-1 — High-Level Operational Concept\n"
            "Mission: continuous portfolio visibility for SAFe-managed programs — "
            "simulate, measure, and report Lean-Agile execution"
        ),
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
        with Cluster("Program Stakeholders"):
            execs    = Users("Executives\n(Tier 1 — daily pulse)")
            rtes     = Users("RTEs / PMs\n(Tier 2 — weekly)")
            leads    = Users("Team Leads\n(Tier 3 — on demand)")
            stewards = Users("Data Stewards\n(Tier 4 — data quality)")

        with Cluster("NCE Safe Simulator"):
            ui  = Vue("Web UI\n(DoD banner + login)")
            api = FastAPI("Tooling & Report\nEngine")
            ui - Edge(style="dotted") - api

        with Cluster("System of Record"):
            gitlab = Gitlab("GitLab\nSAFe portfolio hierarchy\nEpic → Cap/Feature → Issue")

        with Cluster("Published Reporting"):
            wiki    = Gitlab("Group Wiki\n(4-tier portfolio home)")
            pages   = Gitlab("Quarto Site\n(GitLab Pages)")
            marimo  = Client("Interactive Reports\n(Marimo WASM)")
            grafana = AmazonManagedGrafana("Grafana\nDashboards")

        for actor in (execs, rtes, leads, stewards):
            actor >> Edge(label="HTTPS") >> ui

        api >> Edge(label="REST +\nGraphQL") >> gitlab
        api >> Edge(label="publish") >> wiki
        api >> Edge(label="publish") >> pages
        api >> Edge(label="publish") >> marimo
        api >> Edge(label="report JSON") >> grafana

        wiki >> Edge(style="dashed", label="consume") >> execs

        with Cluster("Legend"):
            # fixedsize=false lets graphviz size the node to the label; a fixed
            # width clips the text at the node boundary.
            Blank(LEGEND, labelloc="c", fontsize="12", fixedsize="false",
                  width="0", height="0", imagescale="false")


if __name__ == "__main__":
    main()
