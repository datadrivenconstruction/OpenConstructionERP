# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress-rigor service (T3.2).

Wires the pure per-type progress engine (:mod:`app.modules.schedule.progress_math`)
to persistence: typed progress, weighted steps, suspend/resume, per-activity
calendar, and a read-only time-phased planned-value preview.

It wraps :class:`~app.modules.schedule.service.ScheduleService` to reuse the
canonical activity repository and the predecessor-completion guard, so the
existing event + 409 semantics fire unchanged. All writes ``flush`` only; the
request middleware owns the commit (matching every other schedule service).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cpm import readable_exception_dates, readable_work_days
from app.modules.schedule.models import Activity, ProgressStep, Schedule
from app.modules.schedule.progress_math import (
    DEFAULT_CALENDAR,
    DEFAULT_PERCENT_COMPLETE_TYPE,
    PERCENT_COMPLETE_TYPES,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    STATUS_SUSPENDED,
    ProgressResult,
    WorkCalendar,
    budget_at_completion,
    compute_progress,
    earned_value,
    evm_distortion_warnings,
    forecast_finish,
    original_duration,
    planned_value_at,
    remaining_from_pct,
    steps_total_weight,
)
from app.modules.schedule.progress_math import ProgressStep as EngineStep
from app.modules.schedule.progress_schemas import (
    StepCreate,
    StepPatch,
    TypedProgressRequest,
)
from app.modules.schedule.service import ScheduleService, _safe_publish, _str_to_float


@dataclass
class ProgressOutcome:
    """The resolved progress state returned to the router."""

    activity: Activity
    pct_type: str
    result: ProgressResult
    warnings: list[str] = field(default_factory=list)


def _not_found(detail: str = "Not found") -> HTTPException:
    """404 - existence-oracle safe (used for both missing and cross-tenant)."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


class ScheduleProgressService:
    """Per-type progress, steps, suspend/resume, calendars and PV preview."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.base = ScheduleService(session)

    # ── Loaders ──────────────────────────────────────────────────────────────

    async def get_activity(self, activity_id: uuid.UUID) -> Activity:
        return await self.base.get_activity(activity_id)

    async def get_schedule(self, schedule_id: uuid.UUID) -> Schedule:
        return await self.base.get_schedule(schedule_id)

    async def get_step(self, step_id: uuid.UUID) -> ProgressStep:
        step = await self.session.get(ProgressStep, step_id)
        if step is None:
            raise _not_found("Progress step not found")
        return step

    async def _resolve_calendar(
        self,
        calendar_id: uuid.UUID | None,
        cache: dict[uuid.UUID | None, WorkCalendar] | None = None,
    ) -> WorkCalendar:
        """Resolve an activity's working calendar, falling back to Mon-Fri.

        A ``None`` id, or an id that points at a deleted calendar, degrades to
        :data:`DEFAULT_CALENDAR` - there is no DB-level FK, so a dangling id is
        expected and handled rather than an error.
        """
        if cache is not None and calendar_id in cache:
            return cache[calendar_id]

        resolved = DEFAULT_CALENDAR
        if calendar_id is not None:
            from app.modules.schedule_advanced.models import Calendar

            cal = await self.session.get(Calendar, calendar_id)
            if cal is not None:
                weekdays = frozenset(readable_work_days(cal.work_days, source=f"calendar {cal.id} work days"))
                if not weekdays:
                    weekdays = frozenset({0, 1, 2, 3, 4})
                holidays = frozenset(readable_exception_dates(cal.holidays, source=f"calendar {cal.id} holidays"))
                resolved = WorkCalendar(work_weekdays=weekdays, holidays=holidays)

        if cache is not None:
            cache[calendar_id] = resolved
        return resolved

    async def list_steps(self, activity_id: uuid.UUID) -> list[ProgressStep]:
        await self.get_activity(activity_id)  # 404 if the activity is gone
        stmt = (
            select(ProgressStep)
            .where(ProgressStep.activity_id == activity_id)
            .order_by(ProgressStep.sort_order, ProgressStep.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _engine_steps(orm_steps: list[ProgressStep]) -> list[EngineStep]:
        return [
            EngineStep(
                weight=s.weight,
                percent_complete=s.percent_complete,
                is_milestone=s.is_milestone,
            )
            for s in orm_steps
        ]

    # ── Typed progress ───────────────────────────────────────────────────────

    def _combined_warnings(
        self,
        *,
        pct_type: str,
        budgeted_units: Decimal | None,
        has_steps: bool,
        cost_planned: Decimal | None,
        engine_steps: list[EngineStep],
        result_warnings: list[str],
    ) -> list[str]:
        warnings = list(result_warnings)
        extra = evm_distortion_warnings(
            pct_type=pct_type,
            budgeted_units=budgeted_units,
            has_steps=has_steps,
            cost_planned=cost_planned,
            steps_total_weight=steps_total_weight(engine_steps) if engine_steps else 0,
            cost_is_nonlinear=False,
        )
        for warning in extra:
            if warning not in warnings:
                warnings.append(warning)
        return warnings

    async def set_typed_progress(self, activity_id: uuid.UUID, req: TypedProgressRequest) -> ProgressOutcome:
        """Resolve and persist progress for one activity via the per-type engine."""
        activity = await self.get_activity(activity_id)
        schedule = await self.get_schedule(activity.schedule_id)

        pct_type = req.percent_complete_type or activity.percent_complete_type or DEFAULT_PERCENT_COMPLETE_TYPE
        if pct_type not in PERCENT_COMPLETE_TYPES:
            pct_type = DEFAULT_PERCENT_COMPLETE_TYPE

        calendar = await self._resolve_calendar(activity.calendar_id)
        data_date = req.data_date or schedule.data_date or activity.start_date

        percent_in = req.percent if req.percent is not None else _str_to_float(activity.progress_pct)
        budgeted = req.budgeted_units if req.budgeted_units is not None else activity.budgeted_units
        installed = req.installed_units if req.installed_units is not None else activity.installed_units

        orm_steps = await self.list_steps(activity_id) if pct_type == "physical" else []
        engine_steps = self._engine_steps(orm_steps)

        result = compute_progress(
            pct_type=pct_type,
            calendar=calendar,
            start_iso=activity.start_date,
            end_iso=activity.end_date,
            data_date_iso=data_date,
            percent_in=percent_in,
            installed_units=installed,
            budgeted_units=budgeted,
            explicit_remaining=req.remaining_duration,
            steps=engine_steps,
            suspended=False,
            predecessors_complete=True,
        )

        # Completion guard mirrors ScheduleService.update_progress: block reaching
        # 100% while a canonical predecessor is open, unless already complete.
        was_completed = activity.status == STATUS_COMPLETED or _str_to_float(activity.progress_pct) >= 100.0
        if result.status == STATUS_COMPLETED and not was_completed:
            await self.base._assert_predecessors_complete(activity_id)

        warnings = self._combined_warnings(
            pct_type=pct_type,
            budgeted_units=budgeted,
            has_steps=bool(orm_steps),
            cost_planned=activity.cost_planned,
            engine_steps=engine_steps,
            result_warnings=result.warnings,
        )

        fields: dict[str, object] = {
            "progress_pct": str(result.percent_complete),
            "status": result.status,
            "remaining_duration": result.remaining_duration,
            "percent_complete_type": pct_type,
        }
        if req.budgeted_units is not None:
            fields["budgeted_units"] = req.budgeted_units
        if req.installed_units is not None:
            fields["installed_units"] = req.installed_units
        await self.base.activity_repo.update_fields(activity_id, **fields)

        await _safe_publish(
            "schedule.activity.progress_updated",
            {
                "activity_id": str(activity_id),
                "progress_pct": float(result.percent_complete),
                "status": result.status,
                "percent_complete_type": pct_type,
            },
            source_module="oe_schedule",
        )

        refreshed = await self.get_activity(activity_id)
        return ProgressOutcome(activity=refreshed, pct_type=pct_type, result=result, warnings=warnings)

    async def change_percent_type(self, activity_id: uuid.UUID, pct_type: str) -> tuple[Activity, list[str]]:
        """Change the percent-complete type; return the activity + warnings preview."""
        activity = await self.get_activity(activity_id)
        if pct_type not in PERCENT_COMPLETE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown percent_complete_type {pct_type!r}",
            )
        orm_steps = await self.list_steps(activity_id) if pct_type == "physical" else []
        engine_steps = self._engine_steps(orm_steps)
        warnings = evm_distortion_warnings(
            pct_type=pct_type,
            budgeted_units=activity.budgeted_units,
            has_steps=bool(orm_steps),
            cost_planned=activity.cost_planned,
            steps_total_weight=steps_total_weight(engine_steps) if engine_steps else 0,
            cost_is_nonlinear=False,
        )
        await self.base.activity_repo.update_fields(activity_id, percent_complete_type=pct_type)
        return await self.get_activity(activity_id), warnings

    # ── Steps ────────────────────────────────────────────────────────────────

    async def create_step(self, activity_id: uuid.UUID, data: StepCreate) -> ProgressStep:
        await self.get_activity(activity_id)
        step = ProgressStep(
            activity_id=activity_id,
            name=data.name,
            weight=data.weight,
            percent_complete=data.percent_complete,
            sort_order=data.sort_order,
            is_milestone=data.is_milestone,
        )
        self.session.add(step)
        await self.session.flush()
        await self._recompute_from_steps(activity_id)
        return step

    async def patch_step(self, step_id: uuid.UUID, data: StepPatch) -> ProgressStep:
        step = await self.get_step(step_id)
        if data.name is not None:
            step.name = data.name
        if data.weight is not None:
            step.weight = data.weight
        if data.percent_complete is not None:
            step.percent_complete = data.percent_complete
        if data.sort_order is not None:
            step.sort_order = data.sort_order
        if data.is_milestone is not None:
            step.is_milestone = data.is_milestone
        await self.session.flush()
        await self._recompute_from_steps(step.activity_id)
        return step

    async def delete_step(self, step_id: uuid.UUID) -> uuid.UUID:
        step = await self.get_step(step_id)
        activity_id = step.activity_id
        await self.session.delete(step)
        await self.session.flush()
        await self._recompute_from_steps(activity_id)
        return activity_id

    async def _recompute_from_steps(self, activity_id: uuid.UUID) -> None:
        """Re-roll the parent percent after a step edit (physical type only)."""
        activity = await self.get_activity(activity_id)
        if activity.percent_complete_type != "physical":
            return
        await self.set_typed_progress(activity_id, TypedProgressRequest(percent_complete_type="physical"))

    # ── Suspend / resume ─────────────────────────────────────────────────────

    async def suspend(self, activity_id: uuid.UUID, reason: str, effective_date: str | None) -> Activity:
        activity = await self.get_activity(activity_id)
        schedule = await self.get_schedule(activity.schedule_id)
        if activity.status not in (STATUS_IN_PROGRESS, STATUS_NOT_STARTED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot suspend an activity in status '{activity.status}'",
            )
        calendar = await self._resolve_calendar(activity.calendar_id)
        remaining = activity.remaining_duration
        if remaining is None:
            od = original_duration(calendar, activity.start_date, activity.end_date)
            remaining = remaining_from_pct(od, _str_to_float(activity.progress_pct))
        when = effective_date or schedule.data_date or activity.start_date

        await self.base.activity_repo.update_fields(
            activity_id,
            status=STATUS_SUSPENDED,
            remaining_duration=remaining,
            suspended_at=when,
            suspend_reason=reason,
            resumed_at=None,
        )
        await _safe_publish(
            "schedule.activity.suspended",
            {"activity_id": str(activity_id), "effective_date": when},
            source_module="oe_schedule",
        )
        return await self.get_activity(activity_id)

    async def resume(self, activity_id: uuid.UUID, effective_date: str | None) -> Activity:
        activity = await self.get_activity(activity_id)
        schedule = await self.get_schedule(activity.schedule_id)
        if activity.status != STATUS_SUSPENDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activity is not suspended",
            )
        calendar = await self._resolve_calendar(activity.calendar_id)
        remaining = activity.remaining_duration if activity.remaining_duration is not None else 0
        when = effective_date or schedule.data_date or activity.start_date
        new_end = forecast_finish(calendar, activity.start_date, when, remaining)

        pct = _str_to_float(activity.progress_pct)
        new_status = STATUS_IN_PROGRESS if pct > 0.0 else STATUS_NOT_STARTED

        await self.base.activity_repo.update_fields(
            activity_id,
            status=new_status,
            resumed_at=when,
            end_date=new_end,
        )
        await _safe_publish(
            "schedule.activity.resumed",
            {"activity_id": str(activity_id), "effective_date": when, "end_date": new_end},
            source_module="oe_schedule",
        )
        return await self.get_activity(activity_id)

    # ── Calendar ─────────────────────────────────────────────────────────────

    async def set_calendar(self, activity_id: uuid.UUID, calendar_id: uuid.UUID | None) -> Activity:
        activity = await self.get_activity(activity_id)
        schedule = await self.get_schedule(activity.schedule_id)
        if calendar_id is not None:
            from app.modules.schedule_advanced.models import Calendar

            cal = await self.session.get(Calendar, calendar_id)
            # Reject a calendar from another project (existence-oracle safe 404).
            if cal is None or cal.project_id != schedule.project_id:
                raise _not_found("Calendar not found")
        await self.base.activity_repo.update_fields(activity_id, calendar_id=calendar_id)
        return await self.get_activity(activity_id)

    # ── Time-phased planned value (read-only preview) ────────────────────────

    async def planned_value_preview(self, schedule_id: uuid.UUID, as_of: str) -> dict[str, object]:
        """Time-phased PV / EV / BAC across a schedule at an arbitrary data date."""
        await self.get_schedule(schedule_id)
        activities, _ = await self.base.activity_repo.list_for_schedule(schedule_id, limit=100_000)

        cache: dict[uuid.UUID | None, WorkCalendar] = {}
        rows: list[dict[str, object]] = []
        for act in activities:
            calendar = await self._resolve_calendar(act.calendar_id, cache)
            rows.append(
                {
                    "baseline_start_iso": act.start_date,
                    "baseline_end_iso": act.end_date,
                    "cost_planned": act.cost_planned if act.cost_planned is not None else Decimal("0"),
                    "percent_complete": _str_to_float(act.progress_pct),
                    "_calendar": calendar,
                }
            )

        pv = planned_value_at(rows, as_of, lambda row: row["_calendar"])
        ev = earned_value(rows)
        bac = budget_at_completion(rows)
        return {
            "schedule_id": schedule_id,
            "as_of": as_of,
            "planned_value": pv,
            "earned_value": ev,
            "budget_at_completion": bac,
            "activity_count": len(rows),
        }
