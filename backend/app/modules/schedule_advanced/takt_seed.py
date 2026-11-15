# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo takt plan: four floors worked by four trade wagons on a five day rhythm.

The takt page opened on "No takt schedule yet" on every demo project that is not
one of the curated look-ahead boards. This writes the plan a site manager reads
the line of balance from: floors as locations, trades as activities handing off
in order. A project with no master schedule gets a bare one to hang the plan on.

Idempotent per project (a project with a takt schedule is left alone). Only demo
projects are handed in by the caller.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule_advanced.models import Location, MasterSchedule, TaktActivity, TaktSchedule

logger = logging.getLogger(__name__)

#: English texts of the seeded plan, in one place so they can be localised later.
TEXTS: dict[str, object] = {
    "master": "Master schedule",
    "master_notes": "Contract programme.",
    "name": "Structure and envelope takt plan",
    "description": "Floor by floor rhythm, one trade wagon per floor every five days.",
    "locations": ("Level 1", "Level 2", "Level 3", "Level 4"),
    "activities": (
        ("TK-10", "Formwork and reinforcement", 5, 8),
        ("TK-20", "Concrete pour and curing", 5, 6),
        ("TK-30", "Services first fix", 5, 5),
        ("TK-40", "Partitions and envelope", 5, 7),
    ),
}

_TAKT_DAYS = 5


async def seed_takt_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Write the demo takt plan for the given demo projects. The caller commits."""
    ids = list(project_ids)
    totals = {"projects": 0, "takt_schedules": 0, "locations": 0, "activities": 0}
    if not ids:
        return totals
    today = datetime.now(UTC).date()
    for pid in ids:
        masters = (
            (
                await session.execute(
                    select(MasterSchedule).where(MasterSchedule.project_id == pid).order_by(MasterSchedule.created_at)
                )
            )
            .scalars()
            .all()
        )
        if masters:
            has_takt = (
                await session.execute(
                    select(TaktSchedule.id).where(TaktSchedule.master_schedule_id.in_([m.id for m in masters])).limit(1)
                )
            ).first()
            if has_takt is not None:
                continue
            master = masters[0]
        else:
            master = MasterSchedule(
                project_id=pid,
                name=str(TEXTS["master"]),
                baseline_date=today - timedelta(days=60),
                planned_start=today - timedelta(days=60),
                planned_finish=today + timedelta(days=300),
                status="active",
                notes=str(TEXTS["master_notes"]),
            )
            session.add(master)
            await session.flush()
        locations = TEXTS["locations"]
        takt = TaktSchedule(
            master_schedule_id=master.id,
            name=str(TEXTS["name"]),
            description=str(TEXTS["description"]),
            target_cycle_days=_TAKT_DAYS,
            takt_rhythm_tolerance_days=1,
            location_sequence_count=len(locations),  # type: ignore[arg-type]
            status="active",
        )
        session.add(takt)
        await session.flush()
        for order, name in enumerate(locations, start=1):  # type: ignore[arg-type]
            session.add(
                Location(takt_schedule_id=takt.id, sequence_order=order, name=name, work_area_sqm=Decimal("850"))
            )
            totals["locations"] += 1
        previous: uuid.UUID | None = None
        for order, (code, name, days, crew) in enumerate(TEXTS["activities"], start=1):  # type: ignore[arg-type]
            activity = TaktActivity(
                takt_schedule_id=takt.id,
                name=name,
                activity_code=code,
                sequence_order=order,
                planned_cycle_duration_days=days,
                crew_size=crew,
                sequence_predecessor_activity_id=previous,
                status="planned",
            )
            session.add(activity)
            await session.flush()
            previous = activity.id
            totals["activities"] += 1
        totals["takt_schedules"] += 1
        totals["projects"] += 1
    return totals
