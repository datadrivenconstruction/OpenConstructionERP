# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Drawing revision compare data access layer.

Owns the two compare tables only. Revision sources (takeoff, DWG takeoff,
documents) and follow-up targets (RFI, markups, BOQ) are reached by the
service through lazy imports so this module loads without them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.drawing_compare.models import DrawingChange, DrawingComparison


class ComparisonRepository:
    """Data access for :class:`DrawingComparison` and its changes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, comparison_id: uuid.UUID, *, with_changes: bool = False) -> DrawingComparison | None:
        """A compare by id, optionally with its change list loaded."""
        stmt = select(DrawingComparison).where(DrawingComparison.id == comparison_id)
        if with_changes:
            stmt = stmt.options(selectinload(DrawingComparison.changes))
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        ref_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DrawingComparison]:
        """Compares of a project, newest first, optionally those touching one revision."""
        stmt = select(DrawingComparison).where(DrawingComparison.project_id == project_id)
        if ref_id:
            stmt = stmt.where(or_(DrawingComparison.old_ref_id == ref_id, DrawingComparison.new_ref_id == ref_id))
        stmt = stmt.order_by(DrawingComparison.created_at.desc()).limit(limit).offset(offset)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for_project(self, project_id: uuid.UUID, *, ref_id: str | None = None) -> int:
        """Compares of a project that the ``ref_id`` filter matches."""
        stmt = select(func.count(DrawingComparison.id)).where(DrawingComparison.project_id == project_id)
        if ref_id:
            stmt = stmt.where(or_(DrawingComparison.old_ref_id == ref_id, DrawingComparison.new_ref_id == ref_id))
        return int((await self.session.execute(stmt)).scalar_one())

    async def add(self, comparison: DrawingComparison, changes: list[DrawingChange]) -> DrawingComparison:
        """Insert a compare with its changes in one flush."""
        self.session.add(comparison)
        await self.session.flush()
        for change in changes:
            change.comparison_id = comparison.id
            self.session.add(change)
        await self.session.flush()
        return comparison

    async def delete(self, comparison: DrawingComparison) -> None:
        """Delete a compare; its changes go with it."""
        await self.session.delete(comparison)
        await self.session.flush()

    async def get_change(self, change_id: uuid.UUID) -> DrawingChange | None:
        """A change by id."""
        return await self.session.get(DrawingChange, change_id)

    async def list_changes(self, comparison_id: uuid.UUID) -> list[DrawingChange]:
        """Every change of a compare in list order."""
        stmt = select(DrawingChange).where(DrawingChange.comparison_id == comparison_id).order_by(DrawingChange.seq)
        return list((await self.session.execute(stmt)).scalars().all())
