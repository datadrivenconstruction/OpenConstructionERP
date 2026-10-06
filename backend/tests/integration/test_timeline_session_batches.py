# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Real PostgreSQL savepoints/commits, isolated by an outer test transaction."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.audit_log import ActivityLog, AuditContext, reset_audit_context, set_audit_context
from app.core.events import Event
from app.core.rls import reset_request_tenant, set_request_tenant
from app.modules.timeline import events as timeline
from tests._pg import transactional_session


async def test_batched_timeline_persists_each_row_under_its_original_context(monkeypatch):
    async with transactional_session() as outer:
        factory = async_sessionmaker(bind=outer.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
        opened = active = peak = 0

        @asynccontextmanager
        async def counted_factory():
            nonlocal opened, active, peak
            opened += 1
            active += 1
            peak = max(peak, active)
            try:
                async with factory() as session:
                    yield session
            finally:
                active -= 1

        monkeypatch.setattr(timeline, "async_session_factory", counted_factory)
        tasks = []
        expected = {}
        for group in range(2):
            tenant, actor = str(uuid.uuid4()), str(uuid.uuid4())
            context = AuditContext(tenant_id=tenant, actor_id=actor, request_id=f"batch-{group}")
            token = set_audit_context(context)
            tenant_token = set_request_tenant(tenant)
            try:
                for _ in range(225):
                    entity = str(uuid.uuid4())
                    event = Event(name="ncr.created", data={"ncr_id": entity})
                    expected[event.id] = (entity, tenant, actor, f"batch-{group}")
                    tasks.append(asyncio.create_task(timeline._record_event(event)))
            finally:
                reset_request_tenant(tenant_token)
                reset_audit_context(token)
        await asyncio.gather(*tasks)
        rows = (await outer.execute(select(ActivityLog))).scalars().all()
        actual = {
            row.metadata_["event_id"]: (row.entity_id, str(row.tenant_id), str(row.actor_id), row.request_id)
            for row in rows
            if row.metadata_.get("event_id") in expected
        }
        assert actual == expected
        assert (opened, peak, active) == (4, 1, 0)


async def test_a_failed_timeline_write_rolls_back_only_that_event(monkeypatch):
    async with transactional_session() as outer:
        factory = async_sessionmaker(bind=outer.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
        monkeypatch.setattr(timeline, "async_session_factory", factory)
        real_log = timeline.log_activity

        async def reject_middle(session, **kwargs):
            await real_log(session, **kwargs)
            if kwargs["metadata"]["number"] == 2:
                raise RuntimeError("failure after the audit flush")

        monkeypatch.setattr(timeline, "log_activity", reject_middle)
        events = [Event(name="ncr.created", data={"ncr_id": str(uuid.uuid4()), "number": n}) for n in (1, 2, 3)]
        await asyncio.gather(*(timeline._record_event(event) for event in events))
        rows = (await outer.execute(select(ActivityLog))).scalars().all()
        ids = {row.metadata_.get("event_id") for row in rows}
        assert events[0].id in ids
        assert events[1].id not in ids
        assert events[2].id in ids
