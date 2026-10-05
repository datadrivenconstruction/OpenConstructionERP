# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a notification about a foreign project is dropped (gate E8).

This is the backstop behind the per-module gates. Many subscribers take their
recipient from an event payload, and not every write path that feeds them is
gated yet. In academy mode a notification whose ``metadata.project_id`` names a
project the recipient cannot open is dropped with a log line instead of being
stored, and a channel dispatch (email, webhook) whose payload names such a
project is suppressed. A notification that names no project is delivered as
before, and with the flag off nothing changes.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

CREATED = "notifications.notification.created"
EMAIL = "notifications.dispatch.email"


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


async def _rows(session, user) -> int:
    stmt = select(func.count(Notification.id)).where(Notification.user_id == user.id)
    return (await session.execute(stmt)).scalar_one()


def _to(events, name: str) -> list[str]:
    return [data["user_id"] for n, data in events if n == name]


async def _notify(service, user, project):
    return await service.create(
        user_id=user.id,
        notification_type="task_assigned",
        title_key="notifications.task.assigned.title",
        metadata={"project_id": str(project.id)},
    )


async def test_academy_on_a_notification_about_a_foreign_project_is_dropped(pg_session, academy, events) -> None:
    academy(True)
    project, _alice, bob, carol = await _setup(pg_session)
    service = NotificationService(pg_session)

    assert await _notify(service, bob, project) is None
    sent = await service.notify_users(
        [bob.id, carol.id],
        "task_assigned",
        "notifications.task.assigned.title",
        metadata={"project_id": str(project.id)},
    )
    assert [n.user_id for n in sent] == [carol.id]
    assert await _rows(pg_session, bob) == 0
    assert _to(events, CREATED) == [str(carol.id)]

    outcome = await service.enqueue_or_dispatch("task_assigned", bob.id, {"project_id": str(project.id)}, "email")
    assert outcome == "suppressed"
    assert _to(events, EMAIL) == []


async def test_academy_on_members_and_projectless_notifications_still_arrive(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, carol = await _setup(pg_session)
    service = NotificationService(pg_session)

    assert (await _notify(service, carol, project)) is not None
    assert (await _notify(service, alice, project)) is not None
    # No project named: the backstop has nothing to judge and delivers.
    await service.create(user_id=bob.id, notification_type="system", title_key="notifications.system.title")
    assert await _rows(pg_session, bob) == 1

    outcome = await service.enqueue_or_dispatch("task_assigned", carol.id, {"project_id": str(project.id)}, "email")
    assert outcome == "dispatched"
    assert _to(events, EMAIL) == [str(carol.id)]


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, _alice, bob, carol = await _setup(pg_session)
    service = NotificationService(pg_session)

    assert (await _notify(service, bob, project)) is not None
    sent = await service.notify_users(
        [bob.id, carol.id],
        "task_assigned",
        "notifications.task.assigned.title",
        metadata={"project_id": str(project.id)},
    )
    assert [n.user_id for n in sent] == [bob.id, carol.id]
    assert await _rows(pg_session, bob) == 2

    outcome = await service.enqueue_or_dispatch("task_assigned", bob.id, {"project_id": str(project.id)}, "email")
    assert outcome == "dispatched"
    assert _to(events, EMAIL) == [str(bob.id)]
