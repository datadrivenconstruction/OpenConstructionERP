"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Is this request coming from the machine the server runs on.

Two endpoints answer only to the local desktop shell - the first-run bootstrap
that auto-provisions the workspace owner, and the shutdown request the launcher
sends on its way out - and both of them are dangerous exactly to the degree that
somebody else can reach them. That makes this check a security guard, and a
security guard written twice is a security guard that can be right in one copy
and wrong in the other, so it lives here once.
"""

from __future__ import annotations

import ipaddress
import os

from fastapi import Request

#: Hosts the desktop sidecar may legitimately be reached on. The Tauri shell
#: talks to the bundled backend over 127.0.0.1, so anything else is a remote
#: caller that must never reach a desktop-only path.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

#: Headers a reverse proxy adds. A proxy on this machine connects from
#: loopback, so the peer address alone would make every visitor it forwards
#: look local; the desktop shell never sends any of these.
FORWARDING_HEADERS: tuple[str, ...] = (
    "forwarded",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
)


def _bound_outside_loopback(request: Request) -> bool:
    """True when the server socket that took the request is not on loopback.

    The ASGI test transport reports a hostname here rather than an address,
    so only an address literal counts.
    """
    server = (getattr(request, "scope", None) or {}).get("server")
    if not server:
        return False
    try:
        return not ipaddress.ip_address(server[0]).is_loopback
    except ValueError:
        return False


def running_under_pytest() -> bool:
    """True when this process is a pytest run.

    The ASGI test transport can leave ``request.client`` unset, so the loopback
    guard would otherwise reject every test call. Only the ``client is None``
    case is relaxed under this marker - a real server with a missing client
    (which would be unusual) is still rejected.
    """
    return "PYTEST_CURRENT_TEST" in os.environ


def is_loopback_request(request: Request) -> bool:
    """Return True when the request originates from the local loopback.

    Args:
        request: The incoming request.

    Returns:
        ``True`` for a client on this machine that reached a loopback socket
        directly. A request carrying a proxy's forwarding header is never
        local, whatever its peer address. ``request.client`` is ``None``
        under the ASGI test transport; that case is treated as loopback only
        when running under pytest, and rejected otherwise.
    """
    headers = getattr(request, "headers", None) or {}
    if any(name in headers for name in FORWARDING_HEADERS):
        return False
    if _bound_outside_loopback(request):
        return False
    client = request.client
    if client is None:
        return running_under_pytest()
    return client.host in LOOPBACK_HOSTS
