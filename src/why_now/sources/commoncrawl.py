"""Building a list of careers pages from Common Crawl, a public archive of the web.

Common Crawl keeps an index of the addresses it has seen. Asking it for every address
under a job source's host gives the careers page names the job source's companies use.
"""

import json
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from why_now.sources.polite import USER_AGENT

COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"

# Where each job source keeps its careers pages. The first path segment is the page's name.
HOSTS: dict[str, tuple[str, ...]] = {
    "greenhouse": ("job-boards.greenhouse.io", "boards.greenhouse.io"),
    "lever": ("jobs.lever.co",),
}
# First path segments that are not company pages.
_NOT_NAMES = {"embed"}
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
# Replies that mean "busy" or "too slow": worth waiting and asking again.
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class ListBuildFailed(Exception):
    """The list could not be built. The message says what went wrong, in plain words."""


def board_from_url(url: str, source: str) -> str | None:
    """The careers page name in an address, or None if the address has no name for `source`."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if (parts.hostname or "") not in HOSTS.get(source, ()):
        return None
    name = unquote(parts.path.lstrip("/").split("/", 1)[0])
    if name.lower() in _NOT_NAMES or not _NAME.fullmatch(name):
        return None
    return name


def build_board_list(
    source: str,
    http: httpx.Client,
    existing: list[str],
    *,
    delay_seconds: float,
    attempts: int,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """`existing` followed by the new careers page names found, with no duplicates.

    Names match without regard to case, and the first spelling is kept. Requests are
    spaced `delay_seconds` apart. A request that times out or is told "busy" is tried
    up to `attempts` times, then `ListBuildFailed` is raised.
    """
    if source not in HOSTS:
        raise ValueError(f"unknown job source {source!r}. Known: {', '.join(HOSTS)}")
    fetch = _Fetcher(http, delay_seconds, attempts, sleep)
    index_url = _latest_index(fetch)
    merged = list(existing)
    seen = {name.lower() for name in merged}
    for host in HOSTS[source]:
        query = f"{index_url}?url={host}/*&output=json&fl=url"
        pages = int(json.loads(fetch(f"{query}&showNumPages=true"))["pages"])
        for page in range(pages):
            for url in fetch(f"{query}&page={page}", _urls):
                name = board_from_url(url, source)
                if name and name.lower() not in seen:
                    seen.add(name.lower())
                    merged.append(name)
    return merged


def _urls(text: str) -> list[str]:
    """The addresses in one reply: a JSON object per line. A cut-short reply raises ValueError."""
    return [json.loads(line)["url"] for line in text.splitlines() if line.strip()]


def _latest_index(fetch: "_Fetcher") -> str:
    try:
        return json.loads(fetch(COLLINFO_URL))[0]["cdx-api"]
    except (ValueError, LookupError, TypeError) as e:
        raise ListBuildFailed("Common Crawl's list of indexes was not in the expected form") from e


class _Fetcher:
    """GET with a pause between requests and a few tries when the archive is slow."""

    def __init__(self, http, delay_seconds, attempts, sleep):
        self.http, self.delay_seconds, self.attempts, self.sleep = (
            http,
            delay_seconds,
            attempts,
            sleep,
        )
        self._started = False

    def __call__(self, url: str, parse: Callable[[str], Any] = str) -> Any:
        """The reply to `url` run through `parse`. A reply `parse` refuses is a failed try."""
        problem = ""
        for _ in range(self.attempts):
            if self._started:
                self.sleep(self.delay_seconds)
            self._started = True
            try:
                response = self.http.get(url, headers={"User-Agent": USER_AGENT})
            except httpx.TimeoutException as e:
                problem = f"{type(e).__name__}"
                continue
            except httpx.HTTPError as e:
                raise ListBuildFailed(f"{type(e).__name__}: {e}") from e
            if response.status_code in _RETRY_STATUSES:
                problem = f"reply {response.status_code}"
                continue
            if response.status_code != 200:
                raise ListBuildFailed(f"reply {response.status_code}: {url}")
            try:
                return parse(response.text)
            except (ValueError, LookupError, TypeError):
                problem = "reply was cut short or not in the expected form"
        raise ListBuildFailed(
            f"Common Crawl did not answer ({problem}) after {self.attempts} tries: {url}"
        )
