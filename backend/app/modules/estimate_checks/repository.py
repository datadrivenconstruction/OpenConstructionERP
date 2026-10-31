# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check data access."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.estimate_checks.models import EstimateCheckAcceptance, EstimateCheckSettings, EstimateCheckUserPref


class EstimateCheckRepository:
    """Settings, preferences and acceptances."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_settings(self, tenant_key: str) -> EstimateCheckSettings | None:
        stmt = select(EstimateCheckSettings).where(EstimateCheckSettings.tenant_key == tenant_key)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def save_settings(self, tenant_key: str, settings: dict, user_id: str) -> EstimateCheckSettings:
        row = await self.get_settings(tenant_key)
        if row is None:
            row = EstimateCheckSettings(tenant_key=tenant_key, settings_=settings, updated_by=user_id)
            self.session.add(row)
        else:
            row.settings_ = settings
            row.updated_by = user_id
        await self.session.flush()
        return row

    async def get_pref(self, user_id: str) -> EstimateCheckUserPref | None:
        stmt = select(EstimateCheckUserPref).where(EstimateCheckUserPref.user_id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def save_pref(self, user_id: str, mode: str) -> EstimateCheckUserPref:
        row = await self.get_pref(user_id)
        if row is None:
            row = EstimateCheckUserPref(user_id=user_id, display_mode=mode)
            self.session.add(row)
        else:
            row.display_mode = mode
        await self.session.flush()
        return row

    async def list_acceptances(self, boq_id: uuid.UUID) -> list[EstimateCheckAcceptance]:
        stmt = select(EstimateCheckAcceptance).where(EstimateCheckAcceptance.boq_id == boq_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert_acceptance(
        self, boq_id: uuid.UUID, kpi_id: str, reason: str, status: str, value: str | None, user_id: str
    ) -> EstimateCheckAcceptance:
        stmt = select(EstimateCheckAcceptance).where(
            EstimateCheckAcceptance.boq_id == boq_id, EstimateCheckAcceptance.kpi_id == kpi_id
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = EstimateCheckAcceptance(boq_id=boq_id, kpi_id=kpi_id, accepted_by=user_id, reason=reason)
            self.session.add(row)
        row.reason = reason
        row.status_at_accept = status
        row.value_at_accept = value
        row.accepted_by = user_id
        await self.session.flush()
        return row

    async def delete_acceptance(self, boq_id: uuid.UUID, kpi_id: str) -> int:
        stmt = delete(EstimateCheckAcceptance).where(
            EstimateCheckAcceptance.boq_id == boq_id, EstimateCheckAcceptance.kpi_id == kpi_id
        )
        res = await self.session.execute(stmt)
        return int(res.rowcount or 0)
