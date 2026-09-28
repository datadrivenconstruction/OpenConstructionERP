# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notification mail reaches active accounts only, and each nudge mails once.

Two defects, one symptom: a mailbox that should hear nothing kept hearing the
same reminder.

The first is the recipient. The dispatcher resolved a user id to an address
and sent, without asking whether the account was still active. A deactivated
external account on the showcase collected every overdue reminder addressed to
it, dozens a day, and the only thing between it and its inbox was the
production transport being switched off.

The second is the ledger. The deadline sweep dedupes on its own in-app rows,
but it published the email in the same savepoint as the escalation step. When
escalation raised, the savepoint took the in-app row with it while the email
was already on its way, so the next tick found no record of the nudge and sent
it again, and the lifetime ceiling never engaged because it counts rows that
never survived.

The lookups here open their own session in production. Each test hands them
the test session instead, because a session of their own could not see the
uncommitted rows, and "the deactivated user got no mail" would pass simply
because the user was invisible. Every refusal is paired with an active control
for the same reason.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.email import EmailService, MemoryEmailBackend
from app.core.email.service import _address_belongs_to_deactivated_account
from app.core.events import Event, event_bus
from app.modules.deadlines import sweeper
from app.modules.notifications import dispatcher
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _factory_over(session):
    """A stand-in for ``async_session_factory`` that yields the test session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def _user(session, *, is_active: bool = True, deleted: bool = False) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Site Engineer",
        is_active=is_active,
        deleted_at=datetime.now(UTC) if deleted else None,
    )
    session.add(user)
    await session.flush()
    return user


# ── EmailService address lookup ───────────────────────────────────────────


async def test_the_address_lookup_names_deactivated_and_erased_accounts(pg_session):
    factory = _factory_over(pg_session)
    active = await _user(pg_session)
    inactive = await _user(pg_session, is_active=False)
    erased = await _user(pg_session, deleted=True)

    assert await _address_belongs_to_deactivated_account(inactive.email, session_factory=factory) is True
    assert await _address_belongs_to_deactivated_account(f" {inactive.email.upper()} ", session_factory=factory)
    assert await _address_belongs_to_deactivated_account(erased.email, session_factory=factory) is True
    # Controls: a live account and an address that is nobody's account at all
    # (a tender bidder, a report recipient) are both mailed.
    assert await _address_belongs_to_deactivated_account(active.email, session_factory=factory) is False
    assert await _address_belongs_to_deactivated_account("bidder@example.org", session_factory=factory) is False


# ── notification dispatcher ───────────────────────────────────────────────


async def _dispatch_to(user: User) -> None:
    await dispatcher._on_dispatch_email(
        Event(
            name="notifications.dispatch.email",
            data={
                "user_id": str(user.id),
                "event_type": "deadlines.punchlist.overdue",
                "payload": {"title_key": "notifications.deadline.overdue.title", "body_context": {}},
            },
        )
    )


async def test_the_dispatcher_mails_active_users_only(pg_session, monkeypatch):
    mem = MemoryEmailBackend()
    monkeypatch.setattr(dispatcher, "async_session_factory", _factory_over(pg_session))
    # No address lookup on this service, so only the dispatcher's own check
    # can stop a send.
    monkeypatch.setattr("app.core.email.get_email_service", lambda: EmailService(mem))

    active = await _user(pg_session)
    inactive = await _user(pg_session, is_active=False)
    erased = await _user(pg_session, deleted=True)

    await _dispatch_to(inactive)
    await _dispatch_to(erased)
    assert mem.sent == []

    await _dispatch_to(active)
    assert [m.to for m in mem.sent] == [active.email]


# ── deadline sweep: one nudge, one email ──────────────────────────────────


async def _one_overdue_item(session) -> None:
    owner = await _user(session)
    project = Project(name="Overdue once", owner_id=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        PunchItem(
            id=uuid.uuid4(),
            project_id=project.id,
            title="Late item",
            description="",
            status="open",
            due_date=datetime.now(UTC) - timedelta(days=14),
            assigned_to=str(owner.id),
        )
    )
    await session.flush()


async def test_a_failing_escalation_does_not_resend_the_overdue_email(pg_session, monkeypatch):
    published: list[str] = []

    def record(name, data=None, source_module=None):
        published.append(name)

    async def escalation_fails(*args, **kwargs):
        raise RuntimeError("escalation broke")

    monkeypatch.setattr(event_bus, "publish_detached", record)
    monkeypatch.setattr(sweeper, "_maybe_escalate", escalation_fails)
    await _one_overdue_item(pg_session)

    now = datetime.now(UTC)
    await sweeper.sweep_overdue(pg_session, now=now)
    await sweeper.sweep_overdue(pg_session, now=now + timedelta(hours=1))

    rows = await pg_session.execute(select(Notification).where(Notification.notification_type == sweeper.OVERDUE_TYPE))
    assert len(list(rows.scalars().all())) == 1, "the nudge's own record must survive a failed escalation"
    assert published.count("notifications.dispatch.email") == 1, (
        "one overdue nudge must produce one email, not one per tick"
    )


async def test_the_overdue_email_still_goes_out(pg_session, monkeypatch):
    """Control for the test above: the email is deferred, not dropped."""
    published: list[str] = []
    monkeypatch.setattr(
        event_bus, "publish_detached", lambda name, data=None, source_module=None: published.append(name)
    )
    await _one_overdue_item(pg_session)

    await sweeper.sweep_overdue(pg_session, now=datetime.now(UTC))

    assert published.count("notifications.dispatch.email") == 1
