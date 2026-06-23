import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_efs as efs,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_grafana as grafana,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class NceEcsStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # ── Context ───────────────────────────────────────────────────────────
        ctx = self.node.try_get_context

        vpc_id           = ctx("vpc_id")
        app_name         = ctx("app_name")
        cluster_name     = ctx("cluster_name")
        alb_name         = ctx("alb_name")
        log_group_name   = ctx("log_group")
        config_param     = ctx("config_param")
        container_name   = ctx("container_name")
        container_port   = ctx("container_port")
        image_tag        = ctx("image_tag")
        task_cpu         = ctx("task_cpu")
        task_memory      = ctx("task_memory_mib")
        efs_config_path      = ctx("efs_config_path")
        efs_reports_path     = ctx("efs_reports_path")
        efs_interactive_path = ctx("efs_interactive_path")
        efs_quarto_path      = ctx("efs_quarto_path")
        mnt_config       = ctx("mnt_config")
        mnt_reports      = ctx("mnt_reports")
        mnt_interactive  = ctx("mnt_interactive")
        mnt_quarto       = ctx("mnt_quarto")
        hc_interval      = ctx("hc_interval_seconds")
        hc_codes         = ctx("hc_healthy_codes")
        hc_healthy       = ctx("hc_healthy_count")
        hc_unhealthy     = ctx("hc_unhealthy_count")
        _desired_count   = ctx("desired_count")
        desired_count    = int(_desired_count) if _desired_count is not None else None

        # ── VPC ──────────────────────────────────────────────────────────────
        if vpc_id:
            vpc = ec2.Vpc.from_lookup(self, "Vpc", vpc_id=vpc_id)
        else:
            vpc = ec2.Vpc.from_lookup(self, "Vpc", is_default=True)

        # ── ECR repository ────────────────────────────────────────────────────
        # Image is built and pushed externally via 'make ecr-push'.
        # ECS always pulls :latest; use 'make ecs-redeploy' to pick up a new image.
        repo = ecr.Repository(
            self,
            "Repo",
            repository_name=app_name,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # ── SSM: config seed permission ───────────────────────────────────────
        # config.json is stored as a SecureString in SSM via 'make seed-config'
        # (keeps the GitLab token out of CloudFormation).  The ECS task reads it
        # on first boot, writes it to EFS, and EFS persists it from then on.

        # ── EFS ───────────────────────────────────────────────────────────────
        filesystem = efs.FileSystem(
            self,
            "Efs",
            vpc=vpc,
            # Mount targets must be in the same subnet type as the Fargate tasks
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            throughput_mode=efs.ThroughputMode.BURSTING,
            encrypted=True,
            removal_policy=RemovalPolicy.DESTROY,
            file_system_name=app_name,
        )

        def _ap(name, path):
            return filesystem.add_access_point(
                name,
                path=path,
                create_acl=efs.Acl(owner_uid="0", owner_gid="0", permissions="755"),
                posix_user=efs.PosixUser(uid="0", gid="0"),
            )

        config_ap      = _ap("ConfigAp",      efs_config_path)
        reports_ap     = _ap("ReportsAp",     efs_reports_path)
        interactive_ap = _ap("InteractiveAp", efs_interactive_path)
        quarto_site_ap = _ap("QuartoSiteAp",  efs_quarto_path)

        # ── CloudWatch logs ───────────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=log_group_name,
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── ECS cluster ───────────────────────────────────────────────────────
        cluster = ecs.Cluster(self, "Cluster", cluster_name=cluster_name, vpc=vpc)

        # ── Task definition ───────────────────────────────────────────────────
        task_def = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            family=app_name,
            cpu=task_cpu,
            memory_limit_mib=task_memory,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{config_param}"
                ],
            )
        )
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "ssmmessages:CreateControlChannel",
                    "ssmmessages:CreateDataChannel",
                    "ssmmessages:OpenControlChannel",
                    "ssmmessages:OpenDataChannel",
                ],
                resources=["*"],
            )
        )

        def _vol(vol_name, access_point):
            task_def.add_volume(
                name=vol_name,
                efs_volume_configuration=ecs.EfsVolumeConfiguration(
                    file_system_id=filesystem.file_system_id,
                    transit_encryption="ENABLED",
                    authorization_config=ecs.AuthorizationConfig(
                        access_point_id=access_point.access_point_id,
                        iam="ENABLED",
                    ),
                ),
            )

        _vol("nce-config",      config_ap)
        _vol("nce-reports",     reports_ap)
        _vol("nce-interactive", interactive_ap)
        _vol("nce-quarto-site", quarto_site_ap)

        container = task_def.add_container(
            container_name,
            container_name=container_name,
            image=ecs.ContainerImage.from_ecr_repository(repo, tag=image_tag),
            entry_point=["sh"],
            command=["/app/scripts/entrypoint-ecs.sh"],
            environment={
                "CONFIG_PARAM": config_param,
                "AWS_DEFAULT_REGION": self.region,
            },
            port_mappings=[ecs.PortMapping(container_port=container_port)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ecs",
                log_group=log_group,
            ),
        )
        container.add_mount_points(
            ecs.MountPoint(container_path=mnt_config,      read_only=False, source_volume="nce-config"),
            ecs.MountPoint(container_path=mnt_reports,     read_only=False, source_volume="nce-reports"),
            ecs.MountPoint(container_path=mnt_interactive, read_only=False, source_volume="nce-interactive"),
            ecs.MountPoint(container_path=mnt_quarto,      read_only=False, source_volume="nce-quarto-site"),
        )

        # ── ALB + Fargate service ─────────────────────────────────────────────
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Service",
            cluster=cluster,
            service_name=app_name,
            task_definition=task_def,
            load_balancer_name=alb_name,
            desired_count=desired_count if (desired_count is None or desired_count > 0) else 1,
            public_load_balancer=True,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            # Single-task service: allow 0 tasks during deployment (rolling stop-start)
            min_healthy_percent=0,
            max_healthy_percent=100,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            enable_execute_command=True,
        )

        # CDK L2 rejects desired_count=0, but CloudFormation accepts it.
        # Apply 0 at the L1 layer so the fresh-deploy path can start the service
        # with no tasks (avoiding a hang waiting for a not-yet-pushed image).
        if desired_count == 0:
            service.service.node.default_child.add_property_override("DesiredCount", 0)

        service.target_group.configure_health_check(
            path="/",
            healthy_http_codes=hc_codes,
            interval=Duration.seconds(hc_interval),
            healthy_threshold_count=hc_healthy,
            unhealthy_threshold_count=hc_unhealthy,
        )
        service.target_group.set_attribute("deregistration_delay.timeout_seconds", "30")

        filesystem.connections.allow_default_port_from(service.service.connections)
        filesystem.grant_read_write(task_def.task_role)

        # ── CloudFront distribution ───────────────────────────────────────────
        # Provides HTTPS in front of the HTTP ALB so Grafana's Infinity datasource
        # can run in browser/direct mode without mixed-content or allowedHosts issues.
        distribution = cloudfront.Distribution(
            self,
            "DataDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    service.load_balancer.load_balancer_dns_name,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                # Forward all viewer headers (including Sec-WebSocket-Key/Version) so
                # WebSocket upgrades reach the origin intact.
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(
            self,
            "AppUrl",
            value=f"http://{service.load_balancer.load_balancer_dns_name}",
            description="NCE Safe Simulator public URL",
        )
        CfnOutput(
            self,
            "CloudFrontUrl",
            value=f"https://{distribution.domain_name}",
            description="CloudFront HTTPS endpoint for WebSocket/app access",
        )
        CfnOutput(
            self,
            "EcrRepo",
            value=repo.repository_uri,
            description="ECR repository URI — tag and push :latest, then make ecs-redeploy",
        )
        CfnOutput(
            self,
            "EfsId",
            value=filesystem.file_system_id,
            description="EFS filesystem ID",
        )
        CfnOutput(
            self,
            "LogTail",
            value=f"aws logs tail {log_group_name} --follow --region {self.region}",
            description="Command to follow container logs",
        )

        # ── Amazon Managed Grafana ────────────────────────────────────────────
        grafana_role = iam.Role(
            self,
            "GrafanaRole",
            assumed_by=iam.ServicePrincipal("grafana.amazonaws.com"),
        )

        workspace = grafana.CfnWorkspace(
            self,
            "GrafanaWorkspace",
            name=app_name,
            account_access_type="CURRENT_ACCOUNT",
            authentication_providers=["AWS_SSO"],
            permission_type="SERVICE_MANAGED",
            role_arn=grafana_role.role_arn,
            grafana_version="10.4",
            plugin_admin_enabled=True,
        )

        CfnOutput(
            self,
            "GrafanaWorkspaceId",
            value=workspace.ref,
            description="AMG workspace ID — used by make grafana-setup and grafana-deploy",
        )
        CfnOutput(
            self,
            "GrafanaUrl",
            value=f"https://{workspace.attr_endpoint}",
            description="Grafana dashboard URL",
        )
