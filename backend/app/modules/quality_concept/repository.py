# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the quality concept: every read is scoped by ``project_id``.

A child row is fetched by ``(project_id, id)`` only, so an id from another
project reads as missing and the service answers 404 (IDOR).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality_concept.models import (
    AcceptanceEffect,
    EvidenceLink,
    QualityConcept,
    StageProgress,
)

T = TypeVar("T")


class QualityConceptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def concept(self, project_id: uuid.UUID, *, lock: bool = False) -> QualityConcept | None:
        stmt = select(QualityConcept).where(QualityConcept.project_id == project_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get(self, model: type[T], project_id: uuid.UUID, row_id: uuid.UUID, *, lock: bool = False) -> T | None:
        stmt = select(model).where(model.id == row_id).where(model.project_id == project_id)  # type: ignore[attr-defined]
        if lock:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(self, model: type[T], project_id: uuid.UUID, *order: Any, **filters: Any) -> list[T]:
        stmt = select(model).where(model.project_id == project_id)  # type: ignore[attr-defined]
        for name, value in filters.items():
            stmt = stmt.where(getattr(model, name) == value)
        if order:
            stmt = stmt.order_by(*order)
        else:
            stmt = stmt.order_by(model.created_at)  # type: ignore[attr-defined]
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, row: T) -> T:
        self.session.add(row)
        await self.session.flush()
        return row

    async def remove(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def links_for(self, owner_kind: str, owner_ids: Sequence[uuid.UUID]) -> list[EvidenceLink]:
        if not owner_ids:
            return []
        stmt = (
            select(EvidenceLink)
            .where(EvidenceLink.owner_kind == owner_kind)
            .where(EvidenceLink.owner_id.in_(list(owner_ids)))
            .order_by(EvidenceLink.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def drop_links(self, owner_kind: str, owner_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(EvidenceLink).where(EvidenceLink.owner_kind == owner_kind).where(EvidenceLink.owner_id == owner_id)
        )

    async def progress_for_gate(self, gate_id: uuid.UUID) -> StageProgress | None:
        stmt = select(StageProgress).where(StageProgress.hold_gate_id == gate_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def effects_of(self, unit_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[AcceptanceEffect]]:
        """The effects of many units in one read, each list in the order ``effects`` gives."""
        out: dict[uuid.UUID, list[AcceptanceEffect]] = {u: [] for u in unit_ids}
        if not unit_ids:
            return out
        stmt = (
            select(AcceptanceEffect).where(AcceptanceEffect.unit_id.in_(unit_ids)).order_by(AcceptanceEffect.created_at)
        )
        for effect in (await self.session.execute(stmt)).scalars():
            out[effect.unit_id].append(effect)
        return out

    async def effects(self, unit_id: uuid.UUID) -> list[AcceptanceEffect]:
        stmt = select(AcceptanceEffect).where(AcceptanceEffect.unit_id == unit_id).order_by(AcceptanceEffect.created_at)
        return list((await self.session.execute(stmt)).scalars().all())
