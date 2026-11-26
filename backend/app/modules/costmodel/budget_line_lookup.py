# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Whether a budget line a purchase order or subcontract names belongs to its project.

Purchase-order items and subcontract agreements book their commitment to one
budget line (cost code x cost type). Both modules check the pick here, so the
rule "the line must be on the same project" is written once.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import BudgetLine


async def budget_line_on_project(session: AsyncSession, budget_line_id: uuid.UUID, project_id: uuid.UUID) -> bool:
    """True when ``budget_line_id`` is a budget line of ``project_id``."""
    found = await session.execute(
        select(BudgetLine.id).where(BudgetLine.id == budget_line_id, BudgetLine.project_id == project_id).limit(1)
    )
    return found.scalar_one_or_none() is not None
