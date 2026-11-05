from datetime import date, timedelta

import pytest

from why_now.sources.boards import BoardList
from why_now.workspace import Workspace

TODAY = date(2026, 11, 5)


@pytest.fixture
def workspace(store) -> Workspace:
    return Workspace(store)


def boards(workspace, names=("a", "b"), settings=None) -> BoardList:
    return BoardList(workspace, "s", list(names), settings=settings)


def fail_b_for(b: BoardList, days: int, start: date = TODAY) -> None:
    for i in range(days):
        b.record_results(start + timedelta(days=i), ok=["a"], failed=["b"])


def test_every_board_is_read_at_first(workspace):
    assert boards(workspace).to_read(TODAY) == ["a", "b"]


def test_board_is_set_aside_after_seven_failing_days_and_retried_monthly(workspace):
    b = boards(workspace)
    fail_b_for(b, 7)
    assert b.health("b").set_aside_on == TODAY + timedelta(days=6)
    assert b.to_read(TODAY + timedelta(days=8)) == ["a"]
    assert b.to_read(TODAY + timedelta(days=35)) == ["a"]
    assert "b" in b.to_read(TODAY + timedelta(days=36))


def test_six_failing_days_do_not_set_a_board_aside(workspace):
    b = boards(workspace)
    fail_b_for(b, 6)
    assert b.health("b").failing_days == 6
    assert "b" in b.to_read(TODAY + timedelta(days=6))


def test_a_good_day_resets_the_count(workspace):
    b = boards(workspace)
    fail_b_for(b, 6)
    b.record_results(TODAY + timedelta(days=6), ok=["a", "b"], failed=[])
    fail_b_for(b, 6, start=TODAY + timedelta(days=7))
    assert b.health("b").set_aside_on is None


def test_two_reads_on_one_day_count_as_one_failing_day(workspace):
    b = boards(workspace)
    for _ in range(3):
        b.record_results(TODAY, ok=[], failed=["b"])
    assert b.health("b").failing_days == 1


def test_a_failed_retry_waits_another_month(workspace):
    b = boards(workspace)
    fail_b_for(b, 7)
    retry_day = TODAY + timedelta(days=36)
    b.record_results(retry_day, ok=[], failed=["b"])
    assert "b" not in b.to_read(retry_day + timedelta(days=29))
    assert "b" in b.to_read(retry_day + timedelta(days=30))


def test_a_board_that_comes_back_is_read_daily_again(workspace):
    b = boards(workspace)
    fail_b_for(b, 7)
    b.record_results(TODAY + timedelta(days=36), ok=["b"], failed=[])
    assert b.health("b").set_aside_on is None
    assert "b" in b.to_read(TODAY + timedelta(days=37))


def test_health_is_kept_in_the_workspace_and_shared_by_lists(workspace):
    fail_b_for(boards(workspace, names=["b"]), 7)
    assert boards(workspace, names=["a", "b"]).to_read(TODAY + timedelta(days=8)) == ["a"]


def test_limits_come_from_settings(workspace, settings):
    b = boards(workspace, settings=settings.model_copy(update={"dead_after_days": 2}))
    fail_b_for(b, 2)
    assert b.to_read(TODAY + timedelta(days=3)) == ["a"]
