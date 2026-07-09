"""Multi-tenant isolation regression suite (Wave 3-C, Task #236).

The platform exposes per-tenant data via the ``tenant_id`` column on
contacts and dashboards (snapshots), and per-owner scoping via the
``owner_id`` column on projects. A regression in any of those filters
would leak one tenant's data to another - a privacy disaster.

This module pins the cross-tenant access policy at the HTTP boundary so
the leak surfaces as a red test rather than a customer-reported bug.

Test scaffolding
~~~~~~~~~~~~~~~~
* The DB is the PostgreSQL cluster that ``tests/conftest.py`` provisions
  and binds to the SQLAlchemy engine before any test module imports.
  The global ``async_session_factory`` is already bound to that engine,
  so every fixture and direct DB write here runs against PostgreSQL.

* The two-tenant setup fixture is **module-scoped** because:
  (a) registering 2 users + lifespan boot is expensive (~25-30s on
      Windows + the dashboards module loader);
  (b) ``POST /auth/register`` is rate-limited per IP - repeating the
      registration once per test would hit 429 mid-suite.
  Each test only reads / fails to mutate the data - they don't
  conflict on shared state.

* The dashboards module table (``oe_dashboards_snapshot``) is NOT
  pre-imported by ``app.main.startup``, so the lifespan's
  ``Base.metadata.create_all`` skips it. We import the model and run
  ``create_all`` once more inside the fixture to backfill any
  late-registered tables. This is a no-op for already-existing tables.

* Tenant A is promoted to ``admin`` via direct DB write right after
  registration so they can hit ``POST /api/v1/contacts/`` (the public
  ``/auth/register`` endpoint demotes self-registered users to
  ``viewer``, who lacks the ``contacts.create`` permission). Tenant B
  is left as a viewer - they're the *attacker* in this scenario, and
  giving them admin would defeat the test.

Coverage
~~~~~~~~
* projects   - ``GET /api/v1/projects/{id}`` ownership boundary.
* contacts   - ``GET /api/v1/contacts/`` list scoping + ``GET / PATCH /
                DELETE /api/v1/contacts/{id}`` per-row gate.
* dashboards - ``GET /api/v1/dashboards/snapshots/{id}`` and
                ``DELETE /api/v1/dashboards/snapshots/{id}``.
* rfi / changeorders / submittals - the per-row
                ``GET / PATCH / DELETE`` project-scope gate. The attacker
                here is a MANAGER (holds the module RBAC verbs but has no
                access to the owner's project), so the request clears
                ``RequirePermission`` and the only remaining guard is
                ``verify_project_access``; these cases assert a STRICT 404,
                not the looser 403-or-404 an RBAC-blocked viewer allows.
* costs - the shared reference catalog stays readable across tenants,
                guarding against an over-filtering regression.

If a real cross-tenant leak is found while writing this file, the
offending case is wrapped in ``pytest.mark.xfail(strict=True)`` so the
suite still runs green for the rest of CI but the leak is loud.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once for the whole module.

    Lifespan startup runs ``Base.metadata.create_all`` on the conftest
    PostgreSQL. After lifespan we explicitly import the dashboards models
    (which ``app.main`` does NOT pre-import - they get pulled in by the
    module loader, but only after ``create_all`` has already run) and
    run ``create_all`` a second time to backfill the missing table.
    """
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        # Backfill dashboards / eac tables that the v0.x main.py
        # startup-import block doesn't list. ``create_all`` is idempotent
        # so this never destroys data.
        from app.database import Base, engine
        from app.modules.bid_management import models as _bid_management_models  # noqa: F401
        from app.modules.cost_recovery import models as _cost_recovery_models  # noqa: F401
        from app.modules.dashboards import models as _dashboards_models  # noqa: F401
        from app.modules.eac import models as _eac_models  # noqa: F401
        from app.modules.finance import models as _finance_models  # noqa: F401
        from app.modules.procurement import models as _procurement_models  # noqa: F401
        from app.modules.tendering import models as _tendering_models  # noqa: F401
        from app.modules.variations import models as _variations_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    """Module-scoped HTTP client. Reused across every test in this module."""
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, dict[str, str]]:
    """Register a fresh user, log them in, return ``(user_id, email, headers)``."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@tenant-iso.io"
    password = f"TenantIso{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, {"Authorization": f"Bearer {token}"}


async def _promote_to_admin(email: str) -> None:
    """Promote ``email`` to ``role='admin'`` via direct DB write.

    The public ``/auth/register`` endpoint demotes self-registered users
    to ``viewer`` for security. Admin role is required for the
    ``contacts.create`` permission, which we need to seed tenant A's
    test data. We bypass the HTTP surface to keep the test focused on
    cross-tenant access enforcement, not on the registration policy.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so a self-registered viewer can log in.

    The default registration mode is ``admin-approve`` (BUG-RBAC03), which
    leaves new non-bootstrap accounts inactive until an admin promotes them.
    Tenant B must stay a *viewer* yet still authenticate, so we flip the
    active flag directly via the DB to keep the test focused on cross-tenant
    access enforcement, not on the registration policy.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await session.commit()


async def _set_role(email: str, role: str) -> None:
    """Set ``role`` (and force ``is_active``) on ``email`` via a direct DB write.

    Generalises :func:`_promote_to_admin` for the read/write IDOR world,
    where the attacker is provisioned as a *manager* rather than an admin.
    A manager inherits the ``rfi`` / ``changeorders`` / ``submittals``
    read/update/delete permissions, so every ``RequirePermission`` gate
    lets the request through and the ONLY thing that can block a
    cross-tenant call is ``verify_project_access``. That is what lets the
    read/write tests below assert a strict 404 instead of the 403-or-404 an
    RBAC-blocked viewer produces. An admin attacker would be wrong here: the
    admin bypass inside ``verify_project_access`` would hand them a 200 and
    mask the very gate under test.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()


async def _re_login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    """Log in again so the JWT carries the freshly-promoted role claim."""
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """Module-scoped two-tenant world.

    Tenant A is the data owner: admin role + project + contact +
    dashboard snapshot. Tenant B is the attacker: a fresh viewer
    account with nothing of their own.
    """
    a_password = f"TenantIso{uuid.uuid4().hex[:6]}9"
    b_password = f"TenantIso{uuid.uuid4().hex[:6]}9"

    # ── Register A and B ───────────────────────────────────────────────────
    a_email = f"a-{uuid.uuid4().hex[:8]}@tenant-iso.io"
    reg_a = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": a_email, "password": a_password, "full_name": "Tenant A"},
    )
    assert reg_a.status_code in (200, 201), reg_a.text
    a_uid = reg_a.json()["id"]

    b_email = f"b-{uuid.uuid4().hex[:8]}@tenant-iso.io"
    reg_b = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": b_email, "password": b_password, "full_name": "Tenant B"},
    )
    assert reg_b.status_code in (200, 201), reg_b.text
    b_uid = reg_b.json()["id"]

    # Promote A so they can create contacts; B stays viewer but must be active.
    await _promote_to_admin(a_email)
    await _activate_user(b_email)

    # Re-login both to pick up role claim (and to obtain bearer tokens).
    a_headers = await _re_login(http_client, a_email, a_password)
    b_headers = await _re_login(http_client, b_email, b_password)

    # ── Tenant A creates a project ─────────────────────────────────────────
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Tenant-A Project {uuid.uuid4().hex[:6]}",
            "description": "owned by A",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # ── Tenant A creates a contact ─────────────────────────────────────────
    contact = await http_client.post(
        "/api/v1/contacts/",
        json={
            "contact_type": "subcontractor",
            "company_name": f"Tenant-A Sub {uuid.uuid4().hex[:6]}",
            "primary_email": f"sub-{uuid.uuid4().hex[:6]}@tenant-iso.io",
        },
        headers=a_headers,
    )
    assert contact.status_code in (200, 201), f"contact create failed: {contact.status_code} {contact.text}"
    contact_id = contact.json()["id"]

    # ── Tenant A's dashboard snapshot - direct DB seed ─────────────────────
    # POST /dashboards/projects/{id}/snapshots requires real CAD/BIM
    # uploads + the cad2data bridge - too heavy for an isolation test.
    from app.database import async_session_factory
    from app.modules.dashboards.models import Snapshot

    snapshot_id = uuid.uuid4()
    async with async_session_factory() as s:
        snap = Snapshot(
            id=snapshot_id,
            project_id=uuid.UUID(project_id),
            tenant_id=str(a_uid),  # router uses sub→tenant_id fallback
            label=f"A-baseline-{uuid.uuid4().hex[:6]}",
            parquet_dir=f"snapshots/{project_id}/{snapshot_id}",
            total_entities=0,
            total_categories=0,
            summary_stats={},
            source_files_json=[],
            created_by_user_id=uuid.UUID(a_uid),
        )
        s.add(snap)
        await s.commit()

    return {
        "a": {
            "user_id": a_uid,
            "email": a_email,
            "headers": a_headers,
            "project_id": project_id,
            "contact_id": contact_id,
            "snapshot_id": str(snapshot_id),
        },
        "b": {
            "user_id": b_uid,
            "email": b_email,
            "headers": b_headers,
        },
    }


# ── Projects ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_project(http_client, two_tenants):
    """``GET /projects/{id}`` from B for an A-owned project must NOT 200."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/projects/{a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's project. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_project_list_excludes_tenant_a(http_client, two_tenants):
    """``GET /projects/`` from B must not list any A-owned project."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get("/api/v1/projects/", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body if isinstance(body, list) else body.get("items", [])
    leaked = [p for p in items if p.get("id") == a["project_id"]]
    assert leaked == [], f"LEAK: tenant B's project list contains tenant A's project: {leaked!r}"


# ── Price index (project-scoped rate escalation) ────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_escalate_tenant_a_project_rates(http_client, two_tenants):
    """``POST /price-index/escalate-preview/`` with A's project_id must NOT 200.

    The project scope reads exactly the cost items A's BOQ references plus A's
    project name, so it is gated by ``verify_project_access``. An outsider gets a
    strict not-found, never A's project name or the rates its estimate uses. The
    catalogue scope (no ``project_id``) stays open reference data and is covered
    by the price-index escalation suites.
    """
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        "/api/v1/price-index/escalate-preview/",
        json={"project_id": a["project_id"], "target_date": "2026-01-01"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's project rates. Body: {resp.text!r}"
    )


# ── Contacts ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_contact_list_excludes_tenant_a(http_client, two_tenants):
    """``GET /contacts/`` from B must not include any A-owned contact."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        "/api/v1/contacts/?limit=500",
        headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    items = resp.json().get("items", [])
    leaked = [c for c in items if c.get("id") == a["contact_id"]]
    assert leaked == [], f"LEAK: tenant B's contact list contains tenant A's contact: {leaked!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_contact(http_client, two_tenants):
    """``GET /contacts/{id}`` from B for an A-owned contact must NOT 200."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/contacts/{a['contact_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's contact. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_patch_tenant_a_contact(http_client, two_tenants):
    """``PATCH /contacts/{id}`` from B for an A-owned contact must fail."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/contacts/{a['contact_id']}",
        json={"notes": "owned by B now (should not happen)"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to PATCH tenant A's contact (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_contact(http_client, two_tenants):
    """``DELETE /contacts/{id}`` from B for an A-owned contact must fail."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/contacts/{a['contact_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to DELETE tenant A's contact (status {resp.status_code}). Body: {resp.text!r}"
    )


# ── Dashboards (snapshots) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_snapshot(http_client, two_tenants):
    """``GET /dashboards/snapshots/{id}`` from B must not return A's snapshot."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/dashboards/snapshots/{a['snapshot_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's snapshot. Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_snapshot(http_client, two_tenants):
    """``DELETE /dashboards/snapshots/{id}`` from B must not destroy A's data."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/dashboards/snapshots/{a['snapshot_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to DELETE tenant A's snapshot (status {resp.status_code}). Body: {resp.text!r}"
    )

    # Confirm the row still exists from A's side.
    a_view = await http_client.get(
        f"/api/v1/dashboards/snapshots/{a['snapshot_id']}",
        headers=a["headers"],
    )
    assert a_view.status_code == 200, (
        f"tenant A's snapshot disappeared after B's DELETE attempt - got {a_view.status_code}: {a_view.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_dashboards_project_list_excludes_tenant_a(
    http_client,
    two_tenants,
):
    """``GET /dashboards/projects/{a_project}/snapshots`` from B must be empty.

    Even if the project id is leaked (e.g. via URL guessing), the
    per-tenant filter on the repository must prevent B from enumerating
    A's snapshots.
    """
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/dashboards/projects/{a['project_id']}/snapshots",
        headers=b["headers"],
    )
    # Either 200 with empty list or 403/404 are all acceptable defenses.
    if resp.status_code == 200:
        items = resp.json().get("items", [])
        leaked = [s for s in items if s.get("id") == a["snapshot_id"]]
        assert leaked == [], f"LEAK: tenant B sees tenant A's snapshot in project list: {leaked!r}"
    else:
        assert resp.status_code in (403, 404), f"unexpected status {resp.status_code}: {resp.text!r}"


# ── Cross-module per-row project-scope gate (rfi / changeorders / submittals) ─
#
# The suite above pins the list + per-row scope for projects, contacts and
# dashboards. The block below pins the per-row ``verify_project_access``
# gate that every project-scoped business module funnels through, using
# three high-risk representatives: RFIs, change orders and submittals.
#
# The attacker M is a MANAGER, not a viewer. Manager inherits the
# ``*.read`` / ``*.update`` / ``*.delete`` permissions on all three
# modules, so ``RequirePermission`` lets the request through and the sole
# remaining defence is ``verify_project_access``. That is exactly the seam
# this slice hardens, so these cases assert a STRICT 404: a 403 would mean
# the RBAC layer (not the tenant gate) did the blocking, and any 2xx would
# be an outright cross-tenant read / mutation leak.


def _assert_cross_tenant_404(resp, *, verb: str, target: str) -> None:
    """Assert a manager-outsider request was answered with a strict 404.

    ``verify_project_access`` returns 404 on deny (never 403) so a UUID the
    caller may not see is indistinguishable from one that does not exist (no
    existence oracle). Anything else is a regression: a 2xx served or mutated
    another tenant's row; a 403 means the existence oracle came back.
    """
    assert resp.status_code == 404, (
        f"LEAK: manager outsider got {resp.status_code} on {verb} {target}; "
        f"expected 404 from verify_project_access. Body: {resp.text!r}"
    )


@pytest_asyncio.fixture(scope="module")
async def rw_project_world(http_client):
    """A one-project world for the cross-module read/write IDOR proofs.

    Owner ``O`` (admin) owns a project and seeds one RFI, one change order
    and one submittal inside it. Attacker ``M`` (manager) owns nothing and
    is not a member of O's project, yet holds every module read/update/
    delete permission - so only ``verify_project_access`` stands between M
    and O's data. A global ``CostItem`` is seeded too, so the same two
    identities can prove the shared reference catalog is NOT tenant-scoped.
    """
    o_password = f"TenantIso{uuid.uuid4().hex[:6]}9"
    m_password = f"TenantIso{uuid.uuid4().hex[:6]}9"

    o_email = f"o-{uuid.uuid4().hex[:8]}@tenant-iso.io"
    reg_o = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": o_email, "password": o_password, "full_name": "Owner O"},
    )
    assert reg_o.status_code in (200, 201), reg_o.text

    m_email = f"m-{uuid.uuid4().hex[:8]}@tenant-iso.io"
    reg_m = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": m_email, "password": m_password, "full_name": "Manager M"},
    )
    assert reg_m.status_code in (200, 201), reg_m.text

    # O is the data owner (admin, so they can create); M is the attacker, a
    # manager - RBAC-privileged but with no access to O's project.
    await _set_role(o_email, "admin")
    await _set_role(m_email, "manager")

    owner_headers = await _re_login(http_client, o_email, o_password)
    attacker_headers = await _re_login(http_client, m_email, m_password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"RW-World Project {uuid.uuid4().hex[:6]}",
            "description": "owned by O",
            "currency": "EUR",
        },
        headers=owner_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # Seed one row per module through the owner's authorised POST. The 201
    # doubles as proof the route is mounted, so a later 404 from M on the
    # same URL can only be the access gate, never a missing route.
    rfi = await http_client.post(
        "/api/v1/rfi/",
        json={
            "project_id": project_id,
            "subject": "A-owned RFI",
            "question": "Confidential to project O.",
        },
        headers=owner_headers,
    )
    assert rfi.status_code == 201, f"rfi create failed: {rfi.status_code} {rfi.text}"
    rfi_id = rfi.json()["id"]

    change_order = await http_client.post(
        "/api/v1/changeorders/",
        json={"project_id": project_id, "title": "A-owned change order"},
        headers=owner_headers,
    )
    assert change_order.status_code == 201, (
        f"change order create failed: {change_order.status_code} {change_order.text}"
    )
    change_order_id = change_order.json()["id"]

    submittal = await http_client.post(
        "/api/v1/submittals/",
        json={
            "project_id": project_id,
            "title": "A-owned submittal",
            "submittal_type": "shop_drawing",
        },
        headers=owner_headers,
    )
    assert submittal.status_code == 201, f"submittal create failed: {submittal.status_code} {submittal.text}"
    submittal_id = submittal.json()["id"]

    # A global reference cost item: CostItem has no tenant/owner column by
    # design (CWICR / reference data every deployment is expected to read).
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem
    from app.modules.saved_views.models import SavedView

    o_uid = reg_o.json()["id"]
    cost_item_id = uuid.uuid4()
    cost_item_code = f"REF-XT-{uuid.uuid4().hex[:8]}"
    # A project-SHARED saved view owned by O. Seeded straight through the ORM
    # because the POST /saved-views/ create path needs a registered entity_type
    # and a spec that binds against it; the read path under test (get_view)
    # reads the row back without either, so a bare row is a sufficient target.
    saved_view_id = uuid.uuid4()
    async with async_session_factory() as s:
        s.add(
            CostItem(
                id=cost_item_id,
                code=cost_item_code,
                description="Global reference row (shared catalog)",
                unit="m2",
                rate="123.45",
                currency="EUR",
                source="custom",
                classification={},
                components=[],
                tags=[],
                region=None,
                is_active=True,
                metadata_={},
            )
        )
        s.add(
            SavedView(
                id=saved_view_id,
                owner_id=uuid.UUID(o_uid),
                project_id=uuid.UUID(project_id),
                entity_type="ledger_entry",
                name=f"O-shared-view-{uuid.uuid4().hex[:6]}",
                description="A-owned project-shared saved view",
                spec={},
                share_scope="project",
                is_pinned=False,
                metadata_={},
            )
        )
        await s.commit()

    return {
        "owner_headers": owner_headers,
        "attacker_headers": attacker_headers,
        "project_id": project_id,
        "rfi_id": rfi_id,
        "change_order_id": change_order_id,
        "submittal_id": submittal_id,
        "cost_item_id": str(cost_item_id),
        "cost_item_code": cost_item_code,
        "saved_view_id": str(saved_view_id),
    }


# ── RFI ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outsider_cannot_read_rfi(http_client, rw_project_world):
    """Reading O's RFI as a manager outsider must 404; the owner still can."""
    w = rw_project_world
    resp = await http_client.get(
        f"/api/v1/rfi/{w['rfi_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"rfi/{w['rfi_id']}")

    # Positive control - the owner reads their own RFI, so the 404 above is
    # unambiguously the access gate and not a missing route / row.
    owner_view = await http_client.get(
        f"/api/v1/rfi/{w['rfi_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_rfi(http_client, rw_project_world):
    """Patching O's RFI as a manager outsider must 404 and mutate nothing."""
    w = rw_project_world
    resp = await http_client.patch(
        f"/api/v1/rfi/{w['rfi_id']}",
        json={"subject": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"rfi/{w['rfi_id']}")

    owner_view = await http_client.get(
        f"/api/v1/rfi/{w['rfi_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["subject"] == "A-owned RFI", "outsider PATCH leaked through and mutated tenant O's RFI"


@pytest.mark.asyncio
async def test_outsider_cannot_delete_rfi(http_client, rw_project_world):
    """Deleting O's RFI as a manager outsider must 404 and leave it intact."""
    w = rw_project_world
    resp = await http_client.delete(
        f"/api/v1/rfi/{w['rfi_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="DELETE", target=f"rfi/{w['rfi_id']}")

    owner_view = await http_client.get(
        f"/api/v1/rfi/{w['rfi_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, "outsider DELETE leaked through and removed tenant O's RFI"


# ── Change orders ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outsider_cannot_read_change_order(http_client, rw_project_world):
    """Reading O's change order as a manager outsider must 404."""
    w = rw_project_world
    resp = await http_client.get(
        f"/api/v1/changeorders/{w['change_order_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"changeorders/{w['change_order_id']}")

    owner_view = await http_client.get(
        f"/api/v1/changeorders/{w['change_order_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_change_order(http_client, rw_project_world):
    """Patching O's change order as a manager outsider must 404 and mutate nothing."""
    w = rw_project_world
    resp = await http_client.patch(
        f"/api/v1/changeorders/{w['change_order_id']}",
        json={"title": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"changeorders/{w['change_order_id']}")

    owner_view = await http_client.get(
        f"/api/v1/changeorders/{w['change_order_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["title"] == "A-owned change order", (
        "outsider PATCH leaked through and mutated tenant O's change order"
    )


@pytest.mark.asyncio
async def test_outsider_cannot_delete_change_order(http_client, rw_project_world):
    """Deleting O's change order as a manager outsider must 404 and leave it intact."""
    w = rw_project_world
    resp = await http_client.delete(
        f"/api/v1/changeorders/{w['change_order_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="DELETE", target=f"changeorders/{w['change_order_id']}")

    owner_view = await http_client.get(
        f"/api/v1/changeorders/{w['change_order_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, "outsider DELETE leaked through and removed tenant O's change order"


# ── Submittals ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_outsider_cannot_read_submittal(http_client, rw_project_world):
    """Reading O's submittal as a manager outsider must 404."""
    w = rw_project_world
    resp = await http_client.get(
        f"/api/v1/submittals/{w['submittal_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"submittals/{w['submittal_id']}")

    owner_view = await http_client.get(
        f"/api/v1/submittals/{w['submittal_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_submittal(http_client, rw_project_world):
    """Patching O's submittal as a manager outsider must 404 and mutate nothing."""
    w = rw_project_world
    resp = await http_client.patch(
        f"/api/v1/submittals/{w['submittal_id']}",
        json={"title": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"submittals/{w['submittal_id']}")

    owner_view = await http_client.get(
        f"/api/v1/submittals/{w['submittal_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["title"] == "A-owned submittal", (
        "outsider PATCH leaked through and mutated tenant O's submittal"
    )


@pytest.mark.asyncio
async def test_outsider_cannot_delete_submittal(http_client, rw_project_world):
    """Deleting O's submittal as a manager outsider must 404 and leave it intact."""
    w = rw_project_world
    resp = await http_client.delete(
        f"/api/v1/submittals/{w['submittal_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="DELETE", target=f"submittals/{w['submittal_id']}")

    owner_view = await http_client.get(
        f"/api/v1/submittals/{w['submittal_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, "outsider DELETE leaked through and removed tenant O's submittal"


# ── Global reference data (costs) - guard against over-filtering ─────────────


@pytest.mark.asyncio
async def test_costs_reference_data_readable_across_tenants(http_client, rw_project_world):
    """The shared cost catalog must stay readable by every tenant.

    ``CostItem`` has no tenant/owner column by design - it is public
    reference data (CWICR / RSMeans / BKI). Both the owner and an unrelated
    tenant must read the same seeded row. This guards the OPPOSITE failure
    mode from the IDOR tests above: a tenant filter mistakenly applied to
    the costs reads would make reference data vanish for everyone but its
    creator. Companion to ``tests/integration/test_costs_idor.py``, which
    must stay green alongside this.
    """
    w = rw_project_world
    item_id = w["cost_item_id"]

    for who, headers in (
        ("owner", w["owner_headers"]),
        ("outsider", w["attacker_headers"]),
    ):
        resp = await http_client.get(f"/api/v1/costs/{item_id}", headers=headers)
        assert resp.status_code == 200, (
            f"REGRESSION: {who} can no longer read shared catalog item {item_id} "
            f"(status {resp.status_code}); global reference data must never be "
            f"tenant-filtered. Body: {resp.text!r}"
        )
        body = resp.json()
        assert body["id"] == item_id
        assert body["code"] == w["cost_item_code"]


# --- Commercial modules (finance / procurement / tendering / bids / variations /
#     cost recovery / claims evidence): per-row project-scope gate --------------
#
# RLS Phase 2 extends the manager-outsider proof above from rfi / change orders
# / submittals to the highest-risk project-scoped commercial modules. The
# attacker is the same manager M from ``rw_project_world``: RBAC-privileged on
# every module below (holds each module's read + update) yet not a member of O's
# project, so ``verify_project_access`` is the only guard left. Each read must
# answer a strict 404 with an owner-200 positive control, and each mutation must
# 404 AND leave O's row untouched. These pin the audited-correct behaviour so a
# future refactor that drops a guard surfaces as a red test.


@pytest_asyncio.fixture(scope="module")
async def commercial_records(http_client, rw_project_world):
    """Seed one owner-owned row in each high-risk commercial module.

    Reuses ``rw_project_world``'s owner O (admin), attacker M (manager) and O's
    project, then creates - through O's authorised POST - one finance invoice,
    purchase order, tender package, bid package, variation request and
    back-charge inside that project. Every seed carries an ``A-owned`` marker so
    a later mutation test can prove an outsider PATCH changed nothing. The
    create status doubles as proof each route is mounted, so a 404 from M on the
    same URL can only be the access gate, never a missing route.
    """
    w = rw_project_world
    owner = w["owner_headers"]
    project_id = w["project_id"]

    invoice = await http_client.post(
        "/api/v1/finance/",
        json={
            "project_id": project_id,
            "invoice_direction": "payable",
            "invoice_number": f"INV-OWNER-{uuid.uuid4().hex[:6]}",
        },
        headers=owner,
    )
    assert invoice.status_code in (200, 201), f"invoice seed failed: {invoice.status_code} {invoice.text}"
    invoice_id = invoice.json()["id"]

    po = await http_client.post(
        "/api/v1/procurement/",
        json={"project_id": project_id, "po_type": "A-OWNED-PO"},
        headers=owner,
    )
    assert po.status_code in (200, 201), f"purchase-order seed failed: {po.status_code} {po.text}"
    po_id = po.json()["id"]

    package = await http_client.post(
        "/api/v1/tendering/packages/",
        json={"project_id": project_id, "name": "A-owned package"},
        headers=owner,
    )
    assert package.status_code in (200, 201), f"tender-package seed failed: {package.status_code} {package.text}"
    tender_package_id = package.json()["id"]

    bid_package = await http_client.post(
        "/api/v1/bid-management/bid-packages/",
        json={
            "project_id": project_id,
            "code": f"BM-{uuid.uuid4().hex[:6]}",
            "title": "A-owned bid package",
        },
        headers=owner,
    )
    assert bid_package.status_code in (200, 201), (
        f"bid-package seed failed: {bid_package.status_code} {bid_package.text}"
    )
    bid_package_id = bid_package.json()["id"]

    variation = await http_client.post(
        "/api/v1/variations/variation-requests/",
        json={"project_id": project_id, "title": "A-owned VR"},
        headers=owner,
    )
    assert variation.status_code in (200, 201), f"variation seed failed: {variation.status_code} {variation.text}"
    variation_id = variation.json()["id"]

    back_charge = await http_client.post(
        f"/api/v1/cost-recovery/projects/{project_id}/back-charges",
        json={
            "description": "A-owned back-charge",
            "responsible_party": "Sub-X",
            "gross_amount": "1000",
        },
        headers=owner,
    )
    assert back_charge.status_code in (200, 201), (
        f"back-charge seed failed: {back_charge.status_code} {back_charge.text}"
    )
    back_charge_id = back_charge.json()["id"]

    return {
        "owner_headers": owner,
        "attacker_headers": w["attacker_headers"],
        "project_id": project_id,
        "invoice_id": invoice_id,
        "po_id": po_id,
        "tender_package_id": tender_package_id,
        "bid_package_id": bid_package_id,
        "variation_id": variation_id,
        "back_charge_id": back_charge_id,
    }


# --- Finance (invoices) ------------------------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_invoice(http_client, commercial_records):
    """Reading O's invoice as a manager outsider must 404; the owner still can."""
    w = commercial_records
    resp = await http_client.get(f"/api/v1/finance/{w['invoice_id']}", headers=w["attacker_headers"])
    _assert_cross_tenant_404(resp, verb="GET", target=f"finance/{w['invoice_id']}")

    owner_view = await http_client.get(f"/api/v1/finance/{w['invoice_id']}", headers=w["owner_headers"])
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_invoice(http_client, commercial_records):
    """Patching O's invoice as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/finance/{w['invoice_id']}",
        json={"invoice_direction": "receivable"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"finance/{w['invoice_id']}")

    owner_view = await http_client.get(f"/api/v1/finance/{w['invoice_id']}", headers=w["owner_headers"])
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["invoice_direction"] == "payable", (
        "outsider PATCH leaked through and mutated tenant O's invoice"
    )


# --- Procurement (purchase orders) -------------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_purchase_order(http_client, commercial_records):
    """Reading O's purchase order as a manager outsider must 404."""
    w = commercial_records
    resp = await http_client.get(f"/api/v1/procurement/{w['po_id']}", headers=w["attacker_headers"])
    _assert_cross_tenant_404(resp, verb="GET", target=f"procurement/{w['po_id']}")

    owner_view = await http_client.get(f"/api/v1/procurement/{w['po_id']}", headers=w["owner_headers"])
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_purchase_order(http_client, commercial_records):
    """Patching O's purchase order as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/procurement/{w['po_id']}",
        json={"po_type": "hijacked-type"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"procurement/{w['po_id']}")

    owner_view = await http_client.get(f"/api/v1/procurement/{w['po_id']}", headers=w["owner_headers"])
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["po_type"] == "A-OWNED-PO", (
        "outsider PATCH leaked through and mutated tenant O's purchase order"
    )


# --- Tendering (packages) ----------------------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_tender_package(http_client, commercial_records):
    """Reading O's tender package as a manager outsider must 404."""
    w = commercial_records
    resp = await http_client.get(
        f"/api/v1/tendering/packages/{w['tender_package_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"tendering/packages/{w['tender_package_id']}")

    owner_view = await http_client.get(
        f"/api/v1/tendering/packages/{w['tender_package_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_tender_package(http_client, commercial_records):
    """Patching O's tender package as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/tendering/packages/{w['tender_package_id']}",
        json={"name": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"tendering/packages/{w['tender_package_id']}")

    owner_view = await http_client.get(
        f"/api/v1/tendering/packages/{w['tender_package_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["name"] == "A-owned package", (
        "outsider PATCH leaked through and mutated tenant O's tender package"
    )


# --- Bid management (packages) -----------------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_bid_package(http_client, commercial_records):
    """Reading O's bid package as a manager outsider must 404."""
    w = commercial_records
    resp = await http_client.get(
        f"/api/v1/bid-management/bid-packages/{w['bid_package_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"bid-management/bid-packages/{w['bid_package_id']}")

    owner_view = await http_client.get(
        f"/api/v1/bid-management/bid-packages/{w['bid_package_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_bid_package(http_client, commercial_records):
    """Patching O's bid package as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/bid-management/bid-packages/{w['bid_package_id']}",
        json={"title": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"bid-management/bid-packages/{w['bid_package_id']}")

    owner_view = await http_client.get(
        f"/api/v1/bid-management/bid-packages/{w['bid_package_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["title"] == "A-owned bid package", (
        "outsider PATCH leaked through and mutated tenant O's bid package"
    )


# --- Variations (variation requests) -----------------------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_variation_request(http_client, commercial_records):
    """Reading O's variation request as a manager outsider must 404."""
    w = commercial_records
    resp = await http_client.get(
        f"/api/v1/variations/variation-requests/{w['variation_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"variations/variation-requests/{w['variation_id']}")

    owner_view = await http_client.get(
        f"/api/v1/variations/variation-requests/{w['variation_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


@pytest.mark.asyncio
async def test_outsider_cannot_update_variation_request(http_client, commercial_records):
    """Patching O's variation request as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/variations/variation-requests/{w['variation_id']}",
        json={"title": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"variations/variation-requests/{w['variation_id']}")

    owner_view = await http_client.get(
        f"/api/v1/variations/variation-requests/{w['variation_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["title"] == "A-owned VR", (
        "outsider PATCH leaked through and mutated tenant O's variation request"
    )


# --- Cost recovery (back-charges, project-nested routes) ---------------------


@pytest.mark.asyncio
async def test_outsider_cannot_list_back_charges(http_client, commercial_records):
    """Listing O's project back-charges as a manager outsider must 404.

    The route is nested under ``/projects/{project_id}/`` so the attacker
    supplies O's project id in the URL; ``verify_project_access`` denies it.
    """
    w = commercial_records
    resp = await http_client.get(
        f"/api/v1/cost-recovery/projects/{w['project_id']}/back-charges",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"cost-recovery/projects/{w['project_id']}/back-charges")

    owner_view = await http_client.get(
        f"/api/v1/cost-recovery/projects/{w['project_id']}/back-charges",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert any(bc.get("id") == w["back_charge_id"] for bc in owner_view.json()), (
        "owner cannot see their own seeded back-charge"
    )


@pytest.mark.asyncio
async def test_outsider_cannot_update_back_charge(http_client, commercial_records):
    """Patching O's back-charge as a manager outsider must 404 and mutate nothing."""
    w = commercial_records
    resp = await http_client.patch(
        f"/api/v1/cost-recovery/projects/{w['project_id']}/back-charges/{w['back_charge_id']}",
        json={"description": "hijacked by outsider"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="PATCH", target=f"cost-recovery/.../back-charges/{w['back_charge_id']}")

    owner_view = await http_client.get(
        f"/api/v1/cost-recovery/projects/{w['project_id']}/back-charges",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    seeded = next((bc for bc in owner_view.json() if bc.get("id") == w["back_charge_id"]), None)
    assert seeded is not None and seeded["description"] == "A-owned back-charge", (
        "outsider PATCH leaked through and mutated tenant O's back-charge"
    )


# --- Claims evidence (project-scoped derived pack) ---------------------------


@pytest.mark.asyncio
async def test_outsider_cannot_read_evidence_pack(http_client, commercial_records):
    """Assembling O's evidence pack as a manager outsider must 404.

    The pack is derived (no stored row to seed); the project id in the URL is the
    only tenant handle, so ``verify_project_access`` is the whole guard. The
    owner gets a 200 (an empty pack for an unknown subject is still a 200), which
    proves the 404 is the access gate and not a missing route.
    """
    w = commercial_records
    resp = await http_client.get(
        f"/api/v1/claims-evidence/projects/{w['project_id']}/pack",
        params={"subject_ref": "CLAIM-001"},
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"claims-evidence/projects/{w['project_id']}/pack")

    owner_view = await http_client.get(
        f"/api/v1/claims-evidence/projects/{w['project_id']}/pack",
        params={"subject_ref": "CLAIM-001"},
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text


# ── saved_views (shared-view definition disclosure) ─────────────────────────
#
# ``GET /saved-views/{id}`` returns a stored view definition (name /
# description / filter spec). A project/workspace-shared view is meant to be
# visible to members of its project. Every other saved-views read path (run /
# count / export) reaches the row scoper, which independently runs
# ``verify_project_access`` on the request's project pin. ``get_view`` does
# NOT run the scoper - it returned the definition after comparing the view's
# project to the CALLER-SUPPLIED ``?project_id`` query parameter, so a
# non-member could read a shared definition by echoing the view's own project
# id back. The attacker M is a MANAGER (holds ``saved_views.read``), so the
# only thing that can block the read is the project-access check the fix adds.


@pytest.mark.asyncio
async def test_outsider_cannot_read_shared_saved_view(http_client, rw_project_world):
    """Reading O's project-shared saved view as a manager outsider must 404."""
    w = rw_project_world
    # The attacker echoes the view's real project id back - exactly the input
    # that tripped the pre-fix visibility check.
    resp = await http_client.get(
        f"/api/v1/saved-views/{w['saved_view_id']}?project_id={w['project_id']}",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target=f"saved-views/{w['saved_view_id']}")

    # Positive control - the owner still reads their own shared view, so the
    # 404 above is unambiguously the access gate and not a missing route / row.
    owner_view = await http_client.get(
        f"/api/v1/saved-views/{w['saved_view_id']}?project_id={w['project_id']}",
        headers=w["owner_headers"],
    )
    assert owner_view.status_code == 200, owner_view.text
    assert owner_view.json()["id"] == w["saved_view_id"]


# ── ACAP (layout / RAB / timeline / render) per-project gate (Phase 8) ───────
#
# The ACAP endpoints take a project_id and, before Phase 8, only checked the
# caller was authenticated — not that they may touch THAT project (IDOR). These
# pin the fix wired in app.modules.acap.authz: an outsider manager (M) is denied
# on every ACAP route. Writes return 403 (require_project_owner); reads 404
# (require_project_access, IDOR-hiding). M holds broad RBAC but is not a member
# of O's project, and ACAP has no RequirePermission gate, so a 403/404 here can
# ONLY be the ownership guard — never a missing route (owner control below) nor
# an RBAC block.


@pytest.mark.asyncio
async def test_acap_outsider_cannot_generate_rab(http_client, rw_project_world):
    w = rw_project_world
    resp = await http_client.post(
        f"/api/v1/acap/projects/{w['project_id']}/rab:generate",
        headers=w["attacker_headers"],
    )
    assert resp.status_code == 403, f"LEAK: outsider got {resp.status_code} on ACAP rab:generate. {resp.text!r}"


@pytest.mark.asyncio
async def test_acap_outsider_cannot_generate_timeline(http_client, rw_project_world):
    w = rw_project_world
    resp = await http_client.post(
        f"/api/v1/acap/projects/{w['project_id']}/timeline:generate",
        headers=w["attacker_headers"],
    )
    assert resp.status_code == 403, f"LEAK: outsider got {resp.status_code} on ACAP timeline:generate. {resp.text!r}"


@pytest.mark.asyncio
async def test_acap_outsider_cannot_generate_render(http_client, rw_project_world):
    """403 must come from the ownership guard, which runs BEFORE the render
    key-gate (an outsider must not even learn whether the service is configured)."""
    w = rw_project_world
    resp = await http_client.post(
        f"/api/v1/acap/projects/{w['project_id']}/render:generate",
        headers=w["attacker_headers"],
    )
    assert resp.status_code == 403, f"LEAK: outsider got {resp.status_code} on ACAP render:generate. {resp.text!r}"


@pytest.mark.asyncio
async def test_acap_outsider_cannot_read_layout(http_client, rw_project_world):
    w = rw_project_world
    resp = await http_client.get(
        f"/api/v1/acap/projects/{w['project_id']}/layout",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target="acap/.../layout")


@pytest.mark.asyncio
async def test_acap_outsider_cannot_list_renders(http_client, rw_project_world):
    w = rw_project_world
    resp = await http_client.get(
        f"/api/v1/acap/projects/{w['project_id']}/renders",
        headers=w["attacker_headers"],
    )
    _assert_cross_tenant_404(resp, verb="GET", target="acap/.../renders")


@pytest.mark.asyncio
async def test_acap_owner_passes_ownership_guard(http_client, rw_project_world):
    """Positive control: the owner clears the guard. With no floor plan seeded,
    rab:generate answers 404 'No layout' (NOT 403) — proving O passed the
    ownership check that blocks the outsider M with a 403."""
    w = rw_project_world
    resp = await http_client.post(
        f"/api/v1/acap/projects/{w['project_id']}/rab:generate",
        headers=w["owner_headers"],
    )
    assert resp.status_code != 403, f"owner wrongly denied by the ownership guard: {resp.text!r}"
    assert resp.status_code in (200, 404), f"unexpected owner status {resp.status_code}: {resp.text!r}"
