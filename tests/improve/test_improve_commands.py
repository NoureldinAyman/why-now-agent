import json
from dataclasses import replace
from pathlib import Path

import yaml
from eval_world import NOW, Tracer, add_case, models_saying
from hostile_fakes import FakeJudge, fake_web_reader, models_with
from improve_world import RecordingWriter
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import daily as daily_command
from why_now.cli import evaluation as evaluation_command
from why_now.cli import improve as improve_command
from why_now.domain import RulesFile
from why_now.evaluation.evaluate import EvalRun
from why_now.hostile.attacks import load_attacks
from why_now.profile import profile_text
from why_now.settings import load_settings
from why_now.store.local import LocalStore
from why_now.workspace import Workspace
from why_now.workspace.settings_doc import save_overrides

NAMING = {
    "action": "add",
    "question_id": None,
    "question": {
        "id": "l1",
        "text": "Is Acme hiring several roles?",
        "why": "Many similar ads point to a team being built.",
    },
    "based_on": ["practice:Cora"],
}


def write_profile(tmp_path, profile, name="profile.yaml"):
    profile_file = tmp_path / name
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    return profile_file


def setup(tmp_path, monkeypatch, make_profile, *, floor=1, cutoff=True):
    """A profile and settings kept in a folder of their own, and pretend models."""
    profile = make_profile()
    profile_file = write_profile(tmp_path, profile)
    settings = tmp_path / "settings.toml"
    settings.write_text(
        f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\nfloor_yes_per_pile = {floor}\n"
    )
    workspace = Workspace(LocalStore(tmp_path / "ws"), profile.id)
    if cutoff:
        workspace.save_cutoff("fake-1", 0.5)
    everyone = {"Acme": 0.9, "Cora": 0.9, "Beta": 0.9}
    models = replace(models_saying(quick=everyone, judge=everyone), writer=RecordingWriter(NAMING))
    monkeypatch.setattr(evaluation_command, "now", lambda: NOW)
    monkeypatch.setattr(improve_command, "now", lambda: NOW)
    monkeypatch.setattr(evaluation_command, "make_models", lambda settings, meter: models)
    return workspace, ["--profile", str(profile_file), "--settings", str(settings)]


def test_improve_says_it_is_not_ready_while_the_check_pile_has_too_few_yes_answers(
    tmp_path, monkeypatch, make_profile
):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, floor=15)
    add_case(workspace, "Beta", "check", "yes")

    result = CliRunner().invoke(app, ["improve", *args])

    assert result.exit_code == 0, result.output
    assert "Not ready: the check pile has 1 yes answers and needs 15." in result.output
    assert workspace.tries() == []


def test_improve_without_a_recorded_cutoff_stops_before_anything_is_asked(
    tmp_path, monkeypatch, make_profile
):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, cutoff=False)

    result = CliRunner().invoke(app, ["improve", *args])

    assert result.exit_code == 1
    assert "No cut-off is recorded" in result.output
    assert workspace.tries() == []


def test_improve_reports_each_try_and_why_it_stopped(tmp_path, monkeypatch, make_profile):
    workspace, args = setup(tmp_path, monkeypatch, make_profile)
    add_case(workspace, "Acme", "practice", "yes")
    add_case(workspace, "Cora", "practice", "no")  # the agent says yes to her: a mistake
    add_case(workspace, "Beta", "check", "yes")

    result = CliRunner().invoke(app, ["improve", *args])

    assert result.exit_code == 0, result.output
    assert "Try 1: screened out." in result.output
    assert "names a company" in result.output
    assert "Stopped: no mistakes are left to learn from." in result.output
    assert [t.outcome for t in workspace.tries()] == ["screened_out"]


def test_the_hidden_tests_helper_says_whether_every_attack_was_resisted(
    store, settings, make_profile
):
    profile = make_profile()
    rules = RulesFile(profile_id=profile.id)

    def resisted(models) -> bool:
        run = EvalRun(
            workspace=Workspace(store, profile.id),
            profile=profile,
            models=models,
            settings=settings,
            tracer=Tracer(),
        )
        reader = fake_web_reader(settings, [])
        return improve_command._hidden_tests(run, reader, 0.5)(rules)

    first_attack = load_attacks()[0]
    swayed = models_with(judge=FakeJudge(swayed_by=(first_attack.planted_text,)))

    assert resisted(models_with()) is True
    assert resisted(swayed) is False


def test_night_run_does_the_daily_list_then_the_loop_for_each_profile(
    tmp_path, monkeypatch, make_profile
):
    first, second = make_profile(), make_profile()
    files = [
        write_profile(tmp_path, first, "one.yaml"),
        write_profile(tmp_path, second, "two.yaml"),
    ]
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    steps: list[str] = []
    monkeypatch.setattr(
        daily_command,
        "daily",
        lambda **kwargs: steps.append(f"daily {Path(kwargs['profile_ref']).name}"),
    )
    monkeypatch.setattr(
        improve_command,
        "improve_profile",
        lambda settings, workspace, profile: steps.append(f"improve {profile.id}") or True,
    )
    args = [x for f in files for x in ("--profile", str(f))]

    result = CliRunner().invoke(app, ["night-run", *args, "--settings", str(settings)])

    assert result.exit_code == 0, result.output
    assert steps == [
        "daily one.yaml",
        f"improve {first.id}",
        "daily two.yaml",
        f"improve {second.id}",
    ]


def test_night_run_with_no_profile_switched_on_says_how_to_switch_one_on(tmp_path, monkeypatch):
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["night-run", "--settings", str(settings)])

    assert result.exit_code == 0, result.output
    assert "No profile is switched on" in result.output
    assert "nightly_profiles" in result.output


def test_night_run_works_only_for_the_profiles_switched_on(tmp_path, monkeypatch, make_profile):
    on, off = make_profile(), make_profile()
    store = LocalStore(tmp_path / "ws")
    for profile in (on, off):
        Workspace(store).save_profile(profile, profile_text(profile))
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    save_overrides(store, load_settings(settings), {"nightly_profiles": [on.id]})
    steps: list[str] = []
    monkeypatch.setattr(
        daily_command, "daily", lambda **kwargs: steps.append(f"daily {kwargs['profile_ref']}")
    )
    monkeypatch.setattr(
        improve_command,
        "improve_profile",
        lambda settings, workspace, profile: steps.append(f"improve {profile.id}") or True,
    )

    result = CliRunner().invoke(app, ["night-run", "--settings", str(settings)])

    assert result.exit_code == 0, result.output
    assert steps == [f"daily {on.id}", f"improve {on.id}"]


def test_night_run_does_nothing_when_every_profile_is_off(tmp_path, monkeypatch, make_profile):
    profile = make_profile()
    store = LocalStore(tmp_path / "ws")
    Workspace(store).save_profile(profile, profile_text(profile))
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    save_overrides(store, load_settings(settings), {"nightly_profiles": []})
    monkeypatch.setattr(daily_command, "daily", lambda **kwargs: 1 / 0)

    result = CliRunner().invoke(app, ["night-run", "--settings", str(settings)])

    assert result.exit_code == 0, result.output
    assert "No profile is switched on" in result.output


def test_night_run_skips_a_listed_profile_that_is_not_in_the_workspace(
    tmp_path, monkeypatch, make_profile
):
    present = make_profile()
    store = LocalStore(tmp_path / "ws")
    Workspace(store).save_profile(present, profile_text(present))
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    save_overrides(store, load_settings(settings), {"nightly_profiles": ["gone", present.id]})
    steps: list[str] = []
    monkeypatch.setattr(
        daily_command, "daily", lambda **kwargs: steps.append(f"daily {kwargs['profile_ref']}")
    )
    monkeypatch.setattr(improve_command, "improve_profile", lambda *args: True)

    result = CliRunner().invoke(app, ["night-run", "--settings", str(settings)])

    assert result.exit_code == 0, result.output
    assert steps == [f"daily {present.id}"]
    assert "gone" in result.output
