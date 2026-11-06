"""Find what's new: companies with a relevant ad we have not seen, published recently.

A company is new when it has at least one relevant ad that

- was published in the last `new_ad_days` days, counting today (the same window the
  test case pick uses, so the test matches the real job), and
- the daily run has not finished with before.

A company with a decision in the last `hide_days` days is skipped. Only decisions
count. A mark on a test case never hides a company.
"""

from datetime import date, timedelta

from why_now.domain import Company
from why_now.settings import Settings
from why_now.workspace import Workspace
from why_now.workspace.daily import ad_ref


def find_new(
    companies: list[Company], workspace: Workspace, settings: Settings, today: date
) -> list[Company]:
    oldest = today - timedelta(days=settings.new_ad_days - 1)
    seen = workspace.seen_ads()
    found = []
    for company in companies:
        back = workspace.hidden_until(company.key, settings.hide_days)
        if back is not None and today < back:
            continue
        if any(a.published_at.date() >= oldest and ad_ref(a) not in seen for a in company.ads):
            found.append(company)
    return found
