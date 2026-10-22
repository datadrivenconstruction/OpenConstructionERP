"""Phase 4 - per-element ERP context endpoint.

``GET /api/v1/bim_hub/elements/{element_id}/context`` composes, on demand,
everything the platform knows about one selected model element: its linked
BOQ position (with cost), documents, tasks, schedule activities,
requirements, validation and install/progress. The 3D viewer loads elements
in skeleton mode for speed and calls this only when an element is clicked, so
the panel populates without paying the enrichment cost on the bulk load.

These tests drive the full app through HTTP (same pattern and isolation as
``test_boq_quantity_links_and_compare.py``): the per-session PostgreSQL
database, eager model registration and the synchronous event-bus shim come
from ``backend/tests/conftest.py``; the production database is never touched.

Run:
    cd backend
    python -m pytest tests/integration/test_bim_element_context.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    """Module-scoped client driving the full app lifecycle (creates tables)."""
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
async def auth(client: AsyncClient) -> dict[str, str]:
    """Register + force-promote-to-admin + login -> bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"ectx-{unique}@test.io"
    password = f"Ectx{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Element Context Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in str(data.get("detail", "")):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"Ectx {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": f"Ectx BOQ {uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(client: AsyncClient, auth: dict[str, str], boq_id: str, **body) -> dict:
    payload = {"boq_id": boq_id, "unit": "m3", "quantity": 0.0}
    payload.update(body)
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json=payload, headers=auth)
    assert resp.status_code == 201, f"Add position failed: {resp.text}"
    return resp.json()


async def _create_model_with_element(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    stable_id: str,
    element_type: str = "slab",
) -> tuple[str, str]:
    """Create a BIMModel + one element; return (model_id, element_id)."""
    m = await client.post(
        "/api/v1/bim_hub/",
        json={"project_id": project_id, "name": "Ctx Model", "version": "1", "status": "ready"},
        headers=auth,
    )
    assert m.status_code == 201, f"Create model failed: {m.text}"
    model_id = m.json()["id"]

    e = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/",
        json={"elements": [{"stable_id": stable_id, "element_type": element_type, "quantities": {"volume_m3": 6.0}}]},
        headers=auth,
    )
    assert e.status_code == 201, f"Bulk import elements failed: {e.text}"

    listed = await client.get(
        f"/api/v1/bim_hub/models/{model_id}/elements/?skeleton=true",
        headers=auth,
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "expected one persisted element"
    return model_id, items[0]["id"]


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_element_context_composes_boq_link_with_cost(client: AsyncClient, auth: dict[str, str]) -> None:
    """The context endpoint returns the element's BOQ link with cost fields."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.001",
        description="RC slab from model",
        unit="m3",
        quantity=10.0,
        unit_rate=185.0,
    )
    model_id, element_id = await _create_model_with_element(client, auth, project_id, stable_id="S1")

    link = await client.post(
        "/api/v1/bim_hub/links/",
        json={"boq_position_id": pos["id"], "bim_element_id": element_id, "link_type": "manual"},
        headers=auth,
    )
    assert link.status_code == 201, link.text

    ctx = await client.get(f"/api/v1/bim_hub/elements/{element_id}/context", headers=auth)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()

    # One BOQ link, carrying the position identity AND its cost.
    assert len(body["boq_links"]) == 1
    brief = body["boq_links"][0]
    assert brief["boq_position_ordinal"] == "01.001"
    assert brief["boq_position_description"] == "RC slab from model"
    assert float(brief["boq_position_unit_rate"]) == 185.0
    # Linking a BIM element auto-syncs the position quantity from the element
    # (volume_m3=6.0 here), so assert the cost is internally consistent rather
    # than pinning the pre-link total: total == unit_rate * quantity.
    assert brief["boq_position_total"] is not None
    assert float(brief["boq_position_total"]) == pytest.approx(
        float(brief["boq_position_unit_rate"]) * float(brief["boq_position_quantity"])
    )

    # The other context arrays are present (empty here) so the card can render
    # every section without a second round trip or null-guards.
    assert body["linked_documents"] == []
    assert body["linked_tasks"] == []
    assert body["linked_activities"] == []
    assert body["linked_requirements"] == []
    # Element import auto-runs the validation pipeline, so a model report may
    # exist; either way this element carries no findings, so its status is one
    # of the two "no issues" values ('pass' if a report ran, else 'unchecked').
    assert body["validation_status"] in ("pass", "unchecked")


@pytest.mark.asyncio
async def test_element_context_404_for_unknown_element(client: AsyncClient, auth: dict[str, str]) -> None:
    """An unknown element id is a clean 404, not a 500."""
    missing = uuid.uuid4()
    r = await client.get(f"/api/v1/bim_hub/elements/{missing}/context", headers=auth)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_element_context_empty_when_no_links(client: AsyncClient, auth: dict[str, str]) -> None:
    """A freshly imported element with no links returns empty context arrays."""
    project_id = await _create_project(client, auth)
    _model_id, element_id = await _create_model_with_element(client, auth, project_id, stable_id="LONE")

    ctx = await client.get(f"/api/v1/bim_hub/elements/{element_id}/context", headers=auth)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["id"] == element_id
    assert body["boq_links"] == []
    assert body["linked_documents"] == []
    assert body["linked_tasks"] == []
    assert body["linked_activities"] == []
    assert body["linked_requirements"] == []


@pytest.mark.asyncio
async def test_the_skeleton_listing_keeps_quantities_and_category(client: AsyncClient, auth: dict[str, str]) -> None:
    """The filter panel sums and exports what the skeleton listing carries."""
    project_id = await _create_project(client, auth)
    m = await client.post(
        "/api/v1/bim_hub/",
        json={"project_id": project_id, "name": "Skel Model", "version": "1", "status": "ready"},
        headers=auth,
    )
    model_id = m.json()["id"]
    body = {
        "elements": [
            {
                "stable_id": "w1",
                "element_type": "Walls",
                "properties": {
                    "category": "OST_Walls",
                    "comments": "long text",
                    "Family": "Basic Wall",
                    "Material": "Brick",
                },
                "quantities": {"Volume": 2.5},
            }
        ]
    }
    e = await client.post(f"/api/v1/bim_hub/models/{model_id}/elements/", json=body, headers=auth)
    assert e.status_code == 201, e.text

    listed = await client.get(f"/api/v1/bim_hub/models/{model_id}/elements/?skeleton=true", headers=auth)
    (row,) = listed.json()["items"]
    assert row["quantities"] == {"Volume": 2.5}
    # Grouping properties survive the skinny listing, free text does not.
    assert row["properties"] == {"category": "OST_Walls", "Family": "Basic Wall", "Material": "Brick"}

    full = await client.get(
        f"/api/v1/bim_hub/models/{model_id}/elements/?skeleton=true&include_properties=true", headers=auth
    )
    assert full.json()["items"][0]["properties"]["comments"] == "long text"
