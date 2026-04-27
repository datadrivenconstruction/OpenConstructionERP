"""Costs IDOR audit (v2.4.0 slice A — task #177).

The ``/api/v1/costs/`` router exposes endpoints keyed off
``cost_item_id`` (a.k.a. ``item_id`` in the URL). Unlike most other
modules in the platform, ``CostItem`` is a **shared catalog** — it has
no ``tenant_id`` / ``owner_id`` / ``user_id`` column. The catalog hosts
public reference data (CWICR, RSMeans, BKI) that every tenant on the
deployment is expected to read, and write access is gated by RBAC
permissions (``costs.create`` / ``costs.update`` / ``costs.delete``) +
the admin role for destructive operations like
``DELETE /actions/clear-database/``.

That is a deliberate architectural choice, NOT an IDOR bug:

- Reads are public-by-design (matches autocomplete + search semantics).
- Writes require an editor-or-higher RBAC permission.
- Wholesale deletes require the admin role.

This module pins that contract so a future regression — e.g. someone
adding a per-tenant cost field but forgetting to filter on it — surfaces
as a red test. The cases below cover:

1. A non-privileged user (viewer) cannot create a global cost item.
2. A non-privileged user (viewer) cannot update an existing item.
3. A non-privileged user (viewer) cannot delete an item.
4. A non-privileged user (viewer) CAN read items — that is the
   intended behaviour and any change to it is a separate decision,
   not a security fix.
5. The wholesale ``clear-database`` truncate is admin-only.

If a future model adds a tenant column to ``CostItem``, this file
should be replaced with the same pattern as
``test_erp_chat_idor.py`` (cross-tenant 404 on read, write, delete).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-costs-idor-"))
_TMP_DB = _TMP_DIR / "costs_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


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
        from app.modules.costs import models as _costs_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    """Force ``is_active=True`` so login works in admin-approve mode.

    v2.5.2 flipped the default registration mode to ``admin-approve``,
    which leaves new accounts inactive until an admin promotes them.
    The IDOR audit needs both A and B logged in, so we flip the flag
    directly via the DB to keep the test focused on access control,
    not on the registration policy.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            update(User).where(User.email == email.lower()).values(is_active=True)
        )
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    """Register, activate, log in. Returns ``(uid, email, password, headers)``."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@costs-idor.io"
    password = f"CostsIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), (
        f"register failed for {tenant}: {reg.status_code} {reg.text}"
    )
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_costs_tenants(http_client):
    """A is admin (can seed catalog rows); B is a viewer (the attacker)."""
    a_uid, a_email, a_password, a_headers = await _register_and_login(
        http_client, tenant="a",
    )
    b_uid, b_email, _b_password, b_headers = await _register_and_login(
        http_client, tenant="b",
    )

    # Promote A to admin via direct DB write so they can create cost
    # items (``costs.create`` is gated on editor-or-above). B stays a
    # viewer — they're the attacker and admin would defeat the test.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(
            update(User)
            .where(User.email == a_email.lower())
            .values(role="admin", is_active=True)
        )
        await s.commit()

    # Re-login A so the JWT carries the freshly-promoted role claim.
    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # Seed a cost item directly. Going through the HTTP create endpoint
    # would also work but adds an unnecessary auth round-trip — the
    # important part for this audit is that the row exists, not how it
    # was inserted.
    from app.modules.costs.models import CostItem

    item_id = uuid.uuid4()
    item_code = f"IDOR-TEST-{uuid.uuid4().hex[:8]}"
    async with async_session_factory() as s:
        item = CostItem(
            id=item_id,
            code=item_code,
            description="Seeded for IDOR audit",
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
        s.add(item)
        await s.commit()

    return {
        "a": {"user_id": a_uid, "email": a_email, "headers": a_headers},
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
        "item_id": str(item_id),
        "item_code": item_code,
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_viewer_b_cannot_create_cost_item(http_client, two_costs_tenants):
    """A non-privileged viewer must NOT be able to create a global cost row.

    The catalog is shared but writes are gated on ``costs.create``, which
    a freshly-registered viewer does not hold. The expected response is
    403 (the explicit RBAC denial), but 401 is also acceptable if the
    permission registry treats viewers as unauthenticated for this verb.
    """
    b = two_costs_tenants["b"]

    resp = await http_client.post(
        "/api/v1/costs/",
        json={
            "code": f"VIEWER-INJECT-{uuid.uuid4().hex[:6]}",
            "description": "viewer should not be able to add this",
            "unit": "m2",
            "rate": 1.0,
        },
        headers=b["headers"],
    )
    assert resp.status_code in (401, 403), (
        f"LEAK: viewer B was able to create a cost item "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_viewer_b_cannot_update_cost_item(http_client, two_costs_tenants):
    """A viewer must NOT be able to PATCH an existing global cost row."""
    b = two_costs_tenants["b"]
    item_id = two_costs_tenants["item_id"]

    resp = await http_client.patch(
        f"/api/v1/costs/{item_id}",
        json={"description": "viewer-overwrite"},
        headers=b["headers"],
    )
    assert resp.status_code in (401, 403), (
        f"LEAK: viewer B was able to update cost item {item_id} "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )

    # Defensive: confirm the row was not actually modified.
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        item = await s.get(CostItem, uuid.UUID(item_id))
        assert item is not None
        assert item.description == "Seeded for IDOR audit", (
            "tenant B's PATCH attempt actually mutated the row"
        )


@pytest.mark.asyncio
async def test_viewer_b_cannot_delete_cost_item(http_client, two_costs_tenants):
    """A viewer must NOT be able to soft-delete a cost row."""
    b = two_costs_tenants["b"]
    item_id = two_costs_tenants["item_id"]

    resp = await http_client.delete(
        f"/api/v1/costs/{item_id}",
        headers=b["headers"],
    )
    assert resp.status_code in (401, 403), (
        f"LEAK: viewer B was able to delete cost item {item_id} "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )

    # Confirm the soft-delete flag was not flipped.
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as s:
        item = await s.get(CostItem, uuid.UUID(item_id))
        assert item is not None
        assert item.is_active is True, (
            "tenant B's DELETE attempt actually soft-deleted the row"
        )


@pytest.mark.asyncio
async def test_viewer_b_can_read_cost_item(http_client, two_costs_tenants):
    """Reads are intentionally public — pin the contract.

    ``CostItem`` is a shared reference catalog (CWICR / RSMeans / BKI).
    Every authenticated user can read every entry. This test exists so
    that if someone later adds a per-tenant filter to ``GET /costs/{id}``
    without updating the architecture decision, the test fails loudly
    and forces the discussion.
    """
    b = two_costs_tenants["b"]
    item_id = two_costs_tenants["item_id"]

    resp = await http_client.get(
        f"/api/v1/costs/{item_id}",
        headers=b["headers"],
    )
    assert resp.status_code == 200, (
        f"REGRESSION: cross-tenant read on shared catalog now blocked "
        f"(status {resp.status_code}). If this is intentional, update "
        f"this test and the docstring at the top of this file."
    )
    body = resp.json()
    assert body["id"] == item_id
    assert body["code"] == two_costs_tenants["item_code"]


@pytest.mark.asyncio
async def test_clear_database_requires_admin(http_client, two_costs_tenants):
    """The wholesale truncate endpoint must reject non-admin callers.

    ``DELETE /api/v1/costs/actions/clear-database/`` is the most
    dangerous endpoint in the module — a viewer or estimator hitting it
    would wipe the entire shared catalog. The router gates it on
    ``RequireRole("admin")``; this test pins that gate.
    """
    b = two_costs_tenants["b"]

    resp = await http_client.delete(
        "/api/v1/costs/actions/clear-database/",
        headers=b["headers"],
    )
    assert resp.status_code in (401, 403), (
        f"LEAK: viewer B was able to call clear-database "
        f"(status {resp.status_code}). Body: {resp.text!r}"
    )
