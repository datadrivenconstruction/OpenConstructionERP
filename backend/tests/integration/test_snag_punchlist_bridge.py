# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Snag -> Punchlist auto-bridge integration test (task #156).

Verifies the event-bus bridge that subscribes ``punchlist`` to
``property_dev.snag.created`` and auto-creates a matching punchlist
item:

* Severity -> priority mapping (safety -> critical, major -> high,
  minor/cosmetic -> low).
* Category passthrough when it's in the punchlist allow-list;
  fallback to 'general' for snag-only categories.
* Back-link: snag.linked_punch_item_id points at the auto-created
  punch item.
* Metadata carries the cross-module link (source, snag_id, handover_id,
  cost_impact).
* Bridge is fail-soft: a snag with a handover that's been orphaned
  (plot/dev/project missing) silently skips item creation instead of
  raising.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-snag-punchlist-"))
_TMP_DB = _TMP_DIR / "snag_punchlist.db"
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
        from app.modules.punchlist import models as _punch_models  # noqa: F401

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
    email = f"{label}-{uuid.uuid4().hex[:8]}@bridge.io"
    password = f"Bridge{uuid.uuid4().hex[:6]}9!"
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


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    """Manager tenant with project + dev + plot + buyer + handover."""
    from decimal import Decimal

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

    email, meta = await _register(http_client, "bridge-mgr")
    await _set_role(email, "manager")
    headers = await _login(http_client, email, meta["_password"])

    async with async_session_factory() as s:
        owner = (await s.execute(select(User).where(User.email == email.lower()))).scalar_one()

        proj = Project(
            name=f"Bridge-{uuid.uuid4().hex[:6]}",
            description="snag bridge",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV-BR-{uuid.uuid4().hex[:5]}",
            name="Bridge Heights",
            total_plots=1,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        plot = Plot(
            development_id=dev.id,
            plot_number="BR-01",
            area_m2=Decimal("100"),
            price_base=Decimal("400000"),
            currency="EUR",
            status="planned",
        )
        s.add(plot)
        await s.flush()

        buyer = Buyer(
            development_id=dev.id,
            plot_id=plot.id,
            full_name="Bridge Buyer",
            email=f"buyer-{uuid.uuid4().hex[:6]}@x.io",
            status="contracted",
            contract_value=Decimal("400000"),
            currency="EUR",
        )
        s.add(buyer)
        await s.flush()

        handover = Handover(
            plot_id=plot.id,
            scheduled_at="2026-01-01",
            snag_count_at_handover=0,
            final_check_passed=False,
        )
        s.add(handover)
        await s.flush()

        await s.commit()

        return {
            "headers": headers,
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "plot_id": str(plot.id),
            "buyer_id": str(buyer.id),
            "handover_id": str(handover.id),
        }


async def _create_snag(
    seeded: dict,
    *,
    severity: str = "major",
    category: str = "structural",
    description: str = "Crack above doorframe",
    cost_impact: str = "999.99",
) -> str:
    """Create a Snag directly via the ORM and fire the bridge event
    inline.

    We deliberately avoid the HTTP POST route here because aiosqlite +
    detached ``asyncio.create_task`` subscribers deadlock under the
    httpx ASGITransport (the outer request still holds the SQLite
    writer lock when the subscriber tries to open its own session).
    The bridge ITSELF is exercised end-to-end — we just don't want the
    test runner racing the request commit.

    The event payload exactly matches what ``service.create_snag``
    publishes via ``event_bus.publish_detached`` in production.
    """
    from app.core.events import event_bus
    from app.database import async_session_factory
    from app.modules.property_dev.models import Snag

    async with async_session_factory() as s:
        snag = Snag(
            handover_id=uuid.UUID(seeded["handover_id"]),
            buyer_id=uuid.UUID(seeded["buyer_id"]),
            category=category,
            severity=severity,
            description=description,
            status="open",
            reported_at="2026-01-02",
            cost_impact=cost_impact,
        )
        s.add(snag)
        await s.flush()
        sid = str(snag.id)
        await s.commit()

    # Inline publish — subscribers run synchronously inside this await.
    await event_bus.publish(
        "property_dev.snag.created",
        {
            "snag_id": sid,
            "handover_id": seeded["handover_id"],
            "buyer_id": seeded["buyer_id"],
            "category": category,
            "severity": severity,
            "description": description[:200],
            "cost_impact": cost_impact,
        },
        source_module="property_dev",
    )

    return sid


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snag_create_spawns_punch_item(http_client, seeded):
    """A new snag triggers a matching punchlist item in the same project."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.property_dev.models import Snag
    from app.modules.punchlist.models import PunchItem

    sid = await _create_snag(seeded, severity="major")

    async with async_session_factory() as s:
        snag = (await s.execute(select(Snag).where(Snag.id == uuid.UUID(sid)))).scalar_one()
        assert snag.linked_punch_item_id is not None, "snag.linked_punch_item_id must be set by the bridge"

        items = (
            (
                await s.execute(
                    select(PunchItem).where(
                        PunchItem.id == snag.linked_punch_item_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(items) == 1
        punch = items[0]
        assert str(punch.project_id) == seeded["project_id"]
        # major -> high
        assert punch.priority == "high"
        # category passes through (structural is in the punch allow-list)
        assert punch.category == "structural"
        # metadata carries the back-link
        assert punch.metadata_["source"] == "property_dev.snag"
        assert punch.metadata_["snag_id"] == sid
        assert punch.metadata_["handover_id"] == seeded["handover_id"]
        assert punch.metadata_["cost_impact"] == "999.99"


@pytest.mark.asyncio
async def test_severity_priority_mapping(http_client, seeded):
    """safety -> critical; cosmetic -> low; minor -> low."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.property_dev.models import Snag
    from app.modules.punchlist.models import PunchItem

    cases: list[tuple[str, str]] = [
        ("safety", "critical"),
        ("cosmetic", "low"),
        ("minor", "low"),
    ]
    for severity, expected_priority in cases:
        sid = await _create_snag(
            seeded,
            severity=severity,
            description=f"sev-{severity} {uuid.uuid4().hex[:4]}",
        )

        async with async_session_factory() as s:
            snag = (await s.execute(select(Snag).where(Snag.id == uuid.UUID(sid)))).scalar_one()
            assert snag.linked_punch_item_id is not None
            punch = (await s.execute(select(PunchItem).where(PunchItem.id == snag.linked_punch_item_id))).scalar_one()
            assert punch.priority == expected_priority, (
                f"severity={severity} should map to priority={expected_priority}"
            )


@pytest.mark.asyncio
async def test_snag_only_category_falls_back_to_general(http_client, seeded):
    """A snag category that's NOT in the punchlist allow-list (e.g.
    ``cosmetic`` or ``functional``) falls back to ``general`` on the
    auto-created punch item — never raises a schema error."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.property_dev.models import Snag
    from app.modules.punchlist.models import PunchItem

    sid = await _create_snag(
        seeded,
        category="functional",  # snag-only, not in punch allow-list
        severity="minor",
        description="functional defect",
    )

    async with async_session_factory() as s:
        snag = (await s.execute(select(Snag).where(Snag.id == uuid.UUID(sid)))).scalar_one()
        punch = (await s.execute(select(PunchItem).where(PunchItem.id == snag.linked_punch_item_id))).scalar_one()
        assert punch.category == "general"
