# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Two flushes over the same digest rows send the digest once.

The notification worker flushes every five minutes and the admin endpoint can
flush on demand. ``flush_digest_queue`` read the unsent rows, sent the digest,
and only then stamped ``sent_at``, so a second flush that read the rows before
the first one committed sent the same digest again.

The race needs two connections with real commits, which the savepoint-isolated
``pg_session`` cannot express: a second connection never sees its rows. The
first flush is left uncommitted while the second one starts, which is exactly
the window the old code sent twice in.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import event_bus
from app.modules.notifications.models import NotificationDigestQueue
from app.modules.notifications.service import NotificationService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def test_two_overlapping_flushes_send_one_digest(pg_engine, monkeypatch):
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    published: list[str] = []
    monkeypatch.setattr(
        event_bus, "publish_detached", lambda name, data=None, source_module=None: published.append(name)
    )

    user_id = uuid.uuid4()
    async with factory() as seed:
        seed.add(User(id=user_id, email=f"{uuid.uuid4().hex[:12]}@example.com", hashed_password="x"))
        await seed.flush()
        for _ in range(2):
            seed.add(
                NotificationDigestQueue(
                    user_id=user_id,
                    event_type="deadlines.punchlist.overdue",
                    channel="email",
                    payload={},
                    scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
        await seed.commit()

    try:
        async with factory() as first, factory() as second:
            assert await NotificationService(first).flush_digest_queue("email") == 2

            racing = asyncio.create_task(NotificationService(second).flush_digest_queue("email"))
            # Let the second flush reach the rows while the first still holds them.
            await asyncio.sleep(1.0)
            await first.commit()
            assert await racing == 0
            await second.commit()

        assert published.count("notifications.dispatch.email") == 1
    finally:
        async with factory() as cleanup:
            await cleanup.execute(delete(NotificationDigestQueue).where(NotificationDigestQueue.user_id == user_id))
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.commit()
