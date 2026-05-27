# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Buyer-portal own-snag / own-warranty visibility integration suite (task #156).

The buyer-facing portal must let a buyer see ONLY their own snags +
warranty claims; another buyer in the same development must not be
able to enumerate them.

Surface:
    GET /api/v1/property-dev/portal/me/snags           [portal session]
    GET /api/v1/property-dev/portal/me/warranty-claims [portal session]

Tests:
* Buyer A (portal-linked) sees their own snag + claim.
* Buyer B (separate portal user, same development) sees ONLY their
  own rows -- buyer A's snag/claim are invisible.
* Surveyor-raised snags (``buyer_id IS NULL``) are intentionally
  invisible to the portal (only buyer-raised snags are surfaced).
* A portal session is REQUIRED -- unauthenticated calls 401.
* status= filter narrows the result set.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-buyer-portal-snag-"))
_TMP_DB = _TMP_DIR / "buyer_portal_snag.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from datetime import UTC

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
        from app.modules.portal import models as _portal_models  # noqa: F401
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_portal_session(portal_user_id: uuid.UUID) -> str:
    """Create an active portal session row directly and return the
    bearer token.

    Skips the magic-link round trip; mirrors the session-row write the
    consume endpoint does internally. We activate the user first so
    ``verify_session`` accepts them.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.portal.models import PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    async with async_session_factory() as s:
        # Activate the user — magic-link consume normally flips
        # status=invited -> active on first use.
        await s.execute(update(PortalUser).where(PortalUser.id == portal_user_id).values(status="active"))

        plain = generate_token()
        now = datetime.now(UTC)
        sess = PortalSession(
            portal_user_id=portal_user_id,
            session_token_hash=hash_token(plain),
            ip_address="127.0.0.1",
            user_agent="pytest",
            started_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
        s.add(sess)
        await s.commit()
        return plain


@pytest_asyncio.fixture(scope="module")
async def two_buyers(http_client):
    """Seed a development with two buyers, each on their own plot, each
    with their own snag + warranty claim AND each with a linked
    PortalUser + active session.

    Also seeds a surveyor-raised snag (buyer_id NULL) on buyer A's
    handover so the portal-invisibility test has something to check.
    """
    from decimal import Decimal

    from app.database import async_session_factory
    from app.modules.portal.models import PortalUser
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

    internal_email = f"owner-{uuid.uuid4().hex[:8]}@portal-snag.io"
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=internal_email,
            full_name="Internal Owner",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()

        proj = Project(
            name=f"Portal-Snag-{uuid.uuid4().hex[:6]}",
            description="buyer portal snag visibility",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV-PS-{uuid.uuid4().hex[:5]}",
            name="Portal Snag Heights",
            total_plots=2,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        # Two portal users
        portal_a = PortalUser(
            id=uuid.uuid4(),
            email=f"buyer-a-{uuid.uuid4().hex[:6]}@portal.io",
            portal_role="client",
            full_name="Buyer A",
            status="invited",
        )
        portal_b = PortalUser(
            id=uuid.uuid4(),
            email=f"buyer-b-{uuid.uuid4().hex[:6]}@portal.io",
            portal_role="client",
            full_name="Buyer B",
            status="invited",
        )
        s.add(portal_a)
        s.add(portal_b)
        await s.flush()

        out: dict = {
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "portal_a_id": portal_a.id,
            "portal_b_id": portal_b.id,
        }

        for label, portal_user in [("a", portal_a), ("b", portal_b)]:
            plot = Plot(
                development_id=dev.id,
                plot_number=f"PS-{label.upper()}-01",
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
                portal_user_id=portal_user.id,
                full_name=f"Buyer {label.upper()}",
                email=portal_user.email,
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

            snag = Snag(
                handover_id=handover.id,
                buyer_id=buyer.id,
                category="cosmetic",
                description=f"Buyer-{label.upper()} cosmetic snag",
                severity="minor",
                status="open",
                reported_at="2026-01-02",
            )
            s.add(snag)
            await s.flush()

            claim = WarrantyClaim(
                plot_id=plot.id,
                buyer_id=buyer.id,
                raised_at="2026-01-03",
                category="defect",
                description=f"Buyer-{label.upper()} warranty claim",
                status="raised",
            )
            s.add(claim)
            await s.flush()

            out[f"buyer_{label}_id"] = str(buyer.id)
            out[f"handover_{label}_id"] = str(handover.id)
            out[f"snag_{label}_id"] = str(snag.id)
            out[f"claim_{label}_id"] = str(claim.id)

        # Extra: surveyor-raised snag on buyer A's handover (buyer_id NULL).
        # This must NOT show up in the portal A response.
        surveyor_snag = Snag(
            handover_id=uuid.UUID(out["handover_a_id"]),
            buyer_id=None,
            category="structural",
            description="Surveyor-raised; portal invisible",
            severity="major",
            status="open",
            reported_at="2026-01-02",
        )
        s.add(surveyor_snag)
        await s.flush()
        out["surveyor_snag_id"] = str(surveyor_snag.id)

        await s.commit()

    out["token_a"] = await _create_portal_session(out["portal_a_id"])
    out["token_b"] = await _create_portal_session(out["portal_b_id"])
    return out


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_portal_a_sees_own_snags_only(http_client, two_buyers):
    res = await http_client.get(
        "/api/v1/property-dev/portal/me/snags",
        headers=_bearer(two_buyers["token_a"]),
    )
    assert res.status_code == 200, res.text
    items = res.json()
    ids = {row["id"] for row in items}
    # Buyer A sees their own snag.
    assert two_buyers["snag_a_id"] in ids
    # Buyer A does NOT see buyer B's snag.
    assert two_buyers["snag_b_id"] not in ids
    # Buyer A does NOT see the surveyor-raised snag (buyer_id NULL).
    assert two_buyers["surveyor_snag_id"] not in ids


@pytest.mark.asyncio
async def test_portal_b_sees_own_snags_only(http_client, two_buyers):
    res = await http_client.get(
        "/api/v1/property-dev/portal/me/snags",
        headers=_bearer(two_buyers["token_b"]),
    )
    assert res.status_code == 200, res.text
    items = res.json()
    ids = {row["id"] for row in items}
    assert two_buyers["snag_b_id"] in ids
    assert two_buyers["snag_a_id"] not in ids


@pytest.mark.asyncio
async def test_portal_snags_requires_session(http_client, two_buyers):
    res = await http_client.get("/api/v1/property-dev/portal/me/snags")
    assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_portal_warranty_a_sees_own(http_client, two_buyers):
    res = await http_client.get(
        "/api/v1/property-dev/portal/me/warranty-claims",
        headers=_bearer(two_buyers["token_a"]),
    )
    assert res.status_code == 200, res.text
    items = res.json()
    ids = {row["id"] for row in items}
    assert two_buyers["claim_a_id"] in ids
    assert two_buyers["claim_b_id"] not in ids


@pytest.mark.asyncio
async def test_portal_warranty_status_filter(http_client, two_buyers):
    # Only ``raised`` status was seeded -> filter by it returns the claim;
    # filter by ``closed`` returns nothing.
    res_raised = await http_client.get(
        "/api/v1/property-dev/portal/me/warranty-claims",
        params={"status": "raised"},
        headers=_bearer(two_buyers["token_a"]),
    )
    assert res_raised.status_code == 200
    raised_ids = {r["id"] for r in res_raised.json()}
    assert two_buyers["claim_a_id"] in raised_ids

    res_closed = await http_client.get(
        "/api/v1/property-dev/portal/me/warranty-claims",
        params={"status": "closed"},
        headers=_bearer(two_buyers["token_a"]),
    )
    assert res_closed.status_code == 200
    closed_ids = {r["id"] for r in res_closed.json()}
    assert two_buyers["claim_a_id"] not in closed_ids


@pytest.mark.asyncio
async def test_portal_warranty_requires_session(http_client, two_buyers):
    res = await http_client.get("/api/v1/property-dev/portal/me/warranty-claims")
    assert res.status_code == 401, res.text
