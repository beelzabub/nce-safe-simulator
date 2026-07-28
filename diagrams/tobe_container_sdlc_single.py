#!/usr/bin/env python3
"""To-Be (single team) — the honest two-image framing (#266).

One Dockerfile lineage in the repo; CI publishes the runtime (deploy) image
and the dev image (runtime + toolchain) to the registry; developers pull dev,
volume-mount their source, and keep their own IDE. The images are layers of
one definition, so dev and deploy can't drift. Pairs with
tobe_container_sdlc.py (the multi-toolchain / per-team view).
"""
import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import User
from diagrams.onprem.compute import Server
from diagrams.onprem.vcs import Gitlab
from diagrams.onprem.ci import GitlabCI
from diagrams.onprem.container import Docker


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "tobe-container-sdlc.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "To-Be — container-based SDLC: one Dockerfile lineage; CI publishes runtime (deploy) and dev (runtime + toolchain); developers keep their local IDE",
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
        with Cluster("Development team — local IDE, source volume-mounted into the dev image"):
            dev_a = User("Dev A")
            dev_b = User("Dev B")

        repo = Gitlab("GitLab repo\nsource + Dockerfile\n+ .gitlab-ci.yml")
        ci = GitlabCI("test + containerize\n(kaniko, on merge)")

        # One definition, two published images — dev is FROM runtime, so the
        # environments are layers of each other, never parallel forks.
        with Cluster("GitLab Container Registry — one lineage, two published images"):
            dev_img = Docker("dev image\nFROM runtime + toolchain")
            runtime = Docker("runtime image\nslim, what deploys")

        prod = Server("Deployment\nruns the runtime image")

        dev_a >> Edge(label="git push / MR") >> repo
        dev_b >> Edge(style="invis") >> repo
        repo >> Edge(label="merge to develop") >> ci
        ci >> Edge(color="darkgreen", style="dashed", label="publish both") >> dev_img
        ci >> Edge(color="darkgreen", style="dashed") >> runtime
        dev_img >> Edge(color="darkgreen", style="bold",
                        label="docker pull\n+ mount source") >> dev_a
        dev_img >> Edge(color="darkgreen", style="bold") >> dev_b
        runtime >> Edge(color="darkblue", label="deploy") >> prod


if __name__ == "__main__":
    main()
