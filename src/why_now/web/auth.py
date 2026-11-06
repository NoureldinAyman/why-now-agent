"""Who is using the app. Login for the deployed app comes in Task 25."""

from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Protocol

from starlette.requests import Request

LOCAL_USER = "local"
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}


class Authenticator(Protocol):
    def current_user(self, request: Request) -> str | None:
        """The name of the signed-in reviewer, or None if this request may not use the app."""
        ...


class LocalAuth:
    """For use on one's own machine only: lets in requests that come from this machine.

    Two things must hold. The sender's address must be this machine's own, so a request
    from another machine is refused. And the page must be reached under a local name,
    so a web page that tricks the browser into looking its own name up as 127.0.0.1
    cannot read or save marks.
    """

    def current_user(self, request: Request) -> str | None:
        if request.client is None or not _is_loopback(request.client.host):
            return None
        if _host_name(request.headers.get("host", "")) not in _LOCAL_NAMES:
            return None
        return LOCAL_USER


def _is_loopback(host: str) -> bool:
    try:
        address = ip_address(host)
    except ValueError:
        return False
    # `::ffff:10.0.0.5` carries an IPv4 address inside it, which is judged as that address.
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return isinstance(address, IPv4Address | IPv6Address) and address.is_loopback


def _host_name(header: str) -> str:
    """The name in a Host header, without its port and without brackets around an IPv6 address."""
    if header.startswith("["):
        return header[1 : header.find("]")] if "]" in header else ""
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header
