import json

import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import serve as serve_command


def serve_args(tmp_path, make_profile, deployment: str = "local"):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n"
        f"deployment = {json.dumps(deployment)}\n"
    )
    return ["serve", "--profile", str(profile_file), "--settings", str(settings_file)]


def test_serve_listens_on_this_machine_only(tmp_path, monkeypatch, make_profile):
    started = {}

    class FakeServer:
        def __init__(self, config):
            started.update(app=config.app, host=config.host, port=config.port)

        def run(self):
            started["ran"] = True

    monkeypatch.setattr(serve_command.uvicorn, "Server", FakeServer)
    result = CliRunner().invoke(app, serve_args(tmp_path, make_profile))
    assert result.exit_code == 0, result.output
    assert started["ran"] and started["host"] == "127.0.0.1"
    assert "http://127.0.0.1" in result.output
    page = TestClient(started["app"], client=("127.0.0.1", 5000), base_url="http://localhost")
    assert page.get("/mark").status_code == 200  # the app it serves lets this machine in


def test_serve_on_aws_refuses_to_start_without_its_aws_names(tmp_path, monkeypatch, make_profile):
    class NoServer:
        def __init__(self, config):
            raise AssertionError("the server must not be built")

    monkeypatch.setattr(serve_command.uvicorn, "Server", NoServer)
    result = CliRunner().invoke(app, serve_args(tmp_path, make_profile, deployment="aws"))
    assert result.exit_code != 0
    assert "aws_region must be set" in result.output


def test_serve_needs_a_profile(tmp_path):
    settings_file = tmp_path / "settings.toml"
    settings_file.write_text("")
    result = CliRunner().invoke(app, ["serve", "--settings", str(settings_file)])
    assert result.exit_code != 0
    assert "daily_profiles" in result.output
