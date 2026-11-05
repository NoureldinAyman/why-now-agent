"""Greenhouse: reads one careers page through its public API."""

from datetime import date
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from why_now.domain import JobAd
from why_now.sources import BoardFailed
from why_now.sources.polite import PoliteClient
from why_now.sources.text import escaped_html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"


class GreenhouseSource:
    name = "greenhouse"

    def __init__(self, client: PoliteClient):
        self.client = client

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        reply = self.client.get_json(API.format(board=quote(board, safe="")))
        jobs = reply.get("jobs") if isinstance(reply, dict) else None
        if not isinstance(jobs, list):
            raise BoardFailed(f"no job list in the reply for {board!r}")
        ads = []
        for job in jobs:
            ad = self._to_ad(job, board, today)
            if ad is not None:
                ads.append(ad)
        return ads

    def _to_ad(self, job: Any, board: str, today: date) -> JobAd | None:
        """One job as a `JobAd`, or None if it lacks what an ad needs (an address and a date)."""
        if not isinstance(job, dict):
            return None
        published = job.get("first_published") or job.get("updated_at")
        location = job.get("location") or {}
        try:
            # model_validate checks the reply's types, and reads the ISO date.
            return JobAd.model_validate(
                {
                    "source": self.name,
                    "board": board,
                    "ad_id": str(job["id"]),
                    "company_name": job.get("company_name") or board,
                    "title": job["title"],
                    "location": location.get("name") or "",
                    "country": None,  # Greenhouse has no country field
                    "language": job.get("language") or None,
                    "text": escaped_html_to_text(job.get("content") or ""),
                    "url": job["absolute_url"],
                    "published_at": published,
                    "first_seen": today,
                }
            )
        except (KeyError, TypeError, AttributeError, ValidationError):
            return None
