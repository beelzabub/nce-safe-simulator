"""To-Be SDLC — container-based development, generalized across toolchains (#243).

Leadership-facing "after" picture. The container pattern proved out on this
Python project (#244) is toolchain-agnostic: every team publishes ONE golden
dev/build image to the shared GitLab Container Registry, and every developer —
whatever their language — keeps their local IDE and volume-mounts their working
tree into their team's image. Same pull -> mount -> develop -> CI loop for
Python, Java, and C/C++ alike; GitLab CI builds each project in the very image
its developers use. No per-box drift, fast onboarding, dev == build == CI.

Python was the worked example (#244); Java (#247) and C/C++ (#248) followed on
the identical loop — all three golden images now shipped. Pairs with
asis_vm_sdlc.py (the "before").
Standalone script: takes the output PNG path as its one argument, same
convention as the DoDAF view set.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import User
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
        "label": "To-Be — one golden image per team in a shared registry; same pull → mount → develop → CI loop for any toolchain",
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
        # Developers keep their own IDE; only the runtime/build env is containerized.
        with Cluster("Developers — local IDE, working tree volume-mounted into the team image"):
            py_dev  = User("Python dev")
            java_dev = User("Java dev")
            cpp_dev  = User("C/C++ dev")

        # The single source of truth for every team's toolchain.
        with Cluster("GitLab Container Registry — one golden dev/build image per project"):
            py_img  = Docker("python-app/dev\nPython 3.11 · Node · Quarto\n(shipped — #244)")
            java_img = Docker("java-app/dev\nJDK · Maven/Gradle\n(shipped — #247)")
            cpp_img  = Docker("cpp-app/dev\ngcc/clang · CMake\n(shipped — #248)")

        repo = Gitlab("GitLab repos\nsource + .gitlab-ci.yml")

        with Cluster("GitLab CI — each project builds in its OWN image"):
            ci = GitlabCI("test + containerize\ndev == build == CI\n(rebuilds image on merge)")

        # Each developer pulls only their team's image; identical workflow across toolchains.
        py_img   >> Edge(color="darkgreen", style="bold", label="docker pull\n+ mount source") >> py_dev
        java_img >> Edge(color="darkgreen", style="bold") >> java_dev
        cpp_img  >> Edge(color="darkgreen", style="bold") >> cpp_dev

        # Source flows through git; CI pulls the same images and republishes on merge.
        py_dev   >> Edge(label="git push / MR") >> repo
        java_dev >> Edge(style="invis") >> repo
        cpp_dev  >> Edge(style="invis") >> repo
        repo >> Edge(label="merge to develop") >> ci
        ci >> Edge(color="darkgreen", style="dashed", label="rebuild + push\ngolden images") >> py_img


if __name__ == "__main__":
    main()
