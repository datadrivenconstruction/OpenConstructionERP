"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Websocket handshake guard for the app-wide RLS dependency.

Regression cover for the defect that shipped in 12.3 through 12.6: both
realtime sockets (live notifications and collaboration presence) answered every
handshake with a 500. ``rls_request_context`` is mounted as a global dependency
in :mod:`app.main` and resolves the caller through the optional-user chain. That
chain used to read the bearer token with ``HTTPBearer``, whose ``__call__`` is
typed for ``Request`` and raises on a websocket scope, so the dependency solver
failed before any route body ran. Nothing about the route code was wrong, which
is why it survived four releases.

These tests mount the real global dependency on a throwaway websocket route. No
cluster and no database are needed: an anonymous handshake resolves to
``tenant_id=None`` and short-circuits before the first query. The file lives in
the PG lane because that lane is what *CI (PostgreSQL)* gates, and because the
dependency under test is the multi-tenant RLS plumbing. The lane's cluster
fixture is opt-in, so nothing here pays for an ``initdb``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import APIRouter, Depends, FastAPI, WebSocket
from fastapi.testclient import TestClient

from app.dependencies import _optional_bearer_token, rls_request_context

if TYPE_CHECKING:
    from collections.abc import Iterator


def _build_app() -> FastAPI:
    """A minimal app carrying the same global dependency as the real one."""
    app = FastAPI()
    router = APIRouter(dependencies=[Depends(rls_request_context)])

    @router.websocket("/ws/")
    async def echo(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    @router.get("/http/")
    async def http_probe() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(_build_app()) as test_client:
        yield test_client


def test_anonymous_websocket_handshake_succeeds(client: TestClient) -> None:
    """The 500 was raised here, before the route body, on a bare handshake."""
    with client.websocket_connect("/ws/") as websocket:
        assert websocket.receive_text() == "hello"


def test_websocket_handshake_survives_a_bearer_header(client: TestClient) -> None:
    with client.websocket_connect(
        "/ws/",
        headers={"Authorization": "Bearer not-a-real-token"},
    ) as websocket:
        assert websocket.receive_text() == "hello"


def test_websocket_handshake_survives_a_non_bearer_header(client: TestClient) -> None:
    with client.websocket_connect(
        "/ws/",
        headers={"Authorization": "Basic nonsense"},
    ) as websocket:
        assert websocket.receive_text() == "hello"


def test_http_route_keeps_resolving(client: TestClient) -> None:
    """The strict and optional http auth paths must be untouched by the fix."""
    assert client.get("/http/").json() == {"ok": True}


async def _unused_channel() -> None:  # pragma: no cover - never invoked
    raise AssertionError("the handshake tests never read or write frames")


def _websocket_with_header(value: str | None) -> WebSocket:
    headers = [(b"authorization", value.encode())] if value is not None else []
    scope = {
        "type": "websocket",
        "path": "/ws/",
        "query_string": b"",
        "headers": headers,
    }
    return WebSocket(scope, receive=_unused_channel, send=_unused_channel)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer abc123", "abc123"),
        ("bearer abc123", "abc123"),
        ("Basic abc123", None),
        ("Bearer", None),
        ("", None),
        (None, None),
    ],
)
async def test_optional_bearer_token_reads_a_websocket_scope(
    header: str | None,
    expected: str | None,
) -> None:
    """The resolver reads ``HTTPConnection``, the shared base of both scopes.

    ``HTTPBearer`` cannot do this, and swapping it back in is exactly the
    regression this file exists to catch.
    """
    assert await _optional_bearer_token(_websocket_with_header(header)) == expected
