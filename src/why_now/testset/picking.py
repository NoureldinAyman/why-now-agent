"""Picking test cases: companies chosen at random, never by anything the agent said.

A company can be picked if it has a relevant job ad published in the last
`new_ad_days`, the same window the daily list uses, so the test matches the real
job. The pick takes only the companies, a count, a seed and the keys already
picked. No answer from any model can reach it.
"""

import random
from datetime import date, timedelta

from why_now.domain import Company
from why_now.settings import Settings


def eligible_companies(companies: list[Company], settings: Settings, today: date) -> list[Company]:
    """Companies with at least one relevant ad published within `new_ad_days` of `today`.

    `companies` come from the search step, so every ad in them is already relevant.
    The publish date is the job source's own, in UTC.
    """
    oldest = today - timedelta(days=settings.new_ad_days)
    return [c for c in companies if any(a.published_at.date() >= oldest for a in c.ads)]


def pick_cases(
    eligible: list[Company], n: int, seed: int, already_picked: set[str]
) -> list[Company]:
    """Up to `n` companies at random, the same ones for the same seed, none picked before."""
    # Sorted first, so the pick does not depend on the order the ads were read in.
    pool = sorted((c for c in eligible if c.key not in already_picked), key=lambda c: c.key)
    return random.Random(seed).sample(pool, min(n, len(pool)))
