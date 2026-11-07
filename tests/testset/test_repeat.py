from datetime import UTC, date, datetime, timedelta

import pytest

from why_now.domain import Mark
from why_now.testset.repeat import agreement, agreement_counts, pick_repeats

TODAY = date(2026, 11, 20)


def mark(n: int, answer: str = "yes", days_ago: int = 0, round: str = "first") -> Mark:
    when = datetime(2026, 11, 20, 9, 0, tzinfo=UTC) - timedelta(days=days_ago)
    return Mark.model_validate(
        {
            "case_id": f"case-{n:03d}", "answer": answer, "reason": "r", "marked_at": when,
            "round": round,
        }
    )  # fmt: skip


def test_repeats_wait_a_week():
    marked_today = [mark(i) for i in range(40)]
    assert pick_repeats(marked_today, 30, 1, TODAY, 7) == []
    six_days = [mark(i, days_ago=6) for i in range(40)]
    assert pick_repeats(six_days, 30, 1, TODAY, 7) == []
    seven_days = [mark(i, days_ago=7) for i in range(40)]
    assert len(pick_repeats(seven_days, 30, 1, TODAY, 7)) == 30


def test_only_marks_old_enough_are_picked_from():
    marks = [mark(i, days_ago=10) for i in range(5)] + [mark(i, days_ago=1) for i in range(5, 40)]
    picked = pick_repeats(marks, 30, 1, TODAY, 7)
    assert sorted(picked) == [f"case-{i:03d}" for i in range(5)]


def test_the_seed_fixes_the_pick_and_the_order_of_marks_does_not_matter():
    marks = [mark(i, "yes" if i % 3 == 0 else "no", days_ago=8) for i in range(100)]
    a = pick_repeats(marks, 30, 4, TODAY, 7)
    assert a == pick_repeats(list(reversed(marks)), 30, 4, TODAY, 7)
    assert a != pick_repeats(marks, 30, 5, TODAY, 7)
    assert len(set(a)) == 30


def test_cant_tell_is_never_picked_because_it_cannot_be_compared():
    marks = [mark(i, "cant_tell", days_ago=8) for i in range(20)]
    marks += [mark(i, "no", days_ago=8) for i in range(20, 25)]
    assert sorted(pick_repeats(marks, 30, 1, TODAY, 7)) == [f"case-{i:03d}" for i in range(20, 25)]


def test_repeat_round_marks_are_not_picked_from():
    marks = [mark(i, days_ago=8, round="repeat") for i in range(10)]
    assert pick_repeats(marks, 5, 1, TODAY, 7) == []


def test_agreement_is_the_share_of_matching_answers():
    first = [mark(0, "yes"), mark(1, "no"), mark(2, "yes"), mark(3, "no")]
    again = [mark(0, "yes", round="repeat"), mark(1, "no", round="repeat"),
             mark(2, "no", round="repeat"), mark(3, "no", round="repeat")]  # fmt: skip
    assert agreement(first, again) == pytest.approx(0.75)
    assert agreement_counts(first, again) == (3, 4)


def test_agreement_ignores_cant_tell():
    first = [mark(0, "yes"), mark(1, "cant_tell"), mark(2, "no")]
    again = [mark(0, "yes", round="repeat"), mark(1, "no", round="repeat"),
             mark(2, "cant_tell", round="repeat")]  # fmt: skip
    assert agreement(first, again) == 1.0
    assert agreement_counts(first, again) == (1, 1)


def test_agreement_only_counts_cases_marked_both_times():
    first = [mark(0, "yes"), mark(1, "no")]
    again = [mark(1, "yes", round="repeat")]
    assert agreement(first, again) == 0.0
    assert agreement_counts(first, again) == (0, 1)


def test_agreement_with_nothing_to_compare_is_refused_not_called_zero():
    with pytest.raises(ValueError, match="nothing to compare"):
        agreement([mark(0)], [])
