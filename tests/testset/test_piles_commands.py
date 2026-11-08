import json
from datetime import UTC, datetime, timedelta

import yaml
from typer.testing import CliRunner

from why_now.cli import app
from why_now.cli import piles as piles_command
from why_now.domain import CaseRecord, Mark
from why_now.store.local import LocalStore
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


# Pile and first answer of each case, by hand. "-" is not marked yet.
PILES = [
    ("practice", "yes"), ("practice", "yes"), ("practice", "yes"), ("practice", "no"),
    ("practice", "no"), ("practice", "cant_tell"), ("check", "yes"), ("check", "no"),
    ("check", "no"), ("check", "-"), ("final", "yes"), ("final", "yes"), ("final", "no"),
    ("final", "no"),
]  # fmt: skip


def setup(tmp_path, monkeypatch, make_profile, days_ago=8, floor=3):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(
        f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n"
        "practice_size = 12\ncheck_size = 6\nfinal_size = 6\n"
        f"target_yes_per_pile = 2\nfloor_yes_per_pile = {floor}\nremark_size = 5\n"
    )
    ws = Workspace(LocalStore(tmp_path / "ws"), profile.id)
    for i, (pile, answer) in enumerate(PILES):
        ws.save_case(
            CaseRecord.model_validate(
                {
                    "case_id": f"case-{i:03d}",
                    "profile_id": profile.id,
                    "company_key": f"c{i}",
                    "seed": 1,
                    "pack_id": f"pack-{i}",
                    "pile": pile,
                }
            )
        )
        if answer == "-":
            continue
        ws.save_mark(
            Mark.model_validate(
                {
                    "case_id": f"case-{i:03d}",
                    "answer": answer,
                    "reason": "r",
                    "marked_at": NOW - timedelta(days=days_ago),
                    "round": "first",
                }
            )
        )
    monkeypatch.setattr(piles_command, "now", lambda: NOW)
    return ws, ["--profile", str(profile_file), "--settings", str(settings)]


def test_yes_share_shows_the_counts_and_what_is_needed(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile)
    result = CliRunner().invoke(app, ["yes-share", *args])
    assert result.exit_code == 0, result.output
    assert "13 marked: 6 yes, 6 no, 1 can't tell." in result.output
    assert "50%" in result.output  # 6 of 12
    assert "33%" in result.output  # 2 of a pile of 6


def test_piles_reports_each_pile_and_that_the_loop_must_wait(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile)
    result = CliRunner().invoke(app, ["piles", *args])
    assert result.exit_code == 0, result.output
    # Counted by hand from `PILES` above.
    assert "practice: 6 companies, 6 marked: 3 yes, 2 no, 1 can't tell." in result.output
    assert "check: 4 companies, 3 marked: 1 yes, 2 no, 0 can't tell." in result.output
    assert "final: 4 companies, 4 marked: 2 yes, 2 no, 0 can't tell." in result.output
    assert "Not ready" in result.output and "1 of 3 yes answers" in result.output


def test_piles_says_when_the_loop_can_start(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile, floor=1)
    result = CliRunner().invoke(app, ["piles", *args])
    assert result.exit_code == 0, result.output
    assert "Ready: the check pile has 1 yes answers" in result.output


def test_split_piles_is_gone(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile)
    result = CliRunner().invoke(app, ["split-piles", *args, "--seed", "7"])
    assert result.exit_code != 0 and "No such command" in result.output


def test_repeat_marks_picks_once_and_agreement_follows(tmp_path, monkeypatch, make_profile):
    ws, args = setup(tmp_path, monkeypatch, make_profile)
    runner = CliRunner()
    result = runner.invoke(app, ["repeat-marks", *args, "--seed", "3"])
    assert result.exit_code == 0, result.output
    picked = ws.repeat_selection()
    assert picked is not None and len(picked) == 5

    again = runner.invoke(app, ["repeat-marks", *args, "--seed", "4"])
    assert "already picked" in again.output and ws.repeat_selection() == picked

    nothing = runner.invoke(app, ["agreement", *args])
    assert nothing.exit_code == 1 and "nothing to compare" in nothing.output

    first = {m.case_id: m.answer for m in ws.marks("first")}
    for i, case_id in enumerate(picked):
        opposite = "no" if first[case_id] == "yes" else "yes"
        answer = opposite if i == 0 else first[case_id]  # one answer changes
        ws.save_mark(
            Mark.model_validate(
                {
                    "case_id": case_id,
                    "answer": answer,
                    "reason": "r",
                    "marked_at": NOW,
                    "round": "repeat",
                }
            )
        )
    result = runner.invoke(app, ["agreement", *args])
    assert result.exit_code == 0, result.output
    assert "matched for 4 of 5 companies (80%)" in result.output


def test_repeat_marks_waits_until_first_marks_are_old_enough(tmp_path, monkeypatch, make_profile):
    ws, args = setup(tmp_path, monkeypatch, make_profile, days_ago=2)
    result = CliRunner().invoke(app, ["repeat-marks", *args, "--seed", "3"])
    assert result.exit_code == 1
    assert "Only 0 companies" in result.output and "Nothing was picked" in result.output
    assert ws.repeat_selection() is None
