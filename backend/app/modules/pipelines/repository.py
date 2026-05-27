# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Pipeline Builder data-access layer.

Pure CRUD over the three ORM tables. No business logic — the service
layer owns graph validation, JobRun submission and snapshotting.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pipelines.models import (
    Pipeline,
    PipelineNodeState,
    PipelineRun,
)


class PipelineRepository:
    """‌⁠‍Data access for the Pipeline / PipelineRun / PipelineNodeState tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Pipeline ─────────────────────────────────────────────────────────

    async def get(self, pipeline_id: uuid.UUID) -> Pipeline | None:
        return await self.session.get(Pipeline, pipeline_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
    ) -> list[Pipeline]:
        stmt = select(Pipeline)
        if project_id is not None:
            stmt = stmt.where(Pipeline.project_id == project_id)
        if created_by is not None:
            stmt = stmt.where(Pipeline.created_by == created_by)
        # Deterministic order: newest-touched first, then a stable id
        # tiebreak so two pipelines saved in the same second never swap
        # rows between requests.
        stmt = stmt.order_by(Pipeline.updated_at.desc(), Pipeline.id.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def add(self, pipeline: Pipeline) -> Pipeline:
        self.session.add(pipeline)
        await self.session.flush()
        return pipeline

    async def delete(self, pipeline: Pipeline) -> None:
        await self.session.delete(pipeline)

    # ── PipelineRun ──────────────────────────────────────────────────────

    async def get_run(self, run_id: uuid.UUID) -> PipelineRun | None:
        return await self.session.get(PipelineRun, run_id)

    async def add_run(self, run: PipelineRun) -> PipelineRun:
        self.session.add(run)
        await self.session.flush()
        return run

    async def list_runs(self, pipeline_id: uuid.UUID) -> list[PipelineRun]:
        stmt = (
            select(PipelineRun)
            .where(PipelineRun.pipeline_id == pipeline_id)
            .order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    # ── PipelineNodeState ────────────────────────────────────────────────

    async def list_node_states(self, run_id: uuid.UUID) -> list[PipelineNodeState]:
        stmt = (
            select(PipelineNodeState)
            .where(PipelineNodeState.run_id == run_id)
            .order_by(PipelineNodeState.started_at.asc().nullslast())
        )
        return list((await self.session.execute(stmt)).scalars().all())
