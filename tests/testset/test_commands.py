import json
from datetime import UTC, date, datetime, timedelta

import yaml
from typer.testing import CliRunner

from why_now.ai import ResearchStep
from why_now.cli import app
from why_now.cli import testset as testset_command
from why_now.domain import JobAd
from why_now.settings import Settings
from why_now.store.local import LocalStore
from why_now.testset.piles import pile_for
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def ad(board: str, days_ago: int, title: str = "Sales Rep") -> JobAd:
    return JobAd(
        source="greenhouse",
        board=board,
        ad_id="1",
        company_name=board.title(),
        title=title,
        location="Cairo",
        country=None,
        language=None,
        text="Sell things.",
        url=f"https://jobs.test/{board}/1",
        published_at=NOW - timedelta(days=days_ago),
        first_seen=date(2026, 11, 1),
    )


class DoneModel:
    model = "done"
    answer_key = model

    def __init__(self):
        self.calls = 0

    def step(self, conversation: list[dict], category: str) -> ResearchStep:
        self.calls += 1
        return ResearchStep(read_urls=[], searches_used=0, done=True)


def setup(tmp_path, monkeypatch, make_profile):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n")
    ws = Workspace(LocalStore(tmp_path / "ws"), profile.id)
    for board, days_ago, title in [
        ("acme", 1, "Sales Rep"),
        ("globex", 3, "Account Executive Sales"),
        ("old", 30, "Sales Rep"),
        ("other", 1, "Engineer"),
    ]:
        ws.save_board_ads("greenhouse", board, [ad(board, days_ago, title)])
    model = DoneModel()
    monkeypatch.setattr(testset_command, "now", lambda: NOW)
    monkeypatch.setattr(testset_command, "make_research", lambda settings, meter: model)
    args = ["--profile", str(profile_file), "--settings", str(settings)]
    return ws, args, model


def test_pick_then_build_makes_one_frozen_pack_per_case(tmp_path, monkeypatch, make_profile):
    ws, args, model = setup(tmp_path, monkeypatch, make_profile)
    runner = CliRunner()

    result = runner.invoke(app, ["pick-cases", *args, "--n", "5", "--seed", "42"])
    assert result.exit_code == 0, result.output
    assert "Picked 2 of 2 companies" in result.output and "seed 42" in result.output
    assert sorted(c.company_key for c in ws.cases()) == ["acme", "globex"]
    assert ws.picks()[0].seed == 42

    result = runner.invoke(app, ["build-packs", *args])
    assert result.exit_code == 0, result.output
    assert "Built 2 evidence packs" in result.output
    result = runner.invoke(app, ["build-packs", *args])
    assert "Built 0 evidence packs. 2 were built before" in result.output
    assert model.calls == 2
    assert not ws.one_time_research_active()


def test_each_case_gets_its_pile_when_it_is_picked_and_keeps_it(
    tmp_path, monkeypatch, make_profile, settings: Settings
):
    ws, args, _ = setup(tmp_path, monkeypatch, make_profile)
    runner = CliRunner()
    runner.invoke(app, ["pick-cases", *args, "--n", "1", "--seed", "1"])
    runner.invoke(app, ["pick-cases", *args, "--n", "1", "--seed", "2"])
    seed_of = {pick.picked[0]: pick.seed for pick in ws.picks()}
    expected = {key: pile_for(seed, key, settings) for key, seed in seed_of.items()}
    assert {c.company_key: c.pile for c in ws.cases()} == expected

    runner.invoke(app, ["build-packs", *args])
    assert all(c.pack_id for c in ws.cases())
    assert {c.company_key: c.pile for c in ws.cases()} == expected


def test_picking_again_never_repeats_a_company(tmp_path, monkeypatch, make_profile):
    ws, args, _ = setup(tmp_path, monkeypatch, make_profile)
    runner = CliRunner()
    runner.invoke(app, ["pick-cases", *args, "--n", "1", "--seed", "1"])
    result = runner.invoke(app, ["pick-cases", *args, "--n", "5", "--seed", "2"])
    assert "Only 1 could be picked" in result.output
    assert sorted(c.company_key for c in ws.cases()) == ["acme", "globex"]
    assert [p.seed for p in ws.picks()] == [1, 2]


class Idle:
    model = answer_key = "idle"

    def answer(self, state, questions, category):
        raise AssertionError("not used")

    def structured(self, *, system, untrusted, schema, category):
        raise AssertionError("not used")

    def step(self, conversation, category):
        raise AssertionError("not used")


def use_models(monkeypatch, research):
    from why_now.ai import Models

    monkeypatch.setattr(
        testset_command,
        "make_models",
        lambda settings, meter: Models(
            quick_look=Idle(), judge=Idle(), writer=Idle(), research=research
        ),
    )


def test_prepare_picks_researches_and_a_rerun_with_its_seed_pays_nothing_twice(
    tmp_path, monkeypatch, make_profile
):
    ws, args, model = setup(tmp_path, monkeypatch, make_profile)
    use_models(monkeypatch, model)
    runner = CliRunner()

    result = runner.invoke(app, ["prepare", *args, "--n", "5", "--seed", "42"])
    assert result.exit_code == 0, result.output
    assert "Picked 2 of 2 companies" in result.output and "seed 42" in result.output
    assert "Only 2 could be picked, fewer than the 5 asked for" in result.output
    assert "Built 2 evidence packs" in result.output
    assert all(c.pack_id for c in ws.cases()) and model.calls == 2

    again = runner.invoke(app, ["prepare", *args, "--n", "5", "--seed", "42"])
    assert again.exit_code == 0, again.output
    assert "already picked with seed 42" in again.output
    assert "Built 0 evidence packs" in again.output
    assert model.calls == 2


def test_prepare_uses_the_batch_setting_and_records_a_seed_when_none_is_given(
    tmp_path, monkeypatch, make_profile
):
    ws, args, model = setup(tmp_path, monkeypatch, make_profile)
    use_models(monkeypatch, model)
    settings_file = args[args.index("--settings") + 1]
    with open(settings_file, "a", encoding="utf-8") as f:
        f.write("prepare_batch = 1\n")
    result = CliRunner().invoke(app, ["prepare", *args])
    assert result.exit_code == 0, result.output
    [pick] = ws.picks()
    assert pick.n == 1 and f"seed {pick.seed}" in result.output


def test_prepare_says_so_when_there_are_no_ads_to_pick_from(tmp_path, monkeypatch, make_profile):
    ws, args, model = setup(tmp_path, monkeypatch, make_profile)
    use_models(monkeypatch, model)
    monkeypatch.setattr(testset_command, "now", lambda: NOW + timedelta(days=100))
    result = CliRunner().invoke(app, ["prepare", *args, "--seed", "1"])
    assert result.exit_code == 1
    assert "No company has a relevant ad" in result.output and model.calls == 0
