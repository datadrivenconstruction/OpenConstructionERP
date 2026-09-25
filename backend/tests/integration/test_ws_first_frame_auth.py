# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Realtime sockets authenticate with a first frame, and presence stays in its project.

Two defects, one application start (a start costs minutes here).

The token in the URL. All three sockets took the access token as
``?token=<jwt>``, and a URL is what uvicorn's ``[accepted]`` line, the access
log and any reverse proxy write down, so each of those lines held a working
session token. The token now travels as the first frame. What is asserted:
a socket opened without anything in the URL still authenticates, and a bad,
expired, missing or out-of-order first frame is refused with a policy close
before the socket has joined anything or sent anything.

The global room. Presence used to be one room for the whole server: every
signed-in account saw every other one in the header, with the page each was
on, across projects and across customers. It is now scoped to the project the
tab is working in, and a tab is only let into a project its user may open.
What is asserted: two users in two different projects never receive a frame
naming each other; a user who reports a project they cannot open is placed in
no project; and an admin, who can open every project, still only sees the
people in the project they are in.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

NOTIFY = "/api/v1/notifications/ws/"
GLOBAL = "/api/v1/global_presence/ws/"


@pytest.fixture(scope="module")
def ws_client() -> TestClient:
    app = create_app()
    with TestClient(app) as client:
        yield client


def _user(client: TestClient, tag: str) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"wsfirst-{tag}-{unique}@test.io"
    password = f"Wsfirst{unique}9"
    reg = client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"First Frame {tag} {unique}"},
    )
    assert reg.status_code == 201, reg.text
    login = client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"id": str(reg.json()["id"]), "token": token, "name": f"First Frame {tag} {unique}", "email": email}


def _project(client: TestClient, token: str) -> str:
    resp = client.post(
        "/api/v1/projects/",
        json={"name": "First frame project", "region": "DACH", "currency": "EUR"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _auth(token: str) -> dict[str, str]:
    return {"type": "auth", "token": token}


def _expired_token(user_id: str) -> str:
    from jose import jwt

    settings = get_settings()
    return jwt.encode(
        {"sub": user_id, "type": "access", "exp": int(time.time()) - 60, "iat": int(time.time()) - 3600},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _refused(client: TestClient, path: str, first: Any | None) -> int:
    """Open ``path`` with nothing in the URL, send ``first`` (if any), return the close code."""
    with client.websocket_connect(path) as ws:
        if isinstance(first, dict):
            ws.send_json(first)
        elif isinstance(first, str):
            ws.send_text(first)
        with pytest.raises(WebSocketDisconnect) as excinfo:
            ws.receive_json()
    return excinfo.value.code


def _drain_until_pong(ws: Any) -> list[dict[str, Any]]:
    """Everything the server sent before answering a ping, which it answers in order."""
    ws.send_text("ping")
    frames = []
    while True:
        frame = ws.receive_json()
        if frame.get("event") == "pong":
            return frames
        frames.append(frame)


# ── First-frame authentication ───────────────────────────────────────────────


def test_every_socket_authenticates_from_the_first_frame(ws_client: TestClient) -> None:
    alice = _user(ws_client, "a")
    project = _project(ws_client, alice["token"])

    with ws_client.websocket_connect(NOTIFY) as ws:
        ws.send_json(_auth(alice["token"]))
        assert ws.receive_json()["event"] == "notifications.hello"

    with ws_client.websocket_connect(GLOBAL) as ws:
        ws.send_json(_auth(alice["token"]))
        first = ws.receive_json()
        # In no project yet, so nobody: the tab has not said where it is.
        assert (first["event"], first["users"]) == ("presence_snapshot", [])

    path = f"/api/v1/collaboration_locks/presence/?entity_type=project&entity_id={project}"
    assert "token" not in path
    with ws_client.websocket_connect(path) as ws:
        ws.send_json(_auth(alice["token"]))
        snapshot = ws.receive_json()
        assert snapshot["event"] == "presence_snapshot"
        assert [u["user_id"] for u in snapshot["users"]] == [alice["id"]]


@pytest.mark.parametrize("path", [NOTIFY, GLOBAL])
def test_a_bad_first_frame_is_refused_with_a_policy_close(ws_client: TestClient, path: str) -> None:
    user = _user(ws_client, "bad")
    assert _refused(ws_client, path, _auth("not-a-jwt")) == 1008
    assert _refused(ws_client, path, _auth(_expired_token(user["id"]))) == 1008
    # A valid token in the wrong frame: the auth frame must come first.
    assert _refused(ws_client, path, {"type": "route_update", "route": "/", "token": user["token"]}) == 1008
    assert _refused(ws_client, path, "ping") == 1008


def test_a_silent_socket_is_closed_after_the_auth_timeout(
    ws_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import ws_auth

    monkeypatch.setattr(ws_auth, "WS_AUTH_TIMEOUT_SECONDS", 0.3)
    assert _refused(ws_client, NOTIFY, None) == 1008


# ── Presence scoped to the project ───────────────────────────────────────────


def _enter(ws: Any, token: str, project: str | None) -> dict[str, Any]:
    """Authenticate, report a project, and return the snapshot the server answers with."""
    ws.send_json(_auth(token))
    first = ws.receive_json()
    assert (first["event"], first["users"]) == ("presence_snapshot", [])
    ws.send_json({"type": "route_update", "route": "/boq", "project_id": project})
    frames = _drain_until_pong(ws)
    snapshots = [f for f in frames if f.get("event") == "presence_snapshot"]
    return snapshots[-1] if snapshots else {"event": "presence_snapshot", "users": []}


def _names_in(frames: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()
    for f in frames:
        if f.get("user_id"):
            found.add(str(f["user_id"]))
        for u in f.get("users") or []:
            found.add(str(u.get("user_id")))
    return found


def test_two_users_in_different_projects_never_see_each_other(ws_client: TestClient) -> None:
    alice = _user(ws_client, "pa")
    bob = _user(ws_client, "pb")
    project_a = _project(ws_client, alice["token"])
    project_b = _project(ws_client, bob["token"])

    with ws_client.websocket_connect(GLOBAL) as a_ws, ws_client.websocket_connect(GLOBAL) as b_ws:
        a_snapshot = _enter(a_ws, alice["token"], project_a)
        b_snapshot = _enter(b_ws, bob["token"], project_b)
        assert [u["user_id"] for u in a_snapshot["users"]] == [alice["id"]]
        assert [u["user_id"] for u in b_snapshot["users"]] == [bob["id"]]

        # Bob moves, idles and even claims Alice's project: none of it reaches Alice.
        b_ws.send_json({"type": "status_update", "status": "idle"})
        b_ws.send_json({"type": "route_update", "route": "/schedule", "project_id": project_a})
        bob_frames = _drain_until_pong(b_ws)
        alice_frames = _drain_until_pong(a_ws)

        assert bob["id"] not in _names_in(alice_frames), alice_frames
        assert alice["id"] not in _names_in(bob_frames), bob_frames
        # The project Bob cannot open put him in no project at all.
        assert bob_frames[-1]["event"] == "presence_snapshot"
        assert bob_frames[-1]["users"] == []


def test_a_member_of_the_same_project_is_seen_by_name_not_email(ws_client: TestClient) -> None:
    owner = _user(ws_client, "own")
    member = _user(ws_client, "mem")
    project = _project(ws_client, owner["token"])
    headers = {"Authorization": f"Bearer {owner['token']}"}
    teams = ws_client.get(f"/api/v1/teams/?project_id={project}", headers=headers)
    assert teams.status_code == 200, teams.text
    added = ws_client.post(
        f"/api/v1/teams/{teams.json()[0]['id']}/members/",
        json={"user_id": member["id"], "role": "member"},
        headers=headers,
    )
    assert added.status_code == 201, added.text

    with ws_client.websocket_connect(GLOBAL) as o_ws, ws_client.websocket_connect(GLOBAL) as m_ws:
        _enter(o_ws, owner["token"], project)
        snapshot = _enter(m_ws, member["token"], project)
        assert {u["user_id"] for u in snapshot["users"]} == {owner["id"], member["id"]}
        joined = [f for f in _drain_until_pong(o_ws) if f.get("event") == "presence_join"]
        assert [f["user_id"] for f in joined] == [member["id"]]
        assert joined[0]["user_name"] == member["name"]
        assert member["email"] not in str(joined)


def test_an_admin_only_sees_the_project_they_are_in(ws_client: TestClient) -> None:
    admin = _user(ws_client, "adm")
    other = _user(ws_client, "oth")
    project_a = _project(ws_client, admin["token"])
    project_b = _project(ws_client, other["token"])

    async def _promote() -> None:
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as session:
            await session.execute(update(User).where(User.id == uuid.UUID(admin["id"])).values(role="admin"))
            await session.commit()

    ws_client.portal.call(_promote)

    with ws_client.websocket_connect(GLOBAL) as a_ws, ws_client.websocket_connect(GLOBAL) as o_ws:
        _enter(a_ws, admin["token"], project_a)
        _enter(o_ws, other["token"], project_b)
        assert other["id"] not in _names_in(_drain_until_pong(a_ws))

        # The admin may open project B, so walking into it is allowed and they
        # then see the person there; they did not see them from project A.
        a_ws.send_json({"type": "route_update", "route": "/boq", "project_id": project_b})
        frames = _drain_until_pong(a_ws)
        assert other["id"] in _names_in(frames)
