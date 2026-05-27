# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Warranty Claims integration tests (v3113).

Covers the deep-integration capabilities added on top of the base IDOR
suite in ``test_snag_warranty_idor.py``:

* development-scoped listing with status / severity filters
* end-to-end raise → assign → accept → close lifecycle through the
  HTTP layer
* ``is_in_warranty`` computation against the linked Handover
* snag → warranty promotion endpoint idempotency
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-warranty-"))
_TMP_DB = _TMP_DIR / "warranty.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


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


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@warranty-test.io"
    password = f"Warranty{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def tenant(http_client):
    """One MANAGER tenant with a dev + plot + buyer + completed handover."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.property_dev.models import (
        Buyer,
        Development,
        Handover,
        Plot,
    )
    from app.modules.users.models import User

    email, pwd = await _register(http_client, "warranty-tenant")
    await _set_role(email, "manager")
    headers = await _login(http_client, email, pwd)

    async with async_session_factory() as s:
        owner = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one()

        proj = Project(
            name=f"warranty-{uuid.uuid4().hex[:6]}",
            description="warranty test",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV-W-{uuid.uuid4().hex[:5]}",
            name="Warranty Development",
            total_plots=2,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        plot = Plot(
            development_id=dev.id,
            plot_number="W-01",
            area_m2=Decimal("95"),
            price_base=Decimal("400000"),
            currency="EUR",
            status="handed_over",
        )
        s.add(plot)
        await s.flush()

        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id,
            full_name="Warranty Buyer",
            email=f"buyer-{uuid.uuid4().hex[:6]}@x.io",
            status="completed",
            contract_value=Decimal("400000"),
            currency="EUR",
        )
        s.add(buyer)
        await s.flush()

        # Completed handover 1 year ago so is_in_warranty resolves true
        # for cosmetic claims (1y window) and true for structural (10y).
        from datetime import date, timedelta

        completed = (date.today() - timedelta(days=30)).isoformat()

        handover = Handover(
            plot_id=plot.id,
            scheduled_at=completed,
            completed_at=completed,
            snag_count_at_handover=0,
            final_check_passed=True,
        )
        s.add(handover)
        await s.flush()

        out = {
            "headers": headers,
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "plot_id": str(plot.id),
            "buyer_id": str(buyer.id),
            "handover_id": str(handover.id),
        }
        await s.commit()
    return out


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_warranty_claim_full_payload(http_client: AsyncClient, tenant: dict):
    """POST /warranty-claims/ accepts the v3113 enriched payload + sets
    is_in_warranty=True when the linked Handover is recent."""
    payload = {
        "plot_id": tenant["plot_id"],
        "buyer_id": tenant["buyer_id"],
        "handover_id": tenant["handover_id"],
        "category": "structural",
        "severity": "major",
        "description": "Hairline crack along the east-facing structural beam",
        "sla_deadline": "2026-12-31",
    }
    res = await http_client.post(
        "/api/v1/property-dev/warranty-claims/",
        json=payload,
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["category"] == "structural"
    assert body["severity"] == "major"
    assert body["sla_deadline"] == "2026-12-31"
    assert body["handover_id"] == tenant["handover_id"]
    # Structural claim inside 10-year structural window ⇒ in-warranty.
    assert body["is_in_warranty"] is True


@pytest.mark.asyncio
async def test_list_filters_by_development_and_status(http_client: AsyncClient, tenant: dict):
    """GET /warranty-claims/?development_id=... returns the dev's claims
    and honors status / severity narrowing without per-buyer drill-down."""
    # Raise two claims with different statuses.
    base = "/api/v1/property-dev/warranty-claims/"
    create1 = await http_client.post(
        base,
        json={
            "plot_id": tenant["plot_id"],
            "buyer_id": tenant["buyer_id"],
            "category": "defect",
            "severity": "minor",
            "description": "Door hinge squeak",
        },
        headers=tenant["headers"],
    )
    assert create1.status_code == 201, create1.text
    claim1_id = create1.json()["id"]

    create2 = await http_client.post(
        base,
        json={
            "plot_id": tenant["plot_id"],
            "buyer_id": tenant["buyer_id"],
            "category": "mep",
            "severity": "critical",
            "description": "Boiler pressure dropping overnight",
        },
        headers=tenant["headers"],
    )
    assert create2.status_code == 201, create2.text
    claim2_id = create2.json()["id"]

    # Close the first claim via the lifecycle endpoints.
    accept = await http_client.post(
        f"/api/v1/property-dev/warranty/{claim1_id}/accept",
        headers=tenant["headers"],
    )
    assert accept.status_code == 200, accept.text
    close = await http_client.post(
        f"/api/v1/property-dev/warranty/{claim1_id}/close",
        headers=tenant["headers"],
    )
    assert close.status_code == 200, close.text

    # Development-scoped listing returns BOTH claims.
    all_in_dev = await http_client.get(
        f"{base}?development_id={tenant['development_id']}",
        headers=tenant["headers"],
    )
    assert all_in_dev.status_code == 200, all_in_dev.text
    ids = {r["id"] for r in all_in_dev.json()}
    assert claim1_id in ids and claim2_id in ids

    # Filter status=closed → claim 1 only.
    closed_only = await http_client.get(
        f"{base}?development_id={tenant['development_id']}&status=closed",
        headers=tenant["headers"],
    )
    assert closed_only.status_code == 200
    closed_ids = [r["id"] for r in closed_only.json()]
    assert claim1_id in closed_ids
    assert claim2_id not in closed_ids

    # Filter severity=critical → claim 2 only.
    crit_only = await http_client.get(
        f"{base}?development_id={tenant['development_id']}&severity=critical",
        headers=tenant["headers"],
    )
    assert crit_only.status_code == 200
    crit_ids = [r["id"] for r in crit_only.json()]
    assert claim2_id in crit_ids
    assert claim1_id not in crit_ids


@pytest.mark.asyncio
async def test_lifecycle_assign_accept_close(http_client: AsyncClient, tenant: dict):
    """raised → assign → accept → close transitions hold + persist
    assigned_to_user_id."""
    base = "/api/v1/property-dev/warranty-claims/"
    create = await http_client.post(
        base,
        json={
            "plot_id": tenant["plot_id"],
            "buyer_id": tenant["buyer_id"],
            "category": "cosmetic",
            "severity": "minor",
            "description": "Touch-up needed on stair railing paint",
        },
        headers=tenant["headers"],
    )
    assert create.status_code == 201, create.text
    claim = create.json()
    claim_id = claim["id"]
    assert claim["status"] == "raised"

    # Assign — using a fake UUID so we can verify it round-trips even
    # though there is no actual user with that id (FK-less ref by design).
    assignee = str(uuid.uuid4())
    assign = await http_client.post(
        f"{base}{claim_id}/assign",
        json={"assigned_to_user_id": assignee},
        headers=tenant["headers"],
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["assigned_to_user_id"] == assignee

    # Accept
    accept = await http_client.post(
        f"/api/v1/property-dev/warranty/{claim_id}/accept",
        headers=tenant["headers"],
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "accepted"

    # Close
    close = await http_client.post(
        f"/api/v1/property-dev/warranty/{claim_id}/close",
        headers=tenant["headers"],
    )
    assert close.status_code == 200, close.text
    body = close.json()
    assert body["status"] == "closed"
    assert body["closed_at"] is not None


@pytest.mark.asyncio
async def test_promote_snag_idempotent(http_client: AsyncClient, tenant: dict):
    """POST /warranty-claims/from-snag/{id} promotes a snag into a claim
    and returns the same claim on a second call (no duplicate)."""

    from app.database import async_session_factory
    from app.modules.property_dev.models import Snag

    async with async_session_factory() as s:
        snag = Snag(
            handover_id=uuid.UUID(tenant["handover_id"]),
            buyer_id=uuid.UUID(tenant["buyer_id"]),
            category="general",
            description="kitchen tap leaks at base",
            severity="major",
            status="open",
            reported_at="2026-02-01",
        )
        s.add(snag)
        await s.commit()
        snag_id = str(snag.id)

    base = "/api/v1/property-dev/warranty-claims/from-snag"
    first = await http_client.post(f"{base}/{snag_id}", headers=tenant["headers"])
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert first.json()["source_snag_id"] == snag_id

    second = await http_client.post(f"{base}/{snag_id}", headers=tenant["headers"])
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first_id  # idempotent — same claim
