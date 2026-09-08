# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Resource-depth curve IDOR suite: the assignment-keyed curve routes.

An assignment's spreading curve hangs off the assignment, and the assignment
hangs off a project. The assignment routes themselves resolve that project and
run it through ``verify_project_access`` before touching the row, and so does
the ``/units`` setter that lives next to the curve routes. The three curve
routes did not:

* ``GET    /assignments/{id}/curve`` - read another project's curve.
* ``PUT    /assignments/{id}/curve`` - replace another project's curve.
* ``DELETE /assignments/{id}/curve`` - drop it.

Each enforced the caller's role and nothing about whose project the assignment
belonged to, so any authenticated reader could read a curve by its assignment
id and any editor could rewrite one. Row level security is a deliberate no-op
in this product, so ``verify_project_access`` is the only boundary between
projects and its absence was the whole hole.

Two ways a suite like this reads green while proving nothing, both addressed
below:

* **The attacker is under-privileged.** B is a *manager*: it outranks
  ``resources.read`` and ``resources.update``, so each probe reaches the
  project check instead of stopping at ``RequirePermission``, and it is not
  an admin, so the admin bypass inside ``verify_project_access`` cannot stand
  in for the guard being measured.
* **The route is not mounted.** 404 is both the expected cross-project answer
  and what a mis-typed prefix returns. Every fixed route therefore also
  carries an owner-success control at the bottom of the file, run by B
  against B's own assignment so it exercises the non-admin owner path.

Convention (matches the rest of the IDOR sweep): cross-project access returns
403/404, never 2xx, so no endpoint becomes a UUID-existence oracle.

Scaffolding mirrors ``test_resources_idor.py``: the suite runs on the
PostgreSQL cluster provisioned by ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

RESOURCES = "/api/v1/resources"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.resources import models as _resources_models  # noqa: F401
        from app.modules.resources import resource_depth_models as _depth_models  # noqa: F401

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@curve-idor.io"
    password = f"CurveIdor{uuid.uuid4().hex[:6]}9"

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


async def _make_project_with_assignment(
    client: AsyncClient,
    headers: dict[str, str],
    label: str,
) -> str:
    """A project, a resource homed on it and one assignment, all owned by ``headers``."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Curve-{label} {uuid.uuid4().hex[:6]}",
            "description": f"owned by {label}, used by the curve IDOR suite",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    res = await client.post(
        f"{RESOURCES}/resources/",
        json={
            "code": f"RES-{uuid.uuid4().hex[:6].upper()}",
            "name": f"{label} crane crew",
            "resource_type": "person",
            "home_project_id": project_id,
            "default_cost_rate": "75.00",
            "currency": "EUR",
            "status": "active",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text

    assign = await client.post(
        f"{RESOURCES}/assignments/",
        json={
            "resource_id": res.json()["id"],
            "project_id": project_id,
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "allocation_percent": 100,
            "status": "proposed",
        },
        headers=headers,
    )
    assert assign.status_code == 201, assign.text
    return assign.json()["id"]


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns an assignment; B is a manager with an assignment of its own."""
    a_headers = await _register_login_and_promote(http_client, tenant="a", role="admin")
    # B is a manager, not an admin: it clears ``resources.read`` and
    # ``resources.update`` so every probe reaches the project check, and it
    # misses the admin bypass inside ``verify_project_access``.
    b_headers = await _register_login_and_promote(http_client, tenant="b", role="manager")

    a_assignment = await _make_project_with_assignment(http_client, a_headers, "A")
    b_assignment = await _make_project_with_assignment(http_client, b_headers, "B")

    return {
        "a": {"headers": a_headers, "assignment_id": a_assignment},
        "b": {"headers": b_headers, "assignment_id": b_assignment},
    }


# ── Row builders ───────────────────────────────────────────────────────────

# A curve that cannot be mistaken for the default: the ``flat`` default is what
# a freshly replaced curve would also carry, so a probe that succeeded by
# overwriting A's curve with the default could hide behind "unchanged".
_A_CURVE = {"curve_type": "bell", "manual_weights": [0.1, 0.2, 0.4, 0.2, 0.1]}


async def _put_curve(client: AsyncClient, headers: dict[str, str], assignment_id: str, body: dict) -> dict:
    resp = await client.put(f"{RESOURCES}/assignments/{assignment_id}/curve", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _read_curve(client: AsyncClient, headers: dict[str, str], assignment_id: str) -> dict:
    resp = await client.get(f"{RESOURCES}/assignments/{assignment_id}/curve", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Cross-project vectors ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_b_cannot_read_a_curve_of_a(http_client, two_tenants):
    """``GET /assignments/{id}/curve`` must not hand B the row A wrote."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    await _put_curve(http_client, a["headers"], a["assignment_id"], _A_CURVE)

    resp = await http_client.get(f"{RESOURCES}/assignments/{a['assignment_id']}/curve", headers=b["headers"])
    assert resp.status_code in (403, 404), f"LEAK: B read A's curve: {resp.status_code} {resp.text!r}"
    assert "bell" not in resp.text


@pytest.mark.asyncio
async def test_b_cannot_replace_a_curve_of_a(http_client, two_tenants):
    """``PUT /assignments/{id}/curve`` must not rewrite A's curve."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    await _put_curve(http_client, a["headers"], a["assignment_id"], _A_CURVE)

    resp = await http_client.put(
        f"{RESOURCES}/assignments/{a['assignment_id']}/curve",
        json={"curve_type": "front_load", "manual_weights": []},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B replaced A's curve: {resp.status_code} {resp.text!r}"

    after = await _read_curve(http_client, a["headers"], a["assignment_id"])
    assert after["curve_type"] == "bell", f"A's curve was rewritten by B: {after}"
    assert after["manual_weights"] == _A_CURVE["manual_weights"]


@pytest.mark.asyncio
async def test_b_cannot_delete_a_curve_of_a(http_client, two_tenants):
    """``DELETE /assignments/{id}/curve`` must not drop A's curve."""
    a = two_tenants["a"]
    b = two_tenants["b"]
    await _put_curve(http_client, a["headers"], a["assignment_id"], _A_CURVE)

    resp = await http_client.delete(f"{RESOURCES}/assignments/{a['assignment_id']}/curve", headers=b["headers"])
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B deleted A's curve: {resp.status_code} {resp.text!r}"

    after = await _read_curve(http_client, a["headers"], a["assignment_id"])
    assert after["curve_type"] == "bell", f"A's curve is gone or changed: {after}"


# ── Owner controls: every fixed route still works for its own project ──────
#
# These run as B, a plain manager on a project it owns, so they walk the owner
# branch of ``verify_project_access`` rather than the admin bypass. Without
# them a mis-typed prefix would answer 404 to every probe above and the whole
# suite would read as a pass.


@pytest.mark.asyncio
async def test_owner_can_set_read_and_delete_its_own_curve(http_client, two_tenants):
    b = two_tenants["b"]

    written = await _put_curve(
        http_client,
        b["headers"],
        b["assignment_id"],
        {"curve_type": "back_load", "manual_weights": []},
    )
    assert written["curve_type"] == "back_load"
    assert written["assignment_id"] == b["assignment_id"]

    read = await _read_curve(http_client, b["headers"], b["assignment_id"])
    assert read["curve_type"] == "back_load"

    deleted = await http_client.delete(f"{RESOURCES}/assignments/{b['assignment_id']}/curve", headers=b["headers"])
    assert deleted.status_code == 204, deleted.text

    gone = await http_client.get(f"{RESOURCES}/assignments/{b['assignment_id']}/curve", headers=b["headers"])
    assert gone.status_code == 404, gone.text
