# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets data access."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.haul_tickets.models import HaulInvoice, HaulMaterial, HaulRate, HaulSettings, HaulTicket


class HaulRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_ticket(self, ticket_id: uuid.UUID) -> HaulTicket | None:
        return await self.session.get(HaulTicket, ticket_id)

    async def by_token(self, token: str) -> HaulTicket | None:
        stmt = select(HaulTicket).where(HaulTicket.qr_token == token)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_tickets(
        self,
        project_id: uuid.UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
        haulier: str | None = None,
        haul_type: str | None = None,
        search: str | None = None,
    ) -> list[HaulTicket]:
        stmt = select(HaulTicket).where(HaulTicket.project_id == project_id)
        if date_from:
            stmt = stmt.where(HaulTicket.ticket_date >= date_from)
        if date_to:
            stmt = stmt.where(HaulTicket.ticket_date <= date_to)
        if status:
            stmt = stmt.where(HaulTicket.status == status)
        if haulier:
            stmt = stmt.where(HaulTicket.haulier_name == haulier)
        if haul_type:
            stmt = stmt.where(HaulTicket.haul_type == haul_type)
        if search:
            like = f"%{search.strip()}%"
            stmt = stmt.where(
                HaulTicket.ticket_number.ilike(like)
                | HaulTicket.plate.ilike(like)
                | HaulTicket.material_name.ilike(like)
            )
        stmt = stmt.order_by(HaulTicket.ticket_date.desc(), HaulTicket.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def same_number_count(self, row: HaulTicket) -> int:
        if not row.ticket_number:
            return 0
        stmt = select(func.count()).where(
            HaulTicket.project_id == row.project_id,
            func.lower(HaulTicket.haulier_name) == row.haulier_name.lower(),
            func.upper(HaulTicket.ticket_number) == row.ticket_number.upper(),
            HaulTicket.id != row.id,
            HaulTicket.status != "rejected",
        )
        return int((await self.session.execute(stmt)).scalar() or 0)

    async def dedupe_rows(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = select(
            HaulTicket.haulier_name, HaulTicket.ticket_number, HaulTicket.plate, HaulTicket.time_out, HaulTicket.net_t
        ).where(HaulTicket.project_id == project_id, HaulTicket.status != "rejected")
        return [
            {"haulier_name": r[0], "ticket_number": r[1], "plate": r[2], "time_out": r[3], "net_t": r[4]}
            for r in (await self.session.execute(stmt)).all()
        ]

    async def add(self, row: Any) -> Any:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: Any) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def settings(self, project_id: uuid.UUID) -> HaulSettings | None:
        stmt = select(HaulSettings).where(HaulSettings.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def rates(self, project_id: uuid.UUID, *, offset: int = 0, limit: int | None = None) -> list[HaulRate]:
        stmt = (
            select(HaulRate)
            .where(HaulRate.project_id == project_id)
            .order_by(HaulRate.haulier_name, HaulRate.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_rates(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(HaulRate).where(HaulRate.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def materials(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int | None = None
    ) -> list[HaulMaterial]:
        stmt = (
            select(HaulMaterial)
            .where(HaulMaterial.project_id == project_id)
            .order_by(HaulMaterial.code, HaulMaterial.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def material_codes(self, project_id: uuid.UUID) -> list[str]:
        stmt = select(HaulMaterial.code).where(HaulMaterial.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def invoices(self, project_id: uuid.UUID, *, offset: int = 0, limit: int | None = None) -> list[HaulInvoice]:
        stmt = (
            select(HaulInvoice)
            .where(HaulInvoice.project_id == project_id)
            .order_by(HaulInvoice.created_at.desc(), HaulInvoice.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_invoices(self, project_id: uuid.UUID) -> int:
        stmt = select(func.count()).select_from(HaulInvoice).where(HaulInvoice.project_id == project_id)
        return int((await self.session.execute(stmt)).scalar_one())
