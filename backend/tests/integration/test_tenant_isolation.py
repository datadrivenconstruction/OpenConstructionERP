"""Multi-tenant isolation regression suite (Wave 3-C, Task #236).

The platform exposes per-tenant data via the ``tenant_id`` column on
contacts and dashboards (snapshots), and per-owner scoping via the
``owner_id`` column on projects. A regression in any of those filters
would leak one tenant's data to another — a privacy disaster.

This module pins the cross-tenant access policy at the HTTP boundary so
the leak surfaces as a red test rather than a customer-reported bug.

Test scaffolding
~~~~~~~~~~~~~~~~
* The DB is a per-module temp SQLite file (``tempfile.mkdtemp()`` +
  ``sqlite+aiosqlite:///``). The ``DATABASE_URL`` env var is set
  *before* ``app.database`` is imported so the global
  ``async_session_factory`` binds to the temp file — the production
  ``backend/openestimate.db`` is never touched. This is a hard
  requirement (see ``feedback_test_isolation.md``).

* The two-tenant setup fixture is **module-scoped** because:
  (a) registering 2 users + lifespan boot is expensive (~25-30s on
      Windows + the dashboards module loader);
  (b) ``POST /auth/register`` is rate-limited per IP — repeating the
      registration once per test would hit 429 mid-suite.
  Each test only reads / fails to mutate the data — they don't
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
  is left as a viewer — they're the *attacker* in this scenario, and
  giving them admin would defeat the test.

Coverage
~~~~~~~~
* projects   — ``GET /api/v1/projects/{id}`` ownership boundary.
* contacts   — ``GET /api/v1/contacts/`` list scoping + ``GET / PATCH /
                DELETE /api/v1/contacts/{id}`` per-row gate.
* dashboards — ``GET /api/v1/dashboards/snapshots/{id}`` and
                ``DELETE /api/v1/dashboards/snapshots/{id}``.

If a real cross-tenant leak is found while writing this file, the
offending case is wrapped in ``pytest.mark.xfail(strict=True)`` so the
suite still runs green for the rest of CI but the leak is loud.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-test SQLite isolation (must run BEFORE app imports) ────────────────
#
# ``app.database`` constructs the global async engine at import time using
# the value of ``settings.database_url`` it sees on first import. We
# therefore have to point that env var at a fresh temp file *now*, before
# any ``from app...`` line runs. ``get_settings()`` is ``lru_cache``-d so
# the first call wins — but we still call ``cache_clear()`` defensively
# inside the fixture in case a sibling module pre-imported it.

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-tenant-iso-"))
_TMP_DB = _TMP_DIR / "tenant_iso.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once for the whole module.

    Lifespan startup runs ``Base.metadata.create_all`` on the temp
    SQLite. After lifespan we explicitly import the dashboards models
    (which ``app.main`` does NOT pre-import — they get pulled in by the
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
        from app.modules.dashboards import models as _dashboards_models  # noqa: F401
        from app.modules.eac import models as _eac_models  # noqa: F401

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
    assert reg.status_code in (200, 201), (
        f"register failed for {tenant}: {reg.status_code} {reg.text}"
    )
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
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="admin")
        )
        await session.commit()


async def _re_login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    """Log in again so the JWT carries the freshly-promoted role claim."""
    resp = await client.post(
        "/api/v1/users/auth/login", json={"email": email, "password": password},
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

    # Promote A so they can create contacts; B stays viewer.
    await _promote_to_admin(a_email)

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
    assert contact.status_code in (200, 201), (
        f"contact create failed: {contact.status_code} {contact.text}"
    )
    contact_id = contact.json()["id"]

    # ── Tenant A's dashboard snapshot — direct DB seed ─────────────────────
    # POST /dashboards/projects/{id}/snapshots requires real CAD/BIM
    # uploads + the cad2data bridge — too heavy for an isolation test.
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
        f"/api/v1/projects/{a['project_id']}", headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's project. "
        f"Body: {resp.text!r}"
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
    assert leaked == [], (
        f"LEAK: tenant B's project list contains tenant A's project: {leaked!r}"
    )


# ── Contacts ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_contact_list_excludes_tenant_a(http_client, two_tenants):
    """``GET /contacts/`` from B must not include any A-owned contact."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        "/api/v1/contacts/?limit=500", headers=b["headers"],
    )
    assert resp.status_code == 200, resp.text
    items = resp.json().get("items", [])
    leaked = [c for c in items if c.get("id") == a["contact_id"]]
    assert leaked == [], (
        f"LEAK: tenant B's contact list contains tenant A's contact: {leaked!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_get_tenant_a_contact(http_client, two_tenants):
    """``GET /contacts/{id}`` from B for an A-owned contact must NOT 200."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/contacts/{a['contact_id']}", headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B got status {resp.status_code} on tenant A's contact. "
        f"Body: {resp.text!r}"
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
        f"LEAK: tenant B was able to PATCH tenant A's contact "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_tenant_a_contact(http_client, two_tenants):
    """``DELETE /contacts/{id}`` from B for an A-owned contact must fail."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/contacts/{a['contact_id']}", headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: tenant B was able to DELETE tenant A's contact "
        f"(status {resp.status_code}). Body: {resp.text!r}"
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
        f"LEAK: tenant B got status {resp.status_code} on tenant A's snapshot. "
        f"Body: {resp.text!r}"
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
        f"LEAK: tenant B was able to DELETE tenant A's snapshot "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )

    # Confirm the row still exists from A's side.
    a_view = await http_client.get(
        f"/api/v1/dashboards/snapshots/{a['snapshot_id']}",
        headers=a["headers"],
    )
    assert a_view.status_code == 200, (
        "tenant A's snapshot disappeared after B's DELETE attempt — "
        f"got {a_view.status_code}: {a_view.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_dashboards_project_list_excludes_tenant_a(
    http_client, two_tenants,
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
        assert leaked == [], (
            f"LEAK: tenant B sees tenant A's snapshot in project list: {leaked!r}"
        )
    else:
        assert resp.status_code in (403, 404), (
            f"unexpected status {resp.status_code}: {resp.text!r}"
        )
