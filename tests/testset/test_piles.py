from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from why_now.domain import CaseRecord, Mark
from why_now.settings import Settings
from why_now.testset.piles import (
    PilesFrozen,
    assign_piles,
    refresh_check_pile,
    split_piles,
    yes_share,
)
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def case(n: int) -> CaseRecord:
    return CaseRecord(
        case_id=f"case-{n:04d}", profile_id="p", company_key=f"company-{n:04d}", seed=1,
        pack_id=f"pack-{n:04d}",
    )  # fmt: skip


def mark(n: int, answer: str) -> Mark:
    return Mark.model_validate(
        {"case_id": f"case-{n:04d}", "answer": answer, "reason": "r", "marked_at": NOW}
    )


type Build = Callable[[int, int, int], tuple[list[CaseRecord], dict[str, Mark]]]


@pytest.fixture
def build() -> Build:
    """Cases 0..n-1 where the first `yes` are yes, the next `cant` can't tell, the rest no."""

    def make(n: int, yes: int, cant: int = 0):
        cases = [case(i) for i in range(n)]
        answers = ["yes"] * yes + ["cant_tell"] * cant
        answers += ["no"] * (n - len(answers))
        # Spread the answers out so the order of the cases says nothing about them.
        marks = {f"case-{i:04d}": mark(i, answers[(i * 37) % n]) for i in range(n)}
        return cases, marks

    return make


def piled(result: list[CaseRecord]) -> dict[str, list[CaseRecord]]:
    out: dict[str, list[CaseRecord]] = {}
    for c in result:
        if c.pile is not None:
            out.setdefault(c.pile, []).append(c)
    return out


def test_no_company_in_two_piles_and_seed_fixes_the_split(build, settings):
    cases, marks = build(300, 100)
    a, _ = assign_piles(cases, marks, 7, settings)
    b, _ = assign_piles(cases, marks, 7, settings)
    c, _ = assign_piles(cases, marks, 8, settings)
    assert a == b
    assert a != c
    assert len({x.company_key for x in a}) == len(a)
    assert all(x.pile is not None for x in a)


def test_the_split_does_not_depend_on_the_order_cases_are_given_in(build, settings):
    cases, marks = build(300, 100)
    a, _ = assign_piles(cases, marks, 7, settings)
    b, _ = assign_piles(list(reversed(cases)), marks, 7, settings)
    assert {x.case_id: x.pile for x in a} == {x.case_id: x.pile for x in b}


def test_sizes_are_150_75_75_and_yes_answers_are_spread_evenly(build, settings):
    cases, marks = build(300, 100)
    _, r = assign_piles(cases, marks, 7, settings)
    assert r.counts == {"practice": 150, "check": 75, "final": 75}
    assert r.yes_counts == {"practice": 50, "check": 25, "final": 25}
    assert r.short_piles == []
    assert r.yes_share == pytest.approx(1 / 3)


def test_yes_counts_of_check_and_final_differ_by_at_most_one(build, settings):
    cases, marks = build(300, 91)  # does not divide evenly
    _, r = assign_piles(cases, marks, 7, settings)
    assert abs(r.yes_counts["check"] - r.yes_counts["final"]) <= 1
    assert sum(r.yes_counts.values()) == 91


def test_cant_tell_and_unmarked_cases_are_left_out_of_every_pile(build, settings):
    cases, marks = build(310, 100, cant=10)
    cases.append(case(999))  # never marked
    result, r = assign_piles(cases, marks, 7, settings)
    left_out = {c.case_id for c in result if c.pile is None}
    cant = {k for k, m in marks.items() if m.answer == "cant_tell"}
    assert cant <= left_out
    assert "case-0999" in left_out
    assert sum(r.counts.values()) == 300
    assert r.yes_share == pytest.approx(100 / 300)


def test_extra_marked_cases_are_dropped_without_changing_the_yes_share(build, settings):
    cases, marks = build(400, 120)  # 100 more than the piles hold, 30 percent yes
    _, r = assign_piles(cases, marks, 7, settings)
    assert sum(r.counts.values()) == 300
    assert sum(r.yes_counts.values()) == 90


def test_fewer_marked_cases_than_the_piles_hold_still_fill_in_proportion(build, settings):
    cases, marks = build(120, 40)
    _, r = assign_piles(cases, marks, 7, settings)
    assert r.counts == {"practice": 60, "check": 30, "final": 30}
    assert sum(r.yes_counts.values()) == 40


def test_short_piles_are_reported(build, settings):
    cases, marks = build(300, 30)  # 30 yes answers cannot give 25 each to check and final
    _, r = assign_piles(cases, marks, 7, settings)
    assert r.short_piles == ["check", "final"]


def test_a_lower_aim_in_the_settings_ends_the_shortfall(build, settings: Settings):
    cases, marks = build(300, 60)  # 15 yes each in check and final
    assert assign_piles(cases, marks, 7, settings)[1].short_piles == ["check", "final"]
    lowered = settings.model_copy(update={"target_yes_per_pile": 15})
    assert assign_piles(cases, marks, 7, lowered)[1].short_piles == []


def test_check_cases_get_version_one_and_others_none(build, settings):
    cases, marks = build(300, 100)
    result, _ = assign_piles(cases, marks, 7, settings)
    for c in result:
        assert c.check_version == (1 if c.pile == "check" else None)


def test_the_input_cases_are_not_changed(build, settings):
    cases, marks = build(300, 100)
    assign_piles(cases, marks, 7, settings)
    assert all(c.pile is None for c in cases)


def test_yes_share_leaves_out_cant_tell():
    marks = [mark(0, "yes"), mark(1, "no"), mark(2, "no"), mark(3, "cant_tell")]
    assert yes_share(marks) == pytest.approx(1 / 3)
    assert yes_share([]) == 0.0
    assert yes_share([mark(0, "cant_tell")]) == 0.0


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store, "p")


def fill(workspace: Workspace, n: int, yes: int) -> None:
    for i in range(n):
        workspace.save_case(case(i))
        workspace.save_mark(mark(i, "yes" if (i * 37) % n < yes else "no"))


@pytest.fixture
def small(settings: Settings) -> Settings:
    """Small piles, because every saved case is flushed to disk and 300 of them are slow."""
    return settings.model_copy(
        update={"practice_size": 12, "check_size": 6, "final_size": 6, "target_yes_per_pile": 2}
    )


def test_split_piles_saves_the_piles_and_reports(workspace, small):
    fill(workspace, 24, 9)
    report = split_piles(workspace, 7, small)
    assert report.counts == {"practice": 12, "check": 6, "final": 6}
    saved = Counter(c.pile for c in workspace.cases())
    assert saved == {"practice": 12, "check": 6, "final": 6}


def test_splitting_again_with_the_same_seed_changes_nothing(workspace, small):
    fill(workspace, 24, 9)
    split_piles(workspace, 7, small)
    before = {c.case_id: c.pile for c in workspace.cases()}
    split_piles(workspace, 7, small)
    assert {c.case_id: c.pile for c in workspace.cases()} == before


def test_splitting_is_refused_once_the_loop_has_started(workspace, small):
    fill(workspace, 24, 9)
    split_piles(workspace, 7, small)
    before = {c.case_id: c.pile for c in workspace.cases()}
    workspace.set_loop_started()
    with pytest.raises(PilesFrozen):
        split_piles(workspace, 8, small)
    assert {c.case_id: c.pile for c in workspace.cases()} == before


def test_the_loop_has_not_started_in_a_new_workspace(workspace):
    assert workspace.loop_started() is False


def test_refresh_moves_old_check_cases_to_practice_and_bumps_the_version(workspace, small):
    fill(workspace, 24, 9)
    split_piles(workspace, 7, small)
    old_check = {c.case_id for c in workspace.cases() if c.pile == "check"}
    old_final = {c.case_id for c in workspace.cases() if c.pile == "final"}
    new_cases = [case(1000 + i) for i in range(6)]

    version = refresh_check_pile(workspace, new_cases)

    assert version == 2
    by_id = {c.case_id: c for c in workspace.cases()}
    assert all(by_id[i].pile == "practice" and by_id[i].check_version is None for i in old_check)
    assert all(by_id[i].pile == "final" for i in old_final)
    fresh = [c for c in by_id.values() if c.pile == "check"]
    assert len(fresh) == 6 and {c.check_version for c in fresh} == {2}
    assert {c.case_id for c in fresh} == {c.case_id for c in new_cases}
    assert refresh_check_pile(workspace, [case(2000 + i) for i in range(2)]) == 3


def test_refresh_refuses_a_company_already_in_a_pile(workspace, small):
    fill(workspace, 24, 9)
    split_piles(workspace, 7, small)
    already = next(c for c in workspace.cases() if c.pile == "final")
    twin = already.model_copy(update={"case_id": "case-twin", "pile": None})
    with pytest.raises(ValueError, match="already in a pile"):
        refresh_check_pile(workspace, [twin])
    assert "case-twin" not in {c.case_id for c in workspace.cases()}
