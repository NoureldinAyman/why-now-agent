from pathlib import Path

from aws_cdk import Duration, Stack
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

from why_now.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent


class WhyNowStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, settings: Settings) -> None:
        super().__init__(scope, construct_id)
        self.settings = settings

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
        self.web.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    self.format_arn(
                        service="ssm", resource="parameter", resource_name=f"{parameter_path}/*"
                    )
                ],
            )
        )