# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data access for cutting jobs and plans."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.cutting.models import CuttingJob, CuttingPlan


class CuttingRepository:
    """Queries over the cutting tables; the service owns every rule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_job(self, job_id: uuid.UUID) -> CuttingJob | None:
        """One job with its pieces and stock (both eager by declaration)."""
        return await self.session.get(CuttingJob, job_id)

    async def list_jobs(
        self,
        project_id: uuid.UUID,
        *,
        kind: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[CuttingJob], int]:
        """A project's jobs, most recently changed first, with the total count."""
        base = select(CuttingJob).where(CuttingJob.project_id == project_id)
        if kind:
            base = base.where(CuttingJob.kind == kind)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = await self.session.execute(base.order_by(CuttingJob.updated_at.desc()).offset(offset).limit(limit))
        return list(rows.scalars().all()), int(total)

    async def latest_plans(self, job_ids: list[uuid.UUID]) -> dict[uuid.UUID, CuttingPlan]:
        """The newest plan per job, for the list view."""
        if not job_ids:
            return {}
        rows = await self.session.execute(
            select(CuttingPlan).where(CuttingPlan.job_id.in_(job_ids)).order_by(CuttingPlan.created_at.desc())
        )
        out: dict[uuid.UUID, CuttingPlan] = {}
        for plan in rows.scalars().all():
            out.setdefault(plan.job_id, plan)
        return out

    async def list_plans(self, job_id: uuid.UUID, *, limit: int = 50) -> list[CuttingPlan]:
        """A job's plans, newest first."""
        rows = await self.session.execute(
            select(CuttingPlan).where(CuttingPlan.job_id == job_id).order_by(CuttingPlan.created_at.desc()).limit(limit)
        )
        return list(rows.scalars().all())

    async def get_plan(self, plan_id: uuid.UUID) -> CuttingPlan | None:
        """One plan by id."""
        return await self.session.get(CuttingPlan, plan_id)
