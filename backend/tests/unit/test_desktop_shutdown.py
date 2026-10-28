"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The desktop launcher's clean-stop endpoint, and the guards that refuse it.

    POST /api/system/desktop-shutdown

The endpoint stops the server, so every test here that matters is a negative
one: not the desktop app, not this machine, no token configured, no token sent,
wrong token. A guard without a test that proves it refuses is not a guard.

These tests need no database and no app lifespan - the router is mounted on a
bare FastAPI app for the one round-trip test, and the handler is called directly
everywhere else, the same way ``test_desktop_bootstrap.py`` exercises its own
router guards.

Why the accepting test cannot kill the test run: the trigger refuses to raise
SIGTERM unless something in the process is handling it, and under pytest the
disposition is the default one, which would terminate pytest. The test that
proves the signal really is delivered installs its own handler first and puts
the previous one back afterwards.
"""

from __future__ import annotations

import asyncio
import signal

import pytest
from fastapi import HTTPException

from app.core import desktop_shutdown as ds

TOKEN = "test-token-2f8c41d0"


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in for fastapi.Request: a client host and headers."""

    def __init__(self, host: str | None = "127.0.0.1", token: str | None = TOKEN) -> None:
        self.client = _FakeClient(host) if host is not None else None
        self.headers = {ds.SHUTDOWN_TOKEN_HEADER: token} if token is not None else {}


@pytest.fixture
def desktop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend that is the desktop sidecar and has the launcher's token."""
    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.setenv(ds.SHUTDOWN_TOKEN_ENV, TOKEN)


# ── loopback helper ─────────────────────────────────────────────────────────


def test_loopback_helper_accepts_local_hosts() -> None:
    """The three loopback spellings are all local."""
    from app.core.loopback import is_loopback_request

    for host in ("127.0.0.1", "::1", "localhost"):
        assert is_loopback_request(_FakeRequest(host)) is True


def test_loopback_helper_rejects_a_remote_host() -> None:
    """Anything else is a remote caller."""
    from app.core.loopback import is_loopback_request

    assert is_loopback_request(_FakeRequest("203.0.113.5")) is False


def test_users_router_uses_the_shared_loopback_check() -> None:
    """The bootstrap endpoint's guard is the same one, not a second copy."""
    from app.modules.users import router as users_router

    assert users_router._is_loopback_request(_FakeRequest("127.0.0.1")) is True
    assert users_router._is_loopback_request(_FakeRequest("203.0.113.5")) is False


# ── guard chain: every way in that must be refused ──────────────────────────


@pytest.mark.asyncio
async def test_refused_when_not_desktop_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shared server never answers this endpoint at all."""
    monkeypatch.delenv("OE_DESKTOP", raising=False)
    monkeypatch.setenv(ds.SHUTDOWN_TOKEN_ENV, TOKEN)

    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest())

    assert exc.value.status_code == 403
    assert "desktop app" in str(exc.value.detail).lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_refused_when_not_loopback() -> None:
    """A caller from another machine is refused even in desktop mode."""
    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest("203.0.113.5"))

    assert exc.value.status_code == 403
    assert "local machine" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_refused_when_no_token_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A backend the launcher did not start cannot be stopped this way."""
    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.delenv(ds.SHUTDOWN_TOKEN_ENV, raising=False)

    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest())

    assert exc.value.status_code == 403
    assert "not configured" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_refused_when_the_configured_token_is_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty variable is an absent one, not a token that matches ``""``."""
    monkeypatch.setenv("OE_DESKTOP", "1")
    monkeypatch.setenv(ds.SHUTDOWN_TOKEN_ENV, "   ")

    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest(token=""))

    assert exc.value.status_code == 403
    assert "not configured" in str(exc.value.detail).lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_refused_when_the_token_header_is_missing() -> None:
    """A local process that does not know the token is still a stranger."""
    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest(token=None))

    assert exc.value.status_code == 403
    assert "token" in str(exc.value.detail).lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_refused_when_the_token_is_wrong() -> None:
    """A near miss is a miss - same length, one character apart."""
    near_miss = TOKEN[:-1] + ("1" if TOKEN.endswith("0") else "0")
    assert near_miss != TOKEN, "the near miss has to actually differ"

    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest(token=near_miss))

    assert exc.value.status_code == 403
    assert "token" in str(exc.value.detail).lower()


# ── the accepting path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_503_when_the_process_has_no_shutdown_handler() -> None:
    """Guards pass, but nothing here handles SIGTERM, so say so.

    This is the shape a plain pytest run produces, and it is exactly what the
    launcher needs: a refusal it can act on at once rather than a promise to
    stop that never arrives.
    """
    assert ds._sigterm_handler_installed() is False

    with pytest.raises(HTTPException) as exc:
        await ds.desktop_shutdown(_FakeRequest())

    assert exc.value.status_code == 503
    assert "cannot stop itself" in str(exc.value.detail).lower()


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_accepted_and_the_signal_is_really_delivered() -> None:
    """With a handler installed: 202, then a real SIGTERM reaches the handler.

    The handler stands in for the one uvicorn installs, whose job is to start
    the graceful shutdown - the same path that stops the embedded PostgreSQL
    cluster cleanly.
    """
    fired = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handler(signum: int, frame: object) -> None:
        loop.call_soon_threadsafe(fired.set)

    try:
        previous = signal.signal(signal.SIGTERM, _handler)
    except ValueError:  # pragma: no cover - only when off the main thread
        pytest.skip("signal handlers can only be installed from the main thread")

    try:
        assert ds._sigterm_handler_installed() is True

        response = await ds.desktop_shutdown(_FakeRequest())
        assert response.status == "stopping"

        # Not delivered yet: the response goes out first.
        assert not fired.is_set()

        await asyncio.wait_for(fired.wait(), timeout=5.0)
    finally:
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.asyncio
@pytest.mark.usefixtures("desktop_env")
async def test_route_is_mounted_at_the_path_the_launcher_calls() -> None:
    """Round-trip over ASGI: the path, the header name and the 202 all hold.

    The launcher hard-codes this URL and this header, so a rename that only
    touches the Python side has to fail here.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    fired = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handler(signum: int, frame: object) -> None:
        loop.call_soon_threadsafe(fired.set)

    app = FastAPI()
    app.include_router(ds.router)

    try:
        previous = signal.signal(signal.SIGTERM, _handler)
    except ValueError:  # pragma: no cover - only when off the main thread
        pytest.skip("signal handlers can only be installed from the main thread")

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as ac:
            # No token: refused.
            refused = await ac.post("/api/system/desktop-shutdown")
            assert refused.status_code == 403

            accepted = await ac.post(
                "/api/system/desktop-shutdown",
                headers={ds.SHUTDOWN_TOKEN_HEADER: TOKEN},
            )
            assert accepted.status_code == 202, accepted.text
            assert accepted.json()["status"] == "stopping"

        await asyncio.wait_for(fired.wait(), timeout=5.0)
    finally:
        signal.signal(signal.SIGTERM, previous)
