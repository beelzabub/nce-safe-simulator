"""Developer workflow — inner loop (local) and outer loop (CI), issue #243.

Shows how a developer actually works in the container-based SDLC:

  Inner loop (local, seconds–minutes): edit source in the local IDE, which is
  volume-mounted into the pulled dev container; build and run unit tests INSIDE
  that container — the exact toolchain CI and production use — and iterate on
  fast feedback without pushing.

  Outer loop (GitLab CI, on push / merge): the pipeline runs the full suite at
  larger scale in the SAME image, and on merge to develop rebuilds and
  republishes the golden image everyone pulls.

Same image local, in CI, and in prod. Pairs with asis_vm_sdlc.py /
tobe_container_sdlc.py. Standalone script: takes the output PNG path as its one
argument, same convention as the DoDAF view set.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Client
from diagrams.onprem.vcs import Gitlab
from diagrams.onprem.ci import GitlabCI
from diagrams.onprem.container import Docker


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "container-dev-workflow.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "Developer workflow — fast local inner loop and full-scale CI outer loop, from the same definition",
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
        with Cluster("Inner loop — local machine (seconds–minutes)"):
            ide  = Client("IDE of choice\nedit source locally")
            devc = Docker("dev container\nsource volume-mounted\nbuild + unit tests")
            # the fast edit/build/test cycle
            ide  >> Edge(color="darkgreen", label="mount working tree") >> devc
            devc >> Edge(color="darkgreen", style="dashed", label="fast feedback") >> ide

        repo = Gitlab("GitLab repo\nfeature branch → MR")

        with Cluster("Outer loop — GitLab CI (every push / merge)"):
            ci_test  = GitlabCI("full test suite\n+ integration, at scale\n(dev image — #279)")
            ci_build = GitlabCI("containerize\nrebuild + publish\n(on merge to develop)")

        registry = Docker("GitLab Container Registry\ngolden dev + runtime images")

        devc     >> Edge(label="git push / open MR") >> repo
        repo     >> ci_test
        ci_test  >> Edge(label="merge to develop") >> ci_build >> registry
        # the image everyone (dev + CI + prod) pulls — closes the big loop
        registry >> Edge(color="darkgreen", style="dashed",
                         label="docker pull\nsame definition everywhere") >> ide


if __name__ == "__main__":
    main()
