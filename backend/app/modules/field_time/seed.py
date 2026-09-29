# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Field Time demo seed - a populated timesheet register per demo project.

Books several weeks of foreman timesheets for every project that has the
ingredients a real one needs: workers from the resources module, plant with a
rental on the project, and cost codes taken from the project's own BOQ. Nothing
here is invented - a line can only name a worker, a machine and a cost code that
already exist in the seeded estate.

Every row is written through :class:`FieldTimeService`, the same layer the API
uses, so the seeded estate passes the same validation, gets the same
``FT-000001`` references, mints the same daywork sheets and publishes the same
events as a timesheet booked by hand. A row this seeder cannot submit is a row
the application would have rejected too.

The register is deliberately mixed: the newest days are still drafts, the days
behind them are submitted and waiting, everything older is approved, and one
approved sheet per project has been reversed - so the screen teaches the
workflow instead of showing one uniform status.

Dates are anchored to the run date (the most recent working days), never
hardcoded, so a demo opened a year from now still shows last month's hours.

Idempotent per project: a project that already carries a timesheet is left
untouched, so a re-run never doubles the register.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.field_time.models import FieldTimesheet
from app.modules.field_time.repository import FieldTimeRepository
from app.modules.field_time.schemas import (
    FieldTimesheetCreate,
    FieldTimesheetLineCreate,
    ReverseTimesheetRequest,
)
from app.modules.field_time.service import FieldTimeService

logger = logging.getLogger(__name__)

_SEED = 42

# How many working days of history a project gets, indexed by the project's
# position in the seeding call rather than drawn from its id. A reader flipping
# between two demo projects has to see two different pictures, and a draw from
# four values hands two projects the same register one time in four.
#
# Past the end of the tuple the position wraps and a whole span is added, which
# keeps the mapping injective: every block of four occupies a range of day
# counts disjoint from every other block. Adding 1 per wrap instead would put
# position 11 back on 21 days alongside position 1. Since all registers end on
# the same date, distinct day counts mean distinct sets of dates, so no two
# projects can render the same one. Everything inside a register still comes
# from the project id, so re-seeding one project reproduces it.
_HISTORY_DAYS = (25, 21, 16, 19)
_HISTORY_SPAN = max(_HISTORY_DAYS) - min(_HISTORY_DAYS) + 1

# Timekeeping rules stamped onto each timesheet's metadata and read back by
# ``field_time_math.read_hours_config``. Field Time makes no worldwide
# assumption about overtime, so the estate shows both a project that books
# overtime above a daily threshold and one that does not. The rounding step
# stays at a quarter hour everywhere and every seeded booking is a multiple of
# it, so the header total always ties out to the sum of the lines.
_HOURS_CONFIGS: tuple[dict[str, str], ...] = (
    {"hours_rounding_increment": "0.25", "overtime_daily_threshold": "8"},
    {"hours_rounding_increment": "0.25"},
    {"hours_rounding_increment": "0.25", "overtime_daily_threshold": "9"},
)

# A day's booking per worker, in hours. Multiples of a quarter hour, capped at
# ten so the per-worker daily ceiling is never in play, and weighted so a plain
# eight hour day is the norm and overtime the exception.
_DAY_HOURS: tuple[Decimal, ...] = (
    Decimal("8"),
    Decimal("8"),
    Decimal("8"),
    Decimal("8.5"),
    Decimal("7.5"),
    Decimal("9"),
    Decimal("9.5"),
    Decimal("10"),
    Decimal("4"),
    Decimal("6"),
)

# Hours a machine runs on a day it is used - a machine idles more than a crew.
_PLANT_HOURS: tuple[Decimal, ...] = (
    Decimal("4"),
    Decimal("5"),
    Decimal("6"),
    Decimal("6.5"),
    Decimal("7.5"),
    Decimal("8"),
)

# Foreman's end-of-day note. Neutral, factual, and about the work only.
_SHIFT_NOTES: tuple[str, ...] = (
    "Day shift, full crew on site.",
    "Day shift, dry weather, no stoppages.",
    "Day shift, one crew released at midday.",
    "Day shift, materials delivery mid-morning.",
    "Day shift, works handed over to the next gang.",
)

# Lifecycle statuses (mirrors the service's own vocabulary).
_DRAFT = "draft"
_SUBMITTED = "submitted"
_APPROVED = "approved"

# Resource kinds that can book labour hours.
_LABOUR_KINDS = ("person", "crew")

# Variation-order statuses that still accept daywork cost.
_OPEN_VARIATION_STATUSES = ("issued", "in_progress")

# How many of a project's cost codes the crew actually books to over the seeded
# weeks. A gang works a handful of activities in a month, so spreading the hours
# across every position in a several-hundred-line BOQ would read as noise rather
# than as a month of work.
_WORKING_CODE_COUNT = 8

# Booked shifts start and end the working day; a submission lands the same
# evening and the approval the next morning. Kept relative to the work date so
# a sheet is never approved weeks before or after the day it records.
_SUBMIT_AT = time(17, 30, tzinfo=UTC)
_APPROVE_AT = time(8, 15, tzinfo=UTC)

_REVERSAL_NOTE = "Hours booked to the wrong cost code; re-entered on the following sheet."


def _submitted_stamp(day: date) -> datetime:
    """When the seed says a sheet for ``day`` was sent: the same evening."""
    return datetime.combine(day, _SUBMIT_AT)


def _approved_stamp(day: date) -> datetime:
    """When the seed says a sheet for ``day`` was approved: the next morning."""
    return datetime.combine(day + timedelta(days=1), _APPROVE_AT)


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the register."""
    return random.Random(f"{_SEED}:{project_id}")


def _working_days(count: int, *, ending: date) -> list[date]:
    """Return ``count`` Mon-Fri dates ending on or before ``ending``, oldest first."""
    days: list[date] = []
    cursor = ending
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    return days


def _status_plan(total: int) -> list[str]:
    """Assign a lifecycle status per day (oldest first).

    The newest two days are still drafts the foreman has not sent, the two
    behind them are submitted and waiting on the approver, and everything older
    is approved - the shape a live register actually has mid-week.
    """
    plan = [_APPROVED] * total
    for offset, value in ((1, _DRAFT), (2, _DRAFT), (3, _SUBMITTED), (4, _SUBMITTED)):
        if total >= offset:
            plan[total - offset] = value
    return plan


def _reversal_index(plan: Sequence[str]) -> int | None:
    """Pick the approved day to reverse (about 40% into the history), or None."""
    approved = [i for i, value in enumerate(plan) if value == _APPROVED]
    if len(approved) < 6:
        return None
    return approved[int(len(approved) * 0.4)]


async def _project_workers(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str]]:
    """Return ``(resource_id, name)`` for the project's own people and crews."""
    try:
        from app.modules.resources.models import Resource

        stmt = (
            select(Resource.id, Resource.name)
            .where(
                Resource.home_project_id == project_id,
                Resource.resource_type.in_(_LABOUR_KINDS),
                Resource.status == "active",
            )
            .order_by(Resource.code)
        )
        rows = (await session.execute(stmt)).all()
    except Exception:
        logger.debug("Resource lookup unavailable for project=%s", project_id)
        return []
    return [(rid, str(name or "")) for rid, name in rows]


async def _project_plant(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[tuple[uuid.UUID, str]]:
    """Return ``(equipment_id, name)`` for machines rented to this project.

    Only rented plant is offered: the field-time service prices plant hours from
    the project's rental rate, so a machine with no rental here would book hours
    that cost nothing.
    """
    try:
        from app.modules.equipment.models import Equipment, EquipmentRental

        stmt = (
            select(EquipmentRental.equipment_id, Equipment.name)
            .join(Equipment, Equipment.id == EquipmentRental.equipment_id)
            .where(EquipmentRental.project_id == project_id)
            .order_by(Equipment.code)
        )
        rows = (await session.execute(stmt)).all()
    except Exception:
        logger.debug("Equipment lookup unavailable for project=%s", project_id)
        return []
    seen: set[uuid.UUID] = set()
    out: list[tuple[uuid.UUID, str]] = []
    for eid, name in rows:
        if eid in seen:
            continue
        seen.add(eid)
        out.append((eid, str(name or "")))
    return out


async def _project_cost_codes(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> list[tuple[str, str]]:
    """Return ``(cost_code, description)`` drawn from the project's own BOQ.

    Uses the exact strings the field-time cost-code rule resolves against
    (``Position.reference_code`` falling back to ``Position.ordinal``), so a
    seeded line codes to a position the estimate really priced.
    """
    try:
        from app.modules.boq.models import BOQ, Position

        stmt = (
            select(Position.reference_code, Position.ordinal, Position.description)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id)
            .order_by(Position.ordinal)
        )
        rows = (await session.execute(stmt)).all()
    except Exception:
        logger.debug("BOQ lookup unavailable for project=%s", project_id)
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for reference_code, ordinal, description in rows:
        code = str(reference_code or ordinal or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append((code, str(description or "").strip()))
    return out


async def _open_variation_id(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """Return one open variation order for the project, or None."""
    try:
        from app.modules.variations.models import VariationOrder

        stmt = (
            select(VariationOrder.id)
            .where(
                VariationOrder.project_id == project_id,
                VariationOrder.status.in_(_OPEN_VARIATION_STATUSES),
            )
            .order_by(VariationOrder.id)
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()
    except Exception:
        logger.debug("Variation lookup unavailable for project=%s", project_id)
        return None


async def _actors(session: AsyncSession, owner_id: uuid.UUID) -> tuple[str, str]:
    """Return ``(submitter_id, approver_id)`` as strings.

    A timesheet is signed by the foreman and countersigned by someone else, so
    the demo uses two different accounts where the estate has them. Falls back
    to the project owner for either side when it does not.
    """
    submitter = approver = str(owner_id)
    try:
        from app.modules.users.models import User

        rows = (await session.execute(select(User.id, User.role).order_by(User.email))).all()
    except Exception:
        logger.debug("User lookup unavailable; timesheets signed by the project owner")
        return submitter, approver
    by_role: dict[str, str] = {}
    for uid, role in rows:
        by_role.setdefault(str(role or ""), str(uid))
    submitter = by_role.get("editor") or submitter
    approver = by_role.get("manager") or by_role.get("admin") or approver
    return submitter, approver


def _build_lines(
    rng: random.Random,
    *,
    day_index: int,
    workers: Sequence[tuple[uuid.UUID, str]],
    plant: Sequence[tuple[uuid.UUID, str]],
    cost_codes: Sequence[tuple[str, str]],
    variation_id: uuid.UUID | None,
) -> list[FieldTimesheetLineCreate]:
    """Build one day's labour and plant bookings.

    A worker books a whole day against one cost code, or splits it across two
    when the gang moved between activities - which is what makes the per-worker
    daily total, and therefore overtime, worth computing.
    """
    lines: list[FieldTimesheetLineCreate] = []
    gang_size = min(len(workers), rng.randint(3, 5))
    gang = rng.sample(workers, k=gang_size)

    for resource_id, _name in gang:
        hours = rng.choice(_DAY_HOURS)
        code, description = rng.choice(cost_codes)
        if hours >= Decimal("8") and rng.random() < 0.3:
            # Split the day across two activities: 3 hours on the second code.
            second_code, second_description = rng.choice(cost_codes)
            lines.append(
                FieldTimesheetLineCreate(
                    resource_id=resource_id,
                    hours=hours - Decimal("3"),
                    cost_code=code,
                    note=description[:200] or None,
                ),
            )
            lines.append(
                FieldTimesheetLineCreate(
                    resource_id=resource_id,
                    hours=Decimal("3"),
                    cost_code=second_code,
                    note=second_description[:200] or None,
                ),
            )
            continue
        lines.append(
            FieldTimesheetLineCreate(
                resource_id=resource_id,
                hours=hours,
                cost_code=code,
                note=description[:200] or None,
            ),
        )

    if plant and rng.random() < 0.6:
        equipment_id, _plant_name = rng.choice(plant)
        code, description = rng.choice(cost_codes)
        lines.append(
            FieldTimesheetLineCreate(
                equipment_id=equipment_id,
                hours=rng.choice(_PLANT_HOURS),
                cost_code=code,
                note=description[:200] or None,
            ),
        )

    # Instructed extra work, booked as daywork against an open variation so the
    # approval mirrors it onto a signed daywork sheet in Variations.
    if variation_id is not None and day_index % 6 == 3:
        resource_id, _name = rng.choice(workers)
        code, _description = rng.choice(cost_codes)
        lines.append(
            FieldTimesheetLineCreate(
                resource_id=resource_id,
                hours=Decimal("2.5"),
                cost_code=code,
                is_daywork=True,
                variation_id=variation_id,
                note="Instructed additional works, recorded as daywork.",
            ),
        )
    return lines


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    ordinal: int,
) -> dict[str, int]:
    """Seed one project's register. Returns per-entity counts (zeros when skipped).

    ``ordinal`` is the project's position in the seeding call and decides how far
    back the register runs, which is what keeps two demo projects apart.
    """
    empty = {"timesheets": 0, "lines": 0, "reversals": 0, "projects": 0}

    already = (
        (await session.execute(select(FieldTimesheet.id).where(FieldTimesheet.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    if already is not None:
        return empty

    workers = await _project_workers(session, project_id)
    cost_codes = await _project_cost_codes(session, project_id)
    if not workers or not cost_codes:
        # Without a crew or a priced BOQ there is nothing honest to book hours
        # against: every line needs a worker and a cost code that resolves.
        logger.debug(
            "Field time demo skipped for project=%s (workers=%d, cost codes=%d)",
            project_id,
            len(workers),
            len(cost_codes),
        )
        return empty

    plant = await _project_plant(session, project_id)
    variation_id = await _open_variation_id(session, project_id)
    submitter, approver = await _actors(session, owner_id)

    rng = _rng_for(project_id)
    slot = ordinal % len(_HISTORY_DAYS)
    history = _HISTORY_DAYS[slot] + (ordinal // len(_HISTORY_DAYS)) * _HISTORY_SPAN
    working_codes = rng.sample(cost_codes, k=min(_WORKING_CODE_COUNT, len(cost_codes)))
    days = _working_days(history, ending=datetime.now(UTC).date())
    plan = _status_plan(len(days))
    to_reverse = _reversal_index(plan)
    hours_config = dict(_HOURS_CONFIGS[slot % len(_HOURS_CONFIGS)])

    service = FieldTimeService(session)
    repo = FieldTimeRepository(session)
    counts = {"timesheets": 0, "lines": 0, "reversals": 0, "projects": 1}

    for index, day in enumerate(days):
        lines = _build_lines(
            rng,
            day_index=index,
            workers=workers,
            plant=plant,
            cost_codes=working_codes,
            variation_id=variation_id,
        )
        timesheet = await service.create_timesheet(
            FieldTimesheetCreate(
                project_id=project_id,
                date=day,
                note=rng.choice(_SHIFT_NOTES),
                metadata=dict(hours_config),
                lines=lines,
            ),
            submitter,
        )
        counts["timesheets"] += 1
        counts["lines"] += len(lines)

        target = plan[index]
        if target in (_SUBMITTED, _APPROVED):
            await service.submit_timesheet(timesheet.id, submitter)
        if target == _APPROVED:
            await service.approve_timesheet(timesheet.id, approver)
        # The service stamps "now" on both signatures, which is right for a
        # timesheet booked today and wrong for one booked five weeks ago. Move
        # them onto the day they belong to: signed at the end of the shift,
        # countersigned the next morning.
        await _backdate_signatures(repo, timesheet.id, day, target)

        if index == to_reverse and target == _APPROVED:
            reversal = await service.reverse_timesheet(
                timesheet.id,
                ReverseTimesheetRequest(note=_REVERSAL_NOTE),
                approver,
            )
            counts["reversals"] += 1
            counts["timesheets"] += 1
            counts["lines"] += len(lines)
            await _backdate_signatures(repo, reversal.id, day, _APPROVED)

    return counts


async def _backdate_signatures(
    repo: FieldTimeRepository,
    timesheet_id: uuid.UUID,
    day: date,
    target: str,
) -> None:
    """Move a sheet's submit / approve stamps onto the day it records."""
    fields: dict[str, object] = {}
    if target in (_SUBMITTED, _APPROVED):
        fields["submitted_at"] = _submitted_stamp(day)
    if target == _APPROVED:
        fields["approved_at"] = _approved_stamp(day)
    if fields:
        await repo.update_fields(timesheet_id, **fields)


async def seed_field_time_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Populate the field timesheet register for the given demo projects.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to seed. Each is skipped when it already has a
            timesheet, or when it has no crew or no priced BOQ to code hours to.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "timesheets": 0, "lines": 0, "reversals": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.owner_id).where(Project.id.in_(ids)))).all()
    owners = {pid: owner for pid, owner in rows}

    for ordinal, project_id in enumerate(ids):
        owner_id = owners.get(project_id)
        if owner_id is None:
            continue
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded
            # costs only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, owner_id, ordinal)
        except Exception:
            logger.warning("Field time demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals


def _same_instant(value: datetime | None, expected: datetime) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value == expected


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Timesheets in ``project_ids`` exactly as :func:`seed_field_time_demo` wrote them, and what they caused.

    Timesheet references come from the same per-project sequence a person's
    sheets use, so they prove nothing. A sheet matches instead when its shift
    note is one the seed picks from, its metadata is exactly one of the seed's
    hour configurations, and its signatures sit where the seed backdates them
    (sent at 17:30 on the day, approved at 08:15 the next morning; a draft
    carries neither). A person's sheet with the same note but signed when it
    was really signed is not matched. A reversal matches on the seed's reversal
    note and on reversing a matched sheet.

    Approving a sheet also wrote labour worker-days for the cost model and,
    where hours were booked to a variation, a daywork sheet. Neither has a
    foreign key back to the timesheet, so they are found through what they
    carry (the worker-day's source reference is the sheet id, the daywork
    description ends with the sheet reference) and listed before the sheets.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []
    from app.modules.costmodel.models import LabourWorkerDay
    from app.modules.variations.models import DayworkSheet

    notes = set(_SHIFT_NOTES)
    configs = [dict(c) for c in _HOURS_CONFIGS]
    rows = (
        await session.execute(
            select(
                FieldTimesheet.id,
                FieldTimesheet.project_id,
                FieldTimesheet.reference,
                FieldTimesheet.date,
                FieldTimesheet.status,
                FieldTimesheet.note,
                FieldTimesheet.metadata_,
                FieldTimesheet.submitted_at,
                FieldTimesheet.approved_at,
                FieldTimesheet.reverses_id,
            ).where(FieldTimesheet.project_id.in_(project_ids))
        )
    ).all()

    def signed_like_the_seed(r) -> bool:
        if r.submitted_at is None:
            return r.approved_at is None
        if not _same_instant(r.submitted_at, _submitted_stamp(r.date)):
            return False
        return r.approved_at is None or _same_instant(r.approved_at, _approved_stamp(r.date))

    originals = {
        r.id: r
        for r in rows
        if r.reverses_id is None and r.note in notes and dict(r.metadata_ or {}) in configs and signed_like_the_seed(r)
    }
    reversals = {r.id: r for r in rows if r.reverses_id in originals and r.note == _REVERSAL_NOTE}
    sheets = {**originals, **reversals}

    worker_days = []
    if sheets:
        worker_days = list(
            (
                await session.execute(
                    select(LabourWorkerDay.id).where(
                        LabourWorkerDay.project_id.in_(project_ids),
                        LabourWorkerDay.source_module == "field_time",
                        LabourWorkerDay.source_ref.in_([str(i) for i in sheets]),
                    )
                )
            )
            .scalars()
            .all()
        )

    suffixes = {(r.project_id, f"(timesheet {r.reference})") for r in sheets.values() if r.reference}
    daywork = [
        d.id
        for d in (
            await session.execute(
                select(DayworkSheet.id, DayworkSheet.project_id, DayworkSheet.description).where(
                    DayworkSheet.project_id.in_(project_ids)
                )
            )
        ).all()
        if any(d.project_id == pid and str(d.description or "").endswith(sfx) for pid, sfx in suffixes)
    ]

    return [
        (LabourWorkerDay, worker_days, "field_time_labour_worker_days"),
        (DayworkSheet, daywork, "field_time_daywork_sheets"),
        (FieldTimesheet, list(reversals), "field_time_reversals"),
        (FieldTimesheet, list(originals), "field_timesheets"),
    ]
