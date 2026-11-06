"""The page reader: fetches one web page the agent asked for, safely, and keeps only its plain text.

A link can come from a hostile page, so every address is checked before it is fetched:

- Only `http` and `https` are read. LinkedIn is never read, in any country version or short link.
- The name is looked up first, and if any address it gives is private or internal, the page
  is refused. The request then goes to the address that was checked, so the name can't be
  looked up again and point somewhere else in between.
- Redirects are followed by hand, and each hop is checked the same way.
- Each site's robots rules are followed, for every hop.
- Only web pages and plain text are read. The size and the total time are limited.

What is kept is plain text with email addresses and phone numbers removed.
"""

import codecs
import hashlib
import ipaddress
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from why_now.ai.claude import BLOCKED_DOMAINS
from why_now.domain import Source
from why_now.settings import Settings
from why_now.sources.polite import USER_AGENT
from why_now.sources.text import html_to_text

# Our name in robots files, matched the way robots files name readers.
ROBOTS_NAME = "why-now-agent"
_REDIRECTS = {301, 302, 303, 307, 308}
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_TEXT_TYPES = {"text/plain"}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_ALLOW_NOTHING = ["User-agent: *", "Disallow: /"]
# IPv6 ranges that carry an IPv4 address in their last 32 bits: NAT64 (RFC 6052) and the
# old IPv4-compatible form. Python counts some of these as public whatever they carry.
_CARRIES_IPV4 = [ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("::/96")]


class PageRefused(Exception):
    """The page was not read. `reason` names the rule, such as "linkedin" or "private_address"."""

    def __init__(self, reason: str, url: str, detail: str = ""):
        super().__init__(f"{reason}: {url}" + (f" ({detail})" if detail else ""))
        self.reason = reason
        self.url = url


def is_linkedin(host: str) -> bool:
    """LinkedIn and its country versions (uk.linkedin.com), its China site and its short links."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


@dataclass(frozen=True)
class _Target:
    """A checked address: the page's own URL, and the address the request really goes to."""

    url: str
    scheme: str
    host: str
    connect_url: str
    host_header: str

    @property
    def origin(self) -> str:
        return f"{self.scheme}://{self.host_header}"


@dataclass(frozen=True)
class _Reply:
    status: int
    location: str | None = None
    body: bytes = b""
    content_type: str = ""
    charset: str | None = None


class PageReader:
    """Reads one page at a time. Each site's robots rules are fetched once and then kept.

    `http` must be made with `trust_env=False`, so no proxy from the environment can
    decide where a request really goes.
    """

    def __init__(
        self,
        http: httpx.Client,
        settings: Settings,
        resolve: Callable[..., list[Any]] = socket.getaddrinfo,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if http.trust_env:
            raise ValueError("the page reader needs an httpx.Client made with trust_env=False")
        self.http = http
        self.settings = settings
        self.resolve = resolve
        self.clock = clock
        self._robots: dict[str, RobotFileParser] = {}

    def read(self, url: str) -> Source:
        deadline = self.clock() + timedelta(seconds=self.settings.page_timeout_seconds)
        final_url, reply = self._follow(url, deadline, page=True)
        if reply.status != 200:
            raise PageRefused("not_found", url, f"reply {reply.status}")
        text = reply.body.decode(_codec(reply.charset), errors="replace")
        if reply.content_type in _HTML_TYPES:
            text = html_to_text(text)
        return Source(
            id="page-" + hashlib.sha256(final_url.encode()).hexdigest()[:16],
            kind="page",
            url=final_url,
            text=remove_contacts(text),
            fetched_at=self.clock(),
        )

    def _follow(self, url: str, deadline: datetime, *, page: bool) -> tuple[str, _Reply]:
        """Fetch `url`, following up to `max_redirects` redirects and checking every hop."""
        current = url
        for _ in range(self.settings.max_redirects + 1):
            target = self._check(current)
            if page and not self._robots_allow(target, deadline):
                raise PageRefused("robots", current)
            reply = self._fetch(target, deadline, page=page)
            if reply.status not in _REDIRECTS or not reply.location:
                return current, reply
            current = urljoin(current, reply.location)
        raise PageRefused("too_many_redirects", url)

    def _check(self, url: str) -> _Target:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS:
            raise PageRefused("scheme", url)
        host = (parts.hostname or "").rstrip(".")
        if not host:
            raise PageRefused("bad_address", url, "no host")
        if is_linkedin(host):
            raise PageRefused("linkedin", url)
        try:
            port = parts.port or _DEFAULT_PORTS[scheme]
        except ValueError as e:
            raise PageRefused("bad_address", url, "bad port") from e
        try:
            found = self.resolve(host, port, 0, socket.SOCK_STREAM)
        except (OSError, UnicodeError) as e:
            raise PageRefused("unreachable", url, "name not found") from e
        addresses = [_address(info[4][0]) for info in found]
        if not addresses:
            raise PageRefused("unreachable", url, "name not found")
        for address in addresses:
            if not _is_public(address):
                raise PageRefused("private_address", url, str(address))
        ip = addresses[0]
        ip_text = f"[{ip}]" if ip.version == 6 else str(ip)
        shown_host = f"[{host}]" if ":" in host else host
        host_header = shown_host if port == _DEFAULT_PORTS[scheme] else f"{shown_host}:{port}"
        path = parts.path or "/"
        query = f"?{parts.query}" if parts.query else ""
        return _Target(
            url=url,
            scheme=scheme,
            host=host,
            connect_url=f"{scheme}://{ip_text}:{port}{path}{query}",
            host_header=host_header,
        )

    def _robots_allow(self, target: _Target, deadline: datetime) -> bool:
        rules = self._robots.get(target.origin)
        if rules is None:
            rules, lasting = self._load_robots(target.origin, deadline)
            if lasting:
                self._robots[target.origin] = rules
        return rules.can_fetch(ROBOTS_NAME, target.url)

    def _load_robots(self, origin: str, deadline: datetime) -> tuple[RobotFileParser, bool]:
        """A site's robots rules, and whether they can be kept for later pages.

        As the robots standard (RFC 9309) says, a missing file allows everything, and a
        file that can't be reached, or a server error, allows nothing. A failure is not
        kept, so a short outage doesn't block the site for the rest of the run.
        """
        rules = RobotFileParser()
        try:
            _, reply = self._follow(origin + "/robots.txt", deadline, page=False)
        except PageRefused:
            rules.parse(_ALLOW_NOTHING)
            return rules, False
        if reply.status == 200:
            rules.parse(reply.body.decode(_codec(reply.charset), errors="replace").splitlines())
        elif 400 <= reply.status < 500:
            rules.parse([])
        else:
            rules.parse(_ALLOW_NOTHING)
            return rules, False
        return rules, True

    def _fetch(self, target: _Target, deadline: datetime, *, page: bool) -> _Reply:
        """One GET with no redirects. A page must be a web page or plain text and within the
        size limit. A robots file is cut at the size limit instead, as the standard allows."""
        remaining = (deadline - self.clock()).total_seconds()
        if remaining <= 0:
            raise PageRefused("too_slow", target.url)
        extensions = {"sni_hostname": target.host} if target.scheme == "https" else {}
        try:
            with self.http.stream(
                "GET",
                target.connect_url,
                # A closed connection can't be reused for another site on the same address,
                # which would skip checking that site's certificate.
                headers={
                    "Host": target.host_header,
                    "User-Agent": USER_AGENT,
                    "Connection": "close",
                },
                extensions=extensions,
                timeout=min(remaining, self.settings.page_timeout_seconds),
                follow_redirects=False,
            ) as response:
                if response.status_code in _REDIRECTS:
                    return _Reply(response.status_code, location=response.headers.get("location"))
                if response.status_code != 200:
                    return _Reply(response.status_code)
                content_type = (
                    response.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if page and content_type not in _HTML_TYPES | _TEXT_TYPES:
                    raise PageRefused("content_type", target.url, content_type or "none given")
                body = self._read_body(response, target, deadline, page=page)
                return _Reply(
                    200, body=body, content_type=content_type, charset=response.charset_encoding
                )
        except httpx.TimeoutException as e:
            raise PageRefused("too_slow", target.url) from e
        except httpx.HTTPError as e:
            raise PageRefused("unreachable", target.url, type(e).__name__) from e

    def _read_body(
        self, response: httpx.Response, target: _Target, deadline: datetime, *, page: bool
    ) -> bytes:
        limit = self.settings.max_page_bytes
        declared = response.headers.get("content-length", "")
        if page and declared.isdigit() and int(declared) > limit:
            raise PageRefused("too_big", target.url, f"{declared} bytes")
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > limit:
                if page:
                    raise PageRefused("too_big", target.url, f"over {limit} bytes")
                return bytes(body[:limit])
            if self.clock() > deadline:
                raise PageRefused("too_slow", target.url)
        return bytes(body)


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    ip = ipaddress.ip_address(text)
    # An IPv4 address written as IPv6 (::ffff:127.0.0.1) is judged as the IPv4 address it is.
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return ip.ipv4_mapped
        if ip not in (ipaddress.IPv6Address("::"), ipaddress.IPv6Address("::1")) and any(
            ip in network for network in _CARRIES_IPV4
        ):
            return ipaddress.IPv4Address(ip.packed[-4:])
    return ip


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Only addresses on the public internet. Private, loopback, link-local (where cloud
    machines keep their secrets), shared, reserved and multicast addresses are all refused."""
    return ip.is_global and not ip.is_multicast


def _codec(charset: str | None) -> str:
    """The page's own character set if Python knows it, otherwise UTF-8."""
    if charset:
        try:
            return codecs.lookup(charset).name
        except LookupError:
            pass
    return "utf-8"


_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]+\s*(?:@|\s[\[(]at[\])]\s)\s*[A-Za-z0-9-]+(?:\s*(?:\.|\s[\[(]dot[\])]\s)\s*[A-Za-z0-9-]+)+"
)
# A phone number is either written in the international form, a "+" then digits, or has
# at least 10 digits in groups. Ten is a full national number in many countries, such as
# the US and Canada, and is more digits than a date or a year range has, so "2019-2024",
# "2024-01-15" and "250 staff" stay. Short local numbers without a "+" are missed.
_PHONE = re.compile(r"(?<![\w+])(?:\+\d[\d ().-]{5,}\d|\(?\d[\d ().-]{8,}\d)(?!\w)")
_DIGIT = re.compile(r"\d")


def remove_contacts(text: str) -> str:
    """Email addresses and phone numbers replaced with a marker. Other numbers stay."""
    text = _EMAIL.sub("[email removed]", text)
    return _PHONE.sub(_phone_or_keep, text)


def _phone_or_keep(match: re.Match[str]) -> str:
    found = match.group(0)
    if found.startswith("+") or len(_DIGIT.findall(found)) >= 10:
        return "[phone removed]"
    return found
