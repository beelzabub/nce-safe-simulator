import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_eks as eks,
    aws_iam as iam,
    aws_logs as logs,
)
from aws_cdk.lambda_layer_kubectl_v31 import KubectlV31Layer
from constructs import Construct


class NceEksStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ctx = self.node.try_get_context

        vpc_id            = ctx("vpc_id")
        config_param      = ctx("config_param")
        efs_id            = ctx("efs_id") or ""
        efs_sg_id         = ctx("efs_sg_id") or ""
        eks_cluster_name  = ctx("eks_cluster_name")
        eks_namespace     = ctx("eks_namespace")
        eks_node_instance = ctx("eks_node_instance")

        # ── VPC ───────────────────────────────────────────────────────────────
        if vpc_id:
            vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)
        else:
            vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)

        # ── CloudWatch logs ───────────────────────────────────────────────────
        logs.LogGroup(
            self, "LogGroup",
            log_group_name=f"/eks/{eks_cluster_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── EKS cluster ───────────────────────────────────────────────────────
        public_subnets = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC)

        cluster = eks.Cluster(
            self, "Cluster",
            cluster_name=eks_cluster_name,
            version=eks.KubernetesVersion.V1_31,
            kubectl_layer=KubectlV31Layer(self, "KubectlLayer"),
            vpc=vpc,
            vpc_subnets=[public_subnets],
            default_capacity=0,
            output_cluster_name=True,
            output_config_command=True,
        )

        # ARM64 managed node group
        cluster.add_nodegroup_capacity(
            "NceNodes",
            instance_types=[ec2.InstanceType(eks_node_instance)],
            ami_type=eks.NodegroupAmiType.AL2023_ARM_64_STANDARD,
            min_size=1,
            max_size=3,
            desired_size=1,
            subnets=public_subnets,
        )

        # ── EFS (imported from NceStack — requires 'make set-efs' first) ────────
        # Guarded so the stack synthesizes cleanly before set-efs is run.
        if efs_id and efs_sg_id:
            efs_sg = ec2.SecurityGroup.from_security_group_id(self, "EfsSg", efs_sg_id)
            filesystem = efs.FileSystem.from_file_system_attributes(
                self, "Efs",
                file_system_id=efs_id,
                security_group=efs_sg,
            )
            filesystem.connections.allow_default_port_from(cluster.cluster_security_group)

        # ── EFS CSI driver (IRSA) ─────────────────────────────────────────────
        efs_csi_sa = cluster.add_service_account(
            "EfsCsiSA",
            name="efs-csi-controller-sa",
            namespace="kube-system",
        )
        efs_csi_sa.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AmazonEFSCSIDriverPolicy")
        )
        eks.CfnAddon(
            self, "EfsCsiAddon",
            cluster_name=cluster.cluster_name,
            addon_name="aws-efs-csi-driver",
            service_account_role_arn=efs_csi_sa.role.role_arn,
        )

        # ── AWS Load Balancer Controller (IRSA) ───────────────────────────────
        # AWSLoadBalancerControllerIAMPolicy must be created once per account
        # via 'make eks-install' before deploying this stack.
        lb_sa = cluster.add_service_account(
            "LbControllerSA",
            name="aws-load-balancer-controller",
            namespace="kube-system",
        )
        lb_sa.role.add_managed_policy(
            iam.ManagedPolicy.from_managed_policy_arn(
                self, "LbControllerPolicy",
                managed_policy_arn=f"arn:aws:iam::{self.account}:policy/AWSLoadBalancerControllerIAMPolicy",
            )
        )
        cluster.add_helm_chart(
            "AwsLbController",
            chart="aws-load-balancer-controller",
            repository="https://aws.github.io/eks-charts",
            namespace="kube-system",
            values={
                "clusterName": cluster.cluster_name,
                "serviceAccount": {
                    "create": False,
                    "name": "aws-load-balancer-controller",
                },
                "region": self.region,
                "vpcId": vpc_id,
            },
        )

        # ── App namespace ─────────────────────────────────────────────────────
        cluster.add_manifest(
            "NceNamespace",
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": eks_namespace},
            },
        )

        # ── App service account (IRSA) ────────────────────────────────────────
        app_sa = cluster.add_service_account(
            "NceAppSA",
            name="nce-app",
            namespace=eks_namespace,
        )
        app_sa.role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{config_param}"
                ],
            )
        )
        if efs_id and efs_sg_id:
            filesystem.grant_read_write(app_sa.role)

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "EksClusterName", value=cluster.cluster_name)
        CfnOutput(self, "EksAppSaRoleArn", value=app_sa.role.role_arn)
