import json

import yaml
from eval_world import NOW, ByCompany, Sequence, add_case, models_saying
from typer.testing import CliRunner

from why_now.ai.budget import Meter
from why_now.cli import app
from why_now.cli import evaluation as evaluation_command
from why_now.store.local import LocalStore
from why_now.workspace import Workspace


def setup(tmp_path, monkeypatch, make_profile, *, quick, judge):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    workspace = Workspace(LocalStore(tmp_path / "ws"), profile.id)
    monkeypatch.setattr(evaluation_command, "now", lambda: NOW)
    monkeypatch.setattr(
        evaluation_command,
        "make_models",
        lambda settings, meter: models_saying(quick=quick, judge=judge),
    )
    args = ["--profile", str(profile_file), "--settings", str(settings)]
    return workspace, args


def run(command: str, args: list[str], *extra: str):
    return CliRunner().invoke(app, [command, *args, *extra])


def test_evaluate_shows_the_score_and_keeps_a_score_point(tmp_path, monkeypatch, make_profile):
    both = {"Acme": 0.9, "Beta": 0.9}
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick=both, judge=both)
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")

    result = run("evaluate", args, "--pile", "check")

    assert result.exit_code == 0, result.output
    assert "check pile, 2 companies: 1 right yes, 1 wrong yes" in result.output
    assert "Short lists: no decisions yet." in result.output
    assert [p.result.pile for p in workspace.score_points()] == ["check"]


def test_evaluate_refuses_the_final_pile_and_points_to_open_final(
    tmp_path, monkeypatch, make_profile
):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick={}, judge={})

    result = run("evaluate", args, "--pile", "final")

    assert result.exit_code == 1
    assert "open_final_pile" in result.output
    assert workspace.final_pile_openings() == []


def test_set_cutoff_records_a_cutoff_for_the_judge(tmp_path, monkeypatch, make_profile):
    both = {"Acme": 0.9, "Beta": 0.2}
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick=both, judge=both)
    add_case(workspace, "Acme", "practice", "yes")
    add_case(workspace, "Beta", "practice", "no")

    result = run("set-cutoff", args)

    assert result.exit_code == 0, result.output
    assert "Cut-off for fake-1" in result.output
    assert workspace.cutoff("fake-1") is not None


def test_open_final_logs_the_opening(tmp_path, monkeypatch, make_profile):
    workspace, args = setup(
        tmp_path, monkeypatch, make_profile, quick={"Acme": 0.9}, judge={"Acme": 0.9}
    )
    add_case(workspace, "Acme", "final", "yes")

    result = run("open-final", args, "--moment", "first")

    assert result.exit_code == 0, result.output
    assert "The opening is logged." in result.output
    assert [o.moment for o in workspace.final_pile_openings()] == ["first"]


def test_an_extra_opening_without_a_reason_is_refused_and_not_logged(
    tmp_path, monkeypatch, make_profile
):
    workspace, args = setup(
        tmp_path, monkeypatch, make_profile, quick={"Acme": 0.9}, judge={"Acme": 0.9}
    )
    add_case(workspace, "Acme", "final", "yes")

    result = run("open-final", args, "--moment", "extra")

    assert result.exit_code == 1
    assert "needs a reason" in result.output
    assert workspace.final_pile_openings() == []


def test_baselines_shows_the_three_rivals(tmp_path, monkeypatch, make_profile):
    quick = {"Acme": 0.9, "Beta": 0.9, "Cora": 0.1}
    workspace, args = setup(
        tmp_path, monkeypatch, make_profile, quick=quick, judge={"Acme": 0.9, "Beta": 0.2}
    )
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    add_case(workspace, "Cora", "check", "no")

    result = run("baselines", args, "--pile", "check")

    assert result.exit_code == 0, result.output
    for name in ("yes to all", "quick look only", "empty rules"):
        assert name in result.output


def test_baselines_refuse_the_final_pile_on_the_command_line(tmp_path, monkeypatch, make_profile):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick={}, judge={})
    add_case(workspace, "Acme", "final", "yes")

    result = run("baselines", args, "--pile", "final")

    assert result.exit_code == 1
    assert "open_final_pile" in result.output


def test_without_a_jev_key_the_comparison_uses_the_fallback_and_keeps_the_current_judge_first(
    store, settings
):
    meter = Meter(store, settings, lambda: NOW)
    env = {"ANTHROPIC_API_KEY": "test-key"}

    answerers = evaluation_command.make_answerers(settings, meter, env)

    assert [a.model for a in answerers] == ["claude-sonnet-5-5", "claude-haiku-5-5"]


def test_compare_models_shows_both_scores_and_the_winner(tmp_path, monkeypatch, make_profile):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick={}, judge={})
    names = ["Pia", "Pete", "Acme", "Beta"]
    add_case(workspace, "Pia", "practice", "yes")
    add_case(workspace, "Pete", "practice", "no")
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Beta", "check", "no")
    right = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.2}, "judge-a")
    wrong = ByCompany({"Pia": 0.9, "Pete": 0.2, "Acme": 0.9, "Beta": 0.9}, "judge-b")
    monkeypatch.setattr(evaluation_command, "make_answerers", lambda *a: [right, wrong])
    monkeypatch.setattr(
        evaluation_command,
        "make_models",
        lambda settings, meter: models_saying(quick={n: 0.9 for n in names}, judge={}),
    )

    result = run("compare-models", args)

    assert result.exit_code == 0, result.output
    assert "judge-a: 2 companies" in result.output
    assert "Winner: judge-a" in result.output
    assert [c.winner for c in workspace.comparisons()] == ["judge-a"]


def test_consistency_reads_practice_packs_only_and_shows_the_spread(
    tmp_path, monkeypatch, make_profile
):
    workspace, args = setup(tmp_path, monkeypatch, make_profile, quick={}, judge={})
    add_case(workspace, "Pia", "practice", "yes")
    add_case(workspace, "Pete", "practice", "yes")
    add_case(workspace, "Acme", "check", "yes")
    add_case(workspace, "Dune", "final", "yes")
    wobbly = Sequence([0.2, 0.4, 0.6, 0.8, 1.0])
    monkeypatch.setattr(evaluation_command, "make_answerers", lambda *a: [wobbly])

    result = run("consistency", args)

    assert result.exit_code == 0, result.output
    assert "wobbly-1: 5 asks on 2 companies" in result.output
    assert "f1: answers moved 0.80 on average, 0.80 at worst." in result.output
    assert [r.companies for r in workspace.consistency_results()] == [2]
