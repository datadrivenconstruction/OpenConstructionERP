# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for the project tax profile."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project_tax.models import ProjectTaxProfile


async def get_for_project(session: AsyncSession, project_id: uuid.UUID) -> ProjectTaxProfile | None:
    """The stored profile of one project, or ``None``."""
    stmt = select(ProjectTaxProfile).where(ProjectTaxProfile.project_id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def save(session: AsyncSession, row: ProjectTaxProfile) -> ProjectTaxProfile:
    """Insert or update ``row`` and flush, so the caller sees its id."""
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row
