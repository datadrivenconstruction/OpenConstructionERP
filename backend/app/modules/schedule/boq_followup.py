# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Activities follow the quantities of the BOQ positions they are linked to.

A schedule generated from a bill (or linked to it by hand) keeps each
activity's ``boq_position_ids``. When a position's quantity changes, the
activities that carry it get a new working-day duration and the network is
reflowed with the CPM pass :meth:`ScheduleService.reschedule` already runs, so
the successors move with it.

The new duration is the old one scaled by the effort the generator reads from
the bill (:func:`_position_effort`, the same productivity logic as
generate-from-boq) at the old and the new quantity, at the crew the activity
carries. Scaling the stored duration, instead of recounting it from scratch,
keeps whatever the generation did to fit the window (compression, parallel
gangs) and any calendar the activity runs on.

An activity whose duration a person typed (``metadata.duration_locked``) is
never touched, nor is a completed one or a summary.
"""

from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Metadata key a person's typed duration sets; the follow-up leaves the row alone.
DURATION_LOCKED_KEY = "duration_locked"

_SKIPPED_TYPES = frozenset({"summary", "milestone", "start_milestone", "finish_milestone", "wbs", "hammock"})


def to_decimal(value: Any) -> Decimal | None:
    """A quantity as an exact decimal, or ``None`` when it is not a number."""
    if value is None or value == "":
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def _crew(resources: Any) -> tuple[int, int]:
    """People and machine sets the activity carries, at least one of each."""
    people = machines = 0
    for row in resources if isinstance(resources, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if row.get("type") == "labor":
            people += max(count, 0)
        elif row.get("type") == "equipment":
            machines += max(count, 0)
    return max(people, 1), max(machines, 1)


def position_effort_hours(
    meta: dict[str, Any],
    quantity: Decimal,
    unit: str | None,
    unit_rate: Decimal | None,
    *,
    crew: int,
    machine_sets: int,
    hours_per_day: float = 8.0,
    work_days_per_week: int = 5,
) -> float:
    """Crew-hours the generator's productivity logic gives one position.

    The larger of labour hours per person and machine hours per set, as the
    duration in :func:`_position_effort` is the larger of the two. The money
    context (grand total, window) only feeds its cost-proportional fallback;
    the position's own total stands in for both sides, so the ratio between two
    quantities stays proportional to the money there too.
    """
    from app.modules.schedule.service import _position_effort

    total = float(quantity * unit_rate) if unit_rate is not None else 0.0
    effort = _position_effort(
        meta,
        float(quantity),
        unit,
        total,
        max(total, 1.0),
        365,
        hours_per_day=hours_per_day,
        work_days_per_week=work_days_per_week,
        assumed_workers=crew,
        machine_sets=machine_sets,
    )
    labour = effort.labour_hours / max(effort.crew or crew, 1)
    machine = effort.machine_hours / max(effort.machine_sets or machine_sets, 1)
    if effort.source == "estimated_fallback" and labour <= 0:
        # The unit production-rate table, as the generator's duration basis reads it.
        from app.modules.schedule.service import fallback_production_rate

        labour = float(quantity) * fallback_production_rate(unit) / max(crew, 1)
    if labour <= 0 and machine <= 0:
        # Cost-proportional and minimum durations carry no hours: their days are the measure.
        return float(max(effort.labour_days, effort.machine_days, 0)) * hours_per_day
    return max(labour, machine, 0.0)


def scaled_duration(old_days: int, old_hours: float, new_hours: float, hours_per_day: float = 8.0) -> int:
    """The stored working-day duration moved by the change in norm days, at least one day.

    Norm days are the crew hours over a working day, rounded up as the
    generator rounds them. The stored duration keeps its ratio to its norm, so
    a plan the generator shortened to fit its window stays shortened.
    """
    hpd = hours_per_day if hours_per_day > 0 else 8.0
    new_norm = max(1, math.ceil(new_hours / hpd)) if new_hours > 0 else 1
    if old_hours <= 0 or old_days <= 0:
        return new_norm
    old_norm = max(1, math.ceil(old_hours / hpd))
    return max(1, round(old_days * new_norm / old_norm))


async def follow_position_quantity(
    session: AsyncSession,
    position_id: uuid.UUID,
    old_quantity: Any = None,
) -> list[uuid.UUID]:
    """Rescale the activities linked to one position and reflow their schedules.

    Args:
        session: An open session; the caller commits.
        position_id: The BOQ position whose quantity changed.
        old_quantity: The quantity before the change, when the event carries
            it. Otherwise the quantity the generation recorded on the activity.

    Returns:
        The ids of the activities whose duration changed.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.schedule.service import ScheduleService

    position = await session.get(Position, position_id)
    if position is None:
        return []
    boq = await session.get(BOQ, position.boq_id)
    if boq is None:
        return []
    new_qty = to_decimal(position.quantity)
    if new_qty is None:
        return []

    schedule_ids = list(
        (await session.execute(select(Schedule.id).where(Schedule.project_id == boq.project_id))).scalars().all()
    )
    if not schedule_ids:
        return []
    candidates = (await session.execute(select(Activity).where(Activity.schedule_id.in_(schedule_ids)))).scalars().all()
    key = str(position_id)
    linked = [a for a in candidates if key in [str(p) for p in (a.boq_position_ids or [])]]
    if not linked:
        return []

    service = ScheduleService(session)
    hours_per_day = await service._project_calendar_hours(boq.project_id) or 8.0
    changed: list[uuid.UUID] = []
    touched_schedules: set[uuid.UUID] = set()
    for activity in linked:
        meta = dict(activity.metadata_) if isinstance(activity.metadata_, dict) else {}
        if meta.get(DURATION_LOCKED_KEY) or activity.status == "completed":
            continue
        if isinstance(meta.get("design"), dict) and meta["design"].get("rule"):
            # The model-driven planner owns this duration (sourced rate per storey); it reflows on accept.
            continue
        if (activity.activity_type or "task") in _SKIPPED_TYPES:
            continue
        before = to_decimal(old_quantity)
        if before is None:
            before = to_decimal(meta.get("quantity"))
        if before is None or before == new_qty:
            continue
        people, machines = _crew(activity.resources)
        pos_meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        rate = to_decimal(position.unit_rate)
        old_hours = position_effort_hours(
            pos_meta, before, position.unit, rate, crew=people, machine_sets=machines, hours_per_day=hours_per_day
        )
        new_hours = position_effort_hours(
            pos_meta, new_qty, position.unit, rate, crew=people, machine_sets=machines, hours_per_day=hours_per_day
        )
        if len(activity.boq_position_ids or []) > 1:
            # A rolled-up activity: only this member's share of the work moves.
            share = await _other_members_hours(session, activity, key, people, machines, hours_per_day)
            old_hours += share
            new_hours += share
        old_days = int(activity.duration_days or 0)
        new_days = scaled_duration(old_days, old_hours, new_hours, hours_per_day)
        meta["quantity"] = str(new_qty) if len(activity.boq_position_ids or []) == 1 else meta.get("quantity")
        fields: dict[str, Any] = {"metadata_": meta}
        if new_days != old_days:
            fields["duration_days"] = new_days
            if activity.start_date:
                schedule = await session.get(Schedule, activity.schedule_id)
                fields["end_date"] = await service.working_end_date(
                    schedule.project_id if schedule else boq.project_id,
                    getattr(activity, "calendar_id", None),
                    activity.start_date,
                    new_days,
                )
            changed.append(activity.id)
            touched_schedules.add(activity.schedule_id)
        await service.activity_repo.update_fields(activity.id, **fields)

    for schedule_id in touched_schedules:
        await service.reschedule(schedule_id)
    if changed:
        logger.info("BOQ position %s quantity moved %d linked activities", position_id, len(changed))
    return changed


async def _other_members_hours(
    session: AsyncSession,
    activity: Any,
    changed_key: str,
    people: int,
    machines: int,
    hours_per_day: float,
) -> float:
    from app.modules.boq.models import Position

    ids: list[uuid.UUID] = []
    for raw in activity.boq_position_ids or []:
        if str(raw) == changed_key:
            continue
        try:
            ids.append(uuid.UUID(str(raw)))
        except ValueError:
            continue
    if not ids:
        return 0.0
    rows = (await session.execute(select(Position).where(Position.id.in_(ids)))).scalars().all()
    total = 0.0
    for p in rows:
        qty = to_decimal(p.quantity)
        if qty is None:
            continue
        meta = dict(p.metadata_) if isinstance(p.metadata_, dict) else {}
        total += position_effort_hours(
            meta, qty, p.unit, to_decimal(p.unit_rate), crew=people, machine_sets=machines, hours_per_day=hours_per_day
        )
    return total
