"""Integration tests for the collaboration-locks module.

Drives the HTTP surface end-to-end against a live FastAPI app.
Mirrors the module-scoped ``client + auth`` fixture pattern used by
``test_requirements_bim_cross.py`` so each test file carries its own
registered users and does not rate-limit its sibling suites.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

#: Hands back the id of a fresh lockable entity, one per call.
EntityFactory = Callable[[], Awaitable[str]]

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def collab_client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_and_login(client: AsyncClient, suffix: str) -> dict[str, str]:
    """Register a user and return their auth header, email and id.

    Open registration ignores the requested role and creates a viewer, so the
    admin bypass in the project-access check is not available to anyone here.
    Alice reaches the host project by owning it and Bob only through the team
    membership :func:`_add_project_member` grants him.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"collab-{suffix}-{unique}@test.io"
    password = f"Collab{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Collab Tester {suffix}",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"
    user_id = str(reg.json()["id"])

    token = ""
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}", "_email": email, "_user_id": user_id}


@pytest_asyncio.fixture(scope="module")
async def alice(collab_client: AsyncClient) -> dict[str, str]:
    return await _register_and_login(collab_client, "alice")


@pytest_asyncio.fixture(scope="module")
async def bob(collab_client: AsyncClient) -> dict[str, str]:
    return await _register_and_login(collab_client, "bob")


def _auth(headers: dict[str, str]) -> dict[str, str]:
    return {"Authorization": headers["Authorization"]}


# ── Lockable entities ──────────────────────────────────────────────────────
#
# Every lock endpoint resolves the entity_id to its owning project and refuses
# an entity it cannot reach, with a 404 that deliberately does not distinguish
# "no such row" from "not yours" (the platform-wide IDOR convention). A
# freshly minted UUID belongs to no project, so these tests lock real BOQ
# positions instead: one project and one BOQ for the whole module, and a new
# position per call so that no two tests contend for the same lock.


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Collab Locks {uuid.uuid4().hex[:6]}",
            "description": "Host project for collaboration-lock integration tests",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"Collab Locks BOQ {uuid.uuid4().hex[:6]}",
            "description": "Host BOQ for collaboration-lock integration tests",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_project_member(
    client: AsyncClient,
    owner_headers: dict[str, str],
    project_id: str,
    user_id: str,
) -> None:
    """Put a second user on the project's default team."""
    teams = await client.get(f"/api/v1/teams/?project_id={project_id}", headers=owner_headers)
    assert teams.status_code == 200, teams.text
    team_id = teams.json()[0]["id"]
    added = await client.post(
        f"/api/v1/teams/{team_id}/members/",
        json={"user_id": user_id, "role": "member"},
        headers=owner_headers,
    )
    assert added.status_code == 201, added.text


@pytest_asyncio.fixture(scope="module")
async def new_entity_id(
    collab_client: AsyncClient,
    alice: dict[str, str],
    bob: dict[str, str],
) -> EntityFactory:
    """Factory handing out the id of a real, lockable BOQ position.

    Every position minted here has to be reachable by BOTH users, because the
    point of half these tests is the two of them contending for one entity.
    Alice reaches it by owning the project; Bob is put on its team, which is
    the only route open to him now that registration hands out viewers.
    """
    project_id = await _create_project(collab_client, _auth(alice))
    await _add_project_member(collab_client, _auth(alice), project_id, bob["_user_id"])
    boq_id = await _create_boq(collab_client, _auth(alice), project_id)
    ordinals = count(10, 10)

    async def _mint() -> str:
        resp = await collab_client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": f"{next(ordinals):04d}",
                "description": "RC wall C30/37",
                "unit": "m3",
                "quantity": 10.0,
                "unit_rate": 185.0,
            },
            headers=_auth(alice),
        )
        assert resp.status_code == 201, f"add position failed: {resp.text}"
        return resp.json()["id"]

    return _mint


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_grants_when_free(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    resp = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["entity_id"] == entity_id
    assert body["remaining_seconds"] > 0
    assert body["user_name"]  # non-empty full_name
    assert uuid.UUID(body["id"])


@pytest.mark.asyncio
async def test_acquire_returns_409_when_held_by_other(
    collab_client: AsyncClient,
    alice: dict[str, str],
    bob: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    first = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert first.status_code == 201
    clash = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(bob),
    )
    assert clash.status_code == 409, clash.text
    body = clash.json()
    assert body["current_holder_name"]
    assert body["remaining_seconds"] > 0
    assert body["current_holder_user_id"] == first.json()["user_id"]


@pytest.mark.asyncio
async def test_holder_can_reacquire_idempotently(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    first = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 30,
        },
        headers=_auth(alice),
    )
    assert first.status_code == 201
    second = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 120,
        },
        headers=_auth(alice),
    )
    assert second.status_code == 201, second.text
    # Same lock id, extended expiry.
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["remaining_seconds"] >= first.json()["remaining_seconds"]


@pytest.mark.asyncio
async def test_heartbeat_extends_expiry(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 15,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201
    lock_id = acq.json()["id"]
    expires_before = acq.json()["expires_at"]

    hb = await collab_client.post(
        f"/api/v1/collaboration_locks/{lock_id}/heartbeat/",
        json={"extend_seconds": 120},
        headers=_auth(alice),
    )
    assert hb.status_code == 200, hb.text
    assert hb.json()["expires_at"] > expires_before
    assert hb.json()["remaining_seconds"] >= 100


@pytest.mark.asyncio
async def test_heartbeat_rejects_non_holder(
    collab_client: AsyncClient,
    alice: dict[str, str],
    bob: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201
    lock_id = acq.json()["id"]

    hb = await collab_client.post(
        f"/api/v1/collaboration_locks/{lock_id}/heartbeat/",
        json={"extend_seconds": 30},
        headers=_auth(bob),
    )
    assert hb.status_code == 404, hb.text


@pytest.mark.asyncio
async def test_release_removes_lock(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201
    lock_id = acq.json()["id"]

    rel = await collab_client.delete(
        f"/api/v1/collaboration_locks/{lock_id}/",
        headers=_auth(alice),
    )
    assert rel.status_code == 204

    # After release, the entity is free again.
    probe = await collab_client.get(
        "/api/v1/collaboration_locks/entity/",
        params={"entity_type": "boq_position", "entity_id": entity_id},
        headers=_auth(alice),
    )
    assert probe.status_code == 200
    assert probe.json() is None


@pytest.mark.asyncio
async def test_release_rejects_non_holder(
    collab_client: AsyncClient,
    alice: dict[str, str],
    bob: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201
    lock_id = acq.json()["id"]

    rel = await collab_client.delete(
        f"/api/v1/collaboration_locks/{lock_id}/",
        headers=_auth(bob),
    )
    assert rel.status_code == 403


@pytest.mark.asyncio
async def test_unknown_entity_type_rejected(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    """An off-allowlist type is a bad request, not a missing entity.

    The entity_id is a real, reachable position, so the only thing the
    endpoint can object to is the type itself. That rules out a 400 that
    merely happens to coincide with an unreachable row.
    """
    resp = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "unicorn",
            "entity_id": await new_entity_id(),
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert resp.status_code == 400, resp.text
    assert "unicorn" in resp.text


@pytest.mark.asyncio
async def test_get_entity_returns_none_when_free(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    probe = await collab_client.get(
        "/api/v1/collaboration_locks/entity/",
        params={
            "entity_type": "boq_position",
            "entity_id": await new_entity_id(),
        },
        headers=_auth(alice),
    )
    assert probe.status_code == 200
    assert probe.json() is None


@pytest.mark.asyncio
async def test_get_entity_returns_holder_info(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201

    probe = await collab_client.get(
        "/api/v1/collaboration_locks/entity/",
        params={"entity_type": "boq_position", "entity_id": entity_id},
        headers=_auth(alice),
    )
    assert probe.status_code == 200
    body = probe.json()
    assert body is not None
    assert body["entity_id"] == entity_id
    assert body["user_id"] == acq.json()["user_id"]


@pytest.mark.asyncio
async def test_list_my_locks_contains_held_lock(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201

    mine = await collab_client.get(
        "/api/v1/collaboration_locks/my/",
        headers=_auth(alice),
    )
    assert mine.status_code == 200
    ids = {item["entity_id"] for item in mine.json()}
    assert entity_id in ids


@pytest.mark.asyncio
async def test_expired_lock_can_be_stolen(
    collab_client: AsyncClient,
    alice: dict[str, str],
    bob: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    """Directly forge an already-expired lock at the DB level then
    verify another user can acquire the same entity.

    Exercises the "expired row → steal in place" branch in the
    repository without waiting for the 30s sweeper.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.collaboration_locks.models import CollabLock

    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201

    # Backdate the expiry so the row looks stale to the next caller.
    async with async_session_factory() as sess:
        stmt = select(CollabLock).where(CollabLock.entity_id == uuid.UUID(entity_id))
        row = (await sess.execute(stmt)).scalar_one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=5)
        await sess.commit()

    # Bob can now steal the (stale) lock.
    stolen = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(bob),
    )
    assert stolen.status_code == 201, stolen.text
    assert stolen.json()["user_id"] != acq.json()["user_id"]


@pytest.mark.asyncio
async def test_sweeper_removes_expired_rows(
    collab_client: AsyncClient,
    alice: dict[str, str],
    new_entity_id: EntityFactory,
) -> None:
    """Forge an expired row, invoke ``_sweep_once`` directly, verify
    the row is gone."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.collaboration_locks.models import CollabLock
    from app.modules.collaboration_locks.sweeper import _sweep_once

    entity_id = await new_entity_id()
    acq = await collab_client.post(
        "/api/v1/collaboration_locks/",
        json={
            "entity_type": "boq_position",
            "entity_id": entity_id,
            "ttl_seconds": 60,
        },
        headers=_auth(alice),
    )
    assert acq.status_code == 201
    lock_id = uuid.UUID(acq.json()["id"])

    async with async_session_factory() as sess:
        row = await sess.get(CollabLock, lock_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await sess.commit()

    removed = await _sweep_once()
    assert removed >= 1

    async with async_session_factory() as sess:
        stmt = select(CollabLock).where(CollabLock.id == lock_id)
        gone = (await sess.execute(stmt)).scalar_one_or_none()
        assert gone is None


@pytest.mark.asyncio
async def test_release_missing_lock_is_idempotent(collab_client: AsyncClient, alice: dict[str, str]) -> None:
    # Release a lock that never existed — should silently 204.
    rel = await collab_client.delete(
        f"/api/v1/collaboration_locks/{uuid.uuid4()}/",
        headers=_auth(alice),
    )
    assert rel.status_code == 204
