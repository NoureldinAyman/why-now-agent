import socket
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from why_now.pipeline.reader import PageReader, PageRefused, remove_contacts
from why_now.settings import Settings

PUBLIC_IP = "93.184.216.34"
ABOUT_PAGE = (
    "<html><head><script>alert(1)</script></head><body>"
    "<h1>About Acme</h1><p>Founded 2019, 250 staff.</p>"
    '<p>Write to <a href="mailto:jo@acme.test">jo@acme.test</a> or call +20 100 000 0000.</p>'
    "</body></html>"
)

Handler = Callable[[httpx.Request], httpx.Response]


def html(body: str, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html"} | headers)


def no_robots(request: httpx.Request) -> httpx.Response | None:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return None


def fake_web(pages: dict[str, Handler | httpx.Response], seen: list[httpx.Request]) -> Handler:
    """Pages keyed by "host/path". A missing robots file is a 404, so everything is allowed."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        key = request.headers["host"] + request.url.path
        page = pages.get(key)
        if page is None:
            return no_robots(request) or httpx.Response(404)
        return page(request) if callable(page) else page

    return handle


def resolver(addresses: dict[str, str]) -> Callable[..., list]:
    """Stands in for `socket.getaddrinfo`. Unknown names resolve to a public address."""

    def resolve(host: str, port: int | None, *args: object, **kwargs: object) -> list:
        ip = addresses.get(host, host if host[0].isdigit() or ":" in host else PUBLIC_IP)
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, port or 0))]

    return resolve


def ticking_clock(step_seconds: float = 0) -> Callable[[], datetime]:
    now = [datetime(2026, 11, 6, 9, 0, tzinfo=UTC)]

    def clock() -> datetime:
        now[0] += timedelta(seconds=step_seconds)
        return now[0]

    return clock


@pytest.fixture
def make_reader(settings: Settings):
    def make(
        pages: dict[str, Handler | httpx.Response],
        addresses: dict[str, str] | None = None,
        seen: list[httpx.Request] | None = None,
        clock: Callable[[], datetime] | None = None,
        **setting_overrides: object,
    ) -> PageReader:
        http = httpx.Client(
            transport=httpx.MockTransport(fake_web(pages, [] if seen is None else seen)),
            trust_env=False,
        )
        return PageReader(
            http,
            settings.model_copy(update=setting_overrides),
            resolve=resolver(addresses or {}),
            clock=clock or ticking_clock(),
        )

    return make


@pytest.fixture
def reader(make_reader) -> PageReader:
    return make_reader({"acme.test/about": html(ABOUT_PAGE)})


def refusal(reader: PageReader, url: str) -> str:
    with pytest.raises(PageRefused) as caught:
        reader.read(url)
    return caught.value.reason


def test_returns_plain_text_with_contacts_removed(reader):
    s = reader.read("https://acme.test/about")
    assert "<" not in s.text
    assert "jo@acme.test" not in s.text
    assert "+20 100 000 0000" not in s.text
    assert "About Acme" in s.text and "Founded 2019, 250 staff." in s.text
    assert "alert" not in s.text
    assert s.kind == "page"
    assert s.url == "https://acme.test/about"
    assert s.fetched_at == datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/company/x",
        "https://uk.linkedin.com/x",
        "https://lnkd.in/x",
        "https://LinkedIn.com./x",
        "https://www.linkedin.cn/x",
    ],
)
def test_refuses_linkedin(url, make_reader):
    seen: list[httpx.Request] = []
    assert refusal(make_reader({}, seen=seen), url) == "linkedin"
    assert seen == []


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1", "fd00::1",
           "::ffff:127.0.0.1", "100.64.0.1", "0.0.0.0", "64:ff9b::7f00:1", "::7f00:1",
           "2002:7f00:1::1"]
)  # fmt: skip
def test_refuses_private_addresses(ip, make_reader):
    seen: list[httpx.Request] = []
    reader = make_reader({"inside.test/": html("secret")}, {"inside.test": ip}, seen=seen)
    assert refusal(reader, "http://inside.test/") == "private_address"
    assert seen == []


def test_refuses_a_name_with_any_private_address(make_reader):
    reader = make_reader({})
    reader.resolve = lambda host, port, *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", port)),
    ]
    assert refusal(reader, "https://both.test/") == "private_address"


def test_refuses_a_private_address_written_in_the_link(make_reader):
    assert refusal(make_reader({}), "http://169.254.169.254/latest/meta-data/") == "private_address"


def test_sends_the_request_to_the_address_that_was_checked(make_reader):
    seen: list[httpx.Request] = []
    make_reader({"acme.test/about": html(ABOUT_PAGE)}, seen=seen).read("https://acme.test/about")
    page_request = seen[-1]
    assert page_request.url.host == PUBLIC_IP
    assert page_request.headers["host"] == "acme.test"
    assert page_request.extensions["sni_hostname"] == "acme.test"
    assert page_request.headers["connection"] == "close"


def test_refuses_a_web_client_that_could_use_a_proxy(settings):
    with pytest.raises(ValueError, match="trust_env"):
        PageReader(httpx.Client(), settings)


def test_refuses_a_redirect_into_a_private_address(make_reader):
    seen: list[httpx.Request] = []
    pages = {"acme.test/go": httpx.Response(302, headers={"location": "http://inside.test/admin"})}
    reader = make_reader(pages, {"inside.test": "10.1.2.3"}, seen=seen)
    assert refusal(reader, "https://acme.test/go") == "private_address"
    assert all(r.headers["host"] != "inside.test" for r in seen)


def test_refuses_a_redirect_to_linkedin(make_reader):
    pages = {"acme.test/go": httpx.Response(301, headers={"location": "https://lnkd.in/abc"})}
    assert refusal(make_reader(pages), "https://acme.test/go") == "linkedin"


def test_follows_a_safe_redirect_and_keeps_the_final_address(make_reader):
    pages = {
        "acme.test/old": httpx.Response(301, headers={"location": "/about"}),
        "acme.test/about": html(ABOUT_PAGE),
    }
    assert make_reader(pages).read("https://acme.test/old").url == "https://acme.test/about"


def test_stops_after_too_many_redirects(make_reader):
    pages = {"acme.test/loop": httpx.Response(302, headers={"location": "/loop"})}
    reader = make_reader(pages, max_redirects=3)
    assert refusal(reader, "https://acme.test/loop") == "too_many_redirects"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://acme.test/x", "javascript:alert(1)", "gopher://acme.test/"]
)
def test_refuses_non_http_schemes(url, make_reader):
    assert refusal(make_reader({}), url) == "scheme"


@pytest.mark.parametrize("url", ["https:///no-host", "https://acme.test:99999/"])
def test_refuses_a_broken_address(url, make_reader):
    assert refusal(make_reader({}), url) == "bad_address"


def robots(body: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/plain"})


def test_follows_robots_rules(make_reader):
    pages = {
        "acme.test/robots.txt": robots("User-agent: *\nDisallow: /private\n"),
        "acme.test/about": html(ABOUT_PAGE),
        "acme.test/private/team": html("hidden"),
    }
    reader = make_reader(pages)
    assert "About Acme" in reader.read("https://acme.test/about").text
    assert refusal(reader, "https://acme.test/private/team") == "robots"


def test_follows_robots_rules_that_name_this_reader(make_reader):
    pages = {
        "acme.test/robots.txt": robots("User-agent: why-now-agent\nDisallow: /\n"),
        "acme.test/about": html(ABOUT_PAGE),
    }
    assert refusal(make_reader(pages), "https://acme.test/about") == "robots"


def test_reads_the_robots_file_once_per_site(make_reader):
    seen: list[httpx.Request] = []
    pages = {"acme.test/robots.txt": robots(""), "acme.test/about": html(ABOUT_PAGE)}
    reader = make_reader(pages, seen=seen)
    reader.read("https://acme.test/about")
    reader.read("https://acme.test/about")
    assert [r.url.path for r in seen].count("/robots.txt") == 1


def test_a_robots_file_that_fails_allows_nothing(make_reader):
    pages = {"acme.test/robots.txt": httpx.Response(503), "acme.test/about": html(ABOUT_PAGE)}
    assert refusal(make_reader(pages), "https://acme.test/about") == "robots"


def test_a_robots_file_that_failed_is_tried_again_on_the_next_page(make_reader):
    replies = iter([httpx.Response(503), robots("")])
    pages = {
        "acme.test/robots.txt": lambda request: next(replies),
        "acme.test/about": html(ABOUT_PAGE),
    }
    reader = make_reader(pages)
    assert refusal(reader, "https://acme.test/about") == "robots"
    assert "About Acme" in reader.read("https://acme.test/about").text


def test_checks_robots_rules_after_a_redirect(make_reader):
    pages = {
        "acme.test/go": httpx.Response(302, headers={"location": "https://other.test/x"}),
        "other.test/robots.txt": robots("User-agent: *\nDisallow: /\n"),
        "other.test/x": html("page"),
    }
    assert refusal(make_reader(pages), "https://acme.test/go") == "robots"


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "image/svg+xml", ""])
def test_refuses_pdf_and_images(content_type, make_reader):
    page = httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": content_type})
    reader = make_reader({"acme.test/file": page})
    assert refusal(reader, "https://acme.test/file") == "content_type"


def test_reads_plain_text_pages(make_reader):
    text = "We sell to 3 < 5 teams."
    page = httpx.Response(200, text=text, headers={"content-type": "text/plain"})
    assert make_reader({"acme.test/t.txt": page}).read("https://acme.test/t.txt").text == text


def test_stops_at_the_size_limit(make_reader):
    def streamed(request: httpx.Request) -> httpx.Response:
        # No length is given, so the limit has to hold while the body arrives.
        chunks = (b"<p>" + b"x" * 1000 + b"</p>" for _ in range(100))
        return httpx.Response(200, content=chunks, headers={"content-type": "text/html"})

    reader = make_reader({"acme.test/big": streamed}, max_page_bytes=10_000)
    assert refusal(reader, "https://acme.test/big") == "too_big"


def test_refuses_a_page_that_says_it_is_too_big(make_reader):
    reader = make_reader({"acme.test/big": html("x" * 20_000)}, max_page_bytes=10_000)
    assert refusal(reader, "https://acme.test/big") == "too_big"


def test_stops_at_the_time_limit(make_reader):
    def slow(request: httpx.Request) -> httpx.Response:
        chunks = (b"<p>part</p>" for _ in range(100))
        return httpx.Response(200, content=chunks, headers={"content-type": "text/html"})

    # Each look at the clock moves it on 1 second, against the 15 second limit.
    reader = make_reader({"acme.test/slow": slow}, clock=ticking_clock(1))
    assert refusal(reader, "https://acme.test/slow") == "too_slow"


def test_a_connection_that_times_out_is_too_slow(make_reader):
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no reply", request=request)

    assert refusal(make_reader({"acme.test/about": hang}), "https://acme.test/about") == "too_slow"


def test_a_missing_page_is_refused_as_not_found(make_reader):
    assert refusal(make_reader({}), "https://acme.test/gone") == "not_found"


@pytest.mark.parametrize(
    "text",
    [
        "Founded 2019, 250 staff",
        "Revenue grew 40% to $12.5 million in 2024",
        "From 2019-2024 we hired 1,200 people",
        "Series B on 2024-01-15",
        "Call us on 0800",
    ],
)
def test_remove_contacts_keeps_normal_numbers(text):
    assert remove_contacts(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Mail jo@acme.test today", "Mail [email removed] today"),
        ("Mail jo.smith+jobs@mail.acme.co.uk.", "Mail [email removed]."),
        ("Mail jo [at] acme [dot] test", "Mail [email removed]"),
        ("Call +20 100 000 0000 now", "Call [phone removed] now"),
        ("Call +44 (0)20 7946 0958", "Call [phone removed]"),
        ("Call (555) 123-4567.", "Call [phone removed]."),
        ("Call 555.123.4567", "Call [phone removed]"),
    ],
)
def test_remove_contacts_removes_emails_and_phones(text, expected):
    assert remove_contacts(text) == expected
