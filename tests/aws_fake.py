"""A stand-in AWS for tests, using moto, which keeps S3, DynamoDB and Parameter Store in
this process. No test touches a real AWS account."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

REGION = "us-east-1"  # any region works against moto
BUCKET = "test-workspace-files"
TABLE = "test-workspace"
PARAMETER_PREFIX = "/why-now-test"


@contextmanager
def fake_aws() -> Iterator[None]:
    """The bucket and table the AWS setup creates, in a stand-in AWS."""
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[
                {"AttributeName": "collection", "KeyType": "HASH"},
                {"AttributeName": "key", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "collection", "AttributeType": "S"},
                {"AttributeName": "key", "AttributeType": "S"},
            ],
        )
        yield


def put_parameter(name: str, value: str) -> None:
    boto3.client("ssm", region_name=REGION).put_parameter(
        Name=f"{PARAMETER_PREFIX}/{name}", Value=value, Type="SecureString"
    )
