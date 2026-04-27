"""HTTP roundtrip: BIM picker payload must preserve bim_qty_source.

Regression: when the BIM Quantity picker sends ``{quantity, metadata: {
bim_qty_source: ...}}`` in a single PATCH, the backend was stripping the
``bim_qty_source`` key on the same request that set it — so the icon and
param-name display in the BOQ grid would briefly appear via the
optimistic cache write, then vanish when the server response replaced
the cache.

Fix lives in ``BOQService.update_position`` — the strip pass now skips
link keys explicitly present in incoming metadata.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def shared_client():
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
async def auth_headers(shared_client: AsyncClient) -> dict[str, str]:
    """Register + promote-to-admin + login. Mirrors test_boq_cycle_detection."""
    unique = uuid.uuid4().hex[:8]
    email = f"bimqs-{unique}@test.io"
    password = f"BimQs{unique}9!"
    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "BIM Qty Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

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

    login = await shared_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_bim_picker_preserves_bim_qty_source_through_patch(
    shared_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """The picker's PATCH `{quantity, metadata: {bim_qty_source}}` round-trips
    cleanly: the GET after the PATCH must still report bim_qty_source."""
    proj = await shared_client.post(
        "/api/v1/projects/",
        json={"name": "BIM Qty Source Roundtrip"},
        headers=auth_headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    boq = await shared_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "B"},
        headers=auth_headers,
    )
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]

    pos = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Wall",
            "unit": "m2",
            "quantity": 0,
            "unit_rate": 0,
        },
        headers=auth_headers,
    )
    assert pos.status_code in (200, 201), pos.text
    position_id = pos.json()["id"]

    patch = await shared_client.patch(
        f"/api/v1/boq/positions/{position_id}",
        json={
            "quantity": 42.5,
            "metadata": {"bim_qty_source": "BIM: Wall / Area"},
        },
        headers=auth_headers,
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["metadata"].get("bim_qty_source") == "BIM: Wall / Area", (
        f"PATCH response stripped bim_qty_source: metadata={body['metadata']}"
    )

    get = await shared_client.get(
        f"/api/v1/boq/positions/{position_id}", headers=auth_headers
    )
    assert get.status_code == 200, get.text
    fresh = get.json()
    assert fresh["metadata"].get("bim_qty_source") == "BIM: Wall / Area", (
        f"GET after PATCH lost bim_qty_source: metadata={fresh['metadata']}"
    )


@pytest.mark.asyncio
async def test_manual_quantity_edit_strips_existing_bim_qty_source(
    shared_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """A pure quantity edit (no metadata payload) still drops the existing
    bim_qty_source — manual override semantics for hand edits stay intact."""
    proj = await shared_client.post(
        "/api/v1/projects/",
        json={"name": "Manual Override Roundtrip"},
        headers=auth_headers,
    )
    project_id = proj.json()["id"]
    boq = await shared_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "B"},
        headers=auth_headers,
    )
    boq_id = boq.json()["id"]
    pos = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.002",
            "description": "Wall",
            "unit": "m2",
            "quantity": 10,
            "unit_rate": 50,
            "metadata": {"bim_qty_source": "BIM: Wall / Area"},
        },
        headers=auth_headers,
    )
    position_id = pos.json()["id"]

    patch = await shared_client.patch(
        f"/api/v1/boq/positions/{position_id}",
        json={"quantity": 99.0},  # NO metadata in payload
        headers=auth_headers,
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert "bim_qty_source" not in body["metadata"], (
        "Pure quantity edit must strip existing bim_qty_source — got: "
        f"{body['metadata']}"
    )
