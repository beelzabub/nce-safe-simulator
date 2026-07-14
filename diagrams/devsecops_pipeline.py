"""DevSecOps Pipeline View — build, test, publish, and deploy paths.

Shows the automated GitLab CI path (test on every push, container image publish
to the GitLab Container Registry on develop) and the operator-driven deployment
path (Docker buildx → ECR → CDK/Helm). Rendered at container build time
alongside the other architecture diagrams.
"""

import sys

from diagrams import Diagram, Cluster, Edge
from diagrams.onprem.client import Users
from diagrams.onprem.vcs import Gitlab
from diagrams.onprem.ci import GitlabCI
from diagrams.onprem.container import Docker
from diagrams.aws.compute import ECR, EKS, ECS
from diagrams.aws.management import Cloudformation, SystemsManagerParameterStore


def main():
    output_path = sys.argv[1] if len(sys.argv) > 1 else "devsecops-architecture.png"
    filename = output_path.rsplit(".", 1)[0]

    graph_attr = {
        "fontsize": "16",
        "bgcolor": "white",
        "pad": "0.75",
        "rankdir": "LR",
        "splines": "spline",
        "labelloc": "t",
        "label": "DevSecOps Pipeline — CI tests on every push; cloud deploys are optional and on-demand",
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
        dev  = Users("Developer")
        repo = Gitlab("GitLab repo\n(feature/bugfix branches\n→ MR → develop)")

        with Cluster("GitLab CI (.gitlab-ci.yml)"):
            test  = GitlabCI("test — every push\npip install + pytest")
            containerize = GitlabCI("containerize — develop only\nKaniko build + push\n(needs: test)")

        registry = Docker("GitLab Container Registry\nruntime + dev images\n(:latest + :<sha>)")

        with Cluster("Operator deploy (cdk/Makefile)"):
            build = Docker("docker buildx\nARM64 multi-stage\n(frontend, diagrams, runtime)")
            ecr   = ECR("ECR\nnce-safe-simulator:latest")
            cdk   = Cloudformation("CDK deploy\n(nce-ecs / nce-eks stacks)\n+ Helm chart")
            ssm   = SystemsManagerParameterStore("SSM seed-config\n/nce/config")

        with Cluster("Optional runtime targets — deployed on demand,\ntorn down when idle (make *-destroy)"):
            eks = EKS("EKS nce-eks\n(rolling restart)")
            ecs = ECS("ECS Fargate nce\n(circuit-breaker rollback)")

        dev  >> Edge(label="git push / MR") >> repo
        repo >> test
        repo >> Edge(label="merge to develop") >> containerize >> registry
        registry >> Edge(style="dashed", label="docker pull\n(dev + build image)") >> dev

        dev >> Edge(label="make ecr-push\n(when releasing)") >> build >> ecr
        dev >> Edge(label="make *-full-deploy\n(when standing up)") >> cdk
        ssm >> Edge(style="dashed", label="config at boot") >> eks
        ecr >> Edge(style="dashed", label="image pull\n(at deploy)") >> eks
        ecr >> Edge(style="dashed", label="image pull\n(at deploy)") >> ecs
        cdk >> Edge(style="dashed") >> eks
        cdk >> Edge(style="dashed") >> ecs


if __name__ == "__main__":
    main()
