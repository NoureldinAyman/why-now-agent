"""`why-now profile upload` and `resolve_profile`: a profile from a file or from the workspace."""

import json

import pytest
from typer.testing import CliRunner

from why_now.cli import app
from why_now.profile import ProfileError, profile_text
from why_now.resolve_profile import resolve_profile
from why_now.store.local import LocalStore
from why_now.workspace import Workspace


@pytest.fixture
def settings_file(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    return path


@pytest.fixture
def written(tmp_path, make_profile):
    """A profile file outside the workspace, with the profile it holds."""
    profile = make_profile()
    path = tmp_path / "mine.yaml"
    path.write_text(profile_text(profile), encoding="utf-8")
    return profile, path


def upload(settings_file, path):
    return CliRunner().invoke(
        app, ["profile", "upload", str(path), "--settings", str(settings_file)]
    )


def test_upload_saves_the_profile_in_the_workspace(settings_file, written, tmp_path):
    profile, path = written
    result = upload(settings_file, path)
    assert result.exit_code == 0, result.output
    assert profile.id in result.output
    assert Workspace(LocalStore(tmp_path / "ws")).profile(profile.id) == profile


def test_upload_refuses_a_broken_file(settings_file, tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("id: only-an-id\n", encoding="utf-8")
    result = upload(settings_file, path)
    assert result.exit_code != 0
    assert "incomplete" in result.output
    assert Workspace(LocalStore(tmp_path / "ws")).profile_ids() == []


def test_upload_keeps_the_older_version_readable(settings_file, written, tmp_path):
    profile, path = written
    upload(settings_file, path)
    edited = profile.model_copy(update={"search_words": ["sales", "account executive"]})
    path.write_text(profile_text(edited), encoding="utf-8")

    assert upload(settings_file, path).exit_code == 0

    workspace = Workspace(LocalStore(tmp_path / "ws"))
    assert workspace.profile(profile.id) == edited
    assert workspace.profile_version(profile.id, profile.version) == profile


def test_resolve_profile_takes_a_file_path(written, store):
    profile, path = written
    assert resolve_profile(str(path), store) == profile


def test_resolve_profile_takes_an_id_from_the_workspace(store, make_profile):
    profile = make_profile()
    Workspace(store).save_profile(profile, profile_text(profile))
    assert resolve_profile(profile.id, store) == profile


def test_resolve_profile_says_how_to_upload_when_nothing_matches(store):
    with pytest.raises(ProfileError, match="profile upload"):
        resolve_profile("nowhere", store)


def test_resolve_profile_reports_a_broken_file(tmp_path, store):
    path = tmp_path / "broken.yaml"
    path.write_text("not: [valid", encoding="utf-8")
    with pytest.raises(ProfileError, match="not valid YAML"):
        resolve_profile(str(path), store)
