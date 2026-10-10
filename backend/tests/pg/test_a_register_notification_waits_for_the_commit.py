# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A register notification exists after the commit, and not before it.

Subscribers on the event bus open a session of their own. An event published
from inside the publisher's still-open transaction is therefore handled by a
connection that cannot see what the publisher just wrote: on PostgreSQL the
handler reads the old status, decides there is nothing to announce, and the
notification is lost without an error anywhere. SQLite hides it, because the
test and the handler share one connection.

So this runs on PostgreSQL with real commits (a throwaway database, not the
savepoint session), through the real services and the real bus wiring, and
asserts both halves:

* after the service call and BEFORE the commit, every scheduled subscriber has
  been given the chance to run and no notification exists;
* after the commit, exactly the right people hold one.

If a hook is ever changed back to a plain detached publish, the handler runs
in the first window, finds the request still in its old status, sends nothing,
and the second assertion fails.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.events as core_events
import app.modules.changeorders.service as changeorders_service
import app.modules.notifications._site_register_subscribers as sr
import app.modules.notifications.dispatcher as dispatcher
import app.modules.notifications.service as notifications_service
import app.modules.variations.service as variations_service
from app.core.email import EmailService
from app.core.email.memory import MemoryEmailBackend
from app.core.events import EventBus
from app.modules.changeorders.schemas import ChangeOrderCreate
from app.modules.notifications.models import Notification, NotificationPreference
from app.modules.notifications.schemas import reader_text
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.schemas import VariationRequestCreate
from tests._pg import isolated_engine

pytestmark = pytest.mark.asyncio

PROJECT_NAME = "Kule Projesi"


class _World:
    """A throwaway database with one project, its manager and one originator."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        bus: EventBus,
        mail: MemoryEmailBackend,
        project_id: uuid.UUID,
        manager_id: uuid.UUID,
        originator_id: uuid.UUID,
    ) -> None:
        self.factory = factory
        self.bus = bus
        self.mail = mail
        self.project_id = project_id
        self.manager_id = manager_id
        self.originator_id = originator_id

    async def settle(self) -> None:
        """Let every scheduled subscriber, and whatever it schedules, finish."""
        for _ in range(20):
            pending = self.bus.pending_tasks()
            if not pending:
                # One more turn of the loop for a task created by a callback.
                await asyncio.sleep(0)
                if not self.bus.pending_tasks():
                    return
                continue
            await asyncio.gather(*pending, return_exceptions=True)

    async def notifications(self, entity_id: uuid.UUID) -> list[Notification]:
        async with self.factory() as session:
            rows = await session.execute(
                select(Notification).where(Notification.entity_id == str(entity_id)).order_by(Notification.created_at)
            )
            return list(rows.scalars().all())


async def _user(session: AsyncSession, name: str, locale: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name=name,
        locale=locale,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        # One private bus for every module involved, so nothing else the
        # application subscribes at import time runs against this database.
        bus = EventBus()
        for module in (core_events, variations_service, changeorders_service, notifications_service, sr, dispatcher):
            monkeypatch.setattr(module, "event_bus", bus)
        # The subscribers open their own sessions by design; point them at the
        # throwaway database so they read and write the rows made here.
        monkeypatch.setattr(sr, "async_session_factory", factory)
        monkeypatch.setattr(dispatcher, "async_session_factory", factory)
        mail = MemoryEmailBackend()
        monkeypatch.setattr("app.core.email.get_email_service", lambda: EmailService(mail))
        sr.register_site_register_notification_subscribers()
        bus.subscribe("notifications.dispatch.email", dispatcher._on_dispatch_email)

        async with factory() as session:
            manager = await _user(session, "Ayşe Yılmaz", "tr")
            originator = await _user(session, "Sam Reed", "en")
            project = Project(name=PROJECT_NAME, owner_id=manager.id, currency="TRY")
            session.add(project)
            await session.commit()
            yield _World(factory, bus, mail, project.id, manager.id, originator.id)


async def _a_draft_variation(world: _World) -> uuid.UUID:
    async with world.factory() as session:
        vr = await variations_service.VariationsService(session).create_request(
            VariationRequestCreate(
                project_id=world.project_id,
                title="Ek havalandırma kanalı",
                requested_by=str(world.originator_id),
                estimated_cost_impact=Decimal("12500.00"),
                currency="TRY",
            ),
            user_id=str(world.originator_id),
        )
        await session.commit()
        return vr.id


async def test_a_submitted_variation_is_announced_after_the_commit_and_not_before(world: _World) -> None:
    vr_id = await _a_draft_variation(world)

    async with world.factory() as session:
        service = variations_service.VariationsService(session)
        await service.transition_variation_request(vr_id, "submitted", user_id=str(world.originator_id))

        # The transition is flushed, not committed. Whatever was scheduled so
        # far has now run, on its own connection.
        await world.settle()
        assert await world.notifications(vr_id) == [], "announced before the commit made it true"
        assert world.mail.sent == []

        await session.commit()

    await world.settle()
    rows = await world.notifications(vr_id)
    # The request names nobody as holding the ball, so the project's manager
    # is told; the originator, who submitted it, is not.
    assert [(r.user_id, r.notification_type) for r in rows] == [(world.manager_id, "variation_submitted")]
    row = rows[0]
    assert row.title_key == "notifications.variation.submitted.title"
    assert row.body_context["project"] == PROJECT_NAME
    assert row.body_context["code"].startswith("VR")

    # The manager reads Turkish: the same stored row, in her language.
    title, body, _ = reader_text(row.title_key, row.body_key, row.body_context, "tr")
    assert title == f"İlave İş karar bekliyor: {row.body_context['code']}"
    assert "Kule Projesi projesinde" in body and "karar bekleniyor" in body

    # And her e-mail was written in Turkish, under a subject that names the
    # project and the record.
    assert len(world.mail.sent) == 1
    message = world.mail.sent[0]
    assert message.subject == f"[{PROJECT_NAME}] İlave İş karar bekliyor: {row.body_context['code']}"
    assert "Merhaba Ayşe Yılmaz," in message.html_body


async def test_a_rolled_back_submission_announces_nothing(world: _World) -> None:
    vr_id = await _a_draft_variation(world)

    async with world.factory() as session:
        service = variations_service.VariationsService(session)
        await service.transition_variation_request(vr_id, "submitted", user_id=str(world.originator_id))
        await session.rollback()

    await world.settle()
    assert await world.notifications(vr_id) == []
    assert world.mail.sent == []


async def test_a_decision_goes_to_the_originator_and_never_to_whoever_decided(world: _World) -> None:
    vr_id = await _a_draft_variation(world)
    async with world.factory() as session:
        service = variations_service.VariationsService(session)
        await service.transition_variation_request(vr_id, "submitted", user_id=str(world.originator_id))
        await session.commit()
    await world.settle()

    async with world.factory() as session:
        service = variations_service.VariationsService(session)
        await service.transition_variation_request(
            vr_id, "rejected", user_id=str(world.manager_id), decision_notes="Birim fiyat analizi eksik"
        )
        await session.commit()
    await world.settle()

    rejected = [r for r in await world.notifications(vr_id) if r.notification_type == "variation_rejected"]
    assert [r.user_id for r in rejected] == [world.originator_id]
    assert rejected[0].body_key == "notifications.variation.rejected_reason.body"
    assert rejected[0].body_context["reason"] == "Birim fiyat analizi eksik"


async def test_a_muted_recipient_gets_neither_the_row_nor_the_mail(world: _World) -> None:
    async with world.factory() as session:
        for channel in ("inapp", "email"):
            session.add(
                NotificationPreference(
                    user_id=world.manager_id,
                    event_type="variations.notify.submitted",
                    channel=channel,
                    enabled=False,
                    digest="realtime",
                )
            )
        await session.commit()
    vr_id = await _a_draft_variation(world)

    async with world.factory() as session:
        service = variations_service.VariationsService(session)
        await service.transition_variation_request(vr_id, "submitted", user_id=str(world.originator_id))
        await session.commit()
    await world.settle()

    assert await world.notifications(vr_id) == []
    assert world.mail.sent == []


async def test_a_change_order_tells_its_approver_then_its_submitter(world: _World) -> None:
    async with world.factory() as session:
        service = changeorders_service.ChangeOrderService(session)
        order = await service.create_order(ChangeOrderCreate(project_id=world.project_id, title="Pano yer değişikliği"))
        await session.commit()
        order_id = order.id

    async with world.factory() as session:
        service = changeorders_service.ChangeOrderService(session)
        await service.submit_order(order_id, str(world.originator_id))
        await world.settle()
        assert await world.notifications(order_id) == [], "announced before the commit made it true"
        await session.commit()
    await world.settle()

    awaiting = await world.notifications(order_id)
    assert [(r.user_id, r.notification_type) for r in awaiting] == [(world.manager_id, "changeorder_awaiting_approval")]

    # The manager is then named first approver of a chain: the same person,
    # asked for the same decision, is not asked a second time.
    async with world.factory() as session:
        service = changeorders_service.ChangeOrderService(session)
        await service.start_approval_chain(order_id, [world.manager_id])
        await session.commit()
    await world.settle()
    assert len(await world.notifications(order_id)) == 1

    async with world.factory() as session:
        service = changeorders_service.ChangeOrderService(session)
        await service.advance_approval(order_id, str(world.manager_id), "rejected", comments="Kapsam belirsiz")
        await session.commit()
    await world.settle()

    decided = [r for r in await world.notifications(order_id) if r.notification_type == "changeorder_rejected"]
    assert [r.user_id for r in decided] == [world.originator_id]
    title, _, _ = reader_text(decided[0].title_key, decided[0].body_key, decided[0].body_context, "en")
    assert title == f"Change order rejected: {decided[0].body_context['code']}"
