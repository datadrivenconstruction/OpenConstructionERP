# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing data access."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leasing.models import Lease, LeaseEvent, RentScheduleLine

HOLDING_STATUSES = ("active", "notice")


class LeasingRepository:
    """Queries over leases, schedule lines and events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, lease_id: uuid.UUID) -> Lease | None:
        return await self.session.get(Lease, lease_id)

    async def list_leases(
        self,
        project_ids: Sequence[uuid.UUID],
        *,
        status: str | None = None,
        unit_ref: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Lease]:
        stmt = select(Lease).where(Lease.project_id.in_(list(project_ids)))
        if status:
            stmt = stmt.where(Lease.status == status)
        if unit_ref:
            stmt = stmt.where(Lease.unit_ref == unit_ref)
        stmt = stmt.order_by(Lease.code).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def code_taken(self, project_id: uuid.UUID, code: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(Lease.id).where(Lease.project_id == project_id, Lease.code == code)
        if exclude is not None:
            stmt = stmt.where(Lease.id != exclude)
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def overlapping(
        self, unit_kind: str, unit_ref: str, start: date, end: date, exclude: uuid.UUID | None
    ) -> list[Lease]:
        """Leases that hold the unit (active or notice) in a period overlapping ``start..end``."""
        stmt = select(Lease).where(
            Lease.unit_kind == unit_kind,
            Lease.unit_ref == unit_ref,
            Lease.status.in_(HOLDING_STATUSES),
            Lease.start_date <= end,
            Lease.end_date >= start,
        )
        if exclude is not None:
            stmt = stmt.where(Lease.id != exclude)
        return list((await self.session.execute(stmt)).scalars().all())

    async def lines(self, lease_id: uuid.UUID) -> list[RentScheduleLine]:
        stmt = (
            select(RentScheduleLine)
            .where(RentScheduleLine.lease_id == lease_id)
            .order_by(RentScheduleLine.period_start)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def lines_for_leases(self, lease_ids: Sequence[uuid.UUID]) -> list[RentScheduleLine]:
        if not lease_ids:
            return []
        stmt = (
            select(RentScheduleLine)
            .where(RentScheduleLine.lease_id.in_(list(lease_ids)))
            .order_by(RentScheduleLine.period_start)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def events(self, lease_id: uuid.UUID) -> list[LeaseEvent]:
        stmt = select(LeaseEvent).where(LeaseEvent.lease_id == lease_id).order_by(LeaseEvent.created_at)
        return list((await self.session.execute(stmt)).scalars().all())

    async def review_rates(self, lease_id: uuid.UUID) -> dict[int, str]:
        """Recorded review rates by review number; the newest record of a number wins."""
        out: dict[int, str] = {}
        for ev in await self.events(lease_id):
            if ev.kind == "review" and isinstance(ev.payload, dict) and "review_number" in ev.payload:
                out[int(ev.payload["review_number"])] = str(ev.payload.get("rate", "0"))
        return out
