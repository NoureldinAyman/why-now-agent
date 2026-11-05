from datetime import UTC, datetime

import pytest

from why_now.ai.budget import BudgetExceeded, Meter, call_cost
from why_now.settings import ModelPrice


def test_paid_calls_stop_at_the_limit(store, settings, clock):
    m = Meter(store, settings, clock)
    m.charge("research", 70.0, "x")
    with pytest.raises(BudgetExceeded):
        m.ensure("research")


def test_paid_calls_are_allowed_below_the_limit(store, settings, clock):
    m = Meter(store, settings, clock)
    m.charge("research", 69.0, "x")
    m.ensure("research")
    assert not m.status().stopped


def test_warning_at_fifty(store, settings, clock):
    m = Meter(store, settings, clock)
    m.charge("research", 49.0, "x")
    assert not m.status().warning
    m.charge("judge", 1.0, "x")
    assert m.status().warning and not m.status().stopped


def test_fixed_costs_count_towards_the_limit(store, settings, clock):
    m = Meter(store, settings.model_copy(update={"fixed_monthly_costs_usd": 69.5}), clock)
    m.charge("research", 1.0, "x")
    assert m.status().stopped
    assert m.status().spent_usd == pytest.approx(70.5)


def test_loop_has_its_own_share(store, settings, clock):
    m = Meter(store, settings, clock)
    m.charge("loop", 25.0, "x")
    assert m.status().loop_stopped
    with pytest.raises(BudgetExceeded):
        m.ensure("loop")
    m.ensure("research")  # research money is still available


def test_spending_is_kept_by_category_and_survives_a_restart(store, settings, clock):
    Meter(store, settings, clock).charge("research", 1.5, "a")
    Meter(store, settings, clock).charge("judge", 0.25, "b")
    status = Meter(store, settings, clock).status()
    assert status.by_category == {"research": 1.5, "judge": 0.25}
    assert status.month == "2026-11"


def test_a_new_month_starts_at_zero(store, settings, clock):
    m = Meter(store, settings, clock)
    m.charge("research", 70.0, "x")
    clock.now = datetime(2026, 12, 1, 0, 5, tzinfo=UTC)
    m.ensure("research")
    assert m.status().spent_usd == 0 and m.status().month == "2026-12"


def test_a_negative_charge_is_refused(store, settings, clock):
    with pytest.raises(ValueError):
        Meter(store, settings, clock).charge("research", -1.0, "x")


def test_call_cost_comes_from_tokens_and_searches():
    price = ModelPrice(input_per_million_usd=2, output_per_million_usd=10, per_search_usd=0.01)
    # 1,000,000 input tokens cost $2, 100,000 output tokens cost $1, 3 searches cost $0.03.
    assert call_cost(price, 1_000_000, 100_000, searches=3) == pytest.approx(3.03)
