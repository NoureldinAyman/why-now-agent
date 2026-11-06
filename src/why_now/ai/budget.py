"""The budget meter: every paid call is checked here first and charged here after.

Spending is kept per calendar month (UTC) in the store, one document per month,
so a new month starts at zero. Fixed monthly costs, such as hosting, count
towards the limit from the first day. The improvement loop has its own share,
so reaching it stops the loop but leaves the rest for research.

A call is checked before it is made and charged after, from the cost the model
reports, so the last call of a month can take spending slightly past the limit.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from why_now.settings import ModelPrice, Settings
from why_now.store import Store

COLLECTION = "budget"
LOOP = "loop"  # the category the improvement loop charges to
TEST_CASES = "test_cases"  # the category one-time test case research charges to


class BudgetExceeded(Exception):
    """Raised before a paid call when the money for it has run out."""


class BudgetStatus(BaseModel):
    month: str
    spent_usd: float
    by_category: dict[str, float]
    warning: bool
    stopped: bool
    loop_stopped: bool


def call_cost(price: ModelPrice, input_tokens: int, output_tokens: int, searches: int = 0) -> float:
    """The cost of one call in US dollars, from the token counts the model reported."""
    return (
        input_tokens * price.input_per_million_usd / 1_000_000
        + output_tokens * price.output_per_million_usd / 1_000_000
        + searches * price.per_search_usd
    )


class Meter:
    def __init__(self, store: Store, settings: Settings, clock: Callable[[], datetime]):
        self.store = store
        self.settings = settings
        self.clock = clock

    def ensure(self, category: str) -> None:
        """Raise `BudgetExceeded` if a paid call in `category` may not be made now."""
        status = self.status()
        if status.stopped:
            raise BudgetExceeded(
                f"monthly limit of ${self.settings.budget_limit_usd:g} reached "
                f"(${status.spent_usd:.2f} spent in {status.month})"
            )
        if category == LOOP and status.loop_stopped:
            share = self.settings.loop_budget_usd
            raise BudgetExceeded(f"the loop's share of ${share:g} is spent for {status.month}")

    def charge(self, category: str, usd: float, detail: str) -> None:
        if usd < 0:
            raise ValueError(f"a charge cannot be negative: {usd}")
        month = self._month()
        doc = self.store.get(COLLECTION, month) or {
            "month": month,
            "by_category": {},
            "charges": [],
        }
        doc["by_category"][category] = doc["by_category"].get(category, 0.0) + usd
        doc["charges"].append(
            {"at": self.clock().isoformat(), "category": category, "usd": usd, "detail": detail}
        )
        self.store.put(COLLECTION, month, doc)

    def status(self) -> BudgetStatus:
        month = self._month()
        doc = self.store.get(COLLECTION, month) or {}
        by_category: dict[str, float] = doc.get("by_category", {})
        spent = sum(by_category.values()) + self.settings.fixed_monthly_costs_usd
        stopped = spent >= self.settings.budget_limit_usd
        return BudgetStatus(
            month=month,
            spent_usd=spent,
            by_category=by_category,
            warning=spent >= self.settings.budget_warning_usd,
            stopped=stopped,
            loop_stopped=stopped or by_category.get(LOOP, 0.0) >= self.settings.loop_budget_usd,
        )

    def _month(self) -> str:
        return self.clock().astimezone(UTC).strftime("%Y-%m")
