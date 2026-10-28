# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test for POST /api/v1/client-errors/ returning a 500.

This is the sink the frontend reports its own runtime errors to
(``frontend/src/shared/lib/errorLogger.ts``). It is unauthenticated,
fire-and-forget (``void fetch(...)``, no ``keepalive``), and commonly
fired right as the page navigates away - which is exactly when a browser
aborts the in-flight request client-side before the full body arrives.
Starlette surfaces that as an unhandled ``starlette.requests.ClientDisconnect``
raised out of ``await request.body()`` (``app/modules/client_errors/router.py``),
which nothing catches, so the app's global exception handler turns it into
a real ``500`` - every client-side error captured right at navigation is
silently discarded, and the server log under-reports how unhealthy the UI
actually is.

The happy-path tests go through the full app (not the router in isolation)
to exercise the real middleware chain. The disconnect regression drives the
ASGI app directly with a hand-built ``receive()`` that delivers a partial
body followed by ``http.disconnect`` - the one thing an HTTP test client
(``httpx.AsyncClient`` over ``ASGITransport``) cannot simulate, since it
always delivers a complete body.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    """Test client with app lifecycle (startup/shutdown) triggered.

    Module-scoped to avoid a full app boot (embedded-PG-backed startup and
    seeding) per test; safe here because ``pyproject.toml`` pins both
    asyncio loop scopes to ``session``, matching the pattern already used
    by ``test_bim_persistence.py``.
    """
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def raw_app():
    """The bare ASGI app (lifecycle triggered) for a hand-driven ASGI call.

    Needed for :func:`test_submit_client_error_survives_mid_body_disconnect`,
    which has to control the raw ``receive()`` message stream directly - an
    HTTP test client cannot express "send half the body, then disconnect".
    """
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        yield app


async def test_submit_client_error_does_not_500(client: AsyncClient) -> None:
    """A well-formed, schema-valid client-error report must be accepted (202).

    Regression for a reported defect: this endpoint is unauthenticated and
    write-only, so an unhandled exception here is silent from the caller's
    perspective and only shows up as a 500 in server logs (or, if the
    reporter is fire-and-forget, not even that).
    """
    payload = {
        "error_id": str(uuid.uuid4()),
        "message": "regression test error",
        "path": "/regression-test",
        "timestamp": "2026-08-29T00:00:00Z",
        "user_agent": "pytest-regression-agent",
        "stack_lines": ["at fn (app.js:1:1)", "at g (app.js:2:2)"],
    }
    resp = await client.post("/api/v1/client-errors/", json=payload)
    assert resp.status_code == 202, f"expected 202, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"status": "accepted"}


async def test_submit_client_error_malformed_json_still_202s(client: AsyncClient) -> None:
    """Malformed JSON is discarded silently (202) rather than raising."""
    resp = await client.post(
        "/api/v1/client-errors/",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 202, f"expected 202, got {resp.status_code}: {resp.text}"


async def test_submit_client_error_survives_mid_body_disconnect(raw_app) -> None:
    """A client that disconnects mid-body must not turn into a server 500.

    Regression for the reported defect: the reporter is fire-and-forget and
    routinely fires right as the page navigates away, which aborts the
    fetch client-side before the full JSON body reaches the server. That
    raised an unhandled ``starlette.requests.ClientDisconnect`` out of
    ``await request.body()`` and the app's global handler turned it into a
    ``500`` - reproduced here by feeding the ASGI app a partial
    ``http.request`` message followed by ``http.disconnect``, which an HTTP
    test client cannot express since it always sends a complete body.
    """
    full_body = json.dumps(
        {
            "error_id": str(uuid.uuid4()),
            "message": "disconnect regression test",
            "path": "/regression-test",
            "timestamp": "2026-08-29T00:00:00Z",
            "user_agent": "pytest-regression-agent",
            "stack_lines": [],
        }
    ).encode("utf-8")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/client-errors/",
        "raw_path": b"/api/v1/client-errors/",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(full_body)).encode("ascii")),
        ],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
        "state": {},
    }

    # Only the first few bytes arrive before the connection drops - a page
    # navigating away mid-fetch, not a malformed payload.
    messages = [
        {"type": "http.request", "body": full_body[:8], "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    # Must not raise - a raised exception here is the bug (an unhandled
    # ClientDisconnect propagating out of the ASGI app).
    await raw_app(scope, receive, send)

    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 202, f"expected 202, got {start['status']}: {sent}"
