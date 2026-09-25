# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WebSocket tests for the notifications push channel.

The channel had no test of its own. It is server-push only, so what is worth
covering is the handshake policy and the keep-alive loop: who is let in, and
what the loop does with a frame it did not expect.

Uses Starlette's ``TestClient.websocket_connect`` because ``httpx`` has no
WebSocket transport, and enters the app lifespan through the ``with`` block so
module loading, and therefore route mounting, happens before any request is
made. Without that the route does not exist yet: at construction the app
carries 85 routes and no sockets at all.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def ws_client() -> TestClient:
    app = create_app()
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient) -> str:
    """Register a fresh user and return their access token."""
    unique = uuid.uuid4().hex[:8]
    email = f"wsnotify-{unique}@test.io"
    password = f"Wsnotify{unique}9"
    reg = client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "WS Notify Tester"},
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return token


def test_ws_rejects_missing_token(ws_client: TestClient) -> None:
    """An anonymous handshake is refused by policy rather than by a crash.

    The close code is asserted, not merely that something went wrong: a 500
    during the handshake and a deliberate policy refusal both raise here, and
    only one of them is correct.

    The token now arrives in the first frame (``app.core.ws_auth``), so the
    upgrade is accepted in order to read it; a first frame that carries no
    token is what refuses the caller, before the hello frame.
    """
    with ws_client.websocket_connect("/api/v1/notifications/ws/") as ws:
        ws.send_json({"type": "auth"})
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
    assert excinfo.value.code == 1008


def test_ws_greets_and_answers_a_ping(ws_client: TestClient) -> None:
    """The channel says hello without waiting for a notification to fire."""
    token = _register_and_login(ws_client)
    with ws_client.websocket_connect(f"/api/v1/notifications/ws/?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["event"] == "notifications.hello"
        assert hello["user_id"]

        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"


def test_ws_survives_a_binary_frame(ws_client: TestClient) -> None:
    """A binary frame must not take a working connection down.

    The keep-alive loop used to read with ``receive_text()``, which raises
    ``KeyError('text')`` when the frame carries ``bytes`` rather than text.
    That unwound into the handler's catch-all, logged "notifications websocket
    crashed" and dropped the socket, so the user stopped receiving pushes until
    something reconnected them. Any client can send one in a line, and it means
    nothing on this channel, so the loop ignores it exactly as it ignores an
    unrecognised text frame.

    The ping afterwards is the assertion: it is answered only if the socket
    survived. Measured against the unfixed handler, this test does not fail
    fast - it STALLS. The handler returned without closing, so no close frame
    ever reached the client and the receive below waited forever. It is the
    per-test timeout that turns that into a red test, so do not read a hang
    here as a flake or an environment problem; it is this defect coming back.
    """
    token = _register_and_login(ws_client)
    with ws_client.websocket_connect(f"/api/v1/notifications/ws/?token={token}") as ws:
        assert ws.receive_json()["event"] == "notifications.hello"

        ws.send_bytes(b"\x00\x01\x02 not text")
        ws.send_text("nor is this a ping")
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"
