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


def setup(tmp_path, monkeypatch, make_profile, n=24, yes=9, days_ago=8):
    profile = make_profile()
    profile_file = tmp_path / "profile.yaml"
    profile_file.write_text(yaml.safe_dump(profile.model_dump(mode="json")), encoding="utf-8")
    settings = tmp_path / "settings.toml"
    settings.write_text(
        f"workspace_path = {json.dumps(str(tmp_path / 'ws'))}\n"
        "practice_size = 12\ncheck_size = 6\nfinal_size = 6\n"
        "target_yes_per_pile = 2\nremark_size = 5\n"
    )
    ws = Workspace(LocalStore(tmp_path / "ws"), profile.id)
    for i in range(n):
        ws.save_case(
            CaseRecord(
                case_id=f"case-{i:03d}",
                profile_id=profile.id,
                company_key=f"c{i}",
                seed=1,
                pack_id=f"pack-{i}",
            )  # fmt: skip
        )
        ws.save_mark(
            Mark(
                case_id=f"case-{i:03d}",
                answer="yes" if (i * 7) % n < yes else "no",
                reason="r",
                marked_at=NOW - timedelta(days=days_ago),
                round="first",
            )  # fmt: skip
        )
    monkeypatch.setattr(piles_command, "now", lambda: NOW)
    return ws, ["--profile", str(profile_file), "--settings", str(settings)]


def test_yes_share_shows_the_counts_and_what_is_needed(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile)
    result = CliRunner().invoke(app, ["yes-share", *args])
    assert result.exit_code == 0, result.output
    assert "24 marked: 9 yes, 15 no, 0 can't tell." in result.output
    assert "38%" in result.output  # 9 of 24
    assert "33%" in result.output  # 2 of a pile of 6


def test_split_piles_reports_sizes_and_saves_them(tmp_path, monkeypatch, make_profile):
    ws, args = setup(tmp_path, monkeypatch, make_profile)
    result = CliRunner().invoke(app, ["split-piles", *args, "--seed", "7"])
    assert result.exit_code == 0, result.output
    assert "practice: 12 companies" in result.output and "check: 6 companies" in result.output
    assert "Short of" not in result.output
    assert sorted({str(c.pile) for c in ws.cases()}) == ["check", "final", "practice"]


def test_split_piles_says_which_piles_are_short(tmp_path, monkeypatch, make_profile):
    _, args = setup(tmp_path, monkeypatch, make_profile, yes=2)
    result = CliRunner().invoke(app, ["split-piles", *args, "--seed", "7"])
    assert result.exit_code == 0, result.output
    assert "Short of 2 yes answers: check, final" in result.output


def test_split_piles_is_refused_once_the_loop_has_started(tmp_path, monkeypatch, make_profile):
    ws, args = setup(tmp_path, monkeypatch, make_profile)
    ws.set_loop_started()
    result = CliRunner().invoke(app, ["split-piles", *args, "--seed", "7"])
    assert result.exit_code == 1
    assert "frozen" in result.output and "Nothing was changed" in result.output
    assert all(c.pile is None for c in ws.cases())


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
