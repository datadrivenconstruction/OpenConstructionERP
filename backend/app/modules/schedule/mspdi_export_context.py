# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the MSPDI writer needs beyond the activity rows.

* :func:`tree_order` - activities parent-first with their outline level, so a
  reader that rebuilds the hierarchy from ``OutlineLevel`` gets it back;
* :func:`load_export_context` - the calendars (the ones activities use, the
  project's default, else the project's regional week) and baseline 0 (the
  approved baseline, else the baseline an MSPDI import carried in).
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.mspdi_export import HOURS_PER_DAY, MspdiCalendar


def tree_order(activities: Sequence[Any]) -> list[tuple[Any, int]]:
    """Activities depth-first (parents before children, siblings in given order) with outline level.

    A parent outside the list or a parent cycle leaves the activity at the top level.
    """
    ids = {str(a.id) for a in activities}
    children: dict[str | None, list[Any]] = {}
    for act in activities:
        parent = str(act.parent_id) if getattr(act, "parent_id", None) else None
        children.setdefault(parent if parent in ids and parent != str(act.id) else None, []).append(act)
    out: list[tuple[Any, int]] = []
    seen: set[str] = set()

    def walk(parent: str | None, level: int) -> None:
        for act in children.get(parent, []):
            key = str(act.id)
            if key in seen:
                continue
            seen.add(key)
            out.append((act, level))
            walk(key, level + 1)

    walk(None, 1)
    for act in activities:  # members of a parent cycle never reached from the top
        if str(act.id) not in seen:
            seen.add(str(act.id))
            out.append((act, 1))
    return out


@dataclass
class ExportContext:
    hours_per_day: float = HOURS_PER_DAY
    calendars: list[MspdiCalendar] = field(default_factory=list)
    project_calendar_uid: int | None = None
    calendar_uid_by_id: dict[str, int] = field(default_factory=dict)
    # activity id -> (start, finish, duration days)
    baseline_by_activity: dict[str, tuple[str, str, int | None]] = field(default_factory=dict)


def _regional_calendar(region: str | None, activities: Sequence[Any]) -> MspdiCalendar:
    from app.modules.schedule.service import get_work_calendar

    cal = get_work_calendar(region)
    years = sorted(
        {int(str(d)[:4]) for a in activities for d in (a.start_date, a.end_date) if d and str(d)[:4].isdigit()}
    )
    holidays: list[str] = []
    resolver = cal.get("holidays")
    if callable(resolver) and years:
        for year in range(years[0], years[-1] + 1):
            holidays.extend(d.isoformat() for d in resolver(year))
    return MspdiCalendar(
        uid=1,
        name=str(cal.get("label") or "Standard"),
        work_days=sorted(cal.get("work_days") or {0, 1, 2, 3, 4}),
        holidays=sorted(holidays),
    )


async def load_export_context(
    session: AsyncSession, schedule: Any, activities: Sequence[Any], *, region: str | None
) -> ExportContext:
    """Calendars and baseline 0 for one schedule's MSPDI export."""
    from app.modules.schedule.baseline_revisions import effective_baseline
    from app.modules.schedule.models import ScheduleBaseline
    from app.modules.schedule.snapshot_envelope import normalize_envelope
    from app.modules.schedule_advanced.models import Calendar

    ctx = ExportContext()
    used = {a.calendar_id for a in activities if getattr(a, "calendar_id", None)}
    rows = await session.execute(select(Calendar).where(Calendar.project_id == schedule.project_id))
    project_cals = list(rows.scalars().all())
    default = next((c for c in project_cals if c.is_default), None)
    chosen = [c for c in project_cals if c.id in used or c is default]
    for uid, cal in enumerate(chosen, start=1):
        ctx.calendars.append(
            MspdiCalendar(
                uid=uid, name=cal.name, work_days=list(cal.work_days or []), holidays=list(cal.holidays or [])
            )
        )
        ctx.calendar_uid_by_id[str(cal.id)] = uid
    if default is None and chosen:
        # No project default: the calendar most activities use stands for the project.
        counts = Counter(str(a.calendar_id) for a in activities if getattr(a, "calendar_id", None))
        default = max(chosen, key=lambda c: counts.get(str(c.id), 0))
    if default is not None:
        ctx.project_calendar_uid = ctx.calendar_uid_by_id[str(default.id)]
        ctx.hours_per_day = float(default.work_hours_per_day or HOURS_PER_DAY)
    else:
        regional = _regional_calendar(region, activities)
        regional.uid = len(ctx.calendars) + 1
        ctx.calendars.append(regional)
        ctx.project_calendar_uid = regional.uid
        ctx.hours_per_day = float(HOURS_PER_DAY)

    bl_rows = await session.execute(select(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule.id))
    baselines = list(bl_rows.scalars().all())
    picked = effective_baseline(
        [
            {
                "obj": b,
                "is_active": b.is_active,
                "metadata": b.metadata_ or {},
                "created_at": b.created_at.isoformat() if b.created_at else "",
            }
            for b in baselines
        ]
    )
    if picked is not None:
        env = normalize_envelope(picked["obj"].snapshot_data)
        for row in env.get("activities") or []:
            if row.get("id") and row.get("start_date") and row.get("end_date"):
                dur = row.get("duration_days")
                ctx.baseline_by_activity[str(row["id"])] = (
                    str(row["start_date"])[:10],
                    str(row["end_date"])[:10],
                    int(dur) if isinstance(dur, (int, float)) or str(dur).isdigit() else None,
                )
    for act in activities:
        meta = act.metadata_ if isinstance(getattr(act, "metadata_", None), dict) else {}
        carried = meta.get("msp_baseline")
        if str(act.id) not in ctx.baseline_by_activity and isinstance(carried, dict):
            if carried.get("start") and carried.get("finish"):
                ctx.baseline_by_activity[str(act.id)] = (
                    carried["start"],
                    carried["finish"],
                    carried.get("duration_days"),
                )
    return ctx


def calendar_uid_of(ctx: ExportContext, calendar_id: uuid.UUID | None) -> int | None:
    """The export UID of an activity's own calendar, None when it follows the project calendar."""
    if calendar_id is None:
        return None
    uid = ctx.calendar_uid_by_id.get(str(calendar_id))
    return None if uid == ctx.project_calendar_uid else uid
