"""The store and the login for where the app runs: this machine, or AWS.

On AWS, secrets come from the environment first, under a name in capitals such as
`SESSION_SECRET`, and otherwise from Parameter Store, under the `aws_parameter_prefix`
setting, such as `/why-now/session-secret`. The owner puts them there. No secret is a
setting, so none is ever written in a settings file.

The AWS libraries are only imported for AWS, so running on one's own machine needs none.
"""

from collections.abc import Mapping

from why_now.settings import Settings
from why_now.store import Store
from why_now.store.aws import AwsStore, ClientFactory
from why_now.store.local import LocalStore
from why_now.web.auth import Authenticator, LocalAuth


def aws_clients(settings: Settings) -> ClientFactory:
    import boto3

    return lambda service: boto3.client(service, region_name=settings.aws_region)


def open_store(settings: Settings) -> Store:
    if settings.deployment == "local":
        return LocalStore(settings.workspace_path)
    _require(settings, "aws_region", "aws_bucket", "aws_table")
    return AwsStore(
        settings.aws_bucket,
        settings.aws_table,
        aws_clients(settings),
        inline_max_bytes=settings.aws_inline_max_bytes,
    )


def build_auth(settings: Settings, env: Mapping[str, str]) -> Authenticator:
    if settings.deployment == "local":
        return LocalAuth()
    from why_now.web.auth_cognito import CognitoAuth

    clients = aws_clients(settings)
    if not settings.cognito_client_id:
        # The AWS setup writes the login client's ID to Parameter Store, because the
        # client is made after the web address it sends people back to.
        client_id = read_secret(settings, "cognito-client-id", env, clients) or ""
        settings = settings.model_copy(update={"cognito_client_id": client_id})
    return CognitoAuth(
        settings,
        read_secret(settings, "session-secret", env, clients) or "",
        client_secret=read_secret(settings, "cognito-client-secret", env, clients),
    )


def read_secret(
    settings: Settings, name: str, env: Mapping[str, str], clients: ClientFactory
) -> str | None:
    """`name` from the environment, else from Parameter Store, else None."""
    value = env.get(name.upper().replace("-", "_"))
    if value:
        return value
    from botocore.exceptions import ClientError

    try:
        found = clients("ssm").get_parameter(
            Name=f"{settings.aws_parameter_prefix.rstrip('/')}/{name}", WithDecryption=True
        )
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "ParameterNotFound":
            return None
        raise
    return found["Parameter"]["Value"] or None


def _require(settings: Settings, *names: str) -> None:
    for name in names:
        if not getattr(settings, name):
            raise ValueError(f"{name} must be set when deployment is aws")
