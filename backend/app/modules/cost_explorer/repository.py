# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Cost Explorer data access layer.

Pure data access over three tables, no business logic:
    oe_cost_item_resource  - the resource -> work reverse index (this module)
    oe_costs_item          - priced work items (the costs module)
    oe_catalog_resource    - the resource price book (the catalog module)

The reverse index is the backbone: it turns "which priced works consume
resource X" from a full JSON scan of every cost item into a plain indexed
lookup. Everything else reads the cost and catalog tables the module depends on.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence

from sqlalchemy import String, case, cast, delete, distinct, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import cost_scope
from app.modules.catalog.models import CatalogResource
from app.modules.cost_explorer import search, spelling
from app.modules.cost_explorer.models import CostItemResource
from app.modules.costs.models import CostItem


def _escape_like(term: str) -> str:
    r"""Escape LIKE/ILIKE wildcards so a literal ``%`` / ``_`` stays literal.

    Mirrors the catalog repository: without this, ``q='%'`` matches every row.
    Pair the result with ``.ilike(pattern, escape="\\")``.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class CostExplorerRepository:
    """Data access for the reverse index and the cost / catalog reads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reindex source + bookkeeping ─────────────────────────────────────────

    async def count_cost_items(self) -> int:
        """Total priced work items available to index."""
        return int((await self.session.execute(select(func.count()).select_from(CostItem))).scalar_one())

    async def count_edges(self) -> int:
        """Total reverse-index rows currently stored."""
        return int((await self.session.execute(select(func.count()).select_from(CostItemResource))).scalar_one())

    async def distinct_regions(self) -> list[str]:
        """Non-null region tags that carry at least one cost item."""
        stmt = select(distinct(CostItem.region)).where(CostItem.region.is_not(None))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [r for r in rows if r]

    async def has_null_region_items(self) -> bool:
        """True when any cost item has no region tag (its own reindex bucket)."""
        stmt = select(CostItem.id).where(CostItem.region.is_(None)).limit(1)
        return (await self.session.execute(stmt)).first() is not None

    async def distinct_edge_regions(self) -> list[str]:
        """Non-null region tags that already carry at least one index edge."""
        stmt = select(distinct(CostItemResource.region)).where(CostItemResource.region.is_not(None))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [r for r in rows if r]

    async def stream_items_in_region(self, region: str | None, batch_size: int = 1000) -> AsyncIterator[object]:
        """Yield ``(id, code, region, source, components)`` for one region bucket.

        Paged by id keyset in ``batch_size`` chunks so a large base is never
        materialised in one go during a reindex, yet no server-side cursor is
        held open while the caller writes edges on the same connection (which
        asyncpg forbids). ``region=None`` selects the items whose region IS NULL,
        not all items. Soft-deleted (inactive) items are skipped so a deleted
        work never lingers in the index.
        """
        after: uuid.UUID | None = None
        while True:
            stmt = select(CostItem.id, CostItem.code, CostItem.region, CostItem.source, CostItem.components)
            stmt = stmt.where(CostItem.region.is_(None)) if region is None else stmt.where(CostItem.region == region)
            stmt = stmt.where(CostItem.is_active.is_(True))
            if after is not None:
                stmt = stmt.where(CostItem.id > after)
            stmt = stmt.order_by(CostItem.id).limit(batch_size)
            rows = (await self.session.execute(stmt)).all()
            if not rows:
                return
            for row in rows:
                yield row
            if len(rows) < batch_size:
                return
            after = rows[-1][0]

    async def delete_edges_for_region(self, region: str | None) -> None:
        """Drop all reverse-index rows for one region bucket (None = NULL bucket)."""
        stmt = delete(CostItemResource)
        stmt = (
            stmt.where(CostItemResource.region.is_(None))
            if region is None
            else stmt.where(CostItemResource.region == region)
        )
        await self.session.execute(stmt)

    async def delete_edges_for_item(self, item_id: uuid.UUID) -> None:
        """Drop the reverse-index rows for a single cost item (incremental sync)."""
        await self.session.execute(delete(CostItemResource).where(CostItemResource.cost_item_id == item_id))

    async def bulk_insert_edges(self, rows: list[dict]) -> None:
        """Insert a batch of reverse-index rows."""
        if rows:
            await self.session.execute(insert(CostItemResource), rows)

    # ── By resources ─────────────────────────────────────────────────────────

    async def candidate_item_ids(
        self,
        region: str | None,
        resource_codes: Sequence[str],
        sources: Sequence[str] | None,
        limit: int,
    ) -> list[uuid.UUID]:
        """Work-item ids that consume the requested resources, best match first.

        Ordered by how many of the requested resources each item carries, so the
        candidate cap keeps the most promising items rather than an arbitrary
        slice (the fine-grained scoring then runs in the ranking engine).
        """
        if not resource_codes:
            return []
        match_count = func.count().label("matches")
        # Always join the work item and keep only live ones. The read path
        # filters is_active later, but the candidate cap is applied HERE, so
        # without this a block of edges pointing at removed / soft-deleted works
        # could fill the cap and crowd live candidates out of the results.
        stmt = (
            select(CostItemResource.cost_item_id, match_count)
            .join(CostItem, CostItem.id == CostItemResource.cost_item_id)
            .where(
                CostItemResource.resource_code.in_(list(resource_codes)),
                CostItem.is_active.is_(True),
            )
            .group_by(CostItemResource.cost_item_id)
            .order_by(match_count.desc())
        )
        if region is not None:
            stmt = stmt.where(CostItemResource.region == region)
        if sources:
            stmt = stmt.where(CostItem.source.in_(list(sources)))
        stmt = stmt.limit(limit)
        return [row[0] for row in (await self.session.execute(stmt)).all()]

    async def edges_for_items(self, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[CostItemResource]]:
        """All reverse-index rows for the given items, grouped by item id."""
        if not item_ids:
            return {}
        stmt = select(CostItemResource).where(CostItemResource.cost_item_id.in_(list(item_ids)))
        out: dict[uuid.UUID, list[CostItemResource]] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            out.setdefault(row.cost_item_id, []).append(row)
        return out

    async def cost_items_by_ids(self, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, CostItem]:
        """Load the given cost items keyed by id."""
        if not item_ids:
            return {}
        stmt = select(CostItem).where(CostItem.id.in_(list(item_ids)))
        return {row.id: row for row in (await self.session.execute(stmt)).scalars().all()}

    async def get_item(self, item_id: uuid.UUID) -> CostItem | None:
        """Load a single cost item by id."""
        return await cost_scope.get_cost_item(self.session, item_id)

    # ── Find work (text search) ──────────────────────────────────────────────

    async def search_work(
        self,
        tokens: Sequence[str],
        region: str | None,
        sources: Sequence[str] | None,
        limit: int,
    ) -> tuple[list[CostItem], str | None]:
        """Cost items ranked by query-concept match, plus a spelling suggestion.

        Each token is expanded with multilingual construction synonyms (so
        "rebar" also finds "reinforcement", and "beton" or the folded "béton"
        finds "concrete") and matched against the code or description. The word
        the user typed is matched as a substring so partial typing still lands;
        machine-injected cross-language synonyms are matched on word boundaries
        (PostgreSQL ``~*``) so a short foreign word cannot hide inside an
        unrelated English word. An item needs at least ONE concept to appear, and
        items that match more concepts come first, so a descriptive multi-word
        query returns the best partial matches instead of dead-ending on zero
        results when no single row carries every word. The caller re-ranks this
        pool lexically for the final order.

        Alongside the pool this runs a construction-aware spelling pass over the
        tokens and returns a corrected query (for example "concreet" -> "concrete")
        when one is available, or ``None`` when the tokens are already well-formed
        or only look like a grade or a code. The tokens themselves drive the
        search unchanged, so a typo simply returns its (usually weak) matches and
        the caller can offer the correction as a did-you-mean suggestion.

        Returns:
            A tuple of the matched cost items and the suggested corrected query
            (or ``None``).
        """
        suggestion = spelling.suggest_from_tokens(tokens)
        concept_preds = []
        literal_preds = []
        for tok in tokens:
            like_clauses = []
            # The typed word alone, kept apart from the synonyms it expands to.
            # match_terms marks machine-injected cross-language synonyms as
            # whole-word, so the substring variants ARE what the user typed.
            typed_clauses = []
            for variant, whole_word in search.match_terms(tok):
                if whole_word:
                    rx = rf"\y{search.boundary_pattern(variant)}\y"
                    like_clauses.append(CostItem.code.op("~*")(rx))
                    like_clauses.append(CostItem.description.op("~*")(rx))
                else:
                    pattern = f"%{_escape_like(variant)}%"
                    typed_clauses.append(CostItem.code.ilike(pattern, escape="\\"))
                    typed_clauses.append(CostItem.description.ilike(pattern, escape="\\"))
            like_clauses.extend(typed_clauses)
            if like_clauses:
                concept_preds.append(or_(*like_clauses))
            if typed_clauses:
                literal_preds.append(or_(*typed_clauses))

        stmt = select(CostItem).where(CostItem.is_active.is_(True))
        # The ORDER BY has to be a TOTAL order, because this pool is cut by
        # LIMIT and the caller only ever sees the survivors. Ordering by a
        # score alone is not enough: for a one-word query every row that got
        # past the WHERE scores the same, so the sort key is a constant, the
        # database returns whichever rows the plan happened to produce, and
        # the same search run twice returns different work items at different
        # rates. An estimator cannot cite a rate they cannot find again.
        order_terms = []
        if concept_preds:
            stmt = stmt.where(or_(*concept_preds))
            # Rank by concept-match count (PostgreSQL has no boolean->int cast,
            # so sum CASE expressions) so the pool holds the best candidates.
            match_score = case((concept_preds[0], 1), else_=0)
            for pred in concept_preds[1:]:
                match_score = match_score + case((pred, 1), else_=0)
            if literal_preds:
                # The word the user typed outranks a synonym we injected for
                # them. The caller scores a literal hit at 1.0 and a
                # synonym-only hit at 0.5, so cutting the pool this way keeps
                # the rows it is about to rank highest instead of discarding
                # them for rows it will then rank below.
                literal_score = case((literal_preds[0], 1), else_=0)
                for pred in literal_preds[1:]:
                    literal_score = literal_score + case((pred, 1), else_=0)
                order_terms.append(literal_score.desc())
            order_terms.append(match_score.desc())
        # Shortest description first, the same tiebreak the caller applies: a
        # row whose whole description is the query is a better answer than one
        # that mentions it in passing.
        order_terms.append(func.length(CostItem.description).asc())
        # Terminate on a unique key so the order is total and stable. ``code``
        # is not unique across bases, and the id is cast to text because SQLite
        # stores UUIDs as VARCHAR(36) while PostgreSQL needs the explicit cast -
        # comparing the string form sorts identically on both.
        order_terms.append(CostItem.code.asc())
        order_terms.append(cast(CostItem.id, String).asc())
        stmt = stmt.order_by(*order_terms)
        if region is not None:
            stmt = stmt.where(CostItem.region == region)
        if sources:
            stmt = stmt.where(CostItem.source.in_(list(sources)))
        stmt = stmt.limit(limit)
        items = list((await self.session.execute(stmt)).scalars().all())
        return items, suggestion

    # ── Compare across bases ─────────────────────────────────────────────────

    async def items_by_code(self, code: str, limit: int) -> list[CostItem]:
        """Every priced instance of one rate code (the same work across regions)."""
        stmt = select(CostItem).where(CostItem.code == code, CostItem.is_active.is_(True)).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Substitution / price intelligence ────────────────────────────────────

    async def catalog_resource(self, resource_code: str, region: str | None = None) -> CatalogResource | None:
        """One catalog row for a resource, preferring the given region."""
        stmt = select(CatalogResource).where(CatalogResource.resource_code == resource_code)
        if region is not None:
            stmt = stmt.where(CatalogResource.region == region)
        return (await self.session.execute(stmt.limit(1))).scalars().first()

    async def catalog_rows_for_resource(self, resource_code: str, limit: int = 200) -> list[CatalogResource]:
        """All catalog rows for a resource (one per region price book), capped."""
        stmt = select(CatalogResource).where(CatalogResource.resource_code == resource_code).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def dominant_region_for_resource(self, resource_code: str) -> str | None:
        """The region carrying the most price rows for this resource.

        Price stats must stay inside one currency; when the caller gives no
        region this picks the region with the most data so the spread is a
        single-currency distribution rather than a cross-currency blend.
        """
        stmt = (
            select(CostItemResource.region, func.count().label("n"))
            .join(CostItem, CostItem.id == CostItemResource.cost_item_id)
            .where(
                CostItemResource.resource_code == resource_code,
                CostItemResource.region.is_not(None),
                CostItem.is_active.is_(True),
            )
            .group_by(CostItemResource.region)
            .order_by(func.count().desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).first()
        return row[0] if row else None

    async def resource_usage_count(self, resource_code: str, region: str | None = None) -> int:
        """How many distinct live works consume this resource."""
        stmt = (
            select(func.count(distinct(CostItemResource.cost_item_id)))
            .join(CostItem, CostItem.id == CostItemResource.cost_item_id)
            .where(CostItemResource.resource_code == resource_code, CostItem.is_active.is_(True))
        )
        if region is not None:
            stmt = stmt.where(CostItemResource.region == region)
        return int((await self.session.execute(stmt)).scalar_one())

    async def edge_prices_for_resource(
        self, resource_code: str, region: str | None = None, limit: int = 5000
    ) -> list[str]:
        """A capped sample of the unit prices this resource carries across works.

        Joined to the cost item so a stale edge pointing at a removed / inactive
        work never skews the spread, and capped so the busiest resource cannot
        pull an unbounded column into memory for the in-Python percentiles.

        Ordered by work id so that when the cap does bite (a resource used in
        more than ``limit`` works) the sample is a stable, price-neutral subset
        rather than an arbitrary physical-order slice that could cluster by
        insert time and bias the percentiles.
        """
        stmt = (
            select(CostItemResource.unit_rate)
            .join(CostItem, CostItem.id == CostItemResource.cost_item_id)
            .where(CostItemResource.resource_code == resource_code, CostItem.is_active.is_(True))
        )
        if region is not None:
            stmt = stmt.where(CostItemResource.region == region)
        stmt = stmt.order_by(CostItemResource.cost_item_id).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def top_works_for_resource(
        self, resource_code: str, region: str | None, limit: int
    ) -> list[CostItemResource]:
        """Reverse-index rows for the live works that consume this resource."""
        stmt = (
            select(CostItemResource)
            .join(CostItem, CostItem.id == CostItemResource.cost_item_id)
            .where(CostItemResource.resource_code == resource_code, CostItem.is_active.is_(True))
        )
        if region is not None:
            stmt = stmt.where(CostItemResource.region == region)
        return list((await self.session.execute(stmt.limit(limit))).scalars().all())
