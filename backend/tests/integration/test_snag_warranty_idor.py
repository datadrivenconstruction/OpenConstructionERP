# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Snag + WarrantyClaim IDOR closure integration suite (task #156).

Pre-task #156, every ``/api/v1/property-dev/snags/...`` and
``/api/v1/property-dev/warranty-claims/...`` route accepted any
``CurrentUserPayload`` without walking the ``snag → handover → plot →
development → project → owner`` chain. A logged-in EDITOR in tenant B
could enumerate UUIDs and read/modify/delete tenant A's snags and
warranty claims.

This suite locks the closure in:

* tenant A creates a handover + a snag + a warranty claim.
* tenant B (a separate EDITOR with their own project + dev + plot) is
  blocked from every route with the snag/warranty UUIDs in the path:
    - GET    /snags/{id}                  → 404
    - PATCH  /snags/{id}                  → 404
    - DELETE /snags/{id}                  → 404
    - POST   /snags/{id}/fix              → 404
    - POST   /snags/{id}/wont-fix         → 404
    - GET    /snags/?handover_id={id}     → 404
    - GET    /warranty-claims/{id}        → 404
    - PATCH  /warranty-claims/{id}        → 404
    - DELETE /warranty-claims/{id}        → 404
    - POST   /warranty/{id}/accept        → 404
    - POST   /warranty/{id}/reject        → 404
    - POST   /warranty/{id}/close         → 404
    - GET    /warranty-claims/?buyer_id={tenant-A buyer} → 404
    - GET    /warranty-claims/?plot_id={tenant-A plot}   → 404

All ``forbidden but exists`` responses collapse to 404 so tenant B can't
distinguish "doesn't exist" from "exists but yours not". Mirrors the
closure pattern documented at
``backend/app/modules/property_dev/router.py::_verify_owner_via_plot``.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-snag-warranty-idor-"))
_TMP_DB = _TMP_DIR / "snag_warranty_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

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


async def _register(client: AsyncClient, label: str) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@snag-idor.io"
    password = f"SnagIdor{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, {"_password": password}


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _seed_tenant(
    *,
    label: str,
    role: str,
    client: AsyncClient,
    with_snag: bool = False,
    with_warranty: bool = False,
) -> dict:
    """Direct-DB seeder mirroring test_property_dev_dashboards_aggregations."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.property_dev.models import (
        Buyer,
        Development,
        Handover,
        Plot,
        Snag,
        WarrantyClaim,
    )
    from app.modules.users.models import User

    email, meta = await _register(client, label)
    await _set_role(email, role)
    headers = await _login(client, email, meta["_password"])

    async with async_session_factory() as s:
        owner = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one()

        proj = Project(
            name=f"{label}-{uuid.uuid4().hex[:6]}",
            description=f"{label} project",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV-{label[:3].upper()}-{uuid.uuid4().hex[:5]}",
            name=f"{label} Development",
            total_plots=2,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        plot = Plot(
            development_id=dev.id,
            plot_number=f"{label[:1].upper()}-01",
            area_m2=Decimal("95"),
            price_base=Decimal("400000"),
            currency="EUR",
            status="planned",
        )
        s.add(plot)
        await s.flush()

        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id,
            full_name=f"{label} Buyer",
            email=f"buyer-{uuid.uuid4().hex[:6]}@x.io",
            status="contracted",
            contract_value=Decimal("400000"),
            currency="EUR",
        )
        s.add(buyer)
        await s.flush()

        out = {
            "email": email,
            "headers": headers,
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "plot_id": str(plot.id),
            "buyer_id": str(buyer.id),
        }

        if with_snag or with_warranty:
            handover = Handover(
                plot_id=plot.id,
                scheduled_at="2026-01-01",
                snag_count_at_handover=0,
                final_check_passed=False,
            )
            s.add(handover)
            await s.flush()
            out["handover_id"] = str(handover.id)

        if with_snag:
            snag = Snag(
                handover_id=handover.id,
                description=f"{label}-snag",
                severity="minor",
                status="open",
                reported_at="2026-01-02",
            )
            s.add(snag)
            await s.flush()
            out["snag_id"] = str(snag.id)

        if with_warranty:
            claim = WarrantyClaim(
                plot_id=plot.id,
                buyer_id=buyer.id,
                raised_at="2026-01-03",
                category="defect",
                description=f"{label}-warranty",
                status="raised",
            )
            s.add(claim)
            await s.flush()
            out["claim_id"] = str(claim.id)

        await s.commit()

    return out


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    """Tenant A: EDITOR owning a project + dev + plot + buyer + snag + claim."""
    return await _seed_tenant(
        label="tenant-a",
        role="editor",
        client=http_client,
        with_snag=True,
        with_warranty=True,
    )


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Tenant B: MANAGER with their OWN project. Cannot see tenant_a UUIDs.

    Manager role is intentional: it satisfies every snag/warranty
    permission gate (``property_dev.delete``, ``.handover``, ``.fix_snag``,
    ``.process_warranty``). That way the IDOR closure — not the
    permission gate — is what stops cross-tenant access. A real
    cross-tenant attacker with manager-equivalent in their own org is
    exactly the threat model we care about.
    """
    return await _seed_tenant(
        label="tenant-b",
        role="manager",
        client=http_client,
    )


# ── Snag IDOR closures ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snag_get_other_tenant_404(http_client, tenant_a, tenant_b):
    """Tenant B GET on tenant A's snag → 404 (existence not leaked)."""
    res = await http_client.get(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_patch_other_tenant_404(http_client, tenant_a, tenant_b):
    """Tenant B PATCH on tenant A's snag → 404."""
    res = await http_client.patch(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}",
        json={"description": "hijacked"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_delete_other_tenant_404(http_client, tenant_a, tenant_b):
    """Tenant B DELETE on tenant A's snag → 404."""
    res = await http_client.delete(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_fix_other_tenant_404(http_client, tenant_a, tenant_b):
    """Tenant B POST /fix on tenant A's snag → 404."""
    res = await http_client.post(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}/fix",
        json={"fix_notes": "done"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_wont_fix_other_tenant_404(http_client, tenant_a, tenant_b):
    """Tenant B POST /wont-fix on tenant A's snag → 404."""
    res = await http_client.post(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}/wont-fix",
        json={"fix_notes": "skip"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_list_other_tenant_handover_404(http_client, tenant_a, tenant_b):
    """Tenant B GET /snags/?handover_id=<tenant-A handover> → 404."""
    res = await http_client.get(
        "/api/v1/property-dev/snags/",
        params={"handover_id": tenant_a["handover_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_create_under_other_tenant_handover_404(http_client, tenant_a, tenant_b):
    """Tenant B POST /snags/ for a tenant A handover → 404."""
    res = await http_client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": tenant_a["handover_id"],
            "description": "I should not see this",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_snag_owner_can_still_read(http_client, tenant_a):
    """Smoke: tenant A still reads their own snag (regression guard)."""
    res = await http_client.get(
        f"/api/v1/property-dev/snags/{tenant_a['snag_id']}",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == tenant_a["snag_id"]


# ── WarrantyClaim IDOR closures ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warranty_get_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        f"/api/v1/property-dev/warranty-claims/{tenant_a['claim_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_patch_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.patch(
        f"/api/v1/property-dev/warranty-claims/{tenant_a['claim_id']}",
        json={"description": "hijacked"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_delete_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.delete(
        f"/api/v1/property-dev/warranty-claims/{tenant_a['claim_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_accept_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.post(
        f"/api/v1/property-dev/warranty/{tenant_a['claim_id']}/accept",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_reject_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.post(
        f"/api/v1/property-dev/warranty/{tenant_a['claim_id']}/reject",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_close_other_tenant_404(http_client, tenant_a, tenant_b):
    res = await http_client.post(
        f"/api/v1/property-dev/warranty/{tenant_a['claim_id']}/close",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_list_for_other_tenant_buyer_404(http_client, tenant_a, tenant_b):
    """Tenant B listing claims by tenant A's buyer_id → 404."""
    res = await http_client.get(
        "/api/v1/property-dev/warranty-claims/",
        params={"buyer_id": tenant_a["buyer_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_list_for_other_tenant_plot_404(http_client, tenant_a, tenant_b):
    """Tenant B listing claims by tenant A's plot_id → 404."""
    res = await http_client.get(
        "/api/v1/property-dev/warranty-claims/",
        params={"plot_id": tenant_a["plot_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_create_for_other_tenant_plot_404(http_client, tenant_a, tenant_b):
    """Tenant B POSTing a new claim referencing tenant A's plot → 404."""
    res = await http_client.post(
        "/api/v1/property-dev/warranty-claims/",
        json={
            "plot_id": tenant_a["plot_id"],
            "buyer_id": tenant_a["buyer_id"],
            "description": "I should not be able to write this",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_warranty_owner_can_still_read(http_client, tenant_a):
    """Smoke: tenant A still reads their own warranty claim."""
    res = await http_client.get(
        f"/api/v1/property-dev/warranty-claims/{tenant_a['claim_id']}",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == tenant_a["claim_id"]
