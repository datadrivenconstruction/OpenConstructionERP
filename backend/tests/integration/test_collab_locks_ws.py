"""WebSocket smoke tests for the collaboration-locks presence channel.

Uses Starlette's ``TestClient.websocket_connect`` because ``httpx`` has
no WebSocket transport.  The app lifespan runs via the ``with`` block
so module loading (and therefore route mounting) happens before any
request is made.
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


def _register_and_login(client: TestClient, suffix: str) -> tuple[str, str]:
    """Register a fresh user and return their access token and id.

    Open registration ignores the requested role and creates a viewer, so a
    second user reaches a project only through team membership, never through
    the admin bypass. The tests below add that membership explicitly.
    """
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
    user_id = str(reg.json()["id"])
    login = client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return token, user_id


def _add_project_member(
    client: TestClient,
    owner_token: str,
    project_id: str,
    user_id: str,
) -> None:
    """Put a second user on the project's default team."""
    headers = {"Authorization": f"Bearer {owner_token}"}
    teams = client.get(f"/api/v1/teams/?project_id={project_id}", headers=headers)
    assert teams.status_code == 200, teams.text
    team_id = teams.json()[0]["id"]
    added = client.post(
        f"/api/v1/teams/{team_id}/members/",
        json={"user_id": user_id, "role": "member"},
        headers=headers,
    )
    assert added.status_code == 201, added.text


def _seed_boq_position(client: TestClient, token: str) -> tuple[str, str]:
    """Create a real BOQ position and hand back its project id and its own id.

    The presence socket gates on the caller being able to reach the entity's
    owning project, so a random uuid resolves to no project and the socket
    closes with 1008 before a single frame is sent. These tests used a random
    uuid and had therefore been dead ever since that gate landed, silently,
    because the suite they live in runs in a CI job nobody reads.
    """
    headers = {"Authorization": f"Bearer {token}"}
    project = client.post(
        "/api/v1/projects/",
        json={"name": "WS Presence Project", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = str(project.json()["id"])
    boq = client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "WS Presence Estimate"},
        headers=headers,
    )
    assert boq.status_code == 201, boq.text
    boq_id = boq.json()["id"]
    section = client.post(
        f"/api/v1/boq/boqs/{boq_id}/sections/",
        json={"ordinal": "01", "description": "Substructure"},
        headers=headers,
    )
    assert section.status_code == 201, section.text
    position = client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete foundation",
            "unit": "m3",
            "quantity": 150,
            "unit_rate": 285.00,
            "parent_id": section.json()["id"],
        },
        headers=headers,
    )
    assert position.status_code == 201, position.text
    return project_id, str(position.json()["id"])


def test_ws_rejects_missing_token(ws_client: TestClient) -> None:
    """An anonymous handshake must be refused by policy, not by a crash.

    ``pytest.raises(Exception)`` used to pass here whether the socket closed
    with 1008 or blew up with a 500, which is how the RLS/HTTPBearer handshake
    regression stayed invisible for four releases. Assert the close code.

    The token now arrives in the first frame (``app.core.ws_auth``), so the
    upgrade is accepted in order to read it; a first frame without a token is
    refused before any presence frame is sent.
    """
    entity_id = str(uuid.uuid4())
    with ws_client.websocket_connect(
        f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}"
    ) as ws:
        ws.send_json({"type": "auth"})
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
    assert excinfo.value.code == 1008


def test_ws_receives_presence_snapshot_then_lock_acquired(
    ws_client: TestClient,
) -> None:
    """Connect Alice; she should receive ``presence_snapshot`` with an
    empty lock and roster containing her own user.  Then she POSTs a
    lock and must receive a ``lock_acquired`` broadcast on her own
    socket (the service publishes via the event bus → presence hub).
    """
    alice_token, _ = _register_and_login(ws_client, "alice")

    _, entity_id = _seed_boq_position(ws_client, alice_token)
    path = f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}&token={alice_token}"
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
    bob_token, bob_id = _register_and_login(ws_client, "bobjoin")
    project_id, entity_id = _seed_boq_position(ws_client, alice_token)
    _add_project_member(ws_client, alice_token, project_id, bob_id)
    base = f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}"

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


def test_ws_survives_a_binary_frame(ws_client: TestClient) -> None:
    """A binary frame must not take a working connection down.

    The keep-alive loop used to read with ``receive_text()``, which raises
    ``KeyError('text')`` when the frame carries ``bytes`` rather than text.
    That unwound into the handler's catch-all, logged "presence websocket
    crashed" and dropped the socket, taking the caller out of the presence
    roster and every peer's view of them with it. Any client can send one in
    a line, and several browser keep-alive helpers do, so the channel ignores
    what it does not understand instead of closing on it.

    The ping afterwards is the assertion: it is answered only if the socket
    survived the binary frame. Measured against the unfixed handler, this test
    does not fail fast - it STALLS. The handler returned without closing, so no
    close frame ever reached the client and the receive below waited forever.
    It is the per-test timeout that turns that into a red test, so do not read
    a hang here as a flake; it is this defect coming back.
    """
    token, _ = _register_and_login(ws_client, "binaryframe")
    _, entity_id = _seed_boq_position(ws_client, token)
    path = f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}&token={token}"

    with ws_client.websocket_connect(path) as ws:
        assert ws.receive_json()["event"] == "presence_snapshot"

        ws.send_bytes(b"\x00\x01\x02 not text")
        ws.send_text("still here?")
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"


def _presence_path(entity_id: str, token: str) -> str:
    return f"/api/v1/collaboration_locks/presence/?entity_type=boq_position&entity_id={entity_id}&token={token}"


def test_snapshot_reports_a_free_lock_as_free(ws_client: TestClient) -> None:
    """Nobody holds it, and the frame says so in the field that can be sure."""
    token, _ = _register_and_login(ws_client, "lockfree")
    _, entity_id = _seed_boq_position(ws_client, token)

    with ws_client.websocket_connect(_presence_path(entity_id, token)) as ws:
        snapshot = ws.receive_json()
        assert snapshot["event"] == "presence_snapshot"
        assert snapshot["lock"] is None
        assert snapshot["lock_state"] == "free"


def test_snapshot_reports_a_held_lock_as_held(ws_client: TestClient) -> None:
    """Somebody holds it before the socket opens, so the first frame carries it."""
    token, _ = _register_and_login(ws_client, "lockheld")
    _, entity_id = _seed_boq_position(ws_client, token)
    acquired = ws_client.post(
        "/api/v1/collaboration_locks/",
        json={"entity_type": "boq_position", "entity_id": entity_id, "ttl_seconds": 60},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert acquired.status_code == 201, acquired.text

    with ws_client.websocket_connect(_presence_path(entity_id, token)) as ws:
        snapshot = ws.receive_json()
        assert snapshot["event"] == "presence_snapshot"
        assert snapshot["lock"] is not None
        assert snapshot["lock_state"] == "held"


def test_snapshot_says_unknown_rather_than_free_when_the_lock_cannot_be_read(
    ws_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lock the server could not read must not arrive looking like a free one.

    ``lock`` is ``None`` in both cases and always was, which is the whole
    defect: null already means nobody holds it, so a failed read borrowing
    that value states something false with the confidence of the truth. The
    assertion is therefore on the field that carries the difference, and the
    two tests above are not decoration - without a case that expects ``free``,
    this one passes just as well against a handler that answers ``unknown``
    every time, which would be the same defect with the polarity flipped.
    """
    token, _ = _register_and_login(ws_client, "lockunknown")
    _, entity_id = _seed_boq_position(ws_client, token)

    from app.modules.collaboration_locks.service import CollabLockService

    async def _boom(self, **kwargs):  # noqa: ANN001, ANN003 - stands in for a real read
        raise RuntimeError("simulated failure reading the current lock")

    monkeypatch.setattr(CollabLockService, "get_for_entity", _boom)

    with ws_client.websocket_connect(_presence_path(entity_id, token)) as ws:
        snapshot = ws.receive_json()
        assert snapshot["event"] == "presence_snapshot"
        assert snapshot["lock"] is None
        assert snapshot["lock_state"] == "unknown", (
            f"a lock that could not be read arrived as a free lock: lock_state was {snapshot['lock_state']!r}"
        )
        # The socket still works: a failed lock read degrades the frame, it
        # does not end the connection, because the roster half is still true.
        ws.send_text("ping")
        assert ws.receive_json()["event"] == "pong"
