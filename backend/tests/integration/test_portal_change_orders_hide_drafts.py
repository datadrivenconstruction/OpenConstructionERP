# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A change order still in draft or in review never reaches the client portal.

Surface (portal-session-gated):
    GET /api/v1/portal/me/change-orders

The builder writes change orders with internal pricing long before the client
should see them. The portal lists only decided ones (approved, executed,
rejected, closed), and that holds for a project grant and for a grant on the
draft itself: naming a draft in an access rule must not open it early.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
        from app.modules.changeorders import models as _co_models  # noqa: F401
        from app.modules.portal import models as _portal_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _portal_user(s, now, rules) -> dict[str, str]:
    from app.modules.portal.models import PortalAccessRule, PortalSession, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    user = PortalUser(
        id=uuid.uuid4(),
        email=f"client-{uuid.uuid4().hex[:6]}@co.io",
        portal_role="client",
        full_name="Portal Client",
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


@pytest_asyncio.fixture(scope="module")
async def seeded(http_client):
    from app.database import async_session_factory
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    now = datetime.now(UTC)
    async with async_session_factory() as s:
        owner = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@co.io",
            full_name="Builder",
            hashed_password="x" * 60,
            role="admin",
            is_active=True,
        )
        s.add(owner)
        await s.flush()
        project = Project(name=f"CO-{uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
        s.add(project)
        await s.flush()

        def co(code: str, status: str) -> ChangeOrder:
            return ChangeOrder(
                id=uuid.uuid4(),
                project_id=project.id,
                code=code,
                title=f"{code} title",
                description="internal pricing note",
                status=status,
                cost_impact=Decimal("1000"),
                currency="EUR",
            )

        orders = {
            status: co(f"CO-{status.upper()}", status)
            for status in ("draft", "submitted", "under_review", "approved", "executed")
        }
        s.add_all(orders.values())
        await s.flush()

        project_grant = await _portal_user(s, now, [("project", project.id)])
        draft_grant = await _portal_user(s, now, [("change_order", orders["draft"].id)])
        await s.commit()
    return {"project": project_grant, "draft": draft_grant}


async def _codes(http_client, headers) -> list[str]:
    resp = await http_client.get("/api/v1/portal/me/change-orders", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == len(body["items"])
    return sorted(item["code"] for item in body["items"])


@pytest.mark.asyncio
async def test_a_project_grant_lists_only_decided_change_orders(http_client, seeded):
    assert await _codes(http_client, seeded["project"]) == ["CO-APPROVED", "CO-EXECUTED"]


@pytest.mark.asyncio
async def test_a_grant_on_the_draft_itself_does_not_open_it(http_client, seeded):
    assert await _codes(http_client, seeded["draft"]) == []
