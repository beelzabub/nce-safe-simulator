"""DevSecOps Pipeline View — build, test, publish, and deploy paths.

Shows the automated GitLab CI path (test on every push, Pages publish on
develop) and the operator-driven deployment path (Docker buildx → ECR →
CDK/Helm). Rendered at container build time alongside the other architecture
diagrams.
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
        "label": "DevSecOps Pipeline — CI on every push; operator-driven container deploy",
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
            pages = GitlabCI("pages — develop only\nreports + Quarto + Marimo\n(masked GITLAB_TOKEN)")

        pages_site = Gitlab("GitLab Pages\n(public report site)")

        with Cluster("Operator deploy (cdk/Makefile)"):
            build = Docker("docker buildx\nARM64 multi-stage\n(frontend, diagrams, runtime)")
            ecr   = ECR("ECR\nnce-safe-simulator:latest")
            cdk   = Cloudformation("CDK deploy\n(nce-ecs / nce-eks stacks)\n+ Helm chart")
            ssm   = SystemsManagerParameterStore("SSM seed-config\n/nce/config")

        with Cluster("Runtime targets"):
            eks = EKS("EKS nce-eks\n(rolling restart)")
            ecs = ECS("ECS Fargate nce\n(circuit-breaker rollback)")

        dev  >> Edge(label="git push / MR") >> repo
        repo >> test
        repo >> Edge(label="merge to develop") >> pages >> pages_site

        dev >> Edge(label="make ecr-push") >> build >> ecr
        dev >> Edge(label="make *-full-deploy") >> cdk
        ssm >> Edge(style="dashed", label="config at boot") >> eks
        ecr >> Edge(label="image pull") >> eks
        ecr >> Edge(label="image pull") >> ecs
        cdk >> eks
        cdk >> ecs


if __name__ == "__main__":
    main()
