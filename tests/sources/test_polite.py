import httpx
import pytest

from why_now.sources import BoardFailed
from why_now.sources.polite import PoliteClient


def http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_http() -> httpx.Client:
    return http(lambda request: httpx.Response(200, json={"ok": True}))


def fixed_clock() -> float:
    return 100.0


def polite(client: httpx.Client, sleeps: list[float], **overrides) -> PoliteClient:
    options = {"attempts": 3, "max_retry_wait_seconds": 60} | overrides
    return PoliteClient(client, 1.0, sleep=sleeps.append, clock=fixed_clock, **options)


def test_polite_client_waits_between_requests():
    sleeps: list[float] = []
    c = polite(ok_http(), sleeps)
    assert c.get_json("https://example.test/u1") == {"ok": True}
    c.get_json("https://example.test/u2")
    assert sleeps == [1.0]


def test_polite_client_does_not_wait_when_enough_time_has_passed():
    sleeps: list[float] = []
    now = iter([100.0, 105.0, 105.0])
    c = PoliteClient(
        ok_http(),
        1.0,
        sleep=sleeps.append,
        clock=lambda: next(now),
        attempts=3,
        max_retry_wait_seconds=60,
    )
    c.get_json("https://example.test/u1")
    c.get_json("https://example.test/u2")
    assert sleeps == []


def test_polite_client_obeys_retry_after_then_gives_up():
    sleeps: list[float] = []
    always_429 = http(lambda request: httpx.Response(429, headers={"Retry-After": "7"}))
    with pytest.raises(BoardFailed):
        polite(always_429, sleeps).get_json("https://example.test/u")
    assert 7 in sleeps


def test_polite_client_retries_a_busy_service_and_succeeds():
    replies = iter([httpx.Response(503), httpx.Response(200, json=[1])])
    assert polite(http(lambda request: next(replies)), []).get_json("https://example.test/u") == [1]


def test_polite_client_gives_up_when_told_to_wait_too_long():
    sleeps: list[float] = []
    slow = http(lambda request: httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(BoardFailed, match="3600"):
        polite(slow, sleeps).get_json("https://example.test/u")
    assert 3600 not in sleeps


@pytest.mark.parametrize(
    "reply",
    [httpx.Response(404), httpx.Response(500), httpx.Response(200, text="not json")],
)
def test_bad_replies_raise_board_failed(reply):
    with pytest.raises(BoardFailed):
        polite(http(lambda request: reply), []).get_json("https://example.test/u")


def test_network_errors_raise_board_failed():
    def broken(request):
        raise httpx.ConnectTimeout("too slow")

    with pytest.raises(BoardFailed, match="too slow"):
        polite(http(broken), []).get_json("https://example.test/u")


def test_requests_identify_the_project():
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, json={})

    polite(http(handler), []).get_json("https://example.test/u")
    assert seen[0].startswith("why-now-agent (+https://github.com/")
