import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from infra.app import build_app
from infra.stack import WhyNowStack
from why_now.settings import load_settings

PROFILE = "profiles/test.yaml"
BOARDS = "boards/test.json"
ENV = {
    "WHY_NOW_DAILY_PROFILES": f'["{PROFILE}"]',
    "WHY_NOW_BOARD_LISTS": f'{{"greenhouse": "{BOARDS}"}}',
}


@pytest.fixture(scope="module")
def template() -> Template:
    settings = load_settings(None, env=ENV)
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
                        "WHY_NOW_DAILY_PROFILES": f'["{PROFILE}"]',
                    }
                )
            }
        },
    )


def test_web_lambda_may_use_its_storage_and_read_its_secrets(template: Template) -> None:
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "Roles": [{"Ref": Match.string_like_regexp("^WebServiceRole")}],
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Action": Match.array_with(["s3:PutObject"])}),
                        Match.object_like({"Action": Match.array_with(["dynamodb:PutItem"])}),
                        Match.object_like({"Action": "ssm:GetParameter"}),
                    ]
                )
            },
        },
    )


def test_login_has_a_sign_in_page_and_a_client_that_returns_to_the_web_address(
    template: Template,
) -> None:
    template.resource_count_is("AWS::Cognito::UserPoolDomain", 1)
    template.has_resource_properties(
        "AWS::Cognito::UserPoolClient",
        {
            "AllowedOAuthFlows": ["code"],
            "AllowedOAuthScopes": ["openid"],
            "GenerateSecret": True,
            "CallbackURLs": [
                {
                    "Fn::Join": [
                        "",
                        [
                            {
                                "Fn::GetAtt": [
                                    Match.string_like_regexp("^WebFunctionUrl"),
                                    "FunctionUrl",
                                ]
                            },
                            "auth/callback",
                        ],
                    ]
                }
            ],
        },
    )


def test_the_client_id_is_written_to_parameter_store(template: Template) -> None:
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/why-now/cognito-client-id", "Type": "String"}
    )


def test_web_lambda_knows_its_login_domain_and_pool(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "WHY_NOW_COGNITO_DOMAIN": Match.any_value(),
                        "WHY_NOW_COGNITO_USER_POOL_ID": Match.any_value(),
                    }
                )
            }
        },
    )


def test_the_run_has_a_public_only_network(template: Template) -> None:
    template.resource_count_is("AWS::EC2::VPC", 1)
    template.resource_count_is("AWS::EC2::Subnet", 2)
    public = template.find_resources(
        "AWS::EC2::Subnet", {"Properties": {"MapPublicIpOnLaunch": True}}
    )
    assert len(public) == 2


def test_daily_run_is_a_fargate_task_that_runs_daily(template: Template) -> None:
    template.resource_count_is("AWS::ECS::Cluster", 1)
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "RequiresCompatibilities": ["FARGATE"],
            "NetworkMode": "awsvpc",
            "Cpu": "1024",
            "Memory": "2048",
            "ContainerDefinitions": [
                Match.object_like({"Command": ["daily", "--profile", PROFILE]})
            ],
        },
    )


def test_daily_run_is_told_its_names_by_environment_values(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Environment": Match.array_with(
                            [
                                {"Name": "WHY_NOW_AWS_REGION", "Value": Match.any_value()},
                                {"Name": "WHY_NOW_AWS_BUCKET", "Value": Match.any_value()},
                                {"Name": "WHY_NOW_AWS_TABLE", "Value": Match.any_value()},
                                {
                                    "Name": "WHY_NOW_BOARD_LISTS",
                                    "Value": f'{{"greenhouse": "{BOARDS}"}}',
                                },
                            ]
                        )
                    }
                )
            ]
        },
    )


def test_daily_run_may_use_its_storage_and_read_its_secrets(template: Template) -> None:
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "Roles": [{"Ref": Match.string_like_regexp("^RunTaskTaskRole")}],
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like({"Action": Match.array_with(["s3:PutObject"])}),
                        Match.object_like({"Action": Match.array_with(["dynamodb:PutItem"])}),
                        Match.object_like({"Action": "ssm:GetParameter"}),
                    ]
                )
            },
        },
    )


def test_daily_run_is_scheduled_on_fargate(template: Template) -> None:
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "ScheduleExpression": "cron(0 2 * * ? *)",
            "State": "ENABLED",
            "Targets": [
                Match.object_like(
                    {
                        "EcsParameters": Match.object_like(
                            {
                                "LaunchType": "FARGATE",
                                "TaskCount": 1,
                                "NetworkConfiguration": {
                                    "AwsVpcConfiguration": Match.object_like(
                                        {"AssignPublicIp": "ENABLED"}
                                    )
                                },
                            }
                        )
                    }
                )
            ],
        },
    )


def test_the_run_accepts_no_connections_from_outside(template: Template) -> None:
    template.has_resource_properties(
        "AWS::EC2::SecurityGroup", {"SecurityGroupIngress": Match.absent()}
    )


def test_logs_expire(template: Template) -> None:
    template.resource_count_is("AWS::Logs::LogGroup", 2)
    template.resource_properties_count_is("AWS::Logs::LogGroup", {"RetentionInDays": 14}, 2)


def test_no_secret_values_in_the_template(template: Template) -> None:
    template.resource_count_is("AWS::SecretsManager::Secret", 0)
    template.resource_count_is("AWS::SSM::Parameter", 1)
    template.resource_properties_count_is("AWS::SSM::Parameter", {"Type": "String"}, 1)
    text = json.dumps(template.to_json())
    for word in ("session-secret", "client-secret", "sk-ant-", "PASSWORD"):
        assert word not in text


def test_app_builds_the_stack_where_the_settings_say() -> None:
    settings = load_settings(None, env=ENV | {"WHY_NOW_AWS_REGION": "eu-test-1"})
    app = build_app(settings, account="111111111111")
    stack = app.node.find_child("WhyNow")
    assert isinstance(stack, WhyNowStack)
    assert (stack.region, stack.account) == ("eu-test-1", "111111111111")


def test_the_app_refuses_to_build_without_a_region() -> None:
    with pytest.raises(ValueError, match="aws_region"):
        build_app(load_settings(None, env=ENV), account=None)


def test_stack_builds_from_example_settings() -> None:
    example = Path(__file__).resolve().parents[2] / "examples" / "settings.example.toml"
    settings = load_settings(example, env=ENV | {"WHY_NOW_AWS_REGION": "eu-test-1"})
    app = build_app(settings, account=None)
    assert isinstance(app.node.find_child("WhyNow"), WhyNowStack)


def test_daily_run_gets_its_model_keys_from_parameter_store(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Secrets": [
                            {"Name": "ANTHROPIC_API_KEY", "ValueFrom": Match.any_value()},
                            {"Name": "TYPESAFE_API_KEY", "ValueFrom": Match.any_value()},
                        ]
                    }
                )
            ]
        },
    )


def test_the_staged_image_folder_holds_the_dockerfile() -> None:
    app = build_app(
        load_settings(None, env=ENV | {"WHY_NOW_AWS_REGION": "eu-test-1"}), account=None
    )
    staged = Path(app.synth().directory)
    assert list(staged.glob("asset.*/infra/Dockerfile")), (
        "the image build cannot find its Dockerfile"
    )


def test_zero_web_copies_leaves_the_function_unreserved() -> None:
    settings = load_settings(None, env=ENV | {"WHY_NOW_AWS_WEB_MAX_COPIES": "0"})
    unreserved = Template.from_stack(WhyNowStack(cdk.App(), "WhyNowZero", settings=settings))
    unreserved.has_resource_properties(
        "AWS::Lambda::Function", {"ReservedConcurrentExecutions": Match.absent()}
    )
