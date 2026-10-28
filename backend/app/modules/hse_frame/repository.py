# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the HSE frame: every read is scoped by ``project_id``.

A child row is fetched by ``(project_id, id)`` only, so an id from another
project reads as missing and the service answers 404 (IDOR).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hse_frame.models import HseFrame, HseLink

T = TypeVar("T")


class HseFrameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def frame(self, project_id: uuid.UUID, *, lock: bool = False) -> HseFrame | None:
        stmt = select(HseFrame).where(HseFrame.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, model: type[T], project_id: uuid.UUID, row_id: uuid.UUID) -> T | None:
        stmt = select(model).where(model.id == row_id).where(model.project_id == project_id)  # type: ignore[attr-defined]
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, model: type[T], project_id: uuid.UUID, *order: Any, **filters: Any) -> list[T]:
        stmt = select(model).where(model.project_id == project_id)  # type: ignore[attr-defined]
        for name, value in filters.items():
            stmt = stmt.where(getattr(model, name) == value)
        stmt = stmt.order_by(*(order or (model.created_at,)))  # type: ignore[attr-defined]
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: T) -> T:
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def links_for(self, project_id: uuid.UUID, item_ids: Sequence[uuid.UUID]) -> list[HseLink]:
        if not item_ids:
            return []
        stmt = (
            select(HseLink)
            .where(HseLink.project_id == project_id)
            .where(HseLink.item_id.in_(list(item_ids)))
            .order_by(HseLink.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def links_of_kind(self, project_id: uuid.UUID, kind: str) -> list[HseLink]:
        stmt = select(HseLink).where(HseLink.project_id == project_id).where(HseLink.link_kind == kind)
        return list((await self.session.execute(stmt)).scalars().all())
