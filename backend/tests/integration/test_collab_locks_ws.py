"""WebSocket smoke tests for the collaboration-locks presence channel.

Uses Starlette's ``TestClient.websocket_connect`` because ``httpx`` has
no WebSocket transport.  The app lifespan runs via the ``with`` block
so module loading (and therefore route mounting) happens before any
request is made.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def ws_client() -> TestClient:
    app = create_app()
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"wscollab-{suffix}-{unique}@test.io"
    password = f"Wscollab{unique}9"
    reg = client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"WS Tester {suffix}",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, reg.text
    login = client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return token, email


def test_ws_rejects_missing_token(ws_client: TestClient) -> None:
    entity_id = str(uuid.uuid4())
    with pytest.raises(Exception):
        with ws_client.websocket_connect(
            f"/api/v1/collaboration_locks/presence/"
            f"?entity_type=boq_position&entity_id={entity_id}"
        ):
            pass


def test_ws_receives_presence_snapshot_then_lock_acquired(
    ws_client: TestClient,
) -> None:
    """Connect Alice; she should receive ``presence_snapshot`` with an
    empty lock and roster containing her own user.  Then she POSTs a
    lock and must receive a ``lock_acquired`` broadcast on her own
    socket (the service publishes via the event bus → presence hub).
    """
    alice_token, _ = _register_and_login(ws_client, "alice")

    entity_id = str(uuid.uuid4())
    path = (
        f"/api/v1/collaboration_locks/presence/"
        f"?entity_type=boq_position&entity_id={entity_id}&token={alice_token}"
    )
    with ws_client.websocket_connect(path) as ws:
        snapshot = ws.receive_json()
        assert snapshot["event"] == "presence_snapshot"
        assert snapshot["lock"] is None
        assert isinstance(snapshot["users"], list)
        assert len(snapshot["users"]) == 1

        # Acquire the lock through the HTTP surface.
        resp = ws_client.post(
            "/api/v1/collaboration_locks/",
            json={
                "entity_type": "boq_position",
                "entity_id": entity_id,
                "ttl_seconds": 60,
            },
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert resp.status_code == 201, resp.text
        lock_id = resp.json()["id"]

        # The presence hub fans out a ``lock_acquired`` to Alice's
        # socket (she is subscribed to the same entity).  Pop
        # envelopes until we see it — we may see our own
        # ``presence_join`` echo is excluded but nothing else is.
        seen_lock = False
        for _ in range(5):
            frame = ws.receive_json()
            if frame["event"] == "lock_acquired":
                assert frame["lock_id"] == lock_id
                seen_lock = True
                break
        assert seen_lock, "did not receive lock_acquired broadcast"


def test_ws_two_users_see_each_others_join(
    ws_client: TestClient,
) -> None:
    alice_token, _ = _register_and_login(ws_client, "alicejoin")
    bob_token, _ = _register_and_login(ws_client, "bobjoin")
    entity_id = str(uuid.uuid4())
    base = (
        f"/api/v1/collaboration_locks/presence/"
        f"?entity_type=boq_position&entity_id={entity_id}"
    )

    with ws_client.websocket_connect(f"{base}&token={alice_token}") as alice_ws:
        # Consume Alice's own snapshot.
        snap = alice_ws.receive_json()
        assert snap["event"] == "presence_snapshot"

        with ws_client.websocket_connect(f"{base}&token={bob_token}") as bob_ws:
            # Bob receives his own snapshot...
            bob_snap = bob_ws.receive_json()
            assert bob_snap["event"] == "presence_snapshot"
            assert len(bob_snap["users"]) == 2

            # ...and Alice receives a ``presence_join`` event for Bob.
            join = alice_ws.receive_json()
            assert join["event"] == "presence_join"
