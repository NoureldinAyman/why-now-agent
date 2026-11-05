"""Job sources: hiring services that host careers pages for many companies.

Each job source sits behind one small adapter that turns its data into `JobAd`s.
"""

from datetime import date
from typing import Protocol

from why_now.domain import JobAd


class BoardFailed(Exception):
    """One careers page could not be read. The read carries on with the others."""


class JobSource(Protocol):
    name: str

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        """All open job ads on one careers page, with `first_seen` set to `today`.

        Raises `BoardFailed` if the page cannot be read.
        """
        ...
