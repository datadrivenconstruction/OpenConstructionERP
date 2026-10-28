"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The outbound-HTTP guard must be able to refuse, and to allow.

A guard nobody has ever seen refuse is indistinguishable from a guard that
does nothing: both leave a green suite and a quiet log. So every test here
plants the positive case first - it makes a call that MUST be blocked and
asserts on the refusal - and only then checks that the hermetic shapes still
get through.

The target host is ``blocked.invalid``. ``.invalid`` is reserved by RFC 2606
and never resolves, so if the guard ever stops working these tests fail on the
assertion instead of quietly sending real traffic to somebody's server, which
is the exact accident the guard exists to prevent.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import httpx
import pytest

_BLOCKED = "https://blocked.invalid"


async def _asgi_app(scope, receive, send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


# ── The guard refuses real egress ──────────────────────────────────────────


def test_sync_client_with_a_real_transport_is_refused() -> None:
    with httpx.Client(base_url=_BLOCKED, timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="Outbound HTTP to"):
            client.get("/v1/messages")


@pytest.mark.asyncio
async def test_async_client_with_a_real_transport_is_refused() -> None:
    async with httpx.AsyncClient(base_url=_BLOCKED, timeout=5.0) as client:
        with pytest.raises(RuntimeError, match="Outbound HTTP to"):
            await client.get("/v1/messages")


def test_urlopen_to_an_external_host_is_refused() -> None:
    with pytest.raises(RuntimeError, match="Outbound HTTP to"):
        urllib.request.urlopen(f"{_BLOCKED}/v1/messages", timeout=5)  # noqa: S310


def test_urlretrieve_is_refused() -> None:
    """`urlretrieve` never goes through `urlopen`, so it needs its own cover."""
    with pytest.raises(RuntimeError, match="Outbound HTTP to"):
        urllib.request.urlretrieve(f"{_BLOCKED}/model.tar.gz")  # noqa: S310


def test_a_custom_opener_is_refused() -> None:
    """`build_opener` bypasses `urlopen` entirely - one module here does this."""
    opener = urllib.request.build_opener()
    with pytest.raises(RuntimeError, match="Outbound HTTP to"):
        opener.open(f"{_BLOCKED}/v1/messages", timeout=5)


def test_the_refusal_says_what_to_do_about_it() -> None:
    """A named failure is the whole point; assert it names the way out."""
    with httpx.Client(base_url=_BLOCKED, timeout=5.0) as client:
        with pytest.raises(RuntimeError) as exc:
            client.get("/v1/messages")
    message = str(exc.value)
    assert "blocked.invalid" in message
    assert "Mock the client" in message
    assert "allow_network" in message


# ── The guard lets hermetic transports through ─────────────────────────────


def test_mock_transport_is_allowed_even_at_a_vendor_url() -> None:
    """Judging by hostname would fail this test for doing the right thing."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    with httpx.Client(transport=transport, base_url="https://api.anthropic.com") as client:
        assert client.get("/v1/messages").status_code == 200


@pytest.mark.asyncio
async def test_asgi_transport_is_allowed() -> None:
    transport = httpx.ASGITransport(app=_asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.anthropic.com") as client:
        assert (await client.get("/anything")).status_code == 200


# ── The opt-out works ──────────────────────────────────────────────────────


@pytest.mark.allow_network
def test_the_marker_lifts_the_guard() -> None:
    """With the marker the guard steps aside and the transport decides.

    ``blocked.invalid`` cannot resolve, so the connection fails - that failure
    is the evidence. What must NOT happen is our own RuntimeError.
    """
    with httpx.Client(base_url=_BLOCKED, timeout=5.0) as client:
        with pytest.raises(httpx.HTTPError):
            client.get("/v1/messages")


@pytest.mark.allow_network
def test_the_marker_lifts_the_guard_for_urlopen() -> None:
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(f"{_BLOCKED}/v1/messages", timeout=5)  # noqa: S310
