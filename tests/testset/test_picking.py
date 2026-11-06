import inspect
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from why_now.domain import Company, JobAd
from why_now.testset.picking import eligible_companies, pick_cases

TODAY = date(2026, 11, 6)


def ad(key: str, days_ago: int) -> JobAd:
    return JobAd(
        source="greenhouse",
        board=key,
        ad_id=f"{key}-{days_ago}",
        company_name=key.title(),
        title="Sales Rep",
        location="Cairo",
        country="EG",
        language="en",
        text="Sell things.",
        url=f"https://jobs.test/{key}",
        published_at=datetime(2026, 11, 6, 9, tzinfo=UTC) - timedelta(days=days_ago),
        first_seen=date(2026, 11, 1),
    )


def company(key: str, *days_ago: int) -> Company:
    return Company(key=key, name=key.title(), ads=[ad(key, d) for d in days_ago], total_open_jobs=3)


def many(n: int) -> list[Company]:
    return [company(f"c{i:03}", 1) for i in range(n)]


def test_same_seed_gives_same_companies():
    companies = many(50)
    first = pick_cases(companies, 10, 42, set())
    assert len(first) == 10
    assert first == pick_cases(companies, 10, 42, set())
    assert first != pick_cases(companies, 10, 43, set())


def test_read_order_does_not_change_the_pick():
    companies = many(50)
    assert pick_cases(companies, 10, 42, set()) == pick_cases(companies[::-1], 10, 42, set())


def test_only_companies_with_a_recent_relevant_ad_are_eligible(settings):
    # 14 days counting today: today and the 13 days before it.
    companies = [
        company("fresh", 0),
        company("edge", 13),
        company("stale", 14),
        company("mixed", 40, 3),
    ]
    keys = [c.key for c in eligible_companies(companies, settings, TODAY)]
    assert keys == ["fresh", "edge", "mixed"]


def test_the_window_is_the_setting(settings):
    narrow = settings.model_copy(update={"new_ad_days": 2})
    assert [c.key for c in eligible_companies([company("a", 2)], narrow, TODAY)] == []


def test_already_picked_companies_are_not_picked_again():
    companies = many(20)
    first = pick_cases(companies, 15, 1, set())
    second = pick_cases(companies, 15, 2, {c.key for c in first})
    assert len(second) == 5
    assert not {c.key for c in first} & {c.key for c in second}


def test_asking_for_more_than_there_are_picks_them_all_once():
    picked = pick_cases(many(3), 10, 7, set())
    assert sorted(c.key for c in picked) == ["c000", "c001", "c002"]


def test_picking_ignores_any_agent_answer():
    # Nothing the agent says can reach the pick: it takes only companies, a count,
    # a seed and the keys already picked.
    assert list(inspect.signature(pick_cases).parameters) == [
        "eligible",
        "n",
        "seed",
        "already_picked",
    ]
    # And every company is equally likely: 4,000 picks of 1 from 4.
    counts = Counter(pick_cases(many(4), 1, seed, set())[0].key for seed in range(4000))
    assert all(850 < counts[k] < 1150 for k in ["c000", "c001", "c002", "c003"])
