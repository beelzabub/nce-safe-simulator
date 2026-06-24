import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnJson,
    CfnOutput,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_efs as efs,
    aws_eks as eks,
    aws_grafana as grafana,
    aws_iam as iam,
    aws_logs as logs,
)
from aws_cdk.lambda_layer_kubectl_v31 import KubectlV31Layer
from constructs import Construct


class NceEksStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ctx = self.node.try_get_context

        app_name          = ctx("app_name")
        vpc_id            = ctx("vpc_id")
        config_param      = ctx("config_param")
        eks_cluster_name  = ctx("eks_cluster_name")
        eks_namespace     = ctx("eks_namespace")
        eks_node_instance = ctx("eks_node_instance")
        eks_alb_dns       = ctx("eks_alb_dns")

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
        # us-east-1e does not support EKS control plane — exclude it explicitly.
        public_subnets = ec2.SubnetSelection(
            subnet_type=ec2.SubnetType.PUBLIC,
            subnet_filters=[
                ec2.SubnetFilter.availability_zones(
                    ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f"]
                )
            ],
        )

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
            endpoint_access=eks.EndpointAccess.PUBLIC,
        )

        # ARM64 managed node group
        nodegroup = cluster.add_nodegroup_capacity(
            "NceNodes",
            instance_types=[ec2.InstanceType(eks_node_instance)],
            ami_type=eks.NodegroupAmiType.AL2023_ARM_64_STANDARD,
            min_size=1,
            max_size=3,
            desired_size=1,
            subnets=public_subnets,
        )

        # ── EFS ───────────────────────────────────────────────────────────────
        efs_sg = ec2.SecurityGroup(self, "EfsSg", vpc=vpc, description="EFS NFS for EKS")
        efs_sg.add_ingress_rule(cluster.cluster_security_group, ec2.Port.tcp(2049))

        filesystem = efs.FileSystem(
            self, "Efs",
            vpc=vpc,
            security_group=efs_sg,
            removal_policy=RemovalPolicy.RETAIN,
        )

        def _ap(ap_id, path):
            return filesystem.add_access_point(
                ap_id,
                path=path,
                create_acl=efs.Acl(owner_uid="0", owner_gid="0", permissions="755"),
                posix_user=efs.PosixUser(uid="0", gid="0"),
            )

        ap_config      = _ap("ApConfig",      "/config")
        ap_reports     = _ap("ApReports",     "/reports")
        ap_interactive = _ap("ApInteractive", "/interactive")
        ap_quarto      = _ap("ApQuartoSite",  "/quarto-site")

        # ── EFS CSI driver (IRSA) ─────────────────────────────────────────────
        # The addon creates and owns efs-csi-controller-sa, so we create only
        # the IAM role here (no add_service_account, which would conflict).
        # CfnJson delays OIDC issuer token resolution to deploy time so it can
        # be used as a map key (synth-time interpolation fails with KeyMustResolveToString).
        oidc_issuer = cluster.cluster_open_id_connect_issuer
        efs_csi_conditions = CfnJson(self, "EfsCsiOidcConditions", value={
            f"{oidc_issuer}:sub": "system:serviceaccount:kube-system:efs-csi-controller-sa",
            f"{oidc_issuer}:aud": "sts.amazonaws.com",
        })
        efs_csi_role = iam.Role(
            self, "EfsCsiRole",
            assumed_by=iam.FederatedPrincipal(
                cluster.open_id_connect_provider.open_id_connect_provider_arn,
                {"StringEquals": efs_csi_conditions},
                "sts:AssumeRoleWithWebIdentity",
            ),
        )
        efs_csi_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AmazonEFSCSIDriverPolicy")
        )
        eks.CfnAddon(
            self, "EfsCsiAddon",
            cluster_name=cluster.cluster_name,
            addon_name="aws-efs-csi-driver",
            service_account_role_arn=efs_csi_role.role_arn,
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
        filesystem.grant_read_write(app_sa.role)
        # Node group role performs NFS mounts; it needs ClientMount in addition to
        # the app SA role grant above (which only covers the pod's IRSA identity).
        filesystem.grant_read_write(nodegroup.role)

        # ── ALB security group (CloudFront-only ingress) ──────────────────────
        # The LBC creates its own default SG; specifying this one via the
        # security-groups Ingress annotation replaces that default, so the ALB
        # only accepts traffic from CloudFront edge nodes.
        cf_prefix_list = ec2.PrefixList.from_lookup(
            self, "CfPrefixList",
            prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
        )
        alb_sg = ec2.SecurityGroup(
            self, "AlbSg",
            vpc=vpc,
            description="ALB — allow HTTP inbound only from CloudFront",
            allow_all_outbound=True,
        )
        alb_sg.add_ingress_rule(
            ec2.Peer.prefix_list(cf_prefix_list.prefix_list_id),
            ec2.Port.tcp(80),
        )

        # ── CloudFront distribution ───────────────────────────────────────────
        # Provides HTTPS in front of the HTTP ALB so Grafana's Infinity datasource
        # can run in browser/direct mode without mixed-content or allowedHosts issues.
        distribution = cloudfront.Distribution(
            self, "DataDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    eks_alb_dns,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )

        # ── Amazon Managed Grafana ────────────────────────────────────────────
        grafana_role = iam.Role(
            self, "GrafanaRole",
            assumed_by=iam.ServicePrincipal("grafana.amazonaws.com"),
        )
        workspace = grafana.CfnWorkspace(
            self, "GrafanaWorkspace",
            name=app_name,
            account_access_type="CURRENT_ACCOUNT",
            authentication_providers=["AWS_SSO"],
            permission_type="SERVICE_MANAGED",
            role_arn=grafana_role.role_arn,
            grafana_version="10.4",
            plugin_admin_enabled=True,
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(self, "EksClusterName",    value=cluster.cluster_name)
        CfnOutput(self, "EksLbSaRoleArn",    value=lb_sa.role.role_arn)
        CfnOutput(self, "EksAppSaRoleArn",   value=app_sa.role.role_arn)
        CfnOutput(self, "EfsId",             value=filesystem.file_system_id)
        CfnOutput(self, "EfsApConfig",       value=ap_config.access_point_id)
        CfnOutput(self, "EfsApReports",      value=ap_reports.access_point_id)
        CfnOutput(self, "EfsApInteractive",  value=ap_interactive.access_point_id)
        CfnOutput(self, "EfsApQuartoSite",   value=ap_quarto.access_point_id)
        CfnOutput(self, "AlbSgId",           value=alb_sg.security_group_id)
        CfnOutput(self, "CloudFrontUrl",     value=f"https://{distribution.domain_name}")
        CfnOutput(self, "GrafanaWorkspaceId",value=workspace.ref,
                  description="AMG workspace ID — used by make grafana-setup and eks-grafana-deploy")
        CfnOutput(self, "GrafanaUrl",        value=f"https://{workspace.attr_endpoint}")
