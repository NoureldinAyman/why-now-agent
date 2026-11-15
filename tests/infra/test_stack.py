import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.stack import WhyNowStack
from why_now.settings import load_settings


@pytest.fixture(scope="module")
def template() -> Template:
    settings = load_settings(None, env={})
    app = cdk.App()
    stack = WhyNowStack(app, "WhyNowTest", settings=settings)
    return Template.from_stack(stack)


def test_no_always_on_servers_or_paid_gateways(template: Template) -> None:
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::ElasticLoadBalancingV2::LoadBalancer", 0)
    template.resource_count_is("AWS::RDS::DBInstance", 0)


def test_storage_is_private_and_charged_by_use(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": Match.object_like(
                {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                }
            )
        },
    )
    template.has_resource_properties("AWS::DynamoDB::Table", {"BillingMode": "PAY_PER_REQUEST"})


def test_login_has_no_self_sign_up_and_needs_an_authenticator_app(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Cognito::UserPool",
        {
            "AdminCreateUserConfig": {"AllowAdminCreateUserOnly": True},
            "MfaConfiguration": "ON",
            "EnabledMfas": ["SOFTWARE_TOKEN_MFA"],
        },
    )


def test_web_lambda_has_limited_concurrency_and_a_url(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "PackageType": "Image",
            "MemorySize": 1024,
            "Timeout": 30,
            "ReservedConcurrentExecutions": 2,
        },
    )
    template.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE"})


def test_web_lambda_is_told_its_names_by_environment_values(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "WHY_NOW_AWS_REGION": Match.any_value(),
                        "WHY_NOW_AWS_BUCKET": Match.any_value(),
                        "WHY_NOW_AWS_TABLE": Match.any_value(),
                    }
                )
            }
        },
    )


def test_web_lambda_may_use_its_storage_and_read_its_secrets(template: Template) -> None:
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Action": Match.array_with(["s3:PutObject"])}),
                        Match.object_like({"Action": Match.array_with(["dynamodb:PutItem"])}),
                        Match.object_like({"Action": "ssm:GetParameter"}),
                    ]
                )
            }
        },
    )