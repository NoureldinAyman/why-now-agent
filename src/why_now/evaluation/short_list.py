"""Short-list precision: of the companies shown on short lists, how many the reviewer approved.

It comes free from daily decisions. But the agent chose those companies and the reviewer
judged them from briefs, not from a random pick, so this number is always shown apart from
the pile scores and never joined with them. See `design.md`, "Short-list precision".
"""

from pydantic import BaseModel

from why_now.domain import Decision


class ShortListPrecision(BaseModel):
    approved: int
    decided: int

    @property
    def percent(self) -> int | None:
        """The share approved as a whole number, or None while nothing is decided."""
        return round(100 * self.approved / self.decided) if self.decided else None


def short_list_precision(decisions: list[Decision]) -> ShortListPrecision:
    """Count the decisions made on companies from the short list. Decisions made from the more
    list are left out: they were not put forward by the agent, so they say nothing about it."""
    shown = [d for d in decisions if d.from_list == "short"]
    return ShortListPrecision(approved=sum(d.approved for d in shown), decided=len(shown))
