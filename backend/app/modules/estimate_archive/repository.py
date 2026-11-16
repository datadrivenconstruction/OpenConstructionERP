# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for sealed estimates. Inserts and reads only; seals are never deleted."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.estimate_archive.models import (
    EstimateSeal,
    EstimateSealAttachment,
    EstimateSealReceipt,
    SealDerivation,
    SealEvent,
    SealOpening,
)


class EstimateArchiveRepository:
    """Queries over the six estimate archive tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, row: object) -> None:
        self.session.add(row)
        await self.session.flush()

    async def get_seal(self, seal_id: uuid.UUID) -> EstimateSeal | None:
        return await self.session.get(EstimateSeal, seal_id)

    async def list_seals(
        self,
        *,
        project_ids: Iterable[uuid.UUID] | None,
        project_id: uuid.UUID | None = None,
        contract_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[EstimateSeal]:
        stmt = select(EstimateSeal).order_by(EstimateSeal.sealed_at.desc())
        if project_ids is not None:
            stmt = stmt.where(EstimateSeal.project_id.in_(list(project_ids)))
        if project_id is not None:
            stmt = stmt.where(EstimateSeal.project_id == project_id)
        if contract_id is not None:
            stmt = stmt.where(EstimateSeal.contract_id == contract_id)
        if status:
            stmt = stmt.where(EstimateSeal.status == status)
        return list((await self.session.execute(stmt)).scalars().all())

    async def superseding(self, seal_id: uuid.UUID) -> EstimateSeal | None:
        stmt = select(EstimateSeal).where(EstimateSeal.supersedes_id == seal_id).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def seals_for_boq(self, boq_id: uuid.UUID) -> list[EstimateSeal]:
        stmt = select(EstimateSeal).where(EstimateSeal.source_boq_id == boq_id).order_by(EstimateSeal.sealed_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def attachments(self, seal_id: uuid.UUID) -> list[EstimateSealAttachment]:
        stmt = select(EstimateSealAttachment).where(EstimateSealAttachment.seal_id == seal_id)
        return list((await self.session.execute(stmt.order_by(EstimateSealAttachment.name))).scalars().all())

    async def receipts(self, seal_id: uuid.UUID) -> list[EstimateSealReceipt]:
        stmt = select(EstimateSealReceipt).where(EstimateSealReceipt.seal_id == seal_id)
        return list((await self.session.execute(stmt.order_by(EstimateSealReceipt.created_at))).scalars().all())

    async def openings(
        self, *, seal_ids: Iterable[uuid.UUID] | None = None, status: str | None = None
    ) -> list[SealOpening]:
        stmt = select(SealOpening).order_by(SealOpening.requested_at.desc())
        if seal_ids is not None:
            stmt = stmt.where(SealOpening.seal_id.in_(list(seal_ids)))
        if status:
            stmt = stmt.where(SealOpening.status == status)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_opening(self, opening_id: uuid.UUID) -> SealOpening | None:
        return await self.session.get(SealOpening, opening_id)

    async def opening_counts(self, seal_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not seal_ids:
            return {}
        stmt = (
            select(SealOpening.seal_id, func.count())
            .where(SealOpening.seal_id.in_(seal_ids))
            .group_by(SealOpening.seal_id)
        )
        return {row[0]: int(row[1]) for row in (await self.session.execute(stmt)).all()}

    async def events(
        self,
        *,
        seal_ids: Iterable[uuid.UUID] | None,
        event_type: str | None = None,
        actor_id: uuid.UUID | None = None,
        limit: int = 500,
    ) -> list[SealEvent]:
        stmt = select(SealEvent).order_by(SealEvent.created_at.desc())
        if seal_ids is not None:
            stmt = stmt.where(SealEvent.seal_id.in_(list(seal_ids)))
        if event_type:
            stmt = stmt.where(SealEvent.event_type == event_type)
        if actor_id is not None:
            stmt = stmt.where(SealEvent.actor_id == actor_id)
        return list((await self.session.execute(stmt.limit(limit))).scalars().all())

    async def derivations(
        self, *, seal_id: uuid.UUID | None = None, variation_request_id: uuid.UUID | None = None
    ) -> list[SealDerivation]:
        stmt = select(SealDerivation).order_by(SealDerivation.created_at.desc())
        if seal_id is not None:
            stmt = stmt.where(SealDerivation.seal_id == seal_id)
        if variation_request_id is not None:
            stmt = stmt.where(SealDerivation.variation_request_id == variation_request_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_derivation(self, derivation_id: uuid.UUID) -> SealDerivation | None:
        return await self.session.get(SealDerivation, derivation_id)
