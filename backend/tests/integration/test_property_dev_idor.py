"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Property-dev handover-doc IDOR regression suite (issue #29).

Two by-id / body-id endpoints under ``/api/v1/property-dev/`` historically
ran WITHOUT the ownership guard every sibling handover endpoint already
carried, so a foreign tenant could reach another owner's handover:

* ``GET  /handovers/{h_id}/docs``  (get_handover_bundle) - had no
  ``session`` / ``user_payload`` deps at all, so no guard ran; a stranger
  could enumerate the full handover-doc bundle (warranties, EPCs, key
  receipts) of any handover id they could guess.
* ``POST /handover-docs/``         (create_handover_doc) - trusted the
  body-supplied ``handover_id`` raw and attached a document to another
  owner's handover.

The fix wires ``_verify_owner_via_handover`` onto both (mirroring the
already-guarded PATCH/DELETE/export siblings). Property-dev ownership is
strict OWNER-only (walk handover -> plot -> development -> project.owner),
admins bypass, everyone else collapses to **404** so the endpoints cannot
be used as a UUID-existence oracle.

The attacker B is a *manager*: high enough to clear the ``property_dev.*``
RBAC gate (create_handover_doc needs MANAGER) so the request reaches - and
must be stopped by - the ownership guard rather than the permission layer.

Runs against the shared ``tests/conftest.py`` PostgreSQL cluster.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@propdev-idor.io"
    password = f"PropDevIdor{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def tenant_owner(http_client):
    """Tenant A: admin owning project -> development -> plot -> handover -> doc."""
    email, password = await _register(http_client, "owner")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"PropDev-A {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    dev = await http_client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"HO{uuid.uuid4().hex[:6].upper()}",
            "name": "Owner Heights",
            "total_plots": 1,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plot = await http_client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": "A-01",
            "area_m2": 120,
            "price_base": 400_000,
            "currency": "EUR",
            "status": "ready",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    handover = await http_client.post(
        "/api/v1/property-dev/handovers/",
        json={"plot_id": plot_id, "scheduled_at": "2026-09-15", "notes": "A confidential handover"},
        headers=headers,
    )
    assert handover.status_code == 201, handover.text
    handover_id = handover.json()["id"]

    # A confidential handover doc so the bundle has content that must not leak.
    doc = await http_client.post(
        "/api/v1/property-dev/handover-docs/",
        json={
            "handover_id": handover_id,
            "doc_type": "warranty",
            "title": "secret-handover-doc-marker",
            "is_required": True,
        },
        headers=headers,
    )
    assert doc.status_code == 201, f"handover-doc create failed: {doc.text}"

    return {
        "headers": headers,
        "project_id": project_id,
        "plot_id": plot_id,
        "handover_id": handover_id,
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_stranger(http_client):
    """Tenant B: manager with their own project (the attacker)."""
    email, password = await _register(http_client, "stranger")
    # Manager, NOT admin: clears the property_dev.handover RBAC gate (MANAGER)
    # so create_handover_doc reaches the ownership guard, but never bypasses it.
    await _set_role(email, "manager")
    headers = await _login(http_client, email, password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"PropDev-B {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"headers": headers, "project_id": proj.json()["id"]}


# ── IDOR vectors ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stranger_cannot_get_handover_bundle(http_client, tenant_owner, tenant_stranger):
    """``GET /handovers/{h_id}/docs`` must NOT leak A's handover-doc bundle."""
    resp = await http_client.get(
        f"/api/v1/property-dev/handovers/{tenant_owner['handover_id']}/docs",
        headers=tenant_stranger["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B read A's handover bundle: {resp.status_code} {resp.text!r}"
    assert "secret-handover-doc-marker" not in resp.text


@pytest.mark.asyncio
async def test_stranger_cannot_create_handover_doc(http_client, tenant_owner, tenant_stranger):
    """``POST /handover-docs/`` must reject a body handover_id B does not own."""
    resp = await http_client.post(
        "/api/v1/property-dev/handover-docs/",
        json={
            "handover_id": tenant_owner["handover_id"],
            "doc_type": "warranty",
            "title": "B-injected doc into A's handover",
            "is_required": False,
        },
        headers=tenant_stranger["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B attached a doc to A's handover: {resp.status_code} {resp.text!r}"
    )


# ── Regression guards (fix must not break the owner's own path) ────────────


@pytest.mark.asyncio
async def test_owner_can_get_own_handover_bundle(http_client, tenant_owner):
    """Regression: the guard must NOT block the owner reading their bundle."""
    resp = await http_client.get(
        f"/api/v1/property-dev/handovers/{tenant_owner['handover_id']}/docs",
        headers=tenant_owner["headers"],
    )
    assert resp.status_code == 200, f"REGRESSION: owner blocked from own bundle: {resp.status_code} {resp.text!r}"
    assert "secret-handover-doc-marker" in resp.text


@pytest.mark.asyncio
async def test_owner_can_create_own_handover_doc(http_client, tenant_owner):
    """Regression: the owner can still attach a doc to their own handover."""
    resp = await http_client.post(
        "/api/v1/property-dev/handover-docs/",
        json={
            "handover_id": tenant_owner["handover_id"],
            "doc_type": "manual",
            "title": "owner-added operations manual",
            "is_required": False,
        },
        headers=tenant_owner["headers"],
    )
    assert resp.status_code == 201, f"REGRESSION: owner blocked from own handover-doc: {resp.status_code} {resp.text!r}"
