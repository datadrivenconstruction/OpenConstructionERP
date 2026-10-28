# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Webhook Leads data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.webhook_leads.models import (
    PayloadMapping,
    WebhookLog,
    WebhookSource,
)


async def _update_fields(
    session: AsyncSession,
    model: Any,
    pk: uuid.UUID,
    **fields: Any,
) -> None:
    """Update one row by primary key and keep the identity map honest.

    Expiring the whole session would be right for the row that changed and
    wrong for every other object the caller still holds. Under asyncio the next
    attribute read on any of them is a lazy load attempted from async code,
    which raises MissingGreenlet rather than quietly re-fetching. So the values
    we already know are written straight onto the instance, and only the ones
    the database had to compute are expired so they get read back.
    """
    if not fields:
        return
    stmt = update(model).where(model.id == pk).values(**fields)
    await session.execute(stmt)
    await session.flush()
    instance = session.identity_map.get(identity_key(model, pk))
    if instance is None:
        return
    computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
    for name, value in fields.items():
        if name not in computed:
            set_committed_value(instance, name, value)
    if computed:
        session.expire(instance, computed)


# ── WebhookSource ─────────────────────────────────────────────────────────


class WebhookSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, source_id: uuid.UUID) -> WebhookSource | None:
        return await self.session.get(WebhookSource, source_id)

    async def get_by_slug(self, slug: str) -> WebhookSource | None:
        stmt = select(WebhookSource).where(WebhookSource.slug == slug)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        is_active: bool | None = None,
        allowed_ids: set[uuid.UUID] | None = None,
    ) -> tuple[list[WebhookSource], int]:
        """List sources, optionally scoped to ``allowed_ids``.

        ``allowed_ids`` is the set of source ids the caller may see; pass
        ``None`` for an unrestricted (admin) listing. An empty set yields no
        rows - the safe default for a non-admin caller with no own sources.
        """
        base = select(WebhookSource)
        if is_active is not None:
            base = base.where(WebhookSource.is_active == is_active)
        if allowed_ids is not None:
            base = base.where(WebhookSource.id.in_(allowed_ids))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(WebhookSource.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, source: WebhookSource) -> WebhookSource:
        self.session.add(source)
        await self.session.flush()
        return source

    async def update_fields(self, source_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, WebhookSource, source_id, **fields)

    async def delete(self, source_id: uuid.UUID) -> None:
        source = await self.get_by_id(source_id)
        if source is not None:
            await self.session.delete(source)
            await self.session.flush()


# ── PayloadMapping ────────────────────────────────────────────────────────


class PayloadMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, mapping_id: uuid.UUID) -> PayloadMapping | None:
        return await self.session.get(PayloadMapping, mapping_id)

    async def list_for_source(self, source_id: uuid.UUID) -> list[PayloadMapping]:
        stmt = (
            select(PayloadMapping)
            .where(PayloadMapping.source_id == source_id)
            .order_by(PayloadMapping.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, mapping: PayloadMapping) -> PayloadMapping:
        self.session.add(mapping)
        await self.session.flush()
        return mapping

    async def update_fields(self, mapping_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, PayloadMapping, mapping_id, **fields)

    async def delete(self, mapping_id: uuid.UUID) -> None:
        mapping = await self.get_by_id(mapping_id)
        if mapping is not None:
            await self.session.delete(mapping)
            await self.session.flush()


# ── WebhookLog ────────────────────────────────────────────────────────────


class WebhookLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, log_id: uuid.UUID) -> WebhookLog | None:
        return await self.session.get(WebhookLog, log_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        source_id: uuid.UUID | None = None,
        status: str | None = None,
        allowed_source_ids: set[uuid.UUID] | None = None,
    ) -> tuple[list[WebhookLog], int]:
        """List logs, optionally scoped to ``allowed_source_ids``.

        ``allowed_source_ids`` is the set of source ids whose logs the caller
        may read; pass ``None`` for an unrestricted (admin) listing. An empty
        set yields no rows. Logs whose ``source_id`` is NULL (probes against
        an unknown slug, never tied to a configured source) are only visible
        to admins, since they carry no owner to scope by.
        """
        base = select(WebhookLog)
        if source_id is not None:
            base = base.where(WebhookLog.source_id == source_id)
        if status is not None:
            base = base.where(WebhookLog.status == status)
        if allowed_source_ids is not None:
            base = base.where(WebhookLog.source_id.in_(allowed_source_ids))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(WebhookLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, log: WebhookLog) -> WebhookLog:
        self.session.add(log)
        await self.session.flush()
        return log
