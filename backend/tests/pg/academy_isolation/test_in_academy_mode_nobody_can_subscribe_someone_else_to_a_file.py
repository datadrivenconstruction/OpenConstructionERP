# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode nobody can subscribe someone else to a file (gate E6).

A file subscription takes ``subscriber_user_id`` and ``subscriber_email`` from
the body. The router only checked that the caller can open the project, so one
learner could subscribe another learner's account, and every new revision in
the project then notified that account. In academy mode the subscriber must be
the caller or a project member (422 ``user_not_in_project``), and the email must
be the caller's own (422 ``subscriber_email_not_own``).

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import USER_NOT_IN_PROJECT
from app.modules.file_distribution.models import FileDistributionSubscription
from app.modules.file_distribution.router import create_subscription
from app.modules.file_distribution.schemas import SubscriptionCreate
from app.modules.file_distribution.service import on_file_new_revision
from app.modules.notifications.models import Notification
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return project, alice, bob, carol


async def _subscribe(session, caller, project, *, email: str, subscriber=None, file_kind: str = "*"):
    payload = SubscriptionCreate(
        project_id=project.id,
        file_kind=file_kind,
        subscriber_email=email,
        subscriber_user_id=subscriber.id if subscriber is not None else None,
    )
    return await create_subscription(payload, session=session, current_user_id=str(caller.id))


async def _subscriptions(session, project) -> int:
    stmt = select(func.count(FileDistributionSubscription.id)).where(
        FileDistributionSubscription.project_id == project.id
    )
    return (await session.execute(stmt)).scalar_one()


async def _notified(session, user) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.user_id == user.id, Notification.notification_type == "file_revision"
    )
    return (await session.execute(stmt)).scalar_one()


async def _new_revision(session, project) -> int:
    return await on_file_new_revision(
        session, project_id=project.id, file_kind="document", file_id="doc-1", canonical_name="A-101", version_number=2
    )


async def test_other_subscriber_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol = await _setup(pg_session)

    with pytest.raises(HTTPException) as caught:
        await _subscribe(pg_session, alice, project, email=alice.email, subscriber=bob)
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == USER_NOT_IN_PROJECT
    assert await _subscriptions(pg_session, project) == 0
    assert await _new_revision(pg_session, project) == 0
    assert await _notified(pg_session, bob) == 0


async def test_foreign_email_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, alice, bob, _carol = await _setup(pg_session)

    with pytest.raises(HTTPException) as caught:
        await _subscribe(pg_session, alice, project, email=bob.email)
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == "subscriber_email_not_own"
    assert await _subscriptions(pg_session, project) == 0


async def test_academy_on_a_learner_still_subscribes_themselves(pg_session, academy, events) -> None:
    academy(True)
    project, alice, _bob, carol = await _setup(pg_session)

    mine = await _subscribe(pg_session, alice, project, email=alice.email.upper())
    assert mine.subscriber_user_id == alice.id
    member = await _subscribe(pg_session, alice, project, email=alice.email, subscriber=carol, file_kind="document")
    assert member.subscriber_user_id == carol.id


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, alice, bob, _carol = await _setup(pg_session)

    sub = await _subscribe(pg_session, alice, project, email=bob.email, subscriber=bob)
    assert (sub.subscriber_user_id, sub.subscriber_email) == (bob.id, bob.email)
    assert await _new_revision(pg_session, project) == 1
    assert await _notified(pg_session, bob) == 1
