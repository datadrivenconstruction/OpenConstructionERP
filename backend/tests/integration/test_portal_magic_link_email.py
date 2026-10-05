# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A client asks for a sign-in link and gets it by email.

Surface (anonymous):
    POST /api/v1/portal/auth/magic-link

Tests:
* A registered address and an unknown one get the same 202 body, and the
  token never appears in it.
* Only the registered address gets an email, carrying a link that consumes.
* A second request inside the interval sends nothing more.
* Without a mail transport nothing is minted, so the link the builder copied
  by hand keeps working.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def mail_on(monkeypatch):
    """A server with a working mail transport, unless a test turns it off."""
    from app.core import email as core_email

    monkeypatch.setattr(core_email, "email_delivery_enabled", lambda _settings: True)
    return monkeypatch


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Capture what the endpoint hands to the mailer instead of mailing it."""
    from app.modules.portal import router as portal_router

    calls: list[dict] = []

    async def fake_send(**kwargs):
        calls.append(kwargs)
        return "sent"

    monkeypatch.setattr(portal_router, "send_login_email", fake_send)
    return calls


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.portal import models as _portal_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def client_email(http_client):
    from app.database import async_session_factory
    from app.modules.portal.models import PortalUser

    email = f"client-{uuid.uuid4().hex[:8]}@example.com"
    async with async_session_factory() as session:
        session.add(
            PortalUser(email=email, full_name="Dana Client", portal_role="client", language="de", status="active")
        )
        await session.commit()
    return email


@pytest.mark.asyncio
async def test_known_and_unknown_addresses_read_the_same_and_only_one_is_mailed(http_client, client_email, sent):
    unknown = await http_client.post("/api/v1/portal/auth/magic-link", json={"email": "ghost@example.com"})
    known = await http_client.post("/api/v1/portal/auth/magic-link", json={"email": client_email.upper()})

    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert len(sent) == 1
    mail = sent[0]
    assert mail["kind"] == "login"
    assert mail["email"] == client_email
    assert mail["language"] == "de"
    assert mail["token"] not in known.text

    consumed = await http_client.post("/api/v1/portal/auth/consume", json={"token": mail["token"]})
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["portal_user"]["email"] == client_email


@pytest.mark.asyncio
async def test_a_second_request_within_a_minute_sends_nothing(http_client, client_email, sent):
    first = await http_client.post("/api/v1/portal/auth/magic-link", json={"email": client_email})
    assert first.status_code == 202
    # The first test minted a link for this address moments ago.
    assert sent == []


@pytest.mark.asyncio
async def test_without_mail_the_copied_invite_link_survives_a_public_request(http_client, mail_on, sent):
    from datetime import UTC, datetime, timedelta

    from app.core import email as core_email
    from app.database import async_session_factory
    from app.modules.portal.models import PortalMagicLink, PortalUser
    from app.modules.portal.service import generate_token, hash_token

    email = f"copied-{uuid.uuid4().hex[:8]}@example.com"
    copied = generate_token()
    async with async_session_factory() as session:
        user = PortalUser(email=email, full_name="Copied Link", portal_role="client", status="active")
        session.add(user)
        await session.flush()
        session.add(
            PortalMagicLink(
                portal_user_id=user.id,
                token_hash=hash_token(copied),
                purpose="login",
                # Old enough that the per-minute throttle does not decide this.
                created_at=datetime.now(UTC) - timedelta(hours=2),
                expires_at=datetime.now(UTC) + timedelta(hours=20),
            )
        )
        await session.commit()

    mail_on.setattr(core_email, "email_delivery_enabled", lambda _settings: False)
    resp = await http_client.post("/api/v1/portal/auth/magic-link", json={"email": email})
    assert resp.status_code == 202
    assert sent == []

    consumed = await http_client.post("/api/v1/portal/auth/consume", json={"token": copied})
    assert consumed.status_code == 200, consumed.text
