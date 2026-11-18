"""Every command that takes --profile accepts a workspace profile id as well as a file."""

import json

from typer.testing import CliRunner

from why_now.cli import app
from why_now.profile import profile_text
from why_now.store.local import LocalStore
from why_now.workspace import Workspace


def settings_in(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    return path


def test_a_command_runs_for_a_profile_uploaded_to_the_workspace(tmp_path, make_profile):
    profile = make_profile()
    Workspace(LocalStore(tmp_path / "ws")).save_profile(profile, profile_text(profile))

    result = CliRunner().invoke(
        app, ["piles", "--profile", profile.id, "--settings", str(settings_in(tmp_path))]
    )

    assert result.exit_code == 0, result.output


def test_an_unknown_profile_says_how_to_upload_one(tmp_path):
    result = CliRunner().invoke(
        app, ["piles", "--profile", "nowhere", "--settings", str(settings_in(tmp_path))]
    )

    assert result.exit_code != 0
    assert "profile upload" in result.output


def test_a_run_starts_with_the_settings_stored_in_the_workspace(tmp_path, make_profile):
    from why_now.cli.testset import open_workspace
    from why_now.settings import load_settings
    from why_now.workspace.settings_doc import save_overrides

    profile = make_profile()
    store = LocalStore(tmp_path / "ws")
    Workspace(store).save_profile(profile, profile_text(profile))
    settings_file = settings_in(tmp_path)
    save_overrides(store, load_settings(settings_file), {"prepare_batch": 7})

    settings, _, _ = open_workspace(profile.id, settings_file)

    assert settings.prepare_batch == 7
