# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Progress demo seed - a percent-complete reading per position the crew worked on.

The demo install writes project-level progress only (one S-curve reading per
month, no position attached). That is enough for the project chart, but every
position-level figure - installed quantity, hours per installed unit, the
historical range a new estimate is compared with - needs a reading on the
position itself, so on a fresh demo they all read as "no data".

This seeder fills that gap, and only where the estate has a reason for it: a
position gets a reading when the field-time seed booked approved hours to it.
A position nobody worked on stays without one, which is what a real site has
too, and the KPI then correctly reports it as not started rather than slow.

Each reading is stamped with ``metadata_["demo_seed"] = "position_progress"``.
No API write produces that key, so :func:`seeded_row_ids` can tell these rows
from a person's own measurements on the same positions.

The percentages are drawn from a per-project RNG, so a re-seed of one project
reproduces it. Idempotent per project: a project that already has any
position-level reading is left untouched.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry

logger = logging.getLogger(__name__)

_SEED = 42

#: The mark every seeded reading carries in ``metadata_``.
SEED_MARKER_KEY = "demo_seed"
SEED_MARKER_VALUE = "position_progress"

# Percent complete drawn per position, in half-point steps. A month of hours
# on a position means real work got done, so nothing below about a third, and
# some positions are finished.
_MIN_PERCENT = 35
_MAX_PERCENT = 100

_NOTE = "Installed quantity measured on site."


def _rng_for(project_id: uuid.UUID) -> random.Random:
    """A deterministic RNG per project, so a re-seed reproduces the readings."""
    return random.Random(f"{_SEED}:position_progress:{project_id}")


def _draw_percent(rng: random.Random) -> Decimal:
    """A percent between the bounds, in half-point steps."""
    steps = rng.randint(_MIN_PERCENT * 2, _MAX_PERCENT * 2)
    return Decimal(steps) / Decimal(2)


def _period_label(today: datetime) -> str:
    """``YYYY-MM`` of the run date, the label the demo's own readings use."""
    return f"{today.year:04d}-{today.month:02d}"


def _positive_quantity(value: object) -> bool:
    try:
        return Decimal(str(value or "0")) > 0
    except (InvalidOperation, ValueError):
        return False


async def _worked_positions(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Positions of this project with approved, non-reversed hours booked to them.

    Ordered by ordinal so the RNG hands out the same percent to the same
    position on every run. Section headers and positions without a quantity
    are left out: a percent of nothing installs nothing.
    """
    try:
        from app.modules.boq.models import BOQ, Position
        from app.modules.field_time.counted import counted_timesheet_clause
        from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    except ImportError:
        logger.debug("BOQ or field time module not loaded; no position progress for project=%s", project_id)
        return []

    stmt = (
        select(Position.id, Position.quantity, Position.unit)
        .join(BOQ, Position.boq_id == BOQ.id)
        .where(
            BOQ.project_id == project_id,
            Position.id.in_(
                select(FieldTimesheetLine.boq_position_id)
                .join(FieldTimesheet, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
                .where(
                    FieldTimesheet.project_id == project_id,
                    FieldTimesheetLine.boq_position_id.is_not(None),
                    counted_timesheet_clause(),
                )
            ),
        )
        .order_by(Position.ordinal, Position.id)
    )
    rows = (await session.execute(stmt)).all()
    return [pid for pid, quantity, unit in rows if str(unit or "").strip() and _positive_quantity(quantity)]


async def _has_position_progress(session: AsyncSession, project_id: uuid.UUID) -> bool:
    found = (
        (
            await session.execute(
                select(ProgressEntry.id)
                .where(ProgressEntry.project_id == project_id, ProgressEntry.boq_position_id.is_not(None))
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    return found is not None


async def _seed_project(session: AsyncSession, project_id: uuid.UUID, owner_id: uuid.UUID | None) -> int:
    """Write one reading per worked position. Returns how many were written."""
    if await _has_position_progress(session, project_id):
        return 0
    positions = await _worked_positions(session, project_id)
    if not positions:
        return 0
    rng = _rng_for(project_id)
    period = _period_label(datetime.now(UTC))
    for position_id in positions:
        session.add(
            ProgressEntry(
                project_id=project_id,
                boq_position_id=position_id,
                period_label=period,
                percent_complete=_draw_percent(rng),
                notes=_NOTE,
                recorded_by=str(owner_id) if owner_id else None,
                metadata_={SEED_MARKER_KEY: SEED_MARKER_VALUE},
            )
        )
    await session.flush()
    return len(positions)


async def seed_position_progress_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Record a percent-complete reading on each demo position the crew booked hours to.

    Runs after :func:`app.modules.field_time.seed.seed_field_time_demo`, whose
    approved hours decide which positions get a reading.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to seed. Each is skipped when it already has a
            position-level reading, or when no approved hours name a position.

    Returns:
        Dict with ``projects`` and ``entries`` insert counts.
    """
    totals = {"projects": 0, "entries": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (await session.execute(select(Project.id, Project.owner_id).where(Project.id.in_(ids)))).all()
    owners = {pid: owner for pid, owner in rows}

    for project_id in ids:
        if project_id not in owners:
            continue
        try:
            # A SAVEPOINT per project: on PostgreSQL a failed statement aborts
            # the whole transaction, so without it one bad project would fail
            # every project after it.
            async with session.begin_nested():
                written = await _seed_project(session, project_id, owners[project_id])
        except Exception:
            logger.warning("Position progress demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        if written:
            totals["projects"] += 1
            totals["entries"] += written
    return totals


def is_seeded_entry(metadata: object) -> bool:
    """Whether a reading's metadata carries this seeder's mark."""
    return isinstance(metadata, dict) and metadata.get(SEED_MARKER_KEY) == SEED_MARKER_VALUE


async def seeded_row_ids(session: AsyncSession, project_ids: list[uuid.UUID]) -> list[tuple[type, list, str]]:
    """Position readings in ``project_ids`` that :func:`seed_position_progress_demo` wrote.

    Only rows carrying the seed's mark match, so a person's own measurement on
    the same position is never listed.

    Returns:
        ``(model, ids, label)`` groups; ``label`` names the group in reports.
    """
    if not project_ids:
        return []
    rows = (
        await session.execute(
            select(ProgressEntry.id, ProgressEntry.metadata_).where(
                ProgressEntry.project_id.in_(project_ids),
                ProgressEntry.boq_position_id.is_not(None),
            )
        )
    ).all()
    ids = [rid for rid, metadata in rows if is_seeded_entry(metadata)]
    return [(ProgressEntry, ids, "progress_position_readings")]
