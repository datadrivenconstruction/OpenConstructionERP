"""Webhook Leads data access layer."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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
    if not fields:
        return
    stmt = update(model).where(model.id == pk).values(**fields)
    await session.execute(stmt)
    await session.flush()
    session.expire_all()


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
    ) -> tuple[list[WebhookSource], int]:
        base = select(WebhookSource)
        if is_active is not None:
            base = base.where(WebhookSource.is_active == is_active)

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
    ) -> tuple[list[WebhookLog], int]:
        base = select(WebhookLog)
        if source_id is not None:
            base = base.where(WebhookLog.source_id == source_id)
        if status is not None:
            base = base.where(WebhookLog.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(WebhookLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, log: WebhookLog) -> WebhookLog:
        self.session.add(log)
        await self.session.flush()
        return log
