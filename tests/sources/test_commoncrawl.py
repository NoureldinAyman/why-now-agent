import httpx
import pytest
from commoncrawl_fake import fake_index, lines

from why_now.sources.commoncrawl import ListBuildFailed, board_from_url, build_board_list


@pytest.mark.parametrize(
    "url,source,expected",
    [
        ("https://job-boards.greenhouse.io/0x/jobs/7302322002", "greenhouse", "0x"),
        ("https://job-boards.greenhouse.io/0verwatch?error=true", "greenhouse", "0verwatch"),
        ("https://job-boards.greenhouse.io/", "greenhouse", None),
        ("https://boards.greenhouse.io/embed/job_app?for=acme", "greenhouse", None),
        ("https://jobs.lever.co/acme/1234-abcd", "lever", "acme"),
        ("https://jobs.lever.co", "lever", None),
        ("https://jobs.lever.co/acme", "greenhouse", None),
        ("https://example.com/acme", "lever", None),
        ("not a url", "lever", None),
        ("https://jobs.lever.co/%20/x", "lever", None),
    ],
)
def test_board_from_url(url, source, expected):
    assert board_from_url(url, source) == expected


def build(source, http, existing=(), pauses=None):
    return build_board_list(
        source,
        http,
        list(existing),
        delay_seconds=1.0,
        attempts=3,
        sleep=(pauses.append if pauses is not None else lambda s: None),
    )


def test_build_list_merges_and_dedupes():
    http = fake_index(
        {
            "job-boards.greenhouse.io": [
                lines(
                    "https://job-boards.greenhouse.io/acme/jobs/1",
                    "https://job-boards.greenhouse.io/acme/jobs/2",
                    "https://job-boards.greenhouse.io/",
                ),
                lines("https://job-boards.greenhouse.io/Beta?x=1"),
            ],
            "boards.greenhouse.io": [
                lines(
                    "https://boards.greenhouse.io/beta/jobs/9", "https://boards.greenhouse.io/gamma"
                )
            ],
        }
    )
    got = build("greenhouse", http, existing=["delta", "ACME"])
    assert got == ["delta", "ACME", "Beta", "gamma"]


def test_build_list_pauses_between_requests():
    pauses: list[float] = []
    http = fake_index(
        {"jobs.lever.co": [lines("https://jobs.lever.co/a/1"), lines("https://jobs.lever.co/b/1")]}
    )
    build("lever", http, pauses=pauses)
    assert pauses and all(p == 1.0 for p in pauses)


def test_build_list_retries_on_timeouts_then_reports_failure():
    seen: list[str] = []
    http = fake_index({}, fail_with=504, seen=seen)
    with pytest.raises(ListBuildFailed, match="504.*3 tries"):
        build("lever", http)
    assert len([u for u in seen if "-index" in u]) == 3


def test_build_list_retries_a_connection_timeout():
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ListBuildFailed, match="ReadTimeout"):
        build("lever", httpx.Client(transport=httpx.MockTransport(handle)))
    assert len(calls) == 3


def test_build_list_recovers_when_a_retry_succeeds():
    state = {"n": 0}
    inner = fake_index({"jobs.lever.co": [lines("https://jobs.lever.co/a/1")]})

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("-index"):
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(504)
        return inner.send(inner.build_request("GET", request.url))

    got = build("lever", httpx.Client(transport=httpx.MockTransport(handle)))
    assert got == ["a"]


def test_unknown_source_is_refused():
    with pytest.raises(ValueError, match="nope"):
        build("nope", fake_index({}))


def test_build_list_retries_a_reply_that_was_cut_short():
    state = {"n": 0}
    inner = fake_index({"jobs.lever.co": [lines("https://jobs.lever.co/a/1")]})

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "0":
            state["n"] += 1
            if state["n"] == 1:
                return httpx.Response(200, text='{"url": "https://jobs.lev')
        return inner.send(inner.build_request("GET", request.url))

    assert build("lever", httpx.Client(transport=httpx.MockTransport(handle))) == ["a"]


def test_build_list_reports_a_reply_that_is_always_cut_short():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "0":
            return httpx.Response(200, text='{"url": "https://jobs.lev')
        return fake_index({"jobs.lever.co": [""]}).send(
            httpx.Client().build_request("GET", request.url)
        )

    with pytest.raises(ListBuildFailed, match="cut short"):
        build("lever", httpx.Client(transport=httpx.MockTransport(handle)))


def test_names_already_in_the_list_are_not_kept_twice():
    http = fake_index({"jobs.lever.co": [lines("https://jobs.lever.co/a/1")]})
    assert build("lever", http, existing=["x", "X", "a"]) == ["x", "a"]
