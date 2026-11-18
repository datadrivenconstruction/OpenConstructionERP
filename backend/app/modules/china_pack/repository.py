# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the China pack's fee profile."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.china_pack.models import ChinaFeeProfile


async def get_fee_profile(session: AsyncSession, project_id: uuid.UUID) -> ChinaFeeProfile | None:
    """The stored fee profile of one project, or ``None``."""
    stmt = select(ChinaFeeProfile).where(ChinaFeeProfile.project_id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def save_fee_profile(session: AsyncSession, row: ChinaFeeProfile) -> ChinaFeeProfile:
    """Insert or update ``row`` and flush."""
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row
