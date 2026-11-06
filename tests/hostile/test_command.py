import json

import yaml
from hostile_fakes import FakeJudge, models_with
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import hostile as hostile_command
from why_now.hostile.attacks import load_attacks
from why_now.store.local import LocalStore
from why_now.workspace import Workspace


def setup(tmp_path, make_profile, *, cutoff: float | None = 0.5):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    if cutoff is not None:
        Workspace(LocalStore(tmp_path / "ws"), profile.id).save_cutoff("scripted", cutoff)
    return ["--profile", str(profile_file), "--settings", str(settings)]


def test_models_that_resist_every_attack_give_a_clean_report(tmp_path, monkeypatch, make_profile):
    args = setup(tmp_path, make_profile)
    monkeypatch.setattr(hostile_command, "make_models", lambda settings, meter: models_with())
    result = CliRunner().invoke(app, ["hostile-test", *args])
    n = len(load_attacks())
    assert result.exit_code == 0, result.output
    assert f"{n} of {n} attacks were resisted." in result.output
    assert "WORKED" not in result.output


def test_an_attack_that_worked_is_named_and_the_command_fails(tmp_path, monkeypatch, make_profile):
    args = setup(tmp_path, make_profile)
    first = load_attacks()[0]
    swayed = models_with(judge=FakeJudge(swayed_by=(first.planted_text,)))
    monkeypatch.setattr(hostile_command, "make_models", lambda settings, meter: swayed)
    result = CliRunner().invoke(app, ["hostile-test", *args])
    assert result.exit_code == 1
    assert f"WORKED  {first.id}" in result.output
    assert "decision differs from the clean twin" in result.output


def test_without_a_recorded_cutoff_it_stops_before_any_attack(tmp_path, monkeypatch, make_profile):
    args = setup(tmp_path, make_profile, cutoff=None)
    monkeypatch.setattr(hostile_command, "make_models", lambda settings, meter: models_with())
    result = CliRunner().invoke(app, ["hostile-test", *args])
    assert result.exit_code == 1
    assert "No cut-off is recorded" in result.output
