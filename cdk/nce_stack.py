import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_efs as efs,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
CONFIG_PARAM_NAME = "/nce/config"


class NceStack(Stack):
    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # ── VPC ──────────────────────────────────────────────────────────────
        vpc_id = self.node.try_get_context("vpc_id")
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
            repository_name="nce-safe-simulator",
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
            file_system_name="nce-safe-simulator",
        )

        config_ap = filesystem.add_access_point(
            "ConfigAp",
            path="/config",
            create_acl=efs.Acl(owner_uid="0", owner_gid="0", permissions="755"),
            posix_user=efs.PosixUser(uid="0", gid="0"),
        )
        reports_ap = filesystem.add_access_point(
            "ReportsAp",
            path="/reports",
            create_acl=efs.Acl(owner_uid="0", owner_gid="0", permissions="755"),
            posix_user=efs.PosixUser(uid="0", gid="0"),
        )
        interactive_ap = filesystem.add_access_point(
            "InteractiveAp",
            path="/interactive",
            create_acl=efs.Acl(owner_uid="0", owner_gid="0", permissions="755"),
            posix_user=efs.PosixUser(uid="0", gid="0"),
        )

        # ── CloudWatch logs ───────────────────────────────────────────────────
        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name="/ecs/nce-safe-simulator",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ── ECS cluster ───────────────────────────────────────────────────────
        cluster = ecs.Cluster(self, "Cluster", cluster_name="nce", vpc=vpc)

        # ── Task definition ───────────────────────────────────────────────────
        task_def = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            family="nce-safe-simulator",
            cpu=512,
            memory_limit_mib=1024,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        # Grant task role permission to read the SecureString config parameter
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{CONFIG_PARAM_NAME}"
                ],
            )
        )

        task_def.add_volume(
            name="nce-config",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=filesystem.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=config_ap.access_point_id,
                    iam="ENABLED",
                ),
            ),
        )
        task_def.add_volume(
            name="nce-reports",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=filesystem.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=reports_ap.access_point_id,
                    iam="ENABLED",
                ),
            ),
        )
        task_def.add_volume(
            name="nce-interactive",
            efs_volume_configuration=ecs.EfsVolumeConfiguration(
                file_system_id=filesystem.file_system_id,
                transit_encryption="ENABLED",
                authorization_config=ecs.AuthorizationConfig(
                    access_point_id=interactive_ap.access_point_id,
                    iam="ENABLED",
                ),
            ),
        )

        container = task_def.add_container(
            "nce",
            container_name="nce",
            image=ecs.ContainerImage.from_ecr_repository(repo, tag="latest"),
            entry_point=["sh"],
            command=["/app/scripts/entrypoint-ecs.sh"],
            environment={
                "CONFIG_PARAM": CONFIG_PARAM_NAME,
                "AWS_DEFAULT_REGION": self.region,
            },
            port_mappings=[ecs.PortMapping(container_port=80)],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="ecs",
                log_group=log_group,
            ),
        )
        container.add_mount_points(
            ecs.MountPoint(
                container_path="/mnt/config",
                read_only=False,
                source_volume="nce-config",
            ),
            ecs.MountPoint(
                container_path="/app/reports",
                read_only=False,
                source_volume="nce-reports",
            ),
            ecs.MountPoint(
                container_path="/app/public/interactive",
                read_only=False,
                source_volume="nce-interactive",
            ),
        )

        # ── ALB + Fargate service ─────────────────────────────────────────────
        service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Service",
            cluster=cluster,
            service_name="nce-safe-simulator",
            task_definition=task_def,
            load_balancer_name="nce-alb",
            desired_count=1,
            public_load_balancer=True,
            assign_public_ip=True,
            task_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            # Single-task service: allow 0 tasks during deployment (rolling stop-start)
            min_healthy_percent=0,
            max_healthy_percent=100,
            # Fail fast and roll back if the new task can't start
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )

        service.target_group.configure_health_check(
            path="/",
            healthy_http_codes="200-399",
            interval=Duration.seconds(30),
            healthy_threshold_count=2,
            unhealthy_threshold_count=3,
        )

        # Allow Fargate tasks to reach EFS (NFS port 2049)
        filesystem.connections.allow_default_port_from(service.service.connections)
        filesystem.grant_read_write(task_def.task_role)

        # ── Outputs ───────────────────────────────────────────────────────────
        CfnOutput(
            self,
            "AppUrl",
            value=f"http://{service.load_balancer.load_balancer_dns_name}",
            description="NCE Safe Simulator public URL",
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
            value=f"aws logs tail /ecs/nce-safe-simulator --follow --region {self.region}",
            description="Command to follow container logs",
        )
