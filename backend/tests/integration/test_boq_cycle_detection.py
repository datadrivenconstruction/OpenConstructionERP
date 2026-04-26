"""BOQ position hierarchy cycle detection (BUG-CYCLE01 / BUG-CYCLE02).

Regression coverage for the bug where ``parent_id`` could be set to:

* the position's own id (self-cycle, BUG-CYCLE01),
* a descendant of the position (transitive cycle, BUG-CYCLE02), or
* a position belonging to a different BOQ (cross-BOQ parent).

Any of these states crashes hierarchical recomputation (infinite recursion
during total roll-up) and breaks PDF / Excel / GAEB exports that walk the
tree. The fix lives in ``BOQService._validate_parent_id`` and is invoked
from both the create path (``POST /api/v1/boq/boqs/{boq_id}/positions``)
and the update path (``PATCH /api/v1/boq/positions/{position_id}``).

Run:
    cd backend
    python -m pytest tests/integration/test_boq_cycle_detection.py -v --tb=short
"""

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (module-scoped to avoid rate-limiter & lifespan churn) ──


@pytest_asyncio.fixture(scope="module")
async def shared_client():
    """Module-scoped client with full app lifecycle."""
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    """Module-scoped auth: register + promote-to-admin + login.

    Registration assigns ``admin`` only to the very first user on a fresh
    install; subsequent self-registrations default to ``viewer`` for
    security (BUG-327/386). Tests need a token with ``boq.create`` /
    ``boq.update`` so we promote the freshly-created user directly via
    the ORM before logging in. This keeps the test independent of DB
    state and mirrors what an admin would do in production.
    """
    unique = uuid.uuid4().hex[:8]
    email = f"boqcycle-{unique}@test.io"
    password = f"BoqCycle{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Cycle Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Promote to admin in case this isn't the bootstrap user.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            sa_update(User)
            .where(User.email == email.lower())
            .values(role="admin", is_active=True)
        )
        await session.commit()

    token = ""
    for attempt in range(3):
        resp = await shared_client.post(
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
    return {"Authorization": f"Bearer {token}"}


# ── Per-module helpers ──────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Cycle Test {uuid.uuid4().hex[:6]}",
            "description": "BOQ cycle detection",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"Cycle BOQ {uuid.uuid4().hex[:6]}",
            "description": "cycle detection",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    ordinal: str,
    description: str = "Test position",
    parent_id: str | None = None,
) -> dict:
    body: dict = {
        "boq_id": boq_id,
        "ordinal": ordinal,
        "description": description,
        "unit": "m3",
        "quantity": 1.0,
        "unit_rate": 100.0,
    }
    if parent_id is not None:
        body["parent_id"] = parent_id
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json=body,
        headers=auth,
    )
    assert resp.status_code == 201, f"Add position failed: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
#  Cycle-prevention tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_update_self_parent_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCH parent_id == id must return 400 (self-cycle, BUG-CYCLE01)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    pos = await _add_position(shared_client, shared_auth, boq_id, ordinal="01.001")

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{pos['id']}",
        json={"parent_id": pos["id"]},
        headers=shared_auth,
    )
    # BUG-CYCLE02: structural-validation failures return 422 (FastAPI
    # convention for invalid request bodies). Self-cycle is a structural
    # check that fires before the descendant walk — see
    # ``BOQService._validate_parent_id``.
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "self" in resp.text.lower() or "own parent" in resp.text.lower()


@pytest.mark.asyncio
async def test_update_direct_child_as_parent_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCH P.parent_id = C.id where C is direct child of P must 400."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    parent = await _add_position(shared_client, shared_auth, boq_id, ordinal="02.001")
    child = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="02.001.01",
        parent_id=parent["id"],
    )

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{parent['id']}",
        json={"parent_id": child["id"]},
        headers=shared_auth,
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    assert "cycle" in resp.text.lower() or "descendant" in resp.text.lower()


@pytest.mark.asyncio
async def test_update_grandchild_as_parent_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCH P.parent_id = GC.id where GC is grandchild of P must 400."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    p = await _add_position(shared_client, shared_auth, boq_id, ordinal="03.001")
    c = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="03.001.01", parent_id=p["id"]
    )
    gc = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="03.001.01.01", parent_id=c["id"]
    )

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{p['id']}",
        json={"parent_id": gc["id"]},
        headers=shared_auth,
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    assert "cycle" in resp.text.lower() or "descendant" in resp.text.lower()


@pytest.mark.asyncio
async def test_update_cross_boq_parent_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCH parent_id pointing at a position in a different BOQ must 400."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_a = await _create_boq(shared_client, shared_auth, project_id)
    boq_b = await _create_boq(shared_client, shared_auth, project_id)

    pos_a = await _add_position(shared_client, shared_auth, boq_a, ordinal="04.001")
    pos_b = await _add_position(shared_client, shared_auth, boq_b, ordinal="04.001")

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{pos_a['id']}",
        json={"parent_id": pos_b["id"]},
        headers=shared_auth,
    )
    # BUG-CYCLE02: cross-BOQ parent is a structural rejection (422), not
    # a domain logic conflict (400). See ``BOQService._validate_parent_id``.
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "different boq" in resp.text.lower() or "cross-boq" in resp.text.lower()


@pytest.mark.asyncio
async def test_update_valid_sibling_reparent_succeeds(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Valid re-parenting between two non-overlapping subtrees succeeds.

    Tree before:
        S1
          ├── A
        S2

    Move A under S2: expected to succeed.
    """
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    s1 = await _add_position(shared_client, shared_auth, boq_id, ordinal="05.001")
    s2 = await _add_position(shared_client, shared_auth, boq_id, ordinal="05.002")
    a = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="05.001.01", parent_id=s1["id"]
    )

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{a['id']}",
        json={"parent_id": s2["id"]},
        headers=shared_auth,
    )
    assert resp.status_code == 200, f"Valid reparent failed: {resp.status_code} {resp.text}"
    assert resp.json()["parent_id"] == s2["id"]


@pytest.mark.asyncio
async def test_update_move_subtree_to_other_parent_succeeds(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Moving a position with descendants under a non-descendant parent works.

    Tree before:
        S1
          ├── A
              └── A1
        S2

    Move A under S2 — A1 comes along implicitly. Expected to succeed
    because S2 is not in A's descendant set.
    """
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    s1 = await _add_position(shared_client, shared_auth, boq_id, ordinal="06.001")
    s2 = await _add_position(shared_client, shared_auth, boq_id, ordinal="06.002")
    a = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="06.001.01", parent_id=s1["id"]
    )
    a1 = await _add_position(
        shared_client, shared_auth, boq_id, ordinal="06.001.01.01", parent_id=a["id"]
    )

    resp = await shared_client.patch(
        f"/api/v1/boq/positions/{a['id']}",
        json={"parent_id": s2["id"]},
        headers=shared_auth,
    )
    assert resp.status_code == 200, f"Subtree move failed: {resp.status_code} {resp.text}"
    assert resp.json()["parent_id"] == s2["id"]

    # Sanity: A1 still hangs off A (parent did not change).
    resp = await shared_client.get(f"/api/v1/boq/boqs/{boq_id}", headers=shared_auth)
    assert resp.status_code == 200
    by_id = {p["id"]: p for p in resp.json()["positions"]}
    assert by_id[a1["id"]]["parent_id"] == a["id"]


@pytest.mark.asyncio
async def test_create_with_self_referencing_parent_id_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Creating a position whose parent_id refers to a non-existent UUID
    (which the client also intends to be its own id) is rejected at the
    create path. The server allocates the row's UUID server-side, so the
    most realistic surface for this bug on create is "parent_id pointing
    at a position that does not exist" — which the cycle-guard also
    catches and turns into a clean 400 instead of an opaque 500."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    bogus_parent = str(uuid.uuid4())
    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "07.001",
            "description": "self-ref attempt",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
            "parent_id": bogus_parent,
        },
        headers=shared_auth,
    )
    # BUG-CYCLE02: invalid ``parent_id`` (non-existent UUID) is a 422
    # structural validation failure, not a 400 domain conflict.
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "does not exist" in resp.text.lower() or "parent" in resp.text.lower()


@pytest.mark.asyncio
async def test_create_with_cross_boq_parent_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Creating a position whose parent_id points into a different BOQ is rejected."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_a = await _create_boq(shared_client, shared_auth, project_id)
    boq_b = await _create_boq(shared_client, shared_auth, project_id)

    pos_b = await _add_position(shared_client, shared_auth, boq_b, ordinal="08.001")

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_a}/positions/",
        json={
            "boq_id": boq_a,
            "ordinal": "08.001",
            "description": "cross-boq parent attempt",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
            "parent_id": pos_b["id"],
        },
        headers=shared_auth,
    )
    # BUG-CYCLE02: cross-BOQ parent on create returns 422 (structural).
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "different boq" in resp.text.lower() or "cross-boq" in resp.text.lower()
