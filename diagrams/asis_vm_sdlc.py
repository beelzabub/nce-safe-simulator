"""As-Is SDLC — VM-based build (current state, issue #243).

Leadership-facing "before" picture: the team HAS a working build server and
build VMs that produce releases today — but the knowledge of how they were
provisioned and how the build actually runs has been lost. The environment is
a black box: it works, yet nothing describes it and no one can confidently
change, recover, or explain it. The repo holds source only — there is no
reproducible definition of the build environment.

This is a *lost-knowledge / opacity* story, not a *drift* story: the build is
reliable but undocumented, which is concentrated risk.

Pairs with tobe_container_sdlc.py (the "after" picture, where the build is
captured as a versioned golden image that doubles as its own documentation).
Standalone script: takes the output PNG path as its one argument, same
convention as the DoDAF view set in this directory.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Gitlab
from diagrams.generic.virtualization import Vmware
from diagrams.onprem.compute import Server


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "asis-vm-sdlc.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": ("As-Is — the build server runs today, but how it was provisioned "
                  "and how the build works is undocumented"),
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
        team = Users("Development team")
        repo = Gitlab("Git repo\n(source only —\nno build definition)")
        releases = Server("Release\nartifacts")

        with Cluster("Build system — works today, but undocumented (knowledge lost)"):
            build_srv = Vmware("Build server VM\nhand-provisioned,\nunknown setup")
            build_vm1 = Vmware("Build VM")
            build_vm2 = Vmware("Build VM")

            # The build server orchestrates the build VMs — how, exactly, is
            # part of what's no longer understood (faint, unlabeled).
            build_srv >> Edge(color="gray", style="dotted") >> build_vm1
            build_srv >> Edge(color="gray", style="dotted") >> build_vm2

        # The one thing that reliably works: source goes in, releases come out.
        team >> Edge(label="clone / commit") >> repo
        repo >> Edge(style="dashed", label="source only") >> build_srv
        build_srv >> Edge(label="builds & ships\n(works today)") >> releases

        # ...but no one can explain or safely change how it does that.
        team >> Edge(color="firebrick", style="bold",
                     label="How is it configured?\nHow does the build run?\n— knowledge lost") >> build_srv


if __name__ == "__main__":
    main()
