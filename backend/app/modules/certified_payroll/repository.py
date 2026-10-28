# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Async SQLAlchemy repositories for the Certified Payroll module."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.certified_payroll.models import (
    CertifiedPayrollLine,
    CertifiedPayrollWeek,
    WageClassification,
    WageDetermination,
    WorkerClassificationAssignment,
)


class WageDeterminationRepository:
    """Data access for WageDetermination and its classifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, determination: WageDetermination) -> WageDetermination:
        self.session.add(determination)
        await self.session.flush()
        await self.session.refresh(determination)
        return determination

    async def get_by_id(self, determination_id: uuid.UUID) -> WageDetermination | None:
        # ``classifications`` is a selectin relationship, so a plain get already
        # loads it; the explicit option keeps that true if the strategy changes.
        stmt = (
            select(WageDetermination)
            .where(WageDetermination.id == determination_id)
            .options(selectinload(WageDetermination.classifications))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[WageDetermination], int]:
        base = select(WageDetermination).where(WageDetermination.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            base.options(selectinload(WageDetermination.classifications))
            .order_by(WageDetermination.authority, WageDetermination.identifier)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all()), int(total)

    async def update_fields(self, determination_id: uuid.UUID, **fields: Any) -> None:
        determination = await self.session.get(WageDetermination, determination_id)
        if determination is None:
            return
        for key, value in fields.items():
            attr = "metadata_" if key == "metadata" else key
            setattr(determination, attr, value)
        await self.session.flush()

    async def delete(self, determination: WageDetermination) -> None:
        await self.session.delete(determination)
        await self.session.flush()


class WageClassificationRepository:
    """Data access for WageClassification."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, classification: WageClassification) -> WageClassification:
        self.session.add(classification)
        await self.session.flush()
        await self.session.refresh(classification)
        return classification

    async def get_by_id(self, classification_id: uuid.UUID) -> WageClassification | None:
        return await self.session.get(WageClassification, classification_id)

    async def list_by_ids(self, ids: list[uuid.UUID]) -> list[WageClassification]:
        """Load several classifications in one query (no N+1 from the pivot)."""
        if not ids:
            return []
        stmt = select(WageClassification).where(WageClassification.id.in_(ids))
        return list((await self.session.execute(stmt)).scalars().all())

    async def delete(self, classification: WageClassification) -> None:
        await self.session.delete(classification)
        await self.session.flush()


class AssignmentRepository:
    """Data access for WorkerClassificationAssignment."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, assignment: WorkerClassificationAssignment) -> WorkerClassificationAssignment:
        self.session.add(assignment)
        await self.session.flush()
        await self.session.refresh(assignment)
        return assignment

    async def get_by_id(self, assignment_id: uuid.UUID) -> WorkerClassificationAssignment | None:
        return await self.session.get(WorkerClassificationAssignment, assignment_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[WorkerClassificationAssignment], int]:
        base = select(WorkerClassificationAssignment).where(WorkerClassificationAssignment.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(WorkerClassificationAssignment.worker_name).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def list_all_for_project(self, project_id: uuid.UUID) -> list[WorkerClassificationAssignment]:
        """Every assignment on a project, for resolving a whole week in one pass."""
        stmt = select(WorkerClassificationAssignment).where(WorkerClassificationAssignment.project_id == project_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_fields(self, assignment_id: uuid.UUID, **fields: Any) -> None:
        assignment = await self.session.get(WorkerClassificationAssignment, assignment_id)
        if assignment is None:
            return
        for key, value in fields.items():
            setattr(assignment, key, value)
        await self.session.flush()

    async def delete(self, assignment: WorkerClassificationAssignment) -> None:
        await self.session.delete(assignment)
        await self.session.flush()


class CertifiedWeekRepository:
    """Data access for CertifiedPayrollWeek and its frozen lines."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, week: CertifiedPayrollWeek) -> CertifiedPayrollWeek:
        self.session.add(week)
        await self.session.flush()
        await self.session.refresh(week)
        return week

    async def get_by_id(self, week_id: uuid.UUID) -> CertifiedPayrollWeek | None:
        stmt = (
            select(CertifiedPayrollWeek)
            .where(CertifiedPayrollWeek.id == week_id)
            .options(selectinload(CertifiedPayrollWeek.lines))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CertifiedPayrollWeek], int]:
        base = select(CertifiedPayrollWeek).where(CertifiedPayrollWeek.project_id == project_id)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = (
            base.order_by(CertifiedPayrollWeek.week_ending.desc(), CertifiedPayrollWeek.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def update_fields(self, week_id: uuid.UUID, **fields: Any) -> None:
        week = await self.session.get(CertifiedPayrollWeek, week_id)
        if week is None:
            return
        for key, value in fields.items():
            attr = "metadata_" if key == "metadata" else key
            setattr(week, attr, value)
        await self.session.flush()

    async def bulk_create_lines(self, lines: list[CertifiedPayrollLine]) -> list[CertifiedPayrollLine]:
        if not lines:
            return []
        self.session.add_all(lines)
        await self.session.flush()
        return lines

    async def delete(self, week: CertifiedPayrollWeek) -> None:
        await self.session.delete(week)
        await self.session.flush()
