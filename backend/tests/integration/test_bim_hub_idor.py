"""BIM Hub IDOR / authorization audit (v8.8.3 hardening - findings #12, #13).

Two confirmed cross-tenant defects in ``app.modules.bim_hub.router`` are
pinned here:

#12  ``GET /api/v1/bim-hub/quantity-maps/`` used ``qmap_repo.list_all()`` -
     a bare ``SELECT * FROM oe_bim_quantity_map`` with NO project / org
     filter - so any ``bim.read`` user could enumerate every other tenant's
     project-scoped quantity-mapping rules (their costing/takeoff logic).
     The fix scopes the list to the caller's ``accessible_project_ids`` while
     keeping ``project_id IS NULL`` global templates visible to everyone.
     The same bypass on ``PATCH /quantity-maps/{id}`` for a global
     (``project_id IS NULL``) rule - mutable by ANY ``bim.update`` user - is
     closed by requiring admin for the global case.

#13  ``POST /api/v1/bim-hub/cleanup-orphans/`` is a GLOBAL, cross-tenant
     filesystem sweep (it loads every model id in the deployment and
     ``rmtree``s any unmatched model dir under ``data/bim/``). It was gated
     at ``RequirePermission("bim.delete")`` (Role.MANAGER); a project-level
     MANAGER in one tenant could wipe another tenant's geometry. The fix
     gates it on ``RequireRole("admin")``, matching clear-database /
     demo-reset.

Tenant A is an admin (owns a project, seeds quantity-map rows, and is the
only role allowed to run cleanup-orphans). Tenant B is promoted to MANAGER -
deliberately the strongest non-admin role: it HOLDS ``bim.read`` /
``bim.update`` / ``bim.delete``, so every assertion below proves the
*authorization* guard, not merely an RBAC permission gate.

Mirrors the structure of ``test_costs_idor.py`` (register/activate/login real
users over HTTP, promote roles via a direct DB write, seed rows via the DB).
The BIM Hub router is auto-mounted by the module loader at the kebab-case
prefix ``/api/v1/bim-hub`` (legacy mirror ``/api/v1/bim_hub``).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once per module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim_models  # noqa: F401
        from app.modules.projects import models as _project_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, *, role: str) -> None:
    """Force ``role`` and ``is_active=True`` on a user via a direct DB write.

    v2.5.2 flipped the default registration mode to ``admin-approve`` (new
    accounts inactive until promoted); we set the flag directly to keep the
    test focused on access control rather than the registration policy.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register_and_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, str, dict[str, str]]:
    """Register, activate, log in. Returns ``(uid, email, password, headers)``."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@bim-idor.io"
    password = f"BimIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    return user_id, email, password, {}


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    """(Re-)login and return a fresh Bearer header carrying the current role claim."""
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {email}: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def two_bim_tenants(http_client):
    """A = admin owner+seeder; B = MANAGER attacker (holds bim.* permissions)."""
    a_uid, a_email, a_password, _ = await _register_and_login(http_client, tenant="a")
    b_uid, b_email, b_password, _ = await _register_and_login(http_client, tenant="b")

    # A is admin (needed to seed + to be the legitimate cleanup-orphans caller);
    # B is MANAGER - the strongest non-admin role, so it holds bim.read /
    # bim.update / bim.delete and the tests prove the *authz* guard not the RBAC.
    await _set_role(a_email, role="admin")
    await _set_role(b_email, role="manager")

    # Login AFTER role assignment so each JWT carries the rehydrated role claim.
    a_headers = await _login(http_client, a_email, a_password)
    b_headers = await _login(http_client, b_email, b_password)

    # Seed: a project owned by A, a project-scoped quantity map under it (the
    # cross-tenant secret), plus a global (project_id IS NULL) template that
    # everyone is allowed to see.
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMQuantityMap
    from app.modules.projects.models import Project

    a_project_id = uuid.uuid4()
    scoped_map_id = uuid.uuid4()
    global_map_id = uuid.uuid4()
    scoped_name = f"A-SECRET-{uuid.uuid4().hex[:8]}"
    global_name = f"GLOBAL-TPL-{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as s:
        s.add(
            Project(
                id=a_project_id,
                name="A-BIM-Project",
                owner_id=uuid.UUID(a_uid),
                status="active",
                currency="EUR",
            )
        )
        await s.flush()
        s.add(
            BIMQuantityMap(
                id=scoped_map_id,
                org_id=None,
                project_id=a_project_id,
                name=scoped_name,
                quantity_source="volume_m3",
                multiplier="1",
                waste_factor_pct="0",
                is_active=True,
                metadata_={},
            )
        )
        s.add(
            BIMQuantityMap(
                id=global_map_id,
                org_id=None,
                project_id=None,
                name=global_name,
                quantity_source="area_m2",
                multiplier="1",
                waste_factor_pct="0",
                is_active=True,
                metadata_={},
            )
        )
        await s.commit()

    return {
        "a": {"user_id": a_uid, "email": a_email, "headers": a_headers},
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
        "a_project_id": str(a_project_id),
        "scoped_map_id": str(scoped_map_id),
        "scoped_name": scoped_name,
        "global_map_id": str(global_map_id),
        "global_name": global_name,
    }


# ── #12: quantity-maps list scoping ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_quantity_maps_excludes_other_tenants_project_rule(http_client, two_bim_tenants):
    """B must NOT see A's project-scoped quantity map in the list.

    Before the fix the endpoint called ``list_all()`` (no WHERE clause), so
    B's costing/takeoff logic leaked A's project-scoped rule. After the fix
    the list is scoped to B's accessible projects.
    """
    b = two_bim_tenants["b"]

    resp = await http_client.get("/api/v1/bim-hub/quantity-maps/", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    names = {item["name"] for item in resp.json()["items"]}
    assert two_bim_tenants["scoped_name"] not in names, (
        f"LEAK: tenant A's project-scoped quantity map '{two_bim_tenants['scoped_name']}' "
        f"is visible to manager B. Returned names: {names!r}"
    )


@pytest.mark.asyncio
async def test_list_quantity_maps_includes_global_template(http_client, two_bim_tenants):
    """Global (project_id IS NULL) templates remain visible to every caller."""
    b = two_bim_tenants["b"]

    resp = await http_client.get("/api/v1/bim-hub/quantity-maps/", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    names = {item["name"] for item in resp.json()["items"]}
    assert two_bim_tenants["global_name"] in names, (
        f"REGRESSION: the global template '{two_bim_tenants['global_name']}' should stay "
        f"visible to all callers. Returned names: {names!r}"
    )


@pytest.mark.asyncio
async def test_admin_a_sees_own_project_rule(http_client, two_bim_tenants):
    """Admin A (unrestricted) still sees the project-scoped rule it owns."""
    a = two_bim_tenants["a"]

    resp = await http_client.get("/api/v1/bim-hub/quantity-maps/", headers=a["headers"])
    assert resp.status_code == 200, resp.text
    names = {item["name"] for item in resp.json()["items"]}
    assert two_bim_tenants["scoped_name"] in names
    assert two_bim_tenants["global_name"] in names


# ── #12: PATCH guard on global (project_id IS NULL) rule ─────────────────────


@pytest.mark.asyncio
async def test_manager_b_cannot_patch_global_quantity_map(http_client, two_bim_tenants):
    """A non-admin (even MANAGER, who holds bim.update) cannot mutate a global rule.

    The global template is a cross-tenant shared resource; only an admin may
    rewrite it. The router returns 404 for the non-admin global case to keep
    the IDOR surface consistent.
    """
    b = two_bim_tenants["b"]
    global_map_id = two_bim_tenants["global_map_id"]

    resp = await http_client.patch(
        f"/api/v1/bim-hub/quantity-maps/{global_map_id}",
        json={"name": "manager-overwrite"},
        headers=b["headers"],
    )
    assert resp.status_code == 404, (
        f"LEAK: manager B was able to PATCH the global quantity map (status {resp.status_code}). Body: {resp.text!r}"
    )

    # Defensive: confirm the row was not actually modified.
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMQuantityMap

    async with async_session_factory() as s:
        row = await s.get(BIMQuantityMap, uuid.UUID(global_map_id))
        assert row is not None
        assert row.name == two_bim_tenants["global_name"], "B's PATCH actually mutated the global template"


@pytest.mark.asyncio
async def test_admin_a_can_patch_global_quantity_map(http_client, two_bim_tenants):
    """Admin A may still mutate a global template (positive control)."""
    a = two_bim_tenants["a"]
    global_map_id = two_bim_tenants["global_map_id"]
    new_name = f"GLOBAL-TPL-RENAMED-{uuid.uuid4().hex[:6]}"

    resp = await http_client.patch(
        f"/api/v1/bim-hub/quantity-maps/{global_map_id}",
        json={"name": new_name},
        headers=a["headers"],
    )
    assert resp.status_code == 200, f"admin A should be able to PATCH the global template: {resp.text}"
    assert resp.json()["name"] == new_name


# ── #13: cleanup-orphans must be admin-only ──────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_orphans_rejects_non_admin_manager(http_client, two_bim_tenants):
    """The cross-tenant filesystem sweep must reject a non-admin, even a MANAGER.

    B holds ``bim.delete`` (MANAGER) - the level the endpoint used to require -
    so a 403 here proves the gate is now ``RequireRole("admin")``.
    """
    b = two_bim_tenants["b"]

    resp = await http_client.post("/api/v1/bim-hub/cleanup-orphans/", headers=b["headers"])
    assert resp.status_code in (401, 403), (
        f"LEAK: manager B was able to call cleanup-orphans (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_cleanup_orphans_allows_admin(http_client, two_bim_tenants):
    """Admin A may run cleanup-orphans (positive control)."""
    a = two_bim_tenants["a"]

    resp = await http_client.post("/api/v1/bim-hub/cleanup-orphans/", headers=a["headers"])
    assert resp.status_code == 200, f"admin A should be able to run cleanup-orphans: {resp.text}"
    body = resp.json()
    assert "removed_models" in body and "scanned" in body
