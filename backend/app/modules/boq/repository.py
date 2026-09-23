# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ data access layer.

All database queries for BOQs, positions, markups, and activity logs live here.
No business logic - pure data access.
"""

import json
import uuid
from collections.abc import Iterable

from sqlalchemy import Row, RowMapping, Text, any_, cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import array as pg_array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement, ColumnElement

from app.core.sql_numeric import numeric_value
from app.modules.boq.models import (
    BOQ,
    BOQActivityLog,
    BOQMarkup,
    Position,
    QuantityLink,
)

# ``Position`` declares its self-referential ``children`` and ``parent``
# relationships as ``lazy="selectin"`` so a single position fetch eagerly
# hydrates its tree neighbours. That is wasted work for every BOQ-wide read:
# the service layer NEVER navigates those relationships - it rebuilds the
# hierarchy in-memory from the ``parent_id`` column (see
# ``service.get_boq_structured`` / ``_subtree_height``). Without suppressing
# them, ``list_all_for_boq`` on a 6 k-position BOQ fires the main SELECT plus
# two extra ``selectin`` round trips (one ``parent_id IN (...)`` and one
# ``id IN (...)``) and materialises the full neighbour graph. Suppressing the
# eager load is behaviour-preserving (no caller reads ``.children``/``.parent``)
# and cuts those reads to a single query.
_POSITION_NOLOAD_TREE = (noload(Position.children), noload(Position.parent))

# Code points outside ASCII whose Unicode case fold is nothing but ASCII
# letters: the two sharp s, the long s, the Kelvin sign and the seven Latin
# ligatures. A stored resource code spelled with one of them ("STRAẞE") equals
# an ASCII code ("strasse") under the ``casefold()`` match the #133 propagation
# applies, and no SQL lower-casing maps it there. Found by folding every code
# point and keeping those whose fold is all ASCII.
_NON_ASCII_FOLDING_TO_ASCII = "\u00df\u017f\u1e9e\u212a\ufb00\ufb01\ufb02\ufb03\ufb04\ufb05\ufb06"
_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"
_FOLD_ASCII = str.maketrans(_ASCII_UPPER, _ASCII_LOWER)


def resource_code_prefilter(codes: Iterable[str], dialect_name: str) -> ColumnElement[bool] | None:
    """Build a SQL condition that keeps every position whose metadata may hold one of ``codes``.

    Issue #133 matches a resource code as ``str(code).strip().casefold()`` in
    Python, which no SQL expression reproduces, so this never decides a match.
    It only has to keep every row the Python match would accept, and drop most
    of the rest before their metadata crosses the wire and gets decoded.

    It holds that promise under three conditions, and answers ``None`` (no
    narrowing, scan everything) whenever one is missing:

    * PostgreSQL. ``jsonb`` renders a string value verbatim apart from ``"``,
      ``\\`` and control characters, and ``translate()`` lower-cases A-Z by a
      fixed table. ``lower()`` and ``ILIKE`` would not do: they fold by the
      database locale, and under a Turkish one ``I`` does not become ``i``.
    * Every code is printable ASCII without ``"`` or ``\\``, so it appears
      unescaped in the rendered JSON.
    * A stored code the Python match accepts is then ASCII too, apart from the
      handful of letters in ``_NON_ASCII_FOLDING_TO_ASCII``; a row carrying any
      of those is always kept.

    Every pattern is matched against the one folded text in a single
    ``LIKE ANY (ARRAY[...])``, which PostgreSQL evaluates once per row. One
    ``OR`` branch per pattern rendered and translated the whole metadata again
    for each of them, 25 times a row for a three-code resource: 2.7 s for a
    2160-position project on the E2E server, 7 s on a busy machine.

    Args:
        codes: Resource codes being looked for.
        dialect_name: ``dialect.name`` of the connection the query runs on.

    Returns:
        The condition, or ``None`` when narrowing cannot be proven safe.
    """
    if dialect_name != "postgresql":
        return None
    fragments: list[str] = []
    for raw in codes:
        code = str(raw or "").strip()
        if not code or any(not (" " <= ch <= "~") or ch in '"\\' for ch in code):
            return None
        fragments.append(code.translate(_FOLD_ASCII))
    if not fragments:
        return None
    for ch in _NON_ASCII_FOLDING_TO_ASCII:
        # Verbatim as ``jsonb`` renders it (``translate`` leaves it alone), and
        # as the ``\\u00df`` escape a plain ``json`` column keeps from the
        # writer (either hex case, since the text is lower-cased).
        fragments.append(ch)
        fragments.append(json.dumps(ch)[1:-1])
    folded = func.translate(cast(Position.metadata_, Text), _ASCII_UPPER, _ASCII_LOWER)
    return folded.like(any_(pg_array([_like_containing(f) for f in fragments])))


def _like_containing(fragment: str) -> str:
    """A ``LIKE`` pattern matching ``fragment`` anywhere, under the default backslash escape."""
    escaped = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


#: The BOQ columns a full-BOQ response carries, keyed by attribute name.
BOQ_HEADER_COLUMNS = (
    BOQ.id,
    BOQ.project_id,
    BOQ.name,
    BOQ.description,
    BOQ.status,
    BOQ.metadata_,
    BOQ.created_at,
    BOQ.updated_at,
    BOQ.is_locked,
    BOQ.approved_by,
    BOQ.approved_at,
    BOQ.base_date,
    BOQ.estimate_type,
    BOQ.parent_estimate_id,
    BOQ.variation_request_id,
)

#: Which bills make up a project's bill register. See ``list_for_project`` for
#: why a variation request's own bill is not one of them. Shared by the one
#: project and the many projects listing, so the two cannot disagree about it.
_IN_BILL_REGISTER = BOQ.variation_request_id.is_(None)

#: The order of a bill register, newest first. The id breaks a tie between two
#: bills created in the same instant, which otherwise the database may order
#: differently from one query to the next, so a page boundary could show one of
#: them twice and the other never.
_BILL_REGISTER_ORDER = (BOQ.created_at.desc(), BOQ.id.desc())


class BOQRepository:
    """Data access for BOQ model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, boq_id: uuid.UUID) -> BOQ | None:
        """Get BOQ by ID."""
        return await self.session.get(BOQ, boq_id)

    async def get_header(self, boq_id: uuid.UUID) -> RowMapping | None:
        """The BOQ's own columns, read without loading the BOQ entity.

        ``session.get(BOQ)`` pulls every position and markup through the
        ``selectin`` relationships. A caller that reads the positions itself
        (the full-BOQ read does, in sort order) paid for them twice, and on a
        2100-line bill each read decodes about 2 MB of jsonb on the event loop.
        A plain column select leaves the identity map alone, so no caller that
        later touches ``boq.positions`` sees a half-loaded entity.
        """
        stmt = select(*BOQ_HEADER_COLUMNS).where(BOQ.id == boq_id)
        return (await self.session.execute(stmt)).mappings().first()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[BOQ], int]:
        """List BOQs for a project with pagination. Returns (boqs, total_count).

        Positions and markups are NOT eagerly loaded here - use
        ``grand_totals_for_boqs`` to compute totals via a single aggregate query.

        Bills raised for a variation request (Issue #435) are excluded. This
        is the project's bill register, and a variation's priced scope is not
        part of the project estimate until the variation is agreed - listing
        it here would add its money to a register the estimator reads as the
        project's own. It is reached from the variation request that owns it,
        and by id like any other bill. Rows written before that column existed
        carry NULL, so nothing that is listed today stops being listed.
        """
        base = select(BOQ).where(BOQ.project_id == project_id, _IN_BILL_REGISTER)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch - skip eager loading of positions/markups for list queries
        stmt = (
            base.options(noload(BOQ.positions), noload(BOQ.markups))
            .order_by(*_BILL_REGISTER_ORDER)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        boqs = list(result.scalars().all())

        return boqs, total

    async def list_for_projects(
        self,
        project_ids: list[uuid.UUID],
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> dict[uuid.UUID, list[BOQ]]:
        """The bill register of several projects, paginated per project, in one query.

        Each project gets exactly the page :meth:`list_for_project` would give
        it with the same ``offset`` and ``limit``: the same bills, in the same
        order, with the same bills left out. The page is cut per project by
        numbering each project's bills in register order and keeping the
        numbers ``offset + 1`` to ``offset + limit``, so one busy project
        cannot use up another project's page, which a single ``LIMIT`` over
        the union would do.

        Args:
            project_ids: Projects to list. Access is the caller's business.
            offset: Bills to skip at the head of each project's register.
            limit: Most bills returned for each project.

        Returns:
            ``{project_id: [bill, ...]}`` in register order. A project with no
            bill on the requested page is absent rather than present and empty.
        """
        if not project_ids:
            return {}

        place = func.row_number().over(partition_by=BOQ.project_id, order_by=_BILL_REGISTER_ORDER).label("place")
        ranked = (
            select(BOQ.id.label("boq_id"), place).where(BOQ.project_id.in_(project_ids), _IN_BILL_REGISTER).subquery()
        )
        stmt = (
            select(BOQ)
            .join(ranked, ranked.c.boq_id == BOQ.id)
            .where(ranked.c.place > offset, ranked.c.place <= offset + limit)
            .options(noload(BOQ.positions), noload(BOQ.markups))
            .order_by(BOQ.project_id, ranked.c.place)
        )
        grouped: dict[uuid.UUID, list[BOQ]] = {}
        for boq in (await self.session.execute(stmt)).scalars().all():
            grouped.setdefault(boq.project_id, []).append(boq)
        return grouped

    async def active_markups_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[BOQMarkup]]:
        """Fetch active markups for a set of BOQs grouped by BOQ id.

        Ordered by ``sort_order`` so callers apply markups in the same order
        the editor / structured rollup uses. Pure data access - the
        FX-correct money arithmetic lives in the service layer (which holds
        the project FX table); this just returns the rows.
        """
        if not boq_ids:
            return {}
        stmt = (
            select(BOQMarkup)
            .where(BOQMarkup.boq_id.in_(boq_ids), BOQMarkup.is_active.is_(True))
            .order_by(BOQMarkup.sort_order)
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[BOQMarkup]] = {}
        for markup in result.scalars().all():
            grouped.setdefault(markup.boq_id, []).append(markup)
        return grouped

    async def grand_totals_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Compute grand total (direct cost + markups) for each BOQ by ID.

        Convenience wrapper around :meth:`totals_for_boqs` for the
        majority of callers that only need the grand total - keeps the
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

        # Step 1: sum direct cost (position totals) per BOQ
        pos_stmt = (
            select(
                Position.boq_id,
                func.sum(numeric_value(Position.total)).label("direct_cost"),
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
                    # Σ(preceding markups), identical to ``cumulative`` -
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
        instance = self.session.identity_map.get(identity_key(BOQ, boq_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

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
        stmt = select(Position).where(Position.id.in_(position_ids)).options(*_POSITION_NOLOAD_TREE)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_children(self, parent_id: uuid.UUID) -> list[Position]:
        """List direct children of a position (one level only)."""
        stmt = (
            select(Position)
            .where(Position.parent_id == parent_id)
            .order_by(Position.sort_order)
            .options(*_POSITION_NOLOAD_TREE)
        )
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

        # Fetch ordered by sort_order, then ordinal. Suppress the
        # children/parent selectin eager loads (callers navigate the tree via
        # the parent_id column, never the relationships).
        stmt = (
            base.order_by(Position.sort_order, Position.ordinal)
            .offset(offset)
            .limit(limit)
            .options(*_POSITION_NOLOAD_TREE)
        )
        result = await self.session.execute(stmt)
        positions = list(result.scalars().all())

        return positions, total

    async def list_all_for_boq(self, boq_id: uuid.UUID) -> list[Position]:
        """Return EVERY position for a BOQ ordered by sort_order, no limit.

        BUG-B-006: ``list_for_boq`` carries a hard ``limit=1000`` default for
        paginated UI listing. Every money rollup (direct_cost, grand_total,
        markup base, statistics, cost-breakdown, recalculate-rates,
        duplicate) MUST sum all positions - a 1500-position BOQ was silently
        dropping positions 1001+ from every total. Aggregation callers use
        this method so the count limit can never under-state a tender.

        Suppresses the ``children``/``parent`` selectin eager loads
        (``_POSITION_NOLOAD_TREE``): this is the hottest BOQ read and every
        caller rebuilds the tree from ``parent_id`` in memory, so the two
        extra relationship round trips are pure overhead.
        """
        stmt = (
            select(Position)
            .where(Position.boq_id == boq_id)
            .order_by(Position.sort_order, Position.ordinal)
            .options(*_POSITION_NOLOAD_TREE)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, list[Position]]:
        """Return EVERY position for a SET of BOQs grouped by ``boq_id``.

        Batched sibling of :meth:`list_all_for_boq`: where the list endpoint
        previously fired one unbounded ``list_all_for_boq`` per BOQ (an N+1 on
        a hot read path - a 100-BOQ page = 100 full-table position loads), this
        pulls every position for the whole page in a SINGLE
        ``... WHERE boq_id IN (:ids)`` query and groups in Python.

        Same money-rollup contract as the single-BOQ method: no ``limit`` (a
        large BOQ must never silently drop positions 1001+) and the same
        ``_POSITION_NOLOAD_TREE`` suppression of the children/parent selectin
        loads. Rows are ordered by ``(boq_id, sort_order, ordinal)`` so each
        BOQ's group lands in exactly the order ``list_all_for_boq`` returns.
        BOQs with no positions are absent from the dict (callers default to
        an empty list).
        """
        if not boq_ids:
            return {}
        stmt = (
            select(Position)
            .where(Position.boq_id.in_(boq_ids))
            .order_by(Position.boq_id, Position.sort_order, Position.ordinal)
            .options(*_POSITION_NOLOAD_TREE)
        )
        result = await self.session.execute(stmt)
        grouped: dict[uuid.UUID, list[Position]] = {}
        for pos in result.scalars().all():
            grouped.setdefault(pos.boq_id, []).append(pos)
        return grouped

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
        instance = self.session.identity_map.get(identity_key(Position, position_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, position_id: uuid.UUID) -> None:
        """Delete a single position."""
        stmt = delete(Position).where(Position.id == position_id)
        await self.session.execute(stmt)

    async def reorder(self, position_ids: list[uuid.UUID], boq_id: uuid.UUID) -> None:
        """Reorder positions by assigning sort_order based on list index.

        Only touches positions that belong to ``boq_id`` - foreign IDs are
        silently skipped (UPDATE rows=0) rather than mutating positions in
        another user's BOQ (cross-tenant sort_order pollution).

        Args:
            position_ids: Ordered list of position UUIDs. Index becomes sort_order.
            boq_id: Owning BOQ - positions not in this BOQ are not affected.
        """
        for index, pid in enumerate(position_ids):
            stmt = update(Position).where(Position.id == pid, Position.boq_id == boq_id).values(sort_order=index)
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

    async def project_ids_for_boqs(
        self,
        boq_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, uuid.UUID]:
        """Resolve ``{boq_id: project_id}`` for a SET of BOQs in one query.

        Batched sibling of :meth:`project_id_for_boq`. The list endpoint's
        currency-aware rollup needs each BOQ's project (to look up the project
        FX table) but every BOQ on a page typically shares ONE project, so a
        per-BOQ ``project_id_for_boq`` would be a needless N+1. This resolves
        them all in a single ``SELECT id, project_id WHERE id IN (:ids)`` and
        lets the caller resolve FX once per distinct project.
        """
        if not boq_ids:
            return {}
        stmt = select(BOQ.id, BOQ.project_id).where(BOQ.id.in_(boq_ids))
        rows = (await self.session.execute(stmt)).all()
        return {row[0]: row[1] for row in rows if row[1] is not None}

    async def find_master_by_reference_code(
        self,
        project_id: uuid.UUID,
        reference_code: str,
        boq_id: uuid.UUID | None = None,
    ) -> Position | None:
        """Return the definition-owner Position for ``reference_code``.

        When *boq_id* is given the search is restricted to that single BOQ,
        preventing accidental cross-BOQ inheritance when the caller did not
        explicitly request it.  When *boq_id* is ``None`` the lookup spans
        every BOQ in the project (used for intentional cross-BOQ reuse).

        Preference order:

        1. an explicit ``link_role='master'`` row, else
        2. the oldest standalone owner of that code (will be promoted to
           master by the service when a reuse instance is created).

        Returns ``None`` when the code is unused in the search scope.
        """
        rc = (reference_code or "").strip()
        if not rc:
            return None
        base = (
            select(Position)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.reference_code == rc)
            .options(*_POSITION_NOLOAD_TREE)
        )
        if boq_id is not None:
            base = base.where(Position.boq_id == boq_id)
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
            .options(*_POSITION_NOLOAD_TREE)
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
            .options(*_POSITION_NOLOAD_TREE)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_resource_carrier_rows(
        self,
        project_id: uuid.UUID,
        codes: Iterable[str],
    ) -> list[Row]:
        """Return the rows of a project that may carry one of ``codes``, oldest first.

        Issue #133 propagation reads six columns of every position that holds a
        resource code, and ``list_for_project`` built a full ORM object for every
        position in the project and decoded all their metadata to find them. This
        selects only ``id``, ``boq_id``, ``ordinal``, ``quantity``, ``version``
        and ``metadata`` (as ``meta``), in the same ``created_at, sort_order``
        order, so the first carrier is still the master.

        The row set is narrowed in SQL by :func:`resource_code_prefilter`, which
        only ever keeps too much: the caller must still match each resource's
        code exactly, and does.

        Args:
            project_id: Project whose positions are scanned (all of its BOQs).
            codes: Resource codes the caller is looking for.

        Returns:
            Plain rows, not ORM instances, so nothing lands in the identity map.
        """
        stmt = (
            select(
                Position.id,
                Position.boq_id,
                Position.ordinal,
                Position.quantity,
                Position.version,
                Position.metadata_.label("meta"),
            )
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id)
            .order_by(Position.created_at, Position.sort_order)
        )
        narrowing = resource_code_prefilter(codes, self.session.get_bind().dialect.name)
        if narrowing is not None:
            stmt = stmt.where(narrowing)
        return list((await self.session.execute(stmt)).all())

    async def update_many(self, rows: list[dict[str, object]]) -> None:
        """Write a different field set to each of many positions, one UPDATE per row.

        Sibling of :meth:`update_fields` for fan-out writes, with one flush for
        the batch. Every dict carries the target ``id`` plus the mapped attribute
        names to write. Instances already in the identity map are brought up to
        date the same way ``update_fields`` does it, so a later read in this
        session never sees the value from before the write.

        Deliberately NOT ``session.execute(update(Position), rows)``. That ORM
        bulk form goes out as an asyncpg executemany, which pipelines the rows
        through ``transport.writelines()``. On Windows under the selector event
        loop (the one ``tests/conftest.py`` installs) CPython's
        ``_SelectorSocketTransport._write_send`` pops a buffer before
        ``send()`` and drops it when the socket answers ``BlockingIOError``, so
        PostgreSQL never receives those rows and nothing raises. Measured on a
        2080-line project: the first fan-out applied 313 of its 346 UPDATE
        statements, and this method then reported all of them as written. A single-row
        UPDATE goes out through ``transport.write()``, which keeps what it
        could not send.

        Args:
            rows: One ``{"id": ..., <attribute>: <value>, ...}`` per position.
        """
        if not rows:
            return
        for row in rows:
            values = {name: value for name, value in row.items() if name != "id"}
            await self.session.execute(update(Position).where(Position.id == row["id"]).values(**values))
        await self.session.flush()
        for row in rows:
            instance = self.session.identity_map.get(identity_key(Position, row["id"]))
            if instance is None:
                continue
            for name, value in row.items():
                if name != "id":
                    set_committed_value(instance, name, value)

    async def list_content_keys_for_boq(self, boq_id: uuid.UUID) -> list[Row]:
        """Return ``(id, ordinal, description, unit, quantity, unit_rate)`` for every position of a BOQ.

        The duplicate-content check (BUG-B-014) compares only these columns, and
        ``list_all_for_boq`` made it build a full ORM object and decode the
        metadata of every row in the bill on every price edit. Same order as
        ``list_all_for_boq`` (``sort_order, ordinal``), so the first colliding
        ordinal reported is the one it reported.
        """
        stmt = (
            select(
                Position.id,
                Position.ordinal,
                Position.description,
                Position.unit,
                Position.quantity,
                Position.unit_rate,
            )
            .where(Position.boq_id == boq_id)
            .order_by(Position.sort_order, Position.ordinal)
        )
        return list((await self.session.execute(stmt)).all())

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
    """Data access for QuantityLink - model→position quantity bindings."""

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
        instance = self.session.identity_map.get(identity_key(QuantityLink, link_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, link_id: uuid.UUID) -> None:
        """Delete a single quantity link by id."""
        stmt = delete(QuantityLink).where(QuantityLink.id == link_id)
        await self.session.execute(stmt)
        await self.session.flush()
