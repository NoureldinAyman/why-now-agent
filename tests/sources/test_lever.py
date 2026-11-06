import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from why_now.sources import BoardFailed
from why_now.sources.lever import LeverSource
from why_now.sources.polite import PoliteClient

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "lever_postings.json").read_text())
TODAY = date(2026, 11, 5)


class RecordingHttp:
    """A fake job source that answers with the fixture and remembers every request."""

    def __init__(self, status: int = 200, body: object = FIXTURE):
        self.requests: list[httpx.Request] = []
        self.status, self.body = status, body
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)


def source(http: RecordingHttp) -> LeverSource:
    client = PoliteClient(
        http.client, 0, sleep=lambda s: None, attempts=1, max_retry_wait_seconds=0
    )
    return LeverSource(client)


def test_lever_maps_a_job():
    ad = source(RecordingHttp()).fetch_ads("acme-inc", TODAY)[0]
    assert (ad.source, ad.board, ad.ad_id) == (
        "lever",
        "acme-inc",
        "7a1b2c3d-0000-4000-8000-000000000001",
    )
    assert ad.title == "Sales Development Representative"
    assert ad.company_name == "Acme Inc"
    assert ad.country == "SG"
    assert ad.language is None
    assert ad.location == "Singapore"
    assert ad.published_at == datetime.fromtimestamp(1793354400, tz=UTC)
    assert ad.first_seen == TODAY
    assert ad.url == "https://jobs.lever.co/acme-inc/7a1b2c3d-0000-4000-8000-000000000001"


def test_sections_are_joined_into_plain_text():
    text = source(RecordingHttp()).fetch_ads("acme-inc", TODAY)[0].text
    assert "<" not in text and "&nbsp;" not in text and "alert" not in text
    assert text == (
        "We're growing our sales team.\n"
        "Pay & benefits are fair.\n"
        "What We Require\n"
        "Two years selling software\n"
        "Clear writing\n"
        "and calls\n"
        "What You'll Do\n"
        "Book meetings\n"
        "Research accounts and teams\n"
        "Remote friendly."
    )


def test_a_job_with_no_country_or_places_is_kept():
    ad = source(RecordingHttp()).fetch_ads("acme-inc", TODAY)[1]
    assert ad.country is None and ad.location == ""
    assert ad.text == "Close deals."


def test_board_names_become_display_names():
    ads = source(RecordingHttp()).fetch_ads("big_corp-two", TODAY)
    assert ads[0].company_name == "Big Corp Two"


def test_asks_for_the_board_using_get_only():
    http = RecordingHttp()
    source(http).fetch_ads("acme-inc", TODAY)
    assert {r.method for r in http.requests} == {"GET"}
    assert str(http.requests[0].url) == "https://api.lever.co/v0/postings/acme-inc?mode=json"


def test_board_names_cannot_change_the_address():
    http = RecordingHttp()
    source(http).fetch_ads("../x?y", TODAY)
    assert http.requests[0].url.raw_path == b"/v0/postings/..%2Fx%3Fy?mode=json"


def test_missing_board_raises_board_failed():
    body = {"ok": False, "error": "Document not found"}
    with pytest.raises(BoardFailed):
        source(RecordingHttp(status=404, body=body)).fetch_ads("gone", TODAY)


def test_unexpected_reply_raises_board_failed():
    with pytest.raises(BoardFailed):
        source(RecordingHttp(body={"no": "postings"})).fetch_ads("acme-inc", TODAY)


def test_a_job_that_cannot_be_read_is_skipped_not_fatal():
    body = [{"id": "x", "text": "No address or date"}, FIXTURE[0]]
    ads = source(RecordingHttp(body=body)).fetch_ads("acme-inc", TODAY)
    assert [a.ad_id for a in ads] == ["7a1b2c3d-0000-4000-8000-000000000001"]


def test_a_less_than_sign_in_prose_is_kept():
    job = FIXTURE[1] | {"descriptionPlain": "Teams of < 10 people"}
    ad = source(RecordingHttp(body=[job])).fetch_ads("acme-inc", TODAY)[0]
    assert ad.text == "Teams of < 10 people"
