"""‌⁠‍BOQ data access layer.

All database queries for BOQs, positions, markups, and activity logs live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.modules.boq.models import (
    BOQ,
    BOQActivityLog,
    BOQMarkup,
    Position,
    QuantityLink,
)


class BOQRepository:
    """‌⁠‍Data access for BOQ model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, boq_id: uuid.UUID) -> BOQ | None:
        """‌⁠‍Get BOQ by ID."""
        return await self.session.get(BOQ, boq_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a project with pagination. Returns (boqs, total_count).

        Positions and markups are NOT eagerly loaded here — use
        ``grand_totals_for_boqs`` to compute totals via a single aggregate query.
        """
        base = select(BOQ).where(BOQ.project_id == project_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch — skip eager loading of positions/markups for list queries
        stmt = (
            base.options(noload(BOQ.positions), noload(BOQ.markups))
            .order_by(BOQ.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        boqs = list(result.scalars().all())

        return boqs, total

    async def grand_totals_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Compute grand total (direct cost + markups) for each BOQ by ID.

        Convenience wrapper around :meth:`totals_for_boqs` for the
        majority of callers that only need the grand total — keeps the
        existing `dict[uuid.UUID, float]` shape.
        """
        breakdown = await self.totals_for_boqs(boq_ids)
        return {bid: t["grand_total"] for bid, t in breakdown.items()}

    async def totals_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, float]]:
        """Compute the full money breakdown per BOQ.

        Returns ``{boq_id: {direct_cost, markups_total, grand_total}}``.

        First aggregates position totals per BOQ, then applies active markups
        (percentage or fixed) in sort_order to arrive at the final grand total.
        Single source of truth for BUG-008 (list and detail must match).
        """
        if not boq_ids:
            return {}

        from decimal import Decimal

        from sqlalchemy import Float, cast

        # Step 1: sum direct cost (position totals) per BOQ
        pos_stmt = (
            select(
                Position.boq_id,
                func.sum(cast(Position.total, Float)).label("direct_cost"),
            )
            .where(Position.boq_id.in_(boq_ids))
            .group_by(Position.boq_id)
        )
        pos_result = await self.session.execute(pos_stmt)
        direct_costs: dict[uuid.UUID, float] = {row.boq_id: float(row.direct_cost or 0) for row in pos_result}

        # Step 2: fetch active markups for all requested BOQs
        markup_stmt = (
            select(BOQMarkup)
            .where(BOQMarkup.boq_id.in_(boq_ids), BOQMarkup.is_active.is_(True))
            .order_by(BOQMarkup.sort_order)
        )
        markup_result = await self.session.execute(markup_stmt)
        markups_by_boq: dict[uuid.UUID, list[BOQMarkup]] = {}
        for markup in markup_result.scalars().all():
            markups_by_boq.setdefault(markup.boq_id, []).append(markup)

        # Step 3: apply markups to compute grand total per BOQ
        breakdown: dict[uuid.UUID, dict[str, float]] = {}
        for boq_id in boq_ids:
            dc = Decimal(str(direct_costs.get(boq_id, 0)))
            running = dc
            for m in markups_by_boq.get(boq_id, []):
                if m.markup_type == "percentage":
                    pct = Decimal(m.percentage or "0")
                    # BUG-B-005: ``subtotal`` bases on direct_cost +
                    # Σ(preceding markups), identical to ``cumulative`` —
                    # keep list/detail rollup consistent with
                    # ``_calculate_markup_amounts``.
                    base = running if m.apply_to in ("cumulative", "subtotal") else dc
                    running += base * pct / Decimal("100")
                elif m.markup_type == "fixed":
                    running += Decimal(m.fixed_amount or "0")
            # BUG-B-001 / BUG-B-012: commercial ROUND_HALF_UP to cents,
            # matching service-layer ``_round_currency`` so list and detail
            # report one canonical figure (banker's ``round()`` on float
            # diverged on .xx5 boundaries).
            from decimal import ROUND_HALF_UP

            cent = Decimal("0.01")
            grand_total = float(running.quantize(cent, rounding=ROUND_HALF_UP))
            direct_cost_value = float(dc.quantize(cent, rounding=ROUND_HALF_UP))
            markups_total = float(
                (running - dc).quantize(cent, rounding=ROUND_HALF_UP),
            )
            breakdown[boq_id] = {
                "direct_cost": direct_cost_value,
                "markups_total": markups_total,
                "grand_total": grand_total,
            }

        return breakdown

    async def create(self, boq: BOQ) -> BOQ:
        """Insert a new BOQ."""
        self.session.add(boq)
        await self.session.flush()
        return boq

    async def update_fields(self, boq_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a BOQ."""
        stmt = update(BOQ).where(BOQ.id == boq_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, boq_id: uuid.UUID) -> None:
        """Delete a BOQ and all its positions (via CASCADE)."""
        stmt = delete(BOQ).where(BOQ.id == boq_id)
        await self.session.execute(stmt)


class PositionRepository:
    """Data access for Position model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, position_id: uuid.UUID) -> Position | None:
        """Get position by ID."""
        return await self.session.get(Position, position_id)

    async def list_by_ids(self, position_ids: list[uuid.UUID]) -> list[Position]:
        """Bulk-fetch positions by id set in one query.

        v4.2.2 Round 2 Wave C: callers that previously looped
        ``get_by_id`` per id (an N+1) should pre-fetch with this method
        and look up by id from a dict. Returns positions in unspecified
        order; the empty input case is short-circuited so SQLAlchemy
        never emits a degenerate ``WHERE id IN ()`` query.
        """
        if not position_ids:
            return []
        stmt = select(Position).where(Position.id.in_(position_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_children(self, parent_id: uuid.UUID) -> list[Position]:
        """List direct children of a position (one level only)."""
        stmt = select(Position).where(Position.parent_id == parent_id).order_by(Position.sort_order)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_boq(
        self,
        boq_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Position], int]:
        """List positions for a BOQ ordered by sort_order. Returns (positions, total)."""
        base = select(Position).where(Position.boq_id == boq_id)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch ordered by sort_order, then ordinal
        stmt = base.order_by(Position.sort_order, Position.ordinal).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        positions = list(result.scalars().all())

        return positions, total

    async def list_all_for_boq(self, boq_id: uuid.UUID) -> list[Position]:
        """Return EVERY position for a BOQ ordered by sort_order, no limit.

        BUG-B-006: ``list_for_boq`` carries a hard ``limit=1000`` default for
        paginated UI listing. Every money rollup (direct_cost, grand_total,
        markup base, statistics, cost-breakdown, recalculate-rates,
        duplicate) MUST sum all positions — a 1500-position BOQ was silently
        dropping positions 1001+ from every total. Aggregation callers use
        this method so the count limit can never under-state a tender.
        """
        stmt = select(Position).where(Position.boq_id == boq_id).order_by(Position.sort_order, Position.ordinal)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, position: Position) -> Position:
        """Insert a new position."""
        self.session.add(position)
        await self.session.flush()
        await self.session.refresh(position)
        return position

    async def bulk_create(self, positions: list[Position]) -> list[Position]:
        """Insert multiple positions at once."""
        self.session.add_all(positions)
        await self.session.flush()
        for pos in positions:
            await self.session.refresh(pos)
        return positions

    async def update_fields(self, position_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a position."""
        stmt = update(Position).where(Position.id == position_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def delete(self, position_id: uuid.UUID) -> None:
        """Delete a single position."""
        stmt = delete(Position).where(Position.id == position_id)
        await self.session.execute(stmt)

    async def reorder(self, position_ids: list[uuid.UUID], boq_id: uuid.UUID) -> None:
        """Reorder positions by assigning sort_order based on list index.

        Only touches positions that belong to ``boq_id`` — foreign IDs are
        silently skipped (UPDATE rows=0) rather than mutating positions in
        another user's BOQ (cross-tenant sort_order pollution).

        Args:
            position_ids: Ordered list of position UUIDs. Index becomes sort_order.
            boq_id: Owning BOQ — positions not in this BOQ are not affected.
        """
        for index, pid in enumerate(position_ids):
            stmt = (
                update(Position)
                .where(Position.id == pid, Position.boq_id == boq_id)
                .values(sort_order=index)
            )
            await self.session.execute(stmt)

    async def get_max_sort_order(self, boq_id: uuid.UUID) -> int:
        """Get the highest sort_order for positions in a BOQ."""
        stmt = select(func.coalesce(func.max(Position.sort_order), -1)).where(Position.boq_id == boq_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)

    async def shift_sort_order_after(self, boq_id: uuid.UUID, threshold: int) -> None:
        """Open a one-slot gap by bumping every later position down by one.

        Every position in ``boq_id`` whose ``sort_order`` is strictly greater
        than ``threshold`` gets ``sort_order += 1``. Used by issue #139 so a
        freshly added partida can slot in directly *after* the selected row
        (``sort_order = threshold + 1``) instead of at the end of the section.
        """
        stmt = (
            update(Position)
            .where(Position.boq_id == boq_id, Position.sort_order > threshold)
            .values(sort_order=Position.sort_order + 1)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def ordinal_exists(self, boq_id: uuid.UUID, ordinal: str, exclude_id: uuid.UUID | None = None) -> bool:
        """Check if a position with the given ordinal already exists in the BOQ.

        Args:
            boq_id: The BOQ to check in.
            ordinal: The ordinal string to check for duplicates.
            exclude_id: Optional position ID to exclude (for update checks).

        Returns:
            True if a position with this ordinal already exists.
        """
        stmt = select(func.count()).where(Position.boq_id == boq_id, Position.ordinal == ordinal)
        if exclude_id is not None:
            stmt = stmt.where(Position.id != exclude_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result) > 0

    # ── Issue #127: linked-position group access ──────────────────────────

    async def project_id_for_boq(self, boq_id: uuid.UUID) -> uuid.UUID | None:
        """Resolve the owning project id for a BOQ id.

        Linked-position groups are scoped to ONE project (all BOQs of that
        project), so reuse-by-code lookups must join through the project.
        """
        stmt = select(BOQ.project_id).where(BOQ.id == boq_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def find_master_by_reference_code(
        self,
        project_id: uuid.UUID,
        reference_code: str,
    ) -> Position | None:
        """Return the definition-owner Position for ``reference_code`` in a project.

        Searches every BOQ of the project (Position → BOQ → project_id).
        Preference order:

        1. an explicit ``link_role='master'`` row, else
        2. the oldest standalone owner of that code (will be promoted to
           master by the service when a reuse instance is created).

        Returns ``None`` when the code is unused anywhere in the project.
        """
        rc = (reference_code or "").strip()
        if not rc:
            return None
        base = (
            select(Position)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.reference_code == rc)
        )
        # 1. explicit master wins
        master_stmt = base.where(Position.link_role == "master").order_by(Position.created_at)
        master = (await self.session.execute(master_stmt)).scalars().first()
        if master is not None:
            return master
        # 2. oldest standalone owner of the code
        standalone_stmt = base.order_by(Position.created_at)
        return (await self.session.execute(standalone_stmt)).scalars().first()

    async def list_link_group(self, link_group_id: uuid.UUID) -> list[Position]:
        """Return every position in a link group, oldest first.

        Ordered by ``created_at`` so master-promotion picks the oldest
        instance deterministically.
        """
        stmt = (
            select(Position)
            .where(Position.link_group_id == link_group_id)
            .order_by(Position.created_at, Position.sort_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_project(self, project_id: uuid.UUID) -> list[Position]:
        """Return EVERY position across all BOQs of a project, oldest first.

        Issue #133. Resource codes live in ``metadata.resources[].code``
        (JSON, no SQL column), so a project-wide resource-by-code lookup
        must scan positions of every BOQ in the project. Ordered by
        ``created_at`` so the first match is the original definition.
        """
        stmt = (
            select(Position)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id)
            .order_by(Position.created_at, Position.sort_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def reference_code_exists_in_project(
        self,
        project_id: uuid.UUID,
        reference_code: str,
    ) -> bool:
        """True if any position in the project already uses ``reference_code``.

        Used to keep auto-generated internal codes ("R-XXXXXXXX") unique
        across the whole project.
        """
        rc = (reference_code or "").strip()
        if not rc:
            return False
        stmt = (
            select(func.count())
            .select_from(Position)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.reference_code == rc)
        )
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result) > 0


class MarkupRepository:
    """Data access for BOQMarkup model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, markup_id: uuid.UUID) -> BOQMarkup | None:
        """Get a markup by ID."""
        return await self.session.get(BOQMarkup, markup_id)

    async def list_for_boq(self, boq_id: uuid.UUID) -> list[BOQMarkup]:
        """List all markups for a BOQ ordered by sort_order."""
        stmt = select(BOQMarkup).where(BOQMarkup.boq_id == boq_id).order_by(BOQMarkup.sort_order, BOQMarkup.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, markup: BOQMarkup) -> BOQMarkup:
        """Insert a new markup."""
        self.session.add(markup)
        await self.session.flush()
        await self.session.refresh(markup)
        return markup

    async def bulk_create(self, markups: list[BOQMarkup]) -> list[BOQMarkup]:
        """Insert multiple markups at once."""
        self.session.add_all(markups)
        await self.session.flush()
        for m in markups:
            await self.session.refresh(m)
        return markups

    async def update_fields(self, markup_id: uuid.UUID, **fields: object) -> BOQMarkup | None:
        """Update specific fields on a markup and return refreshed object."""
        stmt = update(BOQMarkup).where(BOQMarkup.id == markup_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        markup = await self.session.get(BOQMarkup, markup_id)
        if markup is not None:
            await self.session.refresh(markup)
        return markup

    async def delete(self, markup_id: uuid.UUID) -> None:
        """Delete a single markup."""
        stmt = delete(BOQMarkup).where(BOQMarkup.id == markup_id)
        await self.session.execute(stmt)

    async def delete_all_for_boq(self, boq_id: uuid.UUID) -> None:
        """Delete all markups for a BOQ (used before applying defaults)."""
        stmt = delete(BOQMarkup).where(BOQMarkup.boq_id == boq_id)
        await self.session.execute(stmt)

    async def get_max_sort_order(self, boq_id: uuid.UUID) -> int:
        """Get the highest sort_order for markups in a BOQ."""
        stmt = select(func.coalesce(func.max(BOQMarkup.sort_order), -1)).where(BOQMarkup.boq_id == boq_id)
        result = (await self.session.execute(stmt)).scalar_one()
        return int(result)


class ActivityLogRepository:
    """Data access for BOQActivityLog model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, entry: BOQActivityLog) -> BOQActivityLog:
        """Insert a new activity log entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_for_boq(
        self,
        boq_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQActivityLog], int]:
        """List activity log entries for a BOQ, newest first.

        Returns (entries, total_count).
        """
        base = select(BOQActivityLog).where(BOQActivityLog.boq_id == boq_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BOQActivityLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQActivityLog], int]:
        """List activity log entries for a project, newest first.

        Returns (entries, total_count).
        """
        base = select(BOQActivityLog).where(BOQActivityLog.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(BOQActivityLog.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        entries = list(result.scalars().all())

        return entries, total


class QuantityLinkRepository:
    """Data access for QuantityLink — model→position quantity bindings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, link_id: uuid.UUID) -> QuantityLink | None:
        """Get a quantity link by its primary key."""
        return await self.session.get(QuantityLink, link_id)

    async def list_for_position(self, position_id: uuid.UUID) -> list[QuantityLink]:
        """List every quantity link bound to a single position, oldest first."""
        stmt = select(QuantityLink).where(QuantityLink.position_id == position_id).order_by(QuantityLink.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_boq(self, boq_id: uuid.UUID) -> list[QuantityLink]:
        """List every quantity link for a BOQ, ordered by position then age."""
        stmt = (
            select(QuantityLink)
            .where(QuantityLink.boq_id == boq_id)
            .order_by(QuantityLink.position_id, QuantityLink.created_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, link: QuantityLink) -> QuantityLink:
        """Insert a new quantity link and return it with its generated id."""
        self.session.add(link)
        await self.session.flush()
        await self.session.refresh(link)
        return link

    async def update_fields(self, link_id: uuid.UUID, **fields: object) -> None:
        """Update specific columns on a quantity link.

        Expires the identity map afterwards so a subsequent ``get_by_id``
        re-reads the freshly persisted row (mirrors PositionRepository).
        """
        stmt = update(QuantityLink).where(QuantityLink.id == link_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, link_id: uuid.UUID) -> None:
        """Delete a single quantity link by id."""
        stmt = delete(QuantityLink).where(QuantityLink.id == link_id)
        await self.session.execute(stmt)
        await self.session.flush()
