# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Progress tracking data access layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progress.models import ProgressEntry, ProgressPlan


def _latest_first() -> tuple:
    """Return the ORDER BY that puts the winning progress entry first.

    Progress entries are append-only: a mistake is corrected by recording a
    NEW entry, so the reading that counts is the LATEST one, never the
    largest. The tiers are:

    1. ``seq DESC`` - the database-assigned insertion counter. Strictly
       increasing per INSERT, NOT NULL and unique, so it is a TOTAL order:
       the row appended last always wins, including for rows written inside
       one transaction where no timestamp can separate them.
    2. ``recorded_at DESC``
    3. ``created_at DESC``
    4. ``id DESC``

    Tiers 2 to 4 are unreachable while ``seq`` is populated, and are kept only
    as a defensive fallback. They are not the guarantee; ``seq`` is.

    Why the timestamps could not do this on their own: ``recorded_at``
    defaults to the DB's ``now()``, which in PostgreSQL is the TRANSACTION
    timestamp and is therefore identical for every row one transaction
    writes, and ``created_at`` is a Python ``datetime.now()`` whose
    granularity is ~1 ms on Windows against ~1 ns on Linux, so it ties on a
    coarse clock. With both tied the winner used to fall to a random uuid4 -
    stable, but arbitrary, which meant a bulk-imported correction won only by
    luck. See migration ``v3258_progress_entry_seq``.
    """
    return (
        ProgressEntry.seq.desc(),
        ProgressEntry.recorded_at.desc(),
        ProgressEntry.created_at.desc(),
        ProgressEntry.id.desc(),
    )


def _oldest_first() -> tuple:
    """Return the ORDER BY the paginated register reads in, oldest first.

    The mirror of :func:`_latest_first`, and total for the same reason. The
    register is read a page at a time with OFFSET/LIMIT, and OFFSET is only
    meaningful against a total order: ``recorded_at`` defaults to the DB's
    ``now()``, which in PostgreSQL is the TRANSACTION timestamp, so every
    entry one write appends shares it, and a bulk field import appends many.
    Ordered by the timestamp alone the database may arrange the tied rows
    differently for each OFFSET it serves, so a walk through the pages can
    return one entry twice and never return another, with each page looking
    correct on its own.

    ``seq`` is NOT NULL and unique per INSERT, so ending on it makes the
    order total. That is the property this tuple exists to hold, and the one
    ``test_progress_entry_page_walk`` asserts: the last key must be a column
    that cannot tie.
    """
    return (
        ProgressEntry.recorded_at.asc(),
        ProgressEntry.seq.asc(),
    )


class ProgressRepository:
    """Data access for ProgressEntry and ProgressPlan models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── ProgressEntry ────────────────────────────────────────────────────

    async def create_entry(self, entry: ProgressEntry) -> ProgressEntry:
        """Insert a new progress entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_entry(self, entry_id: uuid.UUID) -> ProgressEntry | None:
        return await self.session.get(ProgressEntry, entry_id)

    async def list_entries_for_project(
        self,
        project_id: uuid.UUID,
        *,
        boq_position_id: uuid.UUID | None = None,
        period_label: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[ProgressEntry]:
        """Return progress entries, optionally filtered by position or period.

        Paginated, so the order has to be total; see :func:`_oldest_first`.
        """
        stmt = select(ProgressEntry).where(ProgressEntry.project_id == project_id)
        if boq_position_id is not None:
            stmt = stmt.where(ProgressEntry.boq_position_id == boq_position_id)
        if period_label is not None:
            stmt = stmt.where(ProgressEntry.period_label == period_label)
        stmt = stmt.order_by(*_oldest_first()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def latest_pct_for_positions(
        self,
        project_id: uuid.UUID,
        position_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Return the most-recent percent_complete for each requested position.

        Ranks each position's history with ROW_NUMBER and keeps rank 1, so
        exactly one row per position comes back without loading all history.
        The previous MAX(recorded_at) + join produced TWO rows when a position
        had two entries sharing the same ``recorded_at`` and silently kept
        whichever the planner emitted last; see :func:`_latest_first`.
        """
        if not position_ids:
            return {}

        ranked = (
            select(
                ProgressEntry.boq_position_id,
                ProgressEntry.percent_complete,
                func.row_number()
                .over(
                    partition_by=ProgressEntry.boq_position_id,
                    order_by=_latest_first(),
                )
                .label("rn"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.in_(position_ids),
            )
            .subquery()
        )

        stmt = select(ranked.c.boq_position_id, ranked.c.percent_complete).where(ranked.c.rn == 1)
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: float(row[1]) for row in rows}

    async def latest_pct_and_date_for_positions(
        self,
        project_id: uuid.UUID,
        position_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, tuple[float, object | None]]:
        """Return ``{position_id: (percent_complete, recorded_at)}`` for the
        most-recent entry of each requested position.

        Same single-round-trip shape as :meth:`latest_pct_for_positions`, but
        also surfaces the timestamp of the winning entry so callers (the BIM
        "By progress" overlay) can show *when* the headline percentage was
        recorded. ``recorded_at`` is a timezone-aware datetime; the caller
        decides how to format it.
        """
        if not position_ids:
            return {}

        ranked = (
            select(
                ProgressEntry.boq_position_id,
                ProgressEntry.percent_complete,
                ProgressEntry.recorded_at,
                func.row_number()
                .over(
                    partition_by=ProgressEntry.boq_position_id,
                    order_by=_latest_first(),
                )
                .label("rn"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.in_(position_ids),
            )
            .subquery()
        )

        stmt = select(
            ranked.c.boq_position_id,
            ranked.c.percent_complete,
            ranked.c.recorded_at,
        ).where(ranked.c.rn == 1)
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: (float(row[1]), row[2]) for row in rows}

    async def get_latest_for_position(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
        *,
        as_of: datetime | None = None,
    ) -> ProgressEntry | None:
        """Return the most-recent progress observation for one BOQ position.

        Used by the contracts progress-claim bridge (Gap I) to read the current
        percent-complete of a single SoV-linked BOQ position. Returns ``None``
        when no observation has been recorded yet (the bridge then skips that
        line). Scoped by ``project_id`` so a position id from another project
        can never leak an observation across the tenant boundary.

        Ordered by :func:`_latest_first`, like every other "latest wins" read
        here. Ordering by ``recorded_at`` alone was not a total order: two
        readings sharing a timestamp - a correction typed in the same
        transaction as the reading it corrects, or a bulk import - left the
        winner to the planner.

        Args:
            project_id: tenant scope; a position from another project reads
                nothing.
            boq_position_id: the position to read.
            as_of: ignore observations recorded after this instant. A payment
                application bills one period, so the reading that belongs in
                it is the latest one taken by the end of that period, not the
                latest one taken. Without this, a claim raised for March and
                populated in May billed May's percent complete against March's
                period and left April's claim to work out the difference.
                ``recorded_at`` is what this compares, because it is when the
                measurement was taken; ``period_label`` is a free-form
                ``String(20)`` with no order to it, and ``seq`` orders writes
                rather than observations. Callers pass the end of the day,
                since ``recorded_at`` carries a time and the period end is a
                date.
        """
        stmt = select(ProgressEntry).where(
            ProgressEntry.project_id == project_id,
            ProgressEntry.boq_position_id == boq_position_id,
        )
        if as_of is not None:
            stmt = stmt.where(ProgressEntry.recorded_at <= as_of)
        result = await self.session.execute(stmt.order_by(*_latest_first()).limit(1))
        return result.scalar_one_or_none()

    async def get_latest_project_entry(self, project_id: uuid.UUID) -> ProgressEntry | None:
        """Return the most recent *project-level* progress entry.

        A project-level entry is one with ``boq_position_id IS NULL`` - a
        manual overall-completion reading recorded against the whole
        project rather than a single BOQ position. The reporting module
        uses this as the headline "overall % complete" figure on the
        progress report. Returns ``None`` when no project-level entry has
        been recorded yet (the reporting layer then falls back to the
        cumulative series).

        Ordered by :func:`_latest_first`: this is the headline percentage on
        the report, so it has to be the same winner the rest of the module
        would pick, not whichever row a coarse timestamp happened to favour.
        """
        stmt = (
            select(ProgressEntry)
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.is_(None),
            )
            .order_by(*_latest_first())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_entries_for_period(
        self,
        project_id: uuid.UUID,
        period_label: str,
    ) -> list[ProgressEntry]:
        """Return every progress entry recorded in a given period, newest first.

        Used by the reporting module to summarise a reporting window
        (e.g. ``2026-W22``) on the progress report: the number of
        observations and the latest reading inside that window.

        "Newest first" is :func:`_latest_first`, not ``recorded_at`` alone.
        The caller reads the window's headline percentage off element 0, so
        the first row has to be the same winner the rest of the module would
        pick; the count it takes alongside does not depend on the order.
        """
        stmt = (
            select(ProgressEntry)
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.period_label == period_label,
            )
            .order_by(*_latest_first())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def pct_by_period_for_position(
        self,
        project_id: uuid.UUID,
        boq_position_id: uuid.UUID,
    ) -> list[tuple[str, float]]:
        """Return ``(period_label, latest_pct)`` for ONE BOQ position, oldest period first.

        Several readings inside one period collapse to the LATEST one, not
        the largest: a foreman who corrects 90 % down to 30 % must see 30 %.
        See :func:`_latest_first` for the ordering and its tiebreakers.

        Args:
            project_id: Project the position belongs to (tenant scope).
            boq_position_id: The position whose series is wanted.

        Returns:
            ``(period_label, percent_complete)`` pairs sorted by period label.
        """
        ranked = (
            select(
                ProgressEntry.period_label,
                ProgressEntry.percent_complete,
                func.row_number().over(partition_by=ProgressEntry.period_label, order_by=_latest_first()).label("rn"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id == boq_position_id,
            )
            .subquery()
        )
        stmt = (
            select(ranked.c.period_label, ranked.c.percent_complete)
            .where(ranked.c.rn == 1)
            .order_by(ranked.c.period_label.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows]

    async def project_level_pct_by_period(
        self,
        project_id: uuid.UUID,
    ) -> list[tuple[str, float]]:
        """Return ``(period_label, latest_pct)`` over PROJECT-LEVEL entries only.

        A project-level entry is one with ``boq_position_id IS NULL`` - a
        manual overall-completion reading for the whole project. Position
        readings are deliberately excluded: pooling the two scopes in one
        aggregate is what used to let a single 90 % line item present itself
        as the project's headline percentage. Within a period the LATEST
        reading wins (see :func:`_latest_first`).

        Args:
            project_id: Project to read.

        Returns:
            ``(period_label, percent_complete)`` pairs sorted by period label.
        """
        ranked = (
            select(
                ProgressEntry.period_label,
                ProgressEntry.percent_complete,
                func.row_number().over(partition_by=ProgressEntry.period_label, order_by=_latest_first()).label("rn"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.is_(None),
            )
            .subquery()
        )
        stmt = (
            select(ranked.c.period_label, ranked.c.percent_complete)
            .where(ranked.c.rn == 1)
            .order_by(ranked.c.period_label.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], float(row[1])) for row in rows]

    async def position_pct_by_period(
        self,
        project_id: uuid.UUID,
    ) -> list[tuple[str, uuid.UUID, float]]:
        """Return ``(period_label, boq_position_id, latest_pct)`` per position and period.

        The grain is one row per (period, position): several readings for the
        SAME position inside one period collapse to the LATEST one, while
        different positions stay separate so the service can weight them.
        Project-level entries (``boq_position_id IS NULL``) are excluded -
        they are the fallback series, not rollup input.

        Args:
            project_id: Project to read.

        Returns:
            Rows sorted by period label, then position id.
        """
        ranked = (
            select(
                ProgressEntry.period_label,
                ProgressEntry.boq_position_id,
                ProgressEntry.percent_complete,
                func.row_number()
                .over(
                    partition_by=(ProgressEntry.period_label, ProgressEntry.boq_position_id),
                    order_by=_latest_first(),
                )
                .label("rn"),
            )
            .where(
                ProgressEntry.project_id == project_id,
                ProgressEntry.boq_position_id.is_not(None),
            )
            .subquery()
        )
        stmt = (
            select(ranked.c.period_label, ranked.c.boq_position_id, ranked.c.percent_complete)
            .where(ranked.c.rn == 1)
            .order_by(ranked.c.period_label.asc(), ranked.c.boq_position_id.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1], float(row[2])) for row in rows]

    async def period_labels(self, project_id: uuid.UUID) -> list[str]:
        """Return every period label the project has an observation in, oldest first.

        This is the period AXIS of the cumulative series, kept separate from
        the values so that a period is never dropped just because none of the
        readings inside it feed the rollup. A period holding only a
        project-level entry, or only readings against positions that are not
        in the project's BOQs, still happened and still has to render a row.

        Args:
            project_id: Project to read.

        Returns:
            Distinct period labels sorted ascending.
        """
        stmt = (
            select(ProgressEntry.period_label)
            .where(ProgressEntry.project_id == project_id)
            .distinct()
            .order_by(ProgressEntry.period_label.asc())
        )
        rows = (await self.session.execute(stmt)).all()
        return [row[0] for row in rows]

    async def entry_counts_by_period(
        self,
        project_id: uuid.UUID,
        *,
        boq_position_id: uuid.UUID | None = None,
    ) -> dict[str, int]:
        """Return ``{period_label: number_of_entries_recorded_in_it}``.

        Counts observations, not positions: every row recorded in the period
        is counted, project-level and position-level alike, because the
        caller renders it as an "entries" column. Passing a position narrows
        the count to that position's own observations.

        Args:
            project_id: Project to count within.
            boq_position_id: Optional position filter.

        Returns:
            Period label mapped to its entry count. Periods with no entries
            are simply absent.
        """
        stmt = select(ProgressEntry.period_label, func.count()).where(ProgressEntry.project_id == project_id)
        if boq_position_id is not None:
            stmt = stmt.where(ProgressEntry.boq_position_id == boq_position_id)
        stmt = stmt.group_by(ProgressEntry.period_label)
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: int(row[1]) for row in rows}

    # ── ProgressPlan ─────────────────────────────────────────────────────

    async def upsert_plan(
        self,
        project_id: uuid.UUID,
        period_label: str,
        planned_pct: float,
        notes: str | None = None,
    ) -> ProgressPlan:
        """Insert or update a plan point for (project, period_label)."""
        stmt = select(ProgressPlan).where(
            ProgressPlan.project_id == project_id,
            ProgressPlan.period_label == period_label,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.planned_pct = planned_pct  # type: ignore[assignment]
            if notes is not None:
                existing.notes = notes  # type: ignore[assignment]
            await self.session.flush()
            return existing

        plan = ProgressPlan(
            project_id=project_id,
            period_label=period_label,
            planned_pct=planned_pct,
            notes=notes,
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def list_plan(self, project_id: uuid.UUID) -> list[ProgressPlan]:
        """Return all plan points ordered by period_label."""
        stmt = (
            select(ProgressPlan).where(ProgressPlan.project_id == project_id).order_by(ProgressPlan.period_label.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
