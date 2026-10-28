# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠AI Estimate Builder data-access layer.

Three thin repositories over the module's tables, mirroring the
:mod:`app.modules.ai_agents.repository` style: ``add`` + ``flush`` so the row
gets an id, scoped reads, and ``update_fields`` patch helpers. No business
logic lives here - the service composes these.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator.models import (
    AiEstimatorGroup,
    AiEstimatorIntake,
    AiEstimatorRun,
    AiEstimatorStep,
)


def _accessible_project_ids_subquery(user_id: uuid.UUID):
    """Scalar subquery of project ids the user owns or is a member of.

    Used to scope cross-project listings (e.g. the unfiltered runs list) so a
    caller only ever sees runs in projects they can access, never another
    tenant's data.
    """
    from app.modules.projects.models import Project
    from app.modules.teams.access import member_project_ids_subquery

    return select(Project.id).where(
        (Project.owner_id == user_id) | (Project.id.in_(member_project_ids_subquery(user_id)))
    )


class AiEstimatorRunRepository:
    """CRUD-style helpers for :class:`AiEstimatorRun`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, run: AiEstimatorRun) -> AiEstimatorRun:
        """Insert a new run row and flush so it has an id."""
        self.session.add(run)
        await self.session.flush()
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> AiEstimatorRun | None:
        stmt = select(AiEstimatorRun).where(AiEstimatorRun.id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_runs(
        self,
        *,
        project_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        accessible_to: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AiEstimatorRun]:
        """Return runs ordered newest-first, scoped by project/user.

        ``accessible_to`` restricts the result to runs in projects the given
        user owns or is a member of. Pass it for the unfiltered (no
        ``project_id``) listing so a caller never sees another tenant's runs.
        """
        stmt = select(AiEstimatorRun).order_by(AiEstimatorRun.created_at.desc()).limit(limit).offset(offset)
        if project_id is not None:
            stmt = stmt.where(AiEstimatorRun.project_id == project_id)
        if user_id is not None:
            stmt = stmt.where(AiEstimatorRun.user_id == user_id)
        if accessible_to is not None:
            stmt = stmt.where(AiEstimatorRun.project_id.in_(_accessible_project_ids_subquery(accessible_to)))
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_runs(
        self,
        *,
        project_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        accessible_to: uuid.UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(AiEstimatorRun)
        if project_id is not None:
            stmt = stmt.where(AiEstimatorRun.project_id == project_id)
        if user_id is not None:
            stmt = stmt.where(AiEstimatorRun.user_id == user_id)
        if accessible_to is not None:
            stmt = stmt.where(AiEstimatorRun.project_id.in_(_accessible_project_ids_subquery(accessible_to)))
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        """Patch arbitrary scalar fields on a run row.

        ``synchronize_session="evaluate"`` reconciles the bulk UPDATE with
        the matching :class:`AiEstimatorRun` already in this session's identity
        map: the changed columns are written onto that in-memory instance
        (the WHERE is always the primary key, so the criteria evaluate purely
        in Python - no extra round-trip), and the instance is left *un-expired*.
        This is the ASM-013 convention. It replaces the previous
        ``session.expire_all()``, which invalidated every loaded entity
        mid-request and made the next ORM attribute read trigger a lazy reload
        outside the async greenlet bridge (the MissingGreenlet 500).
        """
        if not fields:
            return
        stmt = (
            update(AiEstimatorRun)
            .where(AiEstimatorRun.id == run_id)
            .values(**fields)
            .execution_options(synchronize_session="evaluate")
        )
        await self.session.execute(stmt)
        await self.session.flush()


class AiEstimatorGroupRepository:
    """CRUD-style helpers for :class:`AiEstimatorGroup`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, group: AiEstimatorGroup) -> AiEstimatorGroup:
        self.session.add(group)
        await self.session.flush()
        return group

    async def bulk_add(self, groups: list[AiEstimatorGroup]) -> list[AiEstimatorGroup]:
        self.session.add_all(groups)
        await self.session.flush()
        return groups

    async def get_by_id(self, group_id: uuid.UUID) -> AiEstimatorGroup | None:
        stmt = select(AiEstimatorGroup).where(AiEstimatorGroup.id == group_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_run(
        self,
        run_id: uuid.UUID,
        *,
        statuses: list[str] | None = None,
    ) -> list[AiEstimatorGroup]:
        """Return a run's groups in display order, optionally status-filtered."""
        stmt = (
            select(AiEstimatorGroup)
            .where(AiEstimatorGroup.run_id == run_id)
            .order_by(
                AiEstimatorGroup.sort_order.asc(),
                AiEstimatorGroup.element_count.desc(),
            )
        )
        if statuses:
            stmt = stmt.where(AiEstimatorGroup.status.in_(statuses))
        return list((await self.session.execute(stmt)).scalars().all())

    async def status_counts(self, run_id: uuid.UUID) -> dict[str, int]:
        """Return {status: count} for a run's groups."""
        stmt = (
            select(AiEstimatorGroup.status, func.count())
            .where(AiEstimatorGroup.run_id == run_id)
            .group_by(AiEstimatorGroup.status)
        )
        rows = (await self.session.execute(stmt)).all()
        return {str(status): int(count) for status, count in rows}

    async def delete_for_run(self, run_id: uuid.UUID) -> None:
        """Drop all groups for a run (re-grouping replaces them wholesale)."""
        for group in await self.list_for_run(run_id):
            await self.session.delete(group)
        await self.session.flush()

    async def update_fields(self, group_id: uuid.UUID, **fields: object) -> None:
        """Patch fields on a group row (ASM-013 convention).

        Uses ``synchronize_session="evaluate"`` so the changed columns are
        written onto the matching in-memory :class:`AiEstimatorGroup` without
        expiring it (or any other loaded entity). See the run repository's
        ``update_fields`` for the full rationale - this avoids the
        MissingGreenlet that ``session.expire_all()`` caused.
        """
        if not fields:
            return
        stmt = (
            update(AiEstimatorGroup)
            .where(AiEstimatorGroup.id == group_id)
            .values(**fields)
            .execution_options(synchronize_session="evaluate")
        )
        await self.session.execute(stmt)
        await self.session.flush()


class AiEstimatorIntakeRepository:
    """CRUD-style helpers for :class:`AiEstimatorIntake` (the v2 intake row)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, intake: AiEstimatorIntake) -> AiEstimatorIntake:
        """Insert a new intake row and flush so it has an id."""
        self.session.add(intake)
        await self.session.flush()
        return intake

    async def get_for_run(self, run_id: uuid.UUID) -> AiEstimatorIntake | None:
        """Return the 1:1 intake row for a run, or None."""
        stmt = select(AiEstimatorIntake).where(AiEstimatorIntake.run_id == run_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def update_fields(self, intake_id: uuid.UUID, **fields: object) -> None:
        """Patch fields on an intake row (ASM-013 convention).

        Uses ``synchronize_session="evaluate"`` so the changed columns are
        written onto the matching in-memory :class:`AiEstimatorIntake` without
        expiring it (see the run/group repositories for the full rationale -
        this avoids the MissingGreenlet that ``expire_all()`` caused).
        """
        if not fields:
            return
        stmt = (
            update(AiEstimatorIntake)
            .where(AiEstimatorIntake.id == intake_id)
            .values(**fields)
            .execution_options(synchronize_session="evaluate")
        )
        await self.session.execute(stmt)
        await self.session.flush()


class AiEstimatorStepRepository:
    """CRUD-style helpers for :class:`AiEstimatorStep` (run timeline)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, step: AiEstimatorStep) -> AiEstimatorStep:
        self.session.add(step)
        await self.session.flush()
        return step

    async def next_idx(self, run_id: uuid.UUID) -> int:
        """Return the next monotonic step index for a run."""
        stmt = select(func.coalesce(func.max(AiEstimatorStep.step_idx), -1)).where(
            AiEstimatorStep.run_id == run_id,
        )
        current = int((await self.session.execute(stmt)).scalar_one() or -1)
        return current + 1

    async def list_for_run(
        self,
        run_id: uuid.UUID,
        *,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[AiEstimatorStep]:
        """Return a run's steps in chronological (or newest-first) order."""
        order = AiEstimatorStep.step_idx.desc() if newest_first else AiEstimatorStep.step_idx.asc()
        stmt = select(AiEstimatorStep).where(AiEstimatorStep.run_id == run_id).order_by(order)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
