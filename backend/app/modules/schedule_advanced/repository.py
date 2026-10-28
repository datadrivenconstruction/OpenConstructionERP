# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Schedule Advanced data access layer.

One repository per entity, mirroring the pattern used by ``safety/repository.py``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.schedule_advanced.models import (
    Baseline,
    BaselineDelta,
    Calendar,
    Commitment,
    Constraint,
    Location,
    LookAheadPlan,
    MasterSchedule,
    PhasePlan,
    ReasonForNonCompletion,
    TaktActivity,
    TaktSchedule,
    WeeklyWorkPlan,
)


class _BaseRepo:
    """Generic CRUD helpers shared by all repositories."""

    model: type

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, instance: Any) -> Any:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def get_by_id(self, instance_id: uuid.UUID) -> Any | None:
        return await self.session.get(self.model, instance_id)

    async def delete(self, instance_id: uuid.UUID) -> None:
        instance = await self.get_by_id(instance_id)
        if instance is not None:
            await self.session.delete(instance)
            await self.session.flush()

    async def update_fields(self, instance_id: uuid.UUID, **fields: object) -> None:
        stmt = (
            update(self.model)
            .where(self.model.id == instance_id)  # type: ignore[attr-defined]
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(self.model, instance_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)


class MasterScheduleRepository(_BaseRepo):
    """CRUD for :class:`MasterSchedule`."""

    model = MasterSchedule

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[MasterSchedule], int]:
        base = select(MasterSchedule).where(MasterSchedule.project_id == project_id)
        if status is not None:
            base = base.where(MasterSchedule.status == status)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        stmt = base.order_by(desc(MasterSchedule.created_at)).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class PhasePlanRepository(_BaseRepo):
    """CRUD for :class:`PhasePlan`."""

    model = PhasePlan

    async def list_for_master(
        self,
        master_schedule_id: uuid.UUID,
    ) -> list[PhasePlan]:
        stmt = (
            select(PhasePlan)
            .where(PhasePlan.master_schedule_id == master_schedule_id)
            .order_by(PhasePlan.planned_start.asc().nullslast())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class LookAheadRepository(_BaseRepo):
    """CRUD for :class:`LookAheadPlan`."""

    model = LookAheadPlan

    async def list_for_master(
        self,
        master_schedule_id: uuid.UUID,
    ) -> list[LookAheadPlan]:
        stmt = (
            select(LookAheadPlan)
            .where(LookAheadPlan.master_schedule_id == master_schedule_id)
            .order_by(desc(LookAheadPlan.period_start))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def current_for_master(
        self,
        master_schedule_id: uuid.UUID,
        today: date,
    ) -> LookAheadPlan | None:
        stmt = (
            select(LookAheadPlan)
            .where(LookAheadPlan.master_schedule_id == master_schedule_id)
            .where(LookAheadPlan.period_start <= today)
            .where(LookAheadPlan.period_end >= today)
            .order_by(desc(LookAheadPlan.generated_at).nullslast())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class ConstraintRepository(_BaseRepo):
    """CRUD for :class:`Constraint`."""

    model = Constraint

    async def list_for_look_ahead(
        self,
        look_ahead_id: uuid.UUID,
    ) -> list[Constraint]:
        stmt = select(Constraint).where(Constraint.look_ahead_id == look_ahead_id).order_by(desc(Constraint.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def open_constraints_for_project(
        self,
        project_id: uuid.UUID,
    ) -> list[Constraint]:
        """Return open / in-progress constraints linked via look-aheads in this project."""
        stmt = (
            select(Constraint)
            .join(
                LookAheadPlan,
                LookAheadPlan.id == Constraint.look_ahead_id,
                isouter=True,
            )
            .join(
                MasterSchedule,
                MasterSchedule.id == LookAheadPlan.master_schedule_id,
                isouter=True,
            )
            .where(MasterSchedule.project_id == project_id)
            .where(Constraint.status.in_(["open", "in_progress", "escalated"]))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_open_for_task(self, task_ref: uuid.UUID) -> list[Constraint]:
        stmt = (
            select(Constraint)
            .where(Constraint.task_ref == task_ref)
            .where(Constraint.status.in_(["open", "in_progress", "escalated"]))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WeeklyWorkPlanRepository(_BaseRepo):
    """CRUD for :class:`WeeklyWorkPlan`."""

    model = WeeklyWorkPlan

    async def list_for_master(
        self,
        master_schedule_id: uuid.UUID,
        *,
        limit: int = 52,
    ) -> list[WeeklyWorkPlan]:
        stmt = (
            select(WeeklyWorkPlan)
            .where(WeeklyWorkPlan.master_schedule_id == master_schedule_id)
            .order_by(desc(WeeklyWorkPlan.week_start_date))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def current_week_plan(
        self,
        master_schedule_id: uuid.UUID,
        today: date,
    ) -> WeeklyWorkPlan | None:
        stmt = (
            select(WeeklyWorkPlan)
            .where(WeeklyWorkPlan.master_schedule_id == master_schedule_id)
            .where(WeeklyWorkPlan.week_start_date <= today)
            .where(WeeklyWorkPlan.week_end_date >= today)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def current_week_commitment_count(
        self,
        project_id: uuid.UUID,
        today: date,
    ) -> int:
        """Total commitments in the *current* week plan across a project.

        Single aggregate query replacing the previous per-master N+1
        (one ``current_week_plan`` + one ``commitments_for_week`` round
        trip per active master schedule). A "current" week plan is one
        whose [week_start_date, week_end_date] inclusive range contains
        ``today``; only active master schedules contribute.
        """
        stmt = (
            select(func.count(Commitment.id))
            .select_from(Commitment)
            .join(WeeklyWorkPlan, WeeklyWorkPlan.id == Commitment.week_plan_id)
            .join(
                MasterSchedule,
                MasterSchedule.id == WeeklyWorkPlan.master_schedule_id,
            )
            .where(MasterSchedule.project_id == project_id)
            .where(MasterSchedule.status == "active")
            .where(WeeklyWorkPlan.week_start_date <= today)
            .where(WeeklyWorkPlan.week_end_date >= today)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def last_n_weeks_ppc(
        self,
        project_id: uuid.UUID,
        n: int = 12,
    ) -> list[WeeklyWorkPlan]:
        """Return the last ``n`` closed weekly plans for a project, newest first."""
        stmt = (
            select(WeeklyWorkPlan)
            .join(
                MasterSchedule,
                MasterSchedule.id == WeeklyWorkPlan.master_schedule_id,
            )
            .where(MasterSchedule.project_id == project_id)
            .where(WeeklyWorkPlan.status == "closed")
            .order_by(desc(WeeklyWorkPlan.week_start_date))
            .limit(n)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CommitmentRepository(_BaseRepo):
    """CRUD for :class:`Commitment`."""

    model = Commitment

    async def commitments_for_week(self, week_plan_id: uuid.UUID) -> list[Commitment]:
        stmt = select(Commitment).where(Commitment.week_plan_id == week_plan_id).order_by(Commitment.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RNCRepository(_BaseRepo):
    """CRUD for :class:`ReasonForNonCompletion`."""

    model = ReasonForNonCompletion

    async def list_for_commitment(
        self,
        commitment_id: uuid.UUID,
    ) -> list[ReasonForNonCompletion]:
        stmt = (
            select(ReasonForNonCompletion)
            .where(ReasonForNonCompletion.commitment_id == commitment_id)
            .order_by(desc(ReasonForNonCompletion.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project_period(
        self,
        project_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> list[ReasonForNonCompletion]:
        """Return RNCs for commitments in weekly plans within a date period."""
        stmt = (
            select(ReasonForNonCompletion)
            .join(
                Commitment,
                Commitment.id == ReasonForNonCompletion.commitment_id,
            )
            .join(
                WeeklyWorkPlan,
                WeeklyWorkPlan.id == Commitment.week_plan_id,
            )
            .join(
                MasterSchedule,
                MasterSchedule.id == WeeklyWorkPlan.master_schedule_id,
            )
            .where(MasterSchedule.project_id == project_id)
            .where(WeeklyWorkPlan.week_start_date >= period_start)
            .where(WeeklyWorkPlan.week_end_date <= period_end)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BaselineRepository(_BaseRepo):
    """CRUD for :class:`Baseline`."""

    model = Baseline

    async def list_for_master(
        self,
        master_schedule_id: uuid.UUID,
    ) -> list[Baseline]:
        stmt = (
            select(Baseline)
            .where(Baseline.master_schedule_id == master_schedule_id)
            .order_by(desc(Baseline.captured_at).nullslast(), desc(Baseline.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[Baseline]:
        stmt = (
            select(Baseline)
            .join(
                MasterSchedule,
                MasterSchedule.id == Baseline.master_schedule_id,
            )
            .where(MasterSchedule.project_id == project_id)
        )
        if status is not None:
            stmt = stmt.where(Baseline.status == status)
        stmt = stmt.order_by(desc(Baseline.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BaselineDeltaRepository(_BaseRepo):
    """CRUD for :class:`BaselineDelta`."""

    model = BaselineDelta

    async def list_for_baseline(
        self,
        baseline_id: uuid.UUID,
    ) -> list[BaselineDelta]:
        stmt = (
            select(BaselineDelta)
            .where(BaselineDelta.baseline_id == baseline_id)
            .order_by(desc(BaselineDelta.schedule_variance_days))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class CalendarRepository(_BaseRepo):
    """CRUD for :class:`Calendar`."""

    model = Calendar

    async def list_for_project(self, project_id: uuid.UUID) -> list[Calendar]:
        stmt = (
            select(Calendar).where(Calendar.project_id == project_id).order_by(desc(Calendar.is_default), Calendar.name)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def default_for_project(self, project_id: uuid.UUID) -> Calendar | None:
        stmt = select(Calendar).where(Calendar.project_id == project_id).where(Calendar.is_default.is_(True)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def clear_defaults_except(self, project_id: uuid.UUID, keep_id: uuid.UUID | None = None) -> None:
        """Unset ``is_default`` on every calendar in the project except ``keep_id``.

        Keeps at most one default calendar per project so schedule resolution
        stays deterministic: the calendar most recently flagged default wins,
        matching what the UI shows after the user picks a new default.

        Args:
            project_id: The project whose calendars are reconciled.
            keep_id: The calendar allowed to remain default (the one just set);
                ``None`` clears every default.
        """
        stmt = update(Calendar).where(Calendar.project_id == project_id).where(Calendar.is_default.is_(True))
        if keep_id is not None:
            stmt = stmt.where(Calendar.id != keep_id)
        await self.session.execute(stmt.values(is_default=False))
        await self.session.flush()


# ── Takt / line-of-balance repositories ────────────────────────────────────


class TaktScheduleRepository(_BaseRepo):
    """CRUD for :class:`TaktSchedule`."""

    model = TaktSchedule

    async def list_for_master(
        self,
        master_schedule_id: uuid.UUID,
    ) -> list[TaktSchedule]:
        stmt = (
            select(TaktSchedule)
            .where(TaktSchedule.master_schedule_id == master_schedule_id)
            .order_by(desc(TaktSchedule.created_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class LocationRepository(_BaseRepo):
    """CRUD for :class:`Location`."""

    model = Location

    async def list_for_takt(
        self,
        takt_schedule_id: uuid.UUID,
    ) -> list[Location]:
        stmt = (
            select(Location)
            .where(Location.takt_schedule_id == takt_schedule_id)
            .order_by(Location.sequence_order.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_takts(
        self,
        takt_schedule_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Location]]:
        """Fetch locations for many takt schedules in one query.

        Returns a mapping of ``takt_schedule_id -> ordered locations`` so
        callers can hydrate a list of schedules without an N+1 fan-out.
        """
        if not takt_schedule_ids:
            return {}
        stmt = (
            select(Location)
            .where(Location.takt_schedule_id.in_(takt_schedule_ids))
            .order_by(Location.sequence_order.asc())
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[Location]] = {tid: [] for tid in takt_schedule_ids}
        for loc in result.scalars().all():
            grouped.setdefault(loc.takt_schedule_id, []).append(loc)
        return grouped


class TaktActivityRepository(_BaseRepo):
    """CRUD for :class:`TaktActivity`."""

    model = TaktActivity

    async def list_for_takt(
        self,
        takt_schedule_id: uuid.UUID,
    ) -> list[TaktActivity]:
        stmt = (
            select(TaktActivity)
            .where(TaktActivity.takt_schedule_id == takt_schedule_id)
            .order_by(TaktActivity.sequence_order.asc(), TaktActivity.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
