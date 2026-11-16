import json
from pathlib import Path

from aws_cdk import Duration, Environment, Names, RemovalPolicy, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from why_now.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_RETENTION = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
}


class WhyNowStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        settings: Settings,
        env: Environment | None = None,
    ) -> None:
        super().__init__(scope, construct_id, env=env)
        self.settings = settings
        retention = LOG_RETENTION.get(settings.aws_log_retention_days)
        if retention is None:
            raise ValueError(f"aws_log_retention_days must be one of {sorted(LOG_RETENTION)}")
        web_logs = logs.LogGroup(
            self, "WebLogs", retention=retention, removal_policy=RemovalPolicy.DESTROY
        )
        run_logs = logs.LogGroup(
            self, "RunLogs", retention=retention, removal_policy=RemovalPolicy.DESTROY
        )

        self.bucket = s3.Bucket(
            self,
            "Bucket",
            bucket_name=settings.aws_bucket or None,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
        )
        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=settings.aws_table or None,
            partition_key=dynamodb.Attribute(name="collection", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="key", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
        )
        self.web = lambda_.DockerImageFunction(
            self,
            "Web",
            code=lambda_.DockerImageCode.from_image_asset(str(REPO_ROOT), file="infra/Dockerfile"),
            architecture=lambda_.Architecture.X86_64,
            memory_size=settings.aws_web_memory_mb,
            timeout=Duration.seconds(settings.aws_web_timeout_seconds),
            reserved_concurrent_executions=settings.aws_web_max_copies,
            log_group=web_logs,
            environment={
                "WHY_NOW_AWS_REGION": self.region,
                "WHY_NOW_AWS_BUCKET": self.bucket.bucket_name,
                "WHY_NOW_AWS_TABLE": self.table.table_name,
            },
        )
        self.web_url = self.web.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        self.bucket.grant_read_write(self.web)
        self.table.grant_read_write_data(self.web)
        parameter_path = settings.aws_parameter_prefix.strip("/")
        read_secrets = iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[
                self.format_arn(
                    service="ssm", resource="parameter", resource_name=f"{parameter_path}/*"
                )
            ],
        )
        self.web.add_to_role_policy(read_secrets)
        self.domain = self.user_pool.add_domain(
            "Domain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=Names.unique_id(self.user_pool).lower()
            ),
        )
        self.client = self.user_pool.add_client(
            "Client",
            generate_secret=True,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID],
                callback_urls=[f"{self.web_url.url}auth/callback"],
            ),
        )
        ssm.StringParameter(
            self,
            "ClientId",
            parameter_name=f"/{parameter_path}/cognito-client-id",
            string_value=self.client.user_pool_client_id,
        )
        self.web.add_environment("WHY_NOW_COGNITO_DOMAIN", self.domain.base_url())
        self.web.add_environment("WHY_NOW_COGNITO_USER_POOL_ID", self.user_pool.user_pool_id)
        self.network = ec2.Vpc(
            self,
            "Network",
            max_azs=settings.aws_network_zones,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC)
            ],
        )
        if not settings.daily_profiles:
            raise ValueError("daily_profiles must name a profile for the scheduled run")
        self.cluster = ecs.Cluster(self, "Cluster", vpc=self.network)
        self.run_task = ecs.FargateTaskDefinition(
            self,
            "RunTask",
            cpu=settings.aws_run_cpu,
            memory_limit_mib=settings.aws_run_memory_mb,
        )
        anthropic_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "AnthropicKey", parameter_name=f"/{parameter_path}/anthropic-api-key"
        )
        typesafe_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self, "TypesafeKey", parameter_name=f"/{parameter_path}/typesafe-api-key"
        )
        self.run_task.add_container(
            "Run",
            image=ecs.ContainerImage.from_asset(str(REPO_ROOT), file="infra/Dockerfile"),
            command=["daily", "--profile", settings.daily_profiles[0].as_posix()],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="run", log_group=run_logs),
            environment={
                "WHY_NOW_AWS_REGION": self.region,
                "WHY_NOW_AWS_BUCKET": self.bucket.bucket_name,
                "WHY_NOW_AWS_TABLE": self.table.table_name,
                "WHY_NOW_BOARD_LISTS": json.dumps(
                    {name: path.as_posix() for name, path in settings.board_lists.items()}
                ),
            },
            secrets={
                "ANTHROPIC_API_KEY": ecs.Secret.from_ssm_parameter(anthropic_key),
                "TYPESAFE_API_KEY": ecs.Secret.from_ssm_parameter(typesafe_key),
            },
        )
        self.bucket.grant_read_write(self.run_task.task_role)
        self.table.grant_read_write_data(self.run_task.task_role)
        self.run_task.add_to_task_role_policy(read_secrets)
        run_firewall = ec2.SecurityGroup(self, "RunFirewall", vpc=self.network)
        events.Rule(
            self,
            "DailyRun",
            schedule=events.Schedule.cron(minute="0", hour=str(settings.aws_run_hour_utc)),
            targets=[
                targets.EcsTask(
                    cluster=self.cluster,
                    task_definition=self.run_task,
                    subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                    assign_public_ip=True,
                    security_groups=[run_firewall],
                )
            ],
        )
