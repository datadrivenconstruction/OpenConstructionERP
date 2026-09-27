# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Simple in-memory rate limiter (no Redis required).

Limits requests per user per time window. Thread-safe via dict with timestamps.
For production, replace with Redis-based implementation.

Limits are configurable via environment variables:
  AI_RATE_LIMIT   - max AI requests per minute per user (default 10)
  API_RATE_LIMIT  - max API requests per minute per user/IP (default 100)
  LOGIN_RATE_LIMIT - max login attempts per minute per IP (default 10)
"""

from __future__ import annotations

import ipaddress
import time
from collections import defaultdict
from functools import lru_cache
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request


_DEFAULT_TRUSTED_PROXIES = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"


@lru_cache(maxsize=8)
def _parse_networks(spec: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse a comma-separated list of IPs / CIDR ranges, skipping junk entries."""
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(nets)


def _trusted_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    try:
        from app.config import get_settings

        spec = getattr(get_settings(), "trusted_proxies", _DEFAULT_TRUSTED_PROXIES)
    except Exception:
        spec = _DEFAULT_TRUSTED_PROXIES
    return _parse_networks(spec if isinstance(spec, str) else _DEFAULT_TRUSTED_PROXIES)


def _is_trusted(host: str | None, nets: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> bool:
    """True when ``host`` parses as an IP inside one of ``nets``.

    Anything that does not parse (``"testclient"``, a hostname, garbage from a
    header) is untrusted, so it can never unlock the forwarded headers.
    """
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host.strip().strip("[]"))
    except ValueError:
        return False
    return any(addr in net for net in nets)


def client_ip(request: Request) -> str | None:
    """Resolve the client address, believing forwarding headers only from a trusted proxy.

    ``X-Forwarded-For`` and ``X-Real-IP`` are plain request headers, so any
    caller on the internet can set them. They are honoured only when the
    direct socket peer is in ``TRUSTED_PROXIES`` (loopback and private ranges
    by default, i.e. a reverse proxy on the same host or docker network).
    The forwarded chain is then read from the right, skipping hops that are
    themselves trusted proxies, and the first untrusted address wins: the
    left end of the chain is whatever the client sent and is never believed.
    Returns ``None`` when there is no peer at all.
    """
    peer = request.client.host if request.client and request.client.host else None
    nets = _trusted_networks()
    if not _is_trusted(peer, nets):
        return peer

    xff = request.headers.get("x-forwarded-for")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        for hop in reversed(hops):
            if not _is_trusted(hop, nets):
                return hop
        if hops:
            # Every hop is a trusted proxy: the leftmost one is the client.
            return hops[0]

    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return peer


def client_identifier(request: Request) -> str:
    """Client identifier for rate-limiting buckets.

    Same resolution as :func:`client_ip`, so a spoofed ``X-Forwarded-For``
    from an untrusted peer cannot mint a fresh bucket per request.
    """
    return client_ip(request) or "unknown"


class RateLimiter:
    """Token bucket rate limiter using sliding window."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        now = time.time()
        with self._lock:
            # Clean old entries
            self._requests[key] = [t for t in self._requests[key] if t > now - self.window_seconds]

            if len(self._requests[key]) >= self.max_requests:
                return False, 0

            self._requests[key].append(now)
            remaining = self.max_requests - len(self._requests[key])
            return True, remaining


def _create_limiters() -> tuple[RateLimiter, RateLimiter, RateLimiter]:
    """Create rate limiter instances using values from Settings.

    Reads AI_RATE_LIMIT, API_RATE_LIMIT, and LOGIN_RATE_LIMIT from the
    application configuration (environment variables / .env file).
    Falls back to sensible defaults if settings cannot be loaded.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        ai_max = settings.ai_rate_limit
        api_max = settings.api_rate_limit
        login_max = settings.login_rate_limit
    except Exception:
        # Fallback: config not available yet (e.g. during testing or import)
        ai_max = 20
        api_max = 200
        login_max = 10

    return (
        RateLimiter(max_requests=ai_max, window_seconds=60),
        RateLimiter(max_requests=api_max, window_seconds=60),
        RateLimiter(max_requests=login_max, window_seconds=60),
    )


# Global instances - configured from environment variables
ai_limiter, api_limiter, login_limiter = _create_limiters()

# Rate limiter for approval / financial mutation endpoints.
# Tighter window to limit potential abuse of state-changing actions.
approval_limiter = RateLimiter(max_requests=40, window_seconds=60)

# Rate limiter for file uploads (documents, BIM, CAD, takeoff).
# Each upload buffers the full body server-side and may kick off background
# processing (OCR, thumbnailing, DDC conversion), so a single authenticated
# user could fill disk and/or worker pool if uncapped. 30/min is wide
# enough for legitimate batch BIM uploads while rejecting abuse.
upload_limiter = RateLimiter(max_requests=30, window_seconds=60)


def _register_hourly_max() -> int:
    try:
        from app.config import get_settings

        return int(get_settings().register_rate_limit_per_hour)
    except Exception:
        return 20


# Hourly cap on anonymous account-creating endpoints (self-registration and
# the field magic-link request), keyed per client IP. Registration answers
# 409 for a taken email because the sign-up page shows that message; this cap
# keeps that answer from being an address-list oracle. REGISTER_RATE_LIMIT_PER_HOUR.
registration_limiter = RateLimiter(max_requests=_register_hourly_max(), window_seconds=3600)
