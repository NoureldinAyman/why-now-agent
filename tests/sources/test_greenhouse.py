import json
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

from why_now.sources import BoardFailed
from why_now.sources.greenhouse import GreenhouseSource
from why_now.sources.polite import PoliteClient

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "greenhouse_jobs.json").read_text())
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


def source(http: RecordingHttp) -> GreenhouseSource:
    client = PoliteClient(
        http.client, 0, sleep=lambda s: None, attempts=1, max_retry_wait_seconds=0
    )
    return GreenhouseSource(client)


def test_greenhouse_maps_a_job():
    ad = source(RecordingHttp()).fetch_ads("acme", TODAY)[0]
    assert (ad.source, ad.board, ad.ad_id) == ("greenhouse", "acme", "1001")
    assert ad.title == "Sales Development Representative"
    assert ad.company_name == "Acme"
    assert ad.language == "en"
    assert ad.country is None
    assert ad.location == "Berlin, Germany"
    assert ad.published_at == datetime.fromisoformat("2026-10-30T10:00:00-04:00")
    assert ad.first_seen == TODAY
    assert ad.url == "https://job-boards.greenhouse.io/acme/jobs/1001?gh_jid=1001"


def test_ad_text_is_plain_with_line_breaks_kept():
    text = source(RecordingHttp()).fetch_ads("acme", TODAY)[0].text
    assert "<" not in text and "&lt;" not in text and "&amp;" not in text
    assert "alert" not in text
    assert text == (
        "We're growing our sales team.\n"
        "What you'll do\n"
        "Book meetings\n"
        "Research accounts and teams\n"
        "Pay & benefits\n"
        "Remote friendly"
    )


def test_missing_first_published_falls_back_to_updated_at():
    # 12 of 2,873 sampled jobs had no first_published.
    ad = source(RecordingHttp()).fetch_ads("acme", TODAY)[1]
    assert ad.published_at == datetime.fromisoformat("2026-11-02T12:30:00+00:00")
    assert ad.language is None


def test_asks_for_the_board_with_content_using_get_only():
    http = RecordingHttp()
    source(http).fetch_ads("acme", TODAY)
    assert {r.method for r in http.requests} == {"GET"}
    assert str(http.requests[0].url) == (
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    )


def test_board_names_cannot_change_the_address():
    http = RecordingHttp()
    source(http).fetch_ads("../x?y", TODAY)
    assert http.requests[0].url.raw_path == b"/v1/boards/..%2Fx%3Fy/jobs?content=true"


def test_missing_board_raises_board_failed():
    with pytest.raises(BoardFailed):
        source(RecordingHttp(status=404, body={"status": 404})).fetch_ads("gone", TODAY)


def test_unexpected_reply_raises_board_failed():
    with pytest.raises(BoardFailed):
        source(RecordingHttp(body={"no": "jobs"})).fetch_ads("acme", TODAY)


def test_a_job_that_cannot_be_read_is_skipped_not_fatal():
    body = {"jobs": [{"id": 5, "title": "No address or dates"}, FIXTURE["jobs"][0]]}
    ads = source(RecordingHttp(body=body)).fetch_ads("acme", TODAY)
    assert [a.ad_id for a in ads] == ["1001"]


def test_tags_escaped_twice_are_removed_too():
    twice = "&amp;lt;p&amp;gt;Close &amp;lt;b&amp;gt;deals&amp;lt;/b&amp;gt;.&amp;lt;/p&amp;gt;"
    job = FIXTURE["jobs"][1] | {"content": twice}
    ad = source(RecordingHttp(body={"jobs": [job]})).fetch_ads("acme", TODAY)[0]
    assert ad.text == "Close deals."


def test_a_less_than_sign_in_prose_is_kept():
    job = FIXTURE["jobs"][1] | {"content": "&lt;p&gt;Teams of &amp;lt; 10 people&lt;/p&gt;"}
    ad = source(RecordingHttp(body={"jobs": [job]})).fetch_ads("acme", TODAY)[0]
    assert ad.text == "Teams of < 10 people"
