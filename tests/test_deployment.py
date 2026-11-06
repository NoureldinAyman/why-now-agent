"""Choosing the store and the login for where the app runs: this machine, or AWS."""

import pytest
from aws_fake import BUCKET, PARAMETER_PREFIX, REGION, TABLE, put_parameter

from why_now.deployment import build_auth, open_store
from why_now.settings import Settings
from why_now.store.aws import AwsStore
from why_now.store.local import LocalStore
from why_now.web.auth import LocalAuth
from why_now.web.auth_cognito import CognitoAuth

SECRET = "s" * 40


@pytest.fixture
def settings_aws(settings) -> Settings:
    return settings.model_copy(
        update={
            "deployment": "aws",
            "aws_region": REGION,
            "aws_bucket": BUCKET,
            "aws_table": TABLE,
            "aws_parameter_prefix": PARAMETER_PREFIX,
            "cognito_domain": "https://login.test",
            "cognito_user_pool_id": f"{REGION}_test",
        }
    )


def test_on_this_machine_the_workspace_folder_and_local_login_are_used(settings):
    assert isinstance(open_store(settings), LocalStore)
    assert isinstance(build_auth(settings, env={}), LocalAuth)


def test_on_aws_the_aws_store_is_used(moto_aws, settings_aws):
    store = open_store(settings_aws)
    assert isinstance(store, AwsStore)
    store.put("c", "k", {"v": 1})
    assert store.get("c", "k") == {"v": 1}


def test_the_aws_store_needs_its_names(settings_aws):
    with pytest.raises(ValueError, match="aws_bucket"):
        open_store(settings_aws.model_copy(update={"aws_bucket": ""}))


def test_login_secrets_come_from_parameter_store(moto_aws, settings_aws):
    put_parameter("session-secret", SECRET)
    put_parameter("cognito-client-id", "client-from-parameter-store")
    auth = build_auth(settings_aws, env={})
    assert isinstance(auth, CognitoAuth)
    assert auth.settings.cognito_client_id == "client-from-parameter-store"


def test_the_environment_wins_over_parameter_store(moto_aws, settings_aws):
    put_parameter("session-secret", "too short")
    env = {"SESSION_SECRET": SECRET, "COGNITO_CLIENT_ID": "client-from-env"}
    auth = build_auth(settings_aws, env=env)
    assert isinstance(auth, CognitoAuth)
    assert auth.settings.cognito_client_id == "client-from-env"


def test_a_client_id_in_the_settings_is_used_as_it_is(moto_aws, settings_aws):
    chosen = settings_aws.model_copy(update={"cognito_client_id": "client-from-settings"})
    auth = build_auth(chosen, env={"SESSION_SECRET": SECRET})
    assert isinstance(auth, CognitoAuth)
    assert auth.settings.cognito_client_id == "client-from-settings"


def test_a_missing_session_secret_stops_the_app_on_aws(moto_aws, settings_aws):
    put_parameter("cognito-client-id", "client-1")
    with pytest.raises(ValueError, match="session secret"):
        build_auth(settings_aws, env={})
