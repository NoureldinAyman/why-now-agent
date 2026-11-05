"""Reading a job source politely: GET only, a pause between requests, and backing off when asked."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from why_now.sources import BoardFailed

USER_AGENT = "why-now-agent (+https://github.com/NoureldinAyman/why-now-agent)"
# Replies that mean "slow down" or "busy right now": worth waiting and asking again.
_RETRY_STATUSES = {429, 503}


class PoliteClient:
    """Fetches JSON with GET only, waiting `delay_seconds` between the starts of requests.

    One client serves one job source, so each source is paced on its own. On a
    429 or 503 reply it waits as long as `Retry-After` asks (or `delay_seconds`
    if it doesn't say), up to `attempts` tries in all. If asked to wait longer
    than `max_retry_wait_seconds`, it gives up on that page rather than stall the read.
    """

    def __init__(
        self,
        http: httpx.Client,
        delay_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        *,
        attempts: int,
        max_retry_wait_seconds: float,
    ):
        self.http = http
        self.delay_seconds = delay_seconds
        self.sleep = sleep
        self.clock = clock
        self.attempts = attempts
        self.max_retry_wait_seconds = max_retry_wait_seconds
        self._last_start: float | None = None

    def get_json(self, url: str) -> Any:
        response = self._get(url)
        tries = 1
        while response.status_code in _RETRY_STATUSES:
            if tries >= self.attempts:
                raise BoardFailed(f"still {response.status_code} after {tries} tries: {url}")
            wait = _retry_after(response) or self.delay_seconds
            if wait > self.max_retry_wait_seconds:
                raise BoardFailed(f"asked to wait {wait:g} seconds, which is too long: {url}")
            self.sleep(wait)
            response = self._get(url)
            tries += 1
        if response.status_code != 200:
            raise BoardFailed(f"reply {response.status_code}: {url}")
        try:
            return response.json()
        except ValueError as e:
            raise BoardFailed(f"reply is not JSON: {url}") from e

    def _get(self, url: str) -> httpx.Response:
        if self._last_start is not None:
            wait = self._last_start + self.delay_seconds - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last_start = self.clock()
        try:
            return self.http.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError as e:
            raise BoardFailed(f"{type(e).__name__}: {e}: {url}") from e


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a `Retry-After` header. The date form is rare for APIs and is ignored."""
    try:
        return max(0.0, float(response.headers.get("Retry-After", "")))
    except ValueError:
        return None
