"""The one container image: the web app on Lambda, or the night run on Fargate.

Docker isn't needed to run these. They read `infra/Dockerfile` and run the command it
starts, the way the image would, against a stand-in AWS.
"""

import json
from pathlib import Path

import pytest
import typer
from aws_fake import BUCKET, PARAMETER_PREFIX, REGION, TABLE, put_parameter
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import serve as serve_command
from why_now.store.aws import AwsStore
from why_now.web.auth_cognito import CognitoAuth

ROOT = Path(__file__).parents[1]
DOCKERFILE = ROOT / "infra" / "Dockerfile"


def instructions() -> list[tuple[str, str]]:
    """The Dockerfile's instructions as (name, rest of line), with continued lines joined."""
    joined = DOCKERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    found = []
    for line in joined.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, _, rest = line.partition(" ")
            found.append((name.upper(), rest.strip()))
    return found


def last(name: str) -> str:
    return [rest for found, rest in instructions() if found == name][-1]


def image_env() -> dict[str, str]:
    env = {}
    for found, rest in instructions():
        if found == "ENV":
            for pair in rest.split():
                key, _, value = pair.partition("=")
                env[key] = value.strip('"')
    return env


def command_names() -> set[str]:
    group = typer.main.get_command(app)
    return set(getattr(group, "commands", {}))


def test_the_image_runs_the_why_now_command():
    # So the job is chosen by the command given: the web app by default, and
    # `night-run` when the Fargate task asks for it.
    assert json.loads(last("ENTRYPOINT")) == ["why-now"]


def test_the_web_adapter_is_pinned_and_the_image_runs_on_aws():
    adapter = [rest for name, rest in instructions() if name == "COPY" and "lambda-adapter" in rest]
    assert len(adapter) == 1
    assert "aws-lambda-adapter:1." in adapter[0] and ":latest" not in adapter[0]
    assert "/opt/extensions/lambda-adapter" in adapter[0]
    assert image_env()["WHY_NOW_DEPLOYMENT"] == "aws"


def test_nothing_private_goes_into_the_image():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ignored[0] == "*"  # everything is left out unless named
    named = {line.removeprefix("!").rstrip("/") for line in ignored if line.startswith("!")}
    assert named <= {"pyproject.toml", "uv.lock", "README.md", "src", "examples"}


def test_container_starts_the_app(moto_aws, monkeypatch, tmp_path, make_profile):
    import yaml

    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(make_profile().model_dump(mode="json")))
    empty_settings = tmp_path / "settings.toml"
    empty_settings.write_text("")
    put_parameter("session-secret", "s" * 40)
    put_parameter("cognito-client-id", "client-1")
    # What the image sets, plus what the AWS setup gives the Lambda function.
    env = image_env() | {
        "WHY_NOW_AWS_REGION": REGION,
        "WHY_NOW_AWS_BUCKET": BUCKET,
        "WHY_NOW_AWS_TABLE": TABLE,
        "WHY_NOW_AWS_PARAMETER_PREFIX": PARAMETER_PREFIX,
        "WHY_NOW_COGNITO_DOMAIN": "https://login.test",
        "WHY_NOW_COGNITO_USER_POOL_ID": f"{REGION}_test",
        "WHY_NOW_DAILY_PROFILES": json.dumps([str(profile_file)]),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    started = {}

    class FakeServer:
        def __init__(self, config):
            started.update(app=config.app, host=config.host, port=config.port)

        def run(self):
            started["ran"] = True

    monkeypatch.setattr(serve_command.uvicorn, "Server", FakeServer)
    command = json.loads(last("CMD"))
    assert command[0] in command_names()
    result = CliRunner().invoke(app, [*command, "--settings", str(empty_settings)])
    assert result.exit_code == 0, result.output
    assert started["ran"]
    assert started["port"] == int(env["AWS_LWA_PORT"])  # where the web adapter sends requests
    assert started["host"] == "127.0.0.1"
    assert isinstance(started["app"].state.auth, CognitoAuth)
    assert isinstance(started["app"].state.ctx.store, AwsStore)
    page = TestClient(started["app"], base_url="https://app.test")
    assert page.get("/mark", follow_redirects=False).headers["location"] == "/login"


@pytest.mark.xfail(
    strict=True, reason="`why-now night-run` arrives with ticket 29. Remove this mark then."
)
def test_container_starts_the_night_run():
    assert "night-run" in command_names()
