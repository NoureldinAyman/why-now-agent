"""Lever: reads one careers page through its public postings API."""

from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote

from pydantic import ValidationError

from why_now.domain import JobAd
from why_now.sources import BoardFailed
from why_now.sources.polite import PoliteClient
from why_now.sources.text import html_to_text

API = "https://api.lever.co/v0/postings/{board}?mode=json"


def display_name(board: str) -> str:
    """Lever gives no company name, so tidy the page name: `big_corp-two` becomes `Big Corp Two`."""
    return " ".join(board.replace("-", " ").replace("_", " ").split()).title()


class LeverSource:
    name = "lever"

    def __init__(self, client: PoliteClient):
        self.client = client

    def fetch_ads(self, board: str, today: date) -> list[JobAd]:
        reply = self.client.get_json(API.format(board=quote(board, safe="")))
        if not isinstance(reply, list):
            raise BoardFailed(f"no job list in the reply for {board!r}")
        ads = []
        for job in reply:
            ad = self._to_ad(job, board, today)
            if ad is not None:
                ads.append(ad)
        return ads

    def _to_ad(self, job: Any, board: str, today: date) -> JobAd | None:
        """One posting as a `JobAd`, or None if it lacks what an ad needs (an address, a date)."""
        if not isinstance(job, dict):
            return None
        try:
            # createdAt is in milliseconds.
            published = datetime.fromtimestamp(job["createdAt"] / 1000, tz=UTC)
            categories = job.get("categories") or {}
            # model_validate checks the reply's types.
            return JobAd.model_validate(
                {
                    "source": self.name,
                    "board": board,
                    "ad_id": str(job["id"]),
                    "company_name": display_name(board),
                    "title": job["text"],
                    "location": categories.get("location") or "",
                    "country": job.get("country") or None,
                    "language": None,  # Lever has no language field
                    "text": _ad_text(job),
                    "url": job["hostedUrl"],
                    "published_at": published,
                    "first_seen": today,
                }
            )
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError, ValidationError):
            return None


def _ad_text(job: dict[str, Any]) -> str:
    """The description, each titled list and the closing note, joined into plain text."""
    parts = [job.get("descriptionPlain") or ""]
    for section in job.get("lists") or []:
        parts.append(section.get("text") or "")
        parts.append(section.get("content") or "")
    parts.append(job.get("additionalPlain") or "")
    # Every part goes through the tag stripper, so no tag or script from an ad is kept.
    return "\n".join(t for t in (html_to_text(p) for p in parts) if t)
