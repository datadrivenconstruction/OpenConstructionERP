"""Public document share links must throttle password guessing."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.rate_limiter import share_link_limiter
from app.modules.documents.router import _throttle_share_link


def _request(host: str) -> Request:
    return Request({"type": "http", "headers": [], "client": (host, 1234), "method": "POST", "path": "/"})


@pytest.fixture(autouse=True)
def _clean():
    share_link_limiter._requests.clear()
    yield
    share_link_limiter._requests.clear()


def test_one_host_is_cut_off_after_its_budget():
    req = _request("203.0.113.5")
    for _ in range(share_link_limiter.max_requests):
        _throttle_share_link(req, "tok-a")
    with pytest.raises(HTTPException) as exc:
        _throttle_share_link(req, "tok-a")
    assert exc.value.status_code == 429


def test_many_hosts_cannot_walk_one_link():
    def walk() -> None:
        for i in range(500):
            _throttle_share_link(_request(f"198.51.100.{i % 250}"), "tok-b")

    with pytest.raises(HTTPException) as exc:
        walk()
    assert exc.value.status_code == 429


def test_other_links_are_unaffected():
    req = _request("203.0.113.9")
    for _ in range(share_link_limiter.max_requests):
        _throttle_share_link(req, "tok-c")
    _throttle_share_link(req, "tok-d")


def test_idle_bucket_keys_are_swept():
    from app.core.rate_limiter import RateLimiter

    lim = RateLimiter(max_requests=5, window_seconds=1)
    for i in range(50):
        lim.is_allowed(f"k{i}")
    import time

    time.sleep(1.1)
    lim.is_allowed("fresh")
    assert set(lim._requests) == {"fresh"}
