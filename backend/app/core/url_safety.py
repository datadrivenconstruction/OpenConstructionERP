"""SSRF-safe URL validation.

Used by webhook and outbound-webhook-like features to reject URLs that would
point a server-side HTTP client at the loopback interface, RFC1918 / carrier-
grade NAT / link-local ranges, cloud-metadata addresses, multicast, or any
non-http(s) scheme (``file://``, ``gopher://``, ``dict://`` …).

Two layers of protection:
    1. ``validate_external_url`` — synchronous, no DNS, good for Pydantic
       validators. Rejects bad schemes, literal IPs in blocklisted ranges,
       and the small set of hard-coded cloud metadata hostnames.
    2. ``resolve_and_validate_external_url`` — async, performs DNS lookup
       and rejects any resolved address in a blocklisted range. Call this
       right before ``httpx.post`` so a DNS rebinding or a hostname that
       resolves to a private IP is caught at dispatch time.

Both helpers raise ``UnsafeUrlError`` (a subclass of ``ValueError``) so they
can be used inside Pydantic field validators without any adapter layer.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

__all__ = [
    "UnsafeUrlError",
    "resolve_and_validate_external_url",
    "validate_external_url",
]


_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that are *always* unsafe regardless of DNS result. The cloud
# metadata addresses resolve to link-local ranges anyway, but listing them
# explicitly guards against proxies / split-horizon DNS that rewrite the
# hostname to a public IP. ``localhost`` and friends are blocked here so
# the sync validator catches them without waiting for the async DNS path.
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "broadcasthost",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "169.254.169.254",
        "fd00:ec2::254",
    }
)


class UnsafeUrlError(ValueError):
    """Raised when a URL points at a blocklisted host or scheme."""


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is in a blocklisted range."""
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _parse_host(url: str) -> tuple[str, str]:
    """Return (scheme, hostname) or raise UnsafeUrlError on malformed input."""
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UnsafeUrlError(f"Invalid URL: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(
            f"URL scheme {scheme!r} is not allowed — use http or https"
        )

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeUrlError("URL is missing a hostname")

    return scheme, host


def validate_external_url(url: str) -> str:
    """Reject URLs that are trivially unsafe (bad scheme, literal private IP).

    This check is synchronous and makes no DNS calls, so it is cheap enough
    to run inside a Pydantic validator. For defence in depth, pair it with
    :func:`resolve_and_validate_external_url` at dispatch time.
    """
    _, host = _parse_host(url)

    if host in _BLOCKED_HOSTNAMES:
        raise UnsafeUrlError(f"Hostname {host!r} is blocked")

    # Is the host a literal IP address?
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return url  # hostname — resolve later

    if _is_blocked_address(addr):
        raise UnsafeUrlError(f"URL targets non-routable address {addr}")

    return url


async def resolve_and_validate_external_url(url: str) -> str:
    """Resolve *url*'s hostname and reject if any resolved IP is blocklisted.

    This is the second line of defence, run right before HTTP dispatch so
    DNS-rebinding and split-horizon setups cannot sneak a private address
    past the sync validator.
    """
    validate_external_url(url)  # fast-path
    _, host = _parse_host(url)

    # Skip DNS for literal IPs — already validated above.
    try:
        ipaddress.ip_address(host)
        return url
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host,
            None,
            proto=socket.IPPROTO_TCP,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Hostname does not resolve: {host}") from exc

    for info in infos:
        raw_addr = info[4][0]
        try:
            addr = ipaddress.ip_address(raw_addr)
        except ValueError:
            continue
        if _is_blocked_address(addr):
            raise UnsafeUrlError(
                f"Hostname {host!r} resolves to non-routable address {addr}"
            )

    return url
