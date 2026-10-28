"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Issue #347 - BIM quantity links must resolve against their OWN model.

A project can hold several BIM models. The BOQ grid "pick quantity from BIM"
picker used to resolve EVERY position against one project-level "first ready"
model, so a position whose elements belong to a DIFFERENT model resolved to
nothing (DB-UUID ids -> "not found") or to the wrong element (stable_ids are
unique only per model -> a silent wrong quantity).

The fix records the owning model on the position (``Position.cad_model_id``)
when the link is created, and the picker resolves against that instead of the
project-level fallback. These tests drive the real HTTP surface:

* link a position to an element in the SECOND (non-first) model and assert the
  position now carries that model's id in ``cad_model_id`` (surfaced on the
  BOQ fetch);
* the by-ids element endpoint scoped to the OWNING model returns the element
  (the picker's happy path), while the same lookup scoped to the FIRST model -
  what the buggy code used - returns nothing.

Test isolation mirrors the sibling BOQ/BIM integration tests: the per-session
PostgreSQL database + eager model registration come from
``backend/tests/conftest.py``; the ``cad_model_id`` column is created by
``create_all`` (the model is the schema source of truth), so no
``alembic upgrade`` is needed here.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_bim_multimodel_link.py -v --tb=short
"""

from __future__ import annotations

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
    email = f"mm347-{unique}@test.io"
    password = f"MM347{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Multi-Model Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"MM347 {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": f"BOQ {uuid.uuid4().hex[:6]}"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_position(client: AsyncClient, auth: dict[str, str], boq_id: str, **body) -> dict:
    payload = {"boq_id": boq_id, "unit": "m2", "quantity": 0.0, "unit_rate": 0.0}
    payload.update(body)
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json=payload, headers=auth)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_model(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    version: str,
    elements: list[dict],
) -> tuple[str, list[dict]]:
    """Create a ready BIMModel + elements, return (model_id, element_rows)."""
    m = await client.post(
        "/api/v1/bim_hub/",
        json={"project_id": project_id, "name": f"Model v{version}", "version": version, "status": "ready"},
        headers=auth,
    )
    assert m.status_code == 201, m.text
    model_id = m.json()["id"]

    e = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/",
        json={"elements": elements},
        headers=auth,
    )
    assert e.status_code == 201, e.text
    return model_id, e.json()["items"]


async def _get_position(client: AsyncClient, auth: dict[str, str], boq_id: str, pos_id: str) -> dict:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    return next(p for p in resp.json()["positions"] if p["id"] == pos_id)


async def _elements_by_ids(
    client: AsyncClient, auth: dict[str, str], model_id: str, element_ids: list[str]
) -> list[dict]:
    resp = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/by-ids/",
        json={"element_ids": element_ids},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_link_to_second_model_stamps_cad_model_id(client: AsyncClient, auth: dict[str, str]) -> None:
    """Linking a position to an element in the NON-first model binds the
    position to THAT model, and the by-ids lookup only resolves there."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    # Model A is created FIRST (it would be the buggy "first ready" pick).
    model_a, _elems_a = await _create_model(
        client,
        auth,
        project_id,
        version="1",
        elements=[{"stable_id": "A1", "element_type": "wall", "quantities": {"area_m2": 11.0}}],
    )
    # Model B is the SECOND model and owns the element we link to.
    model_b, elems_b = await _create_model(
        client,
        auth,
        project_id,
        version="2",
        elements=[{"stable_id": "B1", "element_type": "slab", "quantities": {"area_m2": 42.0}}],
    )
    assert model_a != model_b
    elem_b_id = elems_b[0]["id"]

    pos = await _add_position(client, auth, boq_id, ordinal="01.001", description="Slab", unit="m2")
    pos_id = pos["id"]
    # Fresh manual position: no owning model yet -> fallback semantics.
    assert pos.get("cad_model_id") is None

    # Link the position to model B's element (the dominant create_link path).
    link = await client.post(
        "/api/v1/bim_hub/links/",
        json={"boq_position_id": pos_id, "bim_element_id": elem_b_id},
        headers=auth,
    )
    assert link.status_code == 201, link.text

    # The position now owns model B, surfaced on the BOQ fetch, and mirrors the
    # element id into cad_element_ids.
    fresh = await _get_position(client, auth, boq_id, pos_id)
    assert fresh["cad_model_id"] == model_b, f"expected owning model {model_b}, got {fresh.get('cad_model_id')}"
    assert elem_b_id in fresh["cad_element_ids"]

    # Picker happy path: resolving the linked id against the OWNING model
    # returns the element with its quantity.
    matched = await _elements_by_ids(client, auth, model_b, [elem_b_id])
    assert len(matched) == 1
    assert matched[0]["id"] == elem_b_id
    assert float(matched[0]["quantities"]["area_m2"]) == 42.0

    # The pre-fix behaviour resolved against the FIRST model (A). That lookup
    # finds nothing - which is exactly the "quantity silently unavailable" bug.
    assert await _elements_by_ids(client, auth, model_a, [elem_b_id]) == []


@pytest.mark.asyncio
async def test_first_link_wins_when_relinking(client: AsyncClient, auth: dict[str, str]) -> None:
    """The owning model is stamped on the first link and is not clobbered by a
    later link to another element in the SAME model."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    model_id, elems = await _create_model(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "W1", "element_type": "wall", "quantities": {"area_m2": 5.0}},
            {"stable_id": "W2", "element_type": "wall", "quantities": {"area_m2": 7.0}},
        ],
    )
    pos = await _add_position(client, auth, boq_id, ordinal="02.001", description="Walls", unit="m2")
    pos_id = pos["id"]

    for elem in elems:
        r = await client.post(
            "/api/v1/bim_hub/links/",
            json={"boq_position_id": pos_id, "bim_element_id": elem["id"]},
            headers=auth,
        )
        assert r.status_code == 201, r.text

    fresh = await _get_position(client, auth, boq_id, pos_id)
    assert fresh["cad_model_id"] == model_id
    assert len(fresh["cad_element_ids"]) == 2
