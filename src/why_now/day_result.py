"""What a daily run produces: the two lists and what went wrong or was skipped.

Kept apart from the run itself so the workspace can save and load these shapes
without importing the pipeline.
"""

from datetime import date

from pydantic import BaseModel

from why_now.ai.budget import BudgetStatus
from why_now.domain import Brief, JobAd


class ListEntry(BaseModel):
    """One company on the short list, the more list or the judged-no list.

    A short list entry has a brief, a pack and the judge's strength. A judged-no entry has a
    pack and the judge's strength, and no brief. A more list entry has no brief and no pack.
    Its strength is the quick look's, or None when the quick look could not run, for example
    because the budget was spent.
    """

    company_key: str
    company_name: str
    strength: float | None
    brief: Brief | None
    ads: list[JobAd]
    pack_id: str | None
    first_listed: date


class DayResult(BaseModel):
    day: date
    short_list: list[ListEntry]
    more_list: list[ListEntry]
    # A few researched companies the judge said no to, closest to a yes first, so the reviewer
    # can catch good companies the agent wrongly turned down. Empty for days saved before it.
    judged_no: list[ListEntry] = []
    failed: list[str]  # one plain sentence for each company or careers page that failed
    skipped: list[str]  # one plain sentence for each part of the run that was not done
    costs: BudgetStatus
