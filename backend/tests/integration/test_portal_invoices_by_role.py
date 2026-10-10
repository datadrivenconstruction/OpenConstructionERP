# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Only the client side reads the client's invoices through a project grant.

Surface (portal-session-gated):
    GET /api/v1/portal/me/invoices

A ``project`` rule used to list every issued receivable invoice of the project
to any portal role, so a subcontractor or supplier let in for the documents read
what the owner is billed, with amounts and days overdue. The rule now matches
the payment plan: a project grant counts for ``client`` and ``investor`` only,
every other role sees just the invoices granted to it one by one. The count and
pagination follow the same scope as the items.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
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
        from app.modules.finance import models as _finance_models  # noqa: F401
        from app.modules.portal import models as _portal_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _portal_user(s, now, rules, *, role: str, expired: bool = False) -> dict[str, str]:
    from app.modules.portal.models import PortalAccessRule, PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    user = PortalUser(
        id=uuid.uuid4(),
        email=f"{role}-{uuid.uuid4().hex[:6]}@inv.io",
        portal_role=role,
        full_name="Portal Person",
        status="active",
    )
    s.add(user)
    await s.flush()
    for resource_type, resource_id in rules:
        s.add(
            PortalAccessRule(
                portal_user_id=user.id,
                resource_type=resource_type,
                resource_id=resource_id,
                permission="view",
                expires_at=now - timedelta(days=1) if expired else None,
            )
        )
    token = generate_token()
    s.add(
        PortalSession(
            portal_user_id=user.id,
            session_token_hash=hash_token(token),
            ip_address="127.0.0.1",
            user_agent="pytest",
            started_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    return {"Authorization": f"Bearer {token}"}


ROLES = ("client", "investor", "consultant", "subcontractor", "supplier", "building_user")


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    from app.database import async_session_factory
    from app.modules.finance.models import Invoice
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    now = datetime.now(UTC)
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@inv.io",
            full_name="Builder",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()
        mine = Project(name=f"Inv-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
        other = Project(name=f"Inv-other-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
        s.add_all([mine, other])
        await s.flush()

        def invoice(project, number, *, status="sent", direction="receivable"):
            return Invoice(
                id=uuid.uuid4(),
                project_id=project.id,
                invoice_direction=direction,
                invoice_number=number,
                invoice_date="2026-09-01",
                due_date="2026-10-01",
                currency_code="EUR",
                status=status,
            )

        first = invoice(mine, "INV-1")
        second = invoice(mine, "INV-2")
        third = invoice(mine, "INV-3")
        draft = invoice(mine, "INV-DRAFT", status="draft")
        payable = invoice(mine, "BILL-1", direction="payable")
        theirs = invoice(other, "INV-OTHER")
        s.add_all([first, second, third, draft, payable, theirs])
        await s.flush()

        headers: dict[str, dict[str, str]] = {}
        for role in ROLES:
            headers[f"project:{role}"] = await _portal_user(s, now, [("project", mine.id)], role=role)
        headers["sub_one_invoice"] = await _portal_user(
            s, now, [("project", mine.id), ("invoice", second.id)], role="subcontractor"
        )
        headers["supplier_other_invoice"] = await _portal_user(s, now, [("invoice", theirs.id)], role="supplier")
        headers["client_expired"] = await _portal_user(s, now, [("project", mine.id)], role="client", expired=True)
        await s.commit()
    return {
        "project_id": str(mine.id),
        "other_id": str(other.id),
        "headers": headers,
    }


async def _numbers(http_client, headers, **params) -> tuple[list[str], int]:
    resp = await http_client.get("/api/v1/portal/me/invoices", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return sorted(item["invoice_number"] for item in body["items"]), body["total"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["client", "investor"])
async def test_the_client_side_reads_every_issued_invoice_of_the_project(http_client, seeded, role):
    numbers, total = await _numbers(http_client, seeded["headers"][f"project:{role}"])
    assert numbers == ["INV-1", "INV-2", "INV-3"]
    assert total == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["consultant", "subcontractor", "supplier", "building_user"])
async def test_a_project_grant_shows_no_invoice_to_anyone_else(http_client, seeded, role):
    headers = seeded["headers"][f"project:{role}"]
    assert await _numbers(http_client, headers) == ([], 0)
    assert await _numbers(http_client, headers, project_id=seeded["project_id"]) == ([], 0)


@pytest.mark.asyncio
async def test_a_subcontractor_sees_only_the_invoice_granted_to_it(http_client, seeded):
    headers = seeded["headers"]["sub_one_invoice"]
    assert await _numbers(http_client, headers) == (["INV-2"], 1)
    assert await _numbers(http_client, headers, project_id=seeded["project_id"]) == (["INV-2"], 1)


@pytest.mark.asyncio
async def test_an_invoice_grant_does_not_open_its_neighbours(http_client, seeded):
    headers = seeded["headers"]["supplier_other_invoice"]
    assert await _numbers(http_client, headers) == (["INV-OTHER"], 1)
    assert await _numbers(http_client, headers, project_id=seeded["project_id"]) == ([], 0)


@pytest.mark.asyncio
async def test_an_expired_project_grant_shows_nothing(http_client, seeded):
    assert await _numbers(http_client, seeded["headers"]["client_expired"]) == ([], 0)


@pytest.mark.asyncio
async def test_the_count_and_the_page_follow_the_same_scope(http_client, seeded):
    headers = seeded["headers"]["project:client"]
    page, total = await _numbers(http_client, headers, limit=2, offset=0)
    rest, total_again = await _numbers(http_client, headers, limit=2, offset=2)
    assert total == total_again == 3
    assert len(page) == 2 and len(rest) == 1
    assert sorted(page + rest) == ["INV-1", "INV-2", "INV-3"]
