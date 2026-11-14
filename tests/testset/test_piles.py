from collections import Counter
from datetime import UTC, datetime

import pytest

from why_now.domain import CaseRecord, Mark
from why_now.settings import Settings
from why_now.testset.piles import (
    PileCounts,
    PileReport,
    loop_ready,
    pile_for,
    pile_report,
    pile_sizes,
    yes_share,
)
from why_now.workspace import Workspace

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


def mark(n: int, answer: str) -> Mark:
    return Mark.model_validate(
        {"case_id": f"case-{n:04d}", "answer": answer, "reason": "r", "marked_at": NOW}
    )


def test_the_same_seed_and_sizes_always_give_the_same_pile():
    piles = [pile_for(7, f"company-{i}", (45, 45, 45)) for i in range(200)]
    assert piles == [pile_for(7, f"company-{i}", (45, 45, 45)) for i in range(200)]
    assert piles != [pile_for(8, f"company-{i}", (45, 45, 45)) for i in range(200)]
    assert piles != [pile_for(7, f"company-{i}", (150, 75, 75)) for i in range(200)]


def test_the_sizes_come_from_the_settings(settings: Settings):
    assert pile_sizes(settings) == (45, 45, 45)


def test_over_many_keys_the_shares_match_the_sizes():
    counts = Counter(pile_for(7, f"company-{i}", (150, 75, 75)) for i in range(10_000))
    assert set(counts) == {"practice", "check", "final"}
    assert counts["practice"] / 10_000 == pytest.approx(0.50, abs=0.02)
    assert counts["check"] / 10_000 == pytest.approx(0.25, abs=0.02)
    assert counts["final"] / 10_000 == pytest.approx(0.25, abs=0.02)


def test_the_ratio_follows_the_settings(settings: Settings):
    even = settings.model_copy(update={"practice_size": 1, "check_size": 1, "final_size": 1})
    counts = Counter(pile_for(3, f"company-{i}", pile_sizes(even)) for i in range(10_000))
    assert all(c / 10_000 == pytest.approx(1 / 3, abs=0.02) for c in counts.values())


def test_yes_share_leaves_out_cant_tell():
    marks = [mark(0, "yes"), mark(1, "no"), mark(2, "no"), mark(3, "cant_tell")]
    assert yes_share(marks) == pytest.approx(1 / 3)
    assert yes_share([]) == 0.0
    assert yes_share([mark(0, "cant_tell")]) == 0.0


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store, "p")


def picked(workspace: Workspace, n: int, seed: int, settings: Settings) -> list[CaseRecord]:
    """Pick companies 0..n-1 with `seed`, the way the pick does: the pile is set at once."""
    cases = [
        CaseRecord(
            case_id=f"case-{i:04d}",
            profile_id="p",
            company_key=f"company-{i:04d}",
            seed=seed,
            pile=pile_for(seed, f"company-{i:04d}", pile_sizes(settings)),
        )  # fmt: skip
        for i in range(n)
    ]
    for c in cases:
        workspace.save_case(c)
    return cases


def test_the_report_counts_a_worked_example(workspace):
    for i, pile in enumerate(["check", "check", "check", "final", "practice"]):
        workspace.save_case(
            CaseRecord.model_validate(
                {
                    "case_id": f"case-{i:04d}",
                    "profile_id": "p",
                    "company_key": f"k{i}",
                    "seed": 1,
                    "pile": pile,
                }
            )  # fmt: skip
        )
    workspace.save_case(CaseRecord(case_id="case-0009", profile_id="p", company_key="k9", seed=1))
    for i, answer in enumerate(["yes", "yes", "cant_tell", "no"]):
        workspace.save_mark(mark(i, answer))

    report = pile_report(workspace)

    assert report.piles["check"].model_dump() == {
        "cases": 3, "marked": 3, "yes": 2, "no": 0, "cant_tell": 1
    }  # fmt: skip
    assert report.piles["final"].model_dump() == {
        "cases": 1, "marked": 1, "yes": 0, "no": 1, "cant_tell": 0
    }  # fmt: skip
    assert report.piles["practice"].model_dump() == {
        "cases": 1, "marked": 0, "yes": 0, "no": 0, "cant_tell": 0
    }  # fmt: skip
    assert report.no_pile == 1


def test_repeat_marks_are_not_counted_twice(workspace):
    workspace.save_case(
        CaseRecord(case_id="case-0000", profile_id="p", company_key="k", seed=1, pile="check")
    )
    workspace.save_mark(mark(0, "yes"))
    workspace.save_mark(mark(0, "no").model_copy(update={"round": "repeat"}))
    assert pile_report(workspace).piles["check"].model_dump() == {
        "cases": 1, "marked": 1, "yes": 1, "no": 0, "cant_tell": 0
    }  # fmt: skip


def test_no_mark_marking_order_or_cant_tell_moves_a_company(workspace, settings):
    cases = picked(workspace, 30, 11, settings)
    before = {c.case_id: c.pile for c in workspace.cases()}
    for i in reversed(range(30)):  # marked in reverse, with every kind of answer
        workspace.save_mark(mark(i, ["cant_tell", "yes", "no"][i % 3]))
    after = {c.case_id: c.pile for c in workspace.cases()}
    assert (
        after
        == before
        == {c.case_id: pile_for(11, c.company_key, pile_sizes(settings)) for c in cases}
    )


def test_a_saved_case_cannot_change_pile(workspace, settings):
    case = picked(workspace, 1, 3, settings)[0]
    other = next(p for p in ("practice", "check", "final") if p != case.pile)
    with pytest.raises(ValueError, match="never changes pile"):
        workspace.save_case(case.model_copy(update={"pile": other}))
    workspace.save_case(case.model_copy(update={"pack_id": "pack-1"}))  # other fields may change
    assert workspace.cases()[0].pile == case.pile


def report_with_check_yes(yes: int) -> PileReport:
    empty = PileCounts(cases=0, marked=0, yes=0, no=0, cant_tell=0)
    check = PileCounts(cases=yes, marked=yes, yes=yes, no=0, cant_tell=0)
    return PileReport(piles={"practice": empty, "check": check, "final": empty}, no_pile=0)


def test_the_loop_is_ready_only_once_check_has_enough_yes_answers(settings: Settings):
    assert settings.floor_yes_per_pile == 15
    assert loop_ready(report_with_check_yes(14), settings) is False
    assert loop_ready(report_with_check_yes(15), settings) is True
    lower = settings.model_copy(update={"floor_yes_per_pile": 3})
    assert loop_ready(report_with_check_yes(3), lower) is True
