# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Restructure and set_rate stay inside the caller's project (issue 554).

A viewer holds ``boq.update`` but is neither owner nor member of the owner's
project, so only the owner gate stands between them and the bill. The owner
restructures a bill over HTTP and the figures do not move.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_restructure_authz.py -q
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces this suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the ai_estimator + costs
# IDOR baselines).
import app.modules.ai_estimator.models  # noqa: E402,F401
import app.modules.boq.models  # noqa: E402,F401
import app.modules.costs.models  # noqa: E402,F401
import app.modules.projects.models  # noqa: E402,F401
import app.modules.teams.models  # noqa: E402,F401
import app.modules.users.models  # noqa: E402,F401

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# Statuses that count as "denied" for an outsider. 403 is what the BOQ owner
# gate raises for an authenticated non-owner; 404 is accepted because some
# guards prefer to keep the id's existence opaque.
DENIED = (403, 404)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module and create all tables.

    The lifespan runs the module loader's on_startup hooks, which register the
    boq + ai_estimator permissions and validation rules.
    """
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so login works regardless of registration mode."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_login(
    client: AsyncClient,
    *,
    tenant: str,
    role: str | None = None,
) -> tuple[str, str, dict[str, str]]:
    """Register, activate, optionally promote, log in.

    Returns ``(user_id, email, auth_headers)``. When ``role`` is None the user
    keeps the default registration role (``viewer`` under the open-registration
    test mode) - that is what the outsider needs to still hold ``boq.read`` /
    ``boq.update`` while failing the owner gate.
    """
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@boq-authz.io"
    password = f"BoqAuthz{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    if role is not None:
        from sqlalchemy import update

        from app.database import async_session_factory
        from app.modules.users.models import User

        async with async_session_factory() as s:
            await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
            await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def owner_a(http_client):
    """Owner A - admin so they can create projects/BOQs/positions."""
    uid, email, headers = await _register_login(http_client, tenant="owner-a", role="admin")
    return {"user_id": uid, "email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def outsider_b(http_client):
    """Outsider B - a default viewer with no relationship to A's project.

    A viewer still holds boq.read / boq.update (granted to VIEWER by the boq
    module), so B passes the RequirePermission gate and is rejected purely by
    the cross-tenant owner gate.
    """
    uid, email, headers = await _register_login(http_client, tenant="outsider-b", role=None)
    return {"user_id": uid, "email": email, "headers": headers}


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"AuthzProj {uuid.uuid4().hex[:6]}",
            "description": "BOQ cross-tenant authz regression",
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
            "name": f"AuthzBOQ {uuid.uuid4().hex[:6]}",
            "description": "BOQ cross-tenant authz regression",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    headers: dict[str, str],
    boq_id: str,
    *,
    description: str = "RC wall C30/37",
    ordinal: str = "0010",
) -> str:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": ordinal,
            "description": description,
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 185.0,
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"add position failed: {resp.text}"
    return resp.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def a_boq(http_client, owner_a):
    """A project + BOQ + one position, all owned by A. Module-scoped: the owner
    gate is read-only for these resources so all cases can share one fixture."""
    project_id = await _create_project(http_client, owner_a["headers"])
    boq_id = await _create_boq(http_client, owner_a["headers"], project_id)
    position_id = await _add_position(http_client, owner_a["headers"], boq_id)
    return {"project_id": project_id, "boq_id": boq_id, "position_id": position_id}


def _positions_url(boq_id: str, suffix: str) -> str:
    return f"/api/v1/boq/boqs/{boq_id}/positions/{suffix}"


async def _bill_rows(client: AsyncClient, headers: dict[str, str], boq_id: str) -> list[dict]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["positions"]


@pytest.mark.asyncio
async def test_owner_restructures_a_bill_and_the_figures_do_not_move(http_client, owner_a):
    from decimal import Decimal

    h = owner_a["headers"]
    boq_id = await _create_boq(http_client, h, await _create_project(http_client, h))
    chapter = await _add_position(http_client, h, boq_id, description="Gros oeuvre", ordinal="1")
    line = await _add_position(http_client, h, boq_id, description="Beton", ordinal="1.1")
    before = {r["id"]: Decimal(str(r["total"])) for r in await _bill_rows(http_client, h, boq_id)}
    resp = await http_client.post(
        _positions_url(boq_id, "restructure/"),
        json={"rows": [{"position_id": chapter, "level": 1}, {"position_id": line, "level": 0}]},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sections"] == 1 and resp.json()["converted_to_section"] == 1
    after = {r["id"]: r for r in await _bill_rows(http_client, h, boq_id)}
    assert Decimal(str(after[line]["total"])) == before[line]
    assert after[line]["parent_id"] == chapter
    assert Decimal(str(after[chapter]["total"])) == 0


@pytest.mark.asyncio
async def test_outsider_cannot_restructure_the_owners_bill(http_client, a_boq, outsider_b):
    resp = await http_client.post(
        _positions_url(a_boq["boq_id"], "restructure/"),
        json={"rows": [{"position_id": a_boq["position_id"], "level": 1}]},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, resp.text


@pytest.mark.asyncio
async def test_outsider_cannot_set_a_rate_on_the_owners_bill(http_client, owner_a, a_boq, outsider_b):
    resp = await http_client.patch(
        _positions_url(a_boq["boq_id"], "bulk-update/"),
        json={"ids": [a_boq["position_id"]], "set_rate": "1"},
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, resp.text
    row = next(
        r for r in await _bill_rows(http_client, owner_a["headers"], a_boq["boq_id"]) if r["id"] == a_boq["position_id"]
    )
    assert float(row["unit_rate"]) == 185.0
    assert row["unit"] == "m3"


@pytest.mark.asyncio
async def test_outsider_own_bill_cannot_reach_the_owners_rows(http_client, a_boq, outsider_b):
    """The outsider's own bill is open to them, yet rows of A's bill are not theirs to move."""
    me = outsider_b["headers"]
    mine = await _create_boq(http_client, me, await _create_project(http_client, me))
    resp = await http_client.post(
        _positions_url(mine, "restructure/"),
        json={"rows": [{"position_id": a_boq["position_id"], "level": 1}]},
        headers=me,
    )
    assert resp.status_code in (403, 404, 422), resp.text
    resp = await http_client.patch(
        _positions_url(mine, "bulk-update/"),
        json={"ids": [a_boq["position_id"]], "set_rate": "1"},
        headers=me,
    )
    assert resp.status_code in (403, 404, 422) or resp.json().get("updated") == 0, resp.text


@pytest.mark.asyncio
async def test_unauthenticated_calls_are_refused(http_client, a_boq):
    resp = await http_client.post(
        _positions_url(a_boq["boq_id"], "restructure/"),
        json={"rows": [{"position_id": a_boq["position_id"], "level": 1}]},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_restructure_of_an_unknown_bill_is_404(http_client, owner_a):
    resp = await http_client.post(
        _positions_url(str(uuid.uuid4()), "restructure/"),
        json={"rows": [{"position_id": str(uuid.uuid4()), "level": 1}]},
        headers=owner_a["headers"],
    )
    assert resp.status_code == 404
