# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Subcontractor-portal payment-application submission suite (item #22).

A subcontractor portal user must see / submit payment applications ONLY for
the agreements they were granted access to. Another subcontractor on the same
project must never be able to list, read, or submit against an agreement they
do not hold a rule on -- and a miss must surface as 404 (never 403).

Surface (portal-session-gated):
    GET  /api/v1/portal/me/payment-applications
    GET  /api/v1/portal/me/payment-applications/{id}
    POST /api/v1/portal/me/payment-applications

Tests:
* Empty list when the user has applications-free agreement access.
* RLS list filtering: sub A sees only A's application, not B's.
* Submit creates a PaymentApplication + its lines (server computes retention).
* Submit against an inaccessible agreement returns 404.
* Detail of another sub's application returns 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    """Make ``event_bus.publish_detached`` synchronous + side-effect-free.

    The submit path emits ``subcontractors.payment_application.submitted`` and
    ``portal.payment_application.submitted``. In production those spawn
    detached ``asyncio`` tasks; under the per-function test runner on Windows
    those orphan tasks outlive their event loop and crash teardown with
    WinError 10038. The events themselves are not the unit under test here, so
    we replace the publisher with a no-op (mirrors ``test_portal._patch_bus``).
    """
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.portal import models as _portal_models  # noqa: F401
        from app.modules.subcontractors import models as _sub_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_portal_session(portal_user_id: uuid.UUID) -> str:
    """Activate the portal user and open a session row directly, returning the
    bearer token. Skips the magic-link round trip; mirrors what the consume
    endpoint writes internally.
    """
    from datetime import datetime

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.portal.models import PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    async with async_session_factory() as s:
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
async def seeded(http_client):
    """Seed one project with two subcontractors, each on their own active
    agreement with a work package, valid insurance + license certs, and a
    linked portal user + access rule + session token.

    Subcontractor A already has one submitted payment application; B has none.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.portal.models import PortalAccessRule, PortalUser
    from app.modules.projects.models import Project
    from app.modules.subcontractors.models import (
        Certificate,
        PaymentApplication,
        SubcontractAgreement,
        Subcontractor,
        WorkPackage,
    )
    from app.modules.users.models import User

    today = date.today()
    out: dict = {}

    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"gc-{uuid.uuid4().hex[:8]}@payapp.io",
            full_name="GC Owner",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()

        proj = Project(
            name=f"PayApp-{uuid.uuid4().hex[:6]}",
            description="portal payment applications",
            owner_id=owner.id,
            currency="GBP",
        )
        s.add(proj)
        await s.flush()
        out["project_id"] = str(proj.id)
        out["currency"] = "GBP"

        for label in ("a", "b"):
            sub = Subcontractor(
                legal_name=f"Sub {label.upper()} Ltd",
                prequalification_status="approved",
                is_blocked=False,
                is_active=True,
            )
            s.add(sub)
            await s.flush()

            for cert_type in ("insurance", "license"):
                s.add(
                    Certificate(
                        subcontractor_id=sub.id,
                        cert_type=cert_type,
                        valid_until=today + timedelta(days=365),
                        revoked=False,
                        status="valid",
                    )
                )

            agr = SubcontractAgreement(
                subcontractor_id=sub.id,
                project_id=proj.id,
                title=f"Agreement {label.upper()}",
                total_value=Decimal("100000.00"),
                currency="GBP",
                retention_percent=Decimal("5.00"),
                status="active",
            )
            s.add(agr)
            await s.flush()

            wp = WorkPackage(
                agreement_id=agr.id,
                name=f"Groundworks {label.upper()}",
                planned_value=Decimal("40000.00"),
                status="planned",
            )
            s.add(wp)
            await s.flush()

            portal_user = PortalUser(
                id=uuid.uuid4(),
                email=f"sub-{label}-{uuid.uuid4().hex[:6]}@payapp.io",
                portal_role="subcontractor",
                full_name=f"Sub {label.upper()}",
                status="invited",
            )
            s.add(portal_user)
            await s.flush()

            # Grant submit access on this sub's own agreement only.
            s.add(
                PortalAccessRule(
                    portal_user_id=portal_user.id,
                    resource_type="agreement",
                    resource_id=agr.id,
                    permission="submit",
                )
            )

            out[f"sub_{label}_id"] = str(sub.id)
            out[f"agreement_{label}_id"] = str(agr.id)
            out[f"wp_{label}_id"] = str(wp.id)
            out[f"portal_{label}_id"] = portal_user.id

        # Sub A already has one submitted application (B has none).
        pa_a = PaymentApplication(
            agreement_id=uuid.UUID(out["agreement_a_id"]),
            application_number="PA-0001",
            period_start=today - timedelta(days=30),
            period_end=today,
            gross_amount=Decimal("10000.00"),
            retention_amount=Decimal("500.00"),
            net_amount=Decimal("9500.00"),
            currency="GBP",
            status="submitted",
        )
        s.add(pa_a)
        await s.flush()
        out["pa_a_id"] = str(pa_a.id)

        await s.commit()

        # Force-activate the prequal column the FSM defaulting may reset, then
        # open sessions for both portal users.
        await s.execute(
            update(Subcontractor)
            .where(Subcontractor.id == uuid.UUID(out["sub_a_id"]))
            .values(prequalification_status="approved")
        )
        await s.execute(
            update(Subcontractor)
            .where(Subcontractor.id == uuid.UUID(out["sub_b_id"]))
            .values(prequalification_status="approved")
        )
        await s.commit()

    out["token_a"] = await _create_portal_session(out["portal_a_id"])
    out["token_b"] = await _create_portal_session(out["portal_b_id"])
    return out


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_requires_portal_session(http_client, seeded):
    """No bearer token -> 401, never an anonymous read."""
    res = await http_client.get("/api/v1/portal/me/payment-applications")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_list_empty_for_sub_with_no_applications(http_client, seeded):
    """Sub B has agreement access but no applications -> empty list, total 0."""
    res = await http_client.get(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_b"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_list_rls_filters_to_own_agreement(http_client, seeded):
    """Sub A sees only A's application; B's rows never leak across."""
    res = await http_client.get(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_a"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["agreement_id"] == seeded["agreement_a_id"]
    assert item["currency"] == "GBP"
    # Money is serialised as a string, not a JSON float.
    assert isinstance(item["gross_amount"], str)
    assert item["gross_amount"] == "10000.00"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_detail_rls_denies_other_subs_application_with_404(http_client, seeded):
    """Sub B asking for sub A's application id gets 404 (never 403)."""
    res = await http_client.get(
        f"/api/v1/portal/me/payment-applications/{seeded['pa_a_id']}",
        headers=_auth(seeded["token_b"]),
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_detail_visible_to_owner(http_client, seeded):
    """Sub A can read their own application detail with its lines field."""
    res = await http_client.get(
        f"/api/v1/portal/me/payment-applications/{seeded['pa_a_id']}",
        headers=_auth(seeded["token_a"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == seeded["pa_a_id"]
    assert body["net_amount"] == "9500.00"
    assert isinstance(body["lines"], list)


@pytest.mark.asyncio
async def test_submit_creates_application_and_lines(http_client, seeded):
    """Sub B submits against their own agreement -> 201, application + line
    persisted, retention computed server-side (5% of 8000 = 400).
    """
    payload = {
        "agreement_id": seeded["agreement_b_id"],
        "period_start": str(date.today() - timedelta(days=15)),
        "period_end": str(date.today()),
        "lines": [
            {"work_package_id": seeded["wp_b_id"], "claimed_amount": "8000.00"},
        ],
    }
    res = await http_client.post(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_b"]),
        json=payload,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "submitted"
    assert body["agreement_id"] == seeded["agreement_b_id"]
    assert body["gross_amount"] == "8000.00"
    # 5% retention of 8000 = 400; net = 7600. Server-computed, not client-set.
    assert body["retention_amount"] == "400.00"
    assert body["net_amount"] == "7600.00"
    assert body["currency"] == "GBP"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["work_package_id"] == seeded["wp_b_id"]
    assert body["lines"][0]["claimed_amount"] == "8000.00"

    # Now the list reflects it.
    listed = await http_client.get(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_b"]),
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_submit_rls_denies_inaccessible_agreement_with_404(http_client, seeded):
    """Sub B submitting against sub A's agreement gets 404 (never 403)."""
    payload = {
        "agreement_id": seeded["agreement_a_id"],
        "lines": [
            {"work_package_id": seeded["wp_a_id"], "claimed_amount": "1000.00"},
        ],
    }
    res = await http_client.post(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_b"]),
        json=payload,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_payment_agreements_lists_only_accessible_with_work_packages(http_client, seeded):
    """The submit-form picker lists the caller's own active agreement with its
    work packages, and never another subcontractor's agreement.
    """
    res = await http_client.get(
        "/api/v1/portal/me/payment-agreements",
        headers=_auth(seeded["token_b"]),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    agr = body["items"][0]
    assert agr["id"] == seeded["agreement_b_id"]
    assert agr["currency"] == "GBP"
    assert agr["retention_percent"] == "5.00"
    wp_ids = {wp["id"] for wp in agr["work_packages"]}
    assert seeded["wp_b_id"] in wp_ids
    assert seeded["wp_a_id"] not in wp_ids


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_submit_foreign_work_package_with_404(http_client, seeded):
    """A line that references a work package not under the (accessible)
    agreement 404s -- we never confirm the foreign work-package id exists.
    """
    payload = {
        "agreement_id": seeded["agreement_b_id"],
        "lines": [
            {"work_package_id": seeded["wp_a_id"], "claimed_amount": "500.00"},
        ],
    }
    res = await http_client.post(
        "/api/v1/portal/me/payment-applications",
        headers=_auth(seeded["token_b"]),
        json=payload,
    )
    assert res.status_code == 404
