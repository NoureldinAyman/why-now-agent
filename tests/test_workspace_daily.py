from datetime import UTC, date, datetime, time, timedelta

import pytest

from why_now.ai.budget import BudgetStatus
from why_now.day_result import DayResult, ListEntry
from why_now.domain import Decision, JobAd
from why_now.workspace import Workspace

TODAY = date(2026, 11, 6)


def entry(key: str, listed: date = TODAY, strength: float | None = 0.8) -> ListEntry:
    return ListEntry(
        company_key=key,
        company_name=key.title(),
        strength=strength,
        brief=None,
        ads=[],
        pack_id=None,
        first_listed=listed,
    )


def decision(key: str, day: date, profile_id: str = "p1", hour: int = 10) -> Decision:
    return Decision(
        profile_id=profile_id,
        company_key=key,
        approved=True,
        reason="good fit",
        decided_at=datetime.combine(day, time(hour), UTC),
        from_list="short",
    )


def result(short: list[ListEntry], more: list[ListEntry], day: date = TODAY) -> DayResult:
    costs = BudgetStatus(
        month="2026-11",
        spent_usd=0,
        by_category={},
        warning=False,
        stopped=False,
        loop_stopped=False,
    )
    return DayResult(day=day, short_list=short, more_list=more, failed=[], skipped=[], costs=costs)


@pytest.fixture
def ws(store) -> Workspace:
    return Workspace(store, "p1")


def test_a_decision_is_saved_once(ws):
    assert ws.save_decision(decision("acme", TODAY)) is True
    assert ws.save_decision(decision("acme", TODAY)) is False
    assert len(ws.decisions()) == 1


def test_a_decision_for_another_profile_is_refused(ws):
    with pytest.raises(ValueError):
        ws.save_decision(decision("acme", TODAY, profile_id="other"))


def test_hidden_until_is_the_latest_decision_plus_the_hide_days(ws):
    assert ws.hidden_until("acme", 90) is None
    ws.save_decision(decision("acme", TODAY))
    ws.save_decision(decision("acme", TODAY + timedelta(days=10)))
    assert ws.hidden_until("acme", 90) == TODAY + timedelta(days=100)
    assert ws.hidden_until("other", 90) is None


def test_decisions_are_kept_per_profile(store):
    Workspace(store, "p1").save_decision(decision("acme", TODAY))
    assert Workspace(store, "p2").decisions() == []
    assert Workspace(store, "p2").hidden_until("acme", 90) is None


def test_the_lists_start_empty_and_follow_the_last_saved_day(ws):
    assert ws.short_list() == [] and ws.more_list() == []
    ws.save_day(result([entry("a"), entry("b")], [entry("c", strength=None)]))
    assert [e.company_key for e in ws.short_list()] == ["a", "b"]
    assert [e.company_key for e in ws.more_list()] == ["c"]
    ws.save_day(result([entry("a")], [], day=TODAY + timedelta(days=1)))
    assert [e.company_key for e in ws.short_list()] == ["a"]
    assert ws.more_list() == []


def test_each_day_is_kept(ws):
    ws.save_day(result([entry("a")], []))
    assert ws.day_result(TODAY) is not None
    assert ws.day_result(TODAY + timedelta(days=1)) is None


def test_a_decided_company_leaves_both_lists(ws):
    ws.save_day(result([entry("a"), entry("b")], [entry("c")]))
    ws.save_decision(decision("a", TODAY))
    ws.save_decision(decision("c", TODAY))
    assert [e.company_key for e in ws.short_list()] == ["b"]
    assert ws.more_list() == []


def test_an_old_decision_does_not_hide_a_company_listed_again_later(ws):
    ws.save_decision(decision("a", TODAY))
    ws.save_day(result([entry("a", listed=TODAY + timedelta(days=100))], [], TODAY))
    assert [e.company_key for e in ws.short_list()] == ["a"]


def ad(board: str, ad_id: str, source: str = "greenhouse") -> JobAd:
    return JobAd(
        source=source,
        board=board,
        ad_id=ad_id,
        company_name=board,
        title="t",
        location="l",
        country=None,
        language=None,
        text="x",
        url="https://jobs.test/x",
        published_at=datetime(2026, 11, 5, tzinfo=UTC),
        first_seen=TODAY,
    )


def test_seen_ads_are_remembered_per_profile(store, ws):
    assert ws.seen_ads() == set()
    ws.mark_ads_seen([ad("Acme", "1"), ad("Acme", "2"), ad("other", "9", source="lever")])
    ws.mark_ads_seen([ad("acme", "3")])  # board names are not case sensitive
    assert ws.seen_ads() == {
        ("greenhouse", "acme", "1"),
        ("greenhouse", "acme", "2"),
        ("greenhouse", "acme", "3"),
        ("lever", "other", "9"),
    }
    assert Workspace(store, "p2").seen_ads() == set()


def test_marking_seen_twice_changes_nothing(ws):
    ws.mark_ads_seen([ad("acme", "1")])
    ws.mark_ads_seen([ad("acme", "1")])
    assert ws.seen_ads() == {("greenhouse", "acme", "1")}


def test_step_results_are_kept_per_run_step_and_key(ws):
    assert ws.step_result("2026-11-06", "research", "acme") is None
    ws.save_step_result("2026-11-06", "research", "acme", {"pack_id": "pack-1"})
    assert ws.step_result("2026-11-06", "research", "acme") == {"pack_id": "pack-1"}
    assert ws.step_result("2026-11-07", "research", "acme") is None
    assert ws.step_result("2026-11-06", "brief", "acme") is None
