# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Equipment rental routes that name a project check the caller may open it.

The fleet is shared, rentals are not: each rental bills a machine to one
project. ``GET /rentals/?project_id=``, ``POST /rentals/`` and the per-project
cost summary took any project id and never asked whether the caller could
open that project, so a reader of one project could list another project's
rentals and rates, and an editor could bill a machine to a project they do
not belong to.

B is a manager, not an admin, so the admin bypass cannot stand in for the
check, and B's own project is the control that the routes still work.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

EQUIPMENT = "/api/v1/equipment"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.equipment import models as _equipment_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_user_fields(email: str, **values) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()


async def _register_login_and_promote(
    client: AsyncClient,
    *,
    tenant: str,
    role: str,
) -> dict[str, str]:
    """Register a user, activate it, promote it, return its auth headers."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@rental-idor.io"
    password = f"RentIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text

    await _set_user_fields(email, is_active=True, role=role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_project_with_rental(
    client: AsyncClient,
    headers: dict[str, str],
    label: str,
) -> dict[str, str]:
    """A project, a machine and one rental of it to the project, all made by ``headers``."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Rent-{label} {uuid.uuid4().hex[:6]}",
            "description": f"owned by {label}, used by the rental IDOR suite",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    eq = await client.post(
        f"{EQUIPMENT}/equipment/",
        json={"code": f"EQ-{uuid.uuid4().hex[:6].upper()}", "name": f"{label} excavator"},
        headers=headers,
    )
    assert eq.status_code == 201, eq.text
    equipment_id = eq.json()["id"]

    rental = await client.post(
        f"{EQUIPMENT}/rentals/",
        json={
            "equipment_id": equipment_id,
            "project_id": project_id,
            "start_date": "2027-06-01",
            "internal_rate_per_day": "450.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert rental.status_code == 201, rental.text
    return {"project_id": project_id, "equipment_id": equipment_id, "rental_id": rental.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a rented machine on its project; B is a manager with its own."""
    a_headers = await _register_login_and_promote(http_client, tenant="a", role="admin")
    # A manager clears every equipment permission used here and misses the
    # admin bypass inside ``verify_project_access``.
    b_headers = await _register_login_and_promote(http_client, tenant="b", role="manager")

    a_rows = await _make_project_with_rental(http_client, a_headers, "A")
    b_rows = await _make_project_with_rental(http_client, b_headers, "B")

    return {"a": {"headers": a_headers, **a_rows}, "b": {"headers": b_headers, **b_rows}}


@pytest.mark.asyncio
async def test_b_cannot_list_the_rentals_of_a_project(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.get(f"{EQUIPMENT}/rentals/", params={"project_id": a["project_id"]}, headers=b["headers"])
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_b_cannot_read_a_machine_cost_for_a_project(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.get(
        f"{EQUIPMENT}/equipment/{a['equipment_id']}/cost-summary",
        params={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_b_cannot_bill_a_machine_to_a_project(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.post(
        f"{EQUIPMENT}/rentals/",
        json={
            "equipment_id": b["equipment_id"],
            "project_id": a["project_id"],
            "start_date": "2027-07-01",
            "internal_rate_per_day": "1.00",
            "currency": "EUR",
        },
        headers=b["headers"],
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_b_still_lists_and_costs_its_own_project(http_client, two_tenants):
    b = two_tenants["b"]
    listed = await http_client.get(
        f"{EQUIPMENT}/rentals/", params={"project_id": b["project_id"]}, headers=b["headers"]
    )
    assert listed.status_code == 200, listed.text
    assert b["rental_id"] in {r["id"] for r in listed.json()}

    cost = await http_client.get(
        f"{EQUIPMENT}/equipment/{b['equipment_id']}/cost-summary",
        params={"project_id": b["project_id"]},
        headers=b["headers"],
    )
    assert cost.status_code == 200, cost.text


@pytest.mark.asyncio
async def test_the_unfiltered_rental_list_shows_only_reachable_projects(http_client, two_tenants):
    """Without ``project_id`` the list spanned every project; it now spans the caller's."""
    a, b = two_tenants["a"], two_tenants["b"]
    as_b = await http_client.get(f"{EQUIPMENT}/rentals/", params={"limit": 500}, headers=b["headers"])
    assert as_b.status_code == 200, as_b.text
    ids = {r["id"] for r in as_b.json()}
    assert a["rental_id"] not in ids
    assert b["rental_id"] in ids

    as_admin = await http_client.get(f"{EQUIPMENT}/rentals/", params={"limit": 500}, headers=a["headers"])
    assert as_admin.status_code == 200, as_admin.text
    admin_ids = {r["id"] for r in as_admin.json()}
    assert {a["rental_id"], b["rental_id"]} <= admin_ids
