"""‌⁠‍Cost item data access layer.

All database queries for cost items live here.
No business logic — pure data access.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import String, and_, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem
from app.modules.costs.schemas import UNSPECIFIED_CATEGORY

# ── Classification-path helpers ──────────────────────────────────────────────
#
# CWICR rows store classification as a JSON map with four logical depths:
#   collection > department > section > subsection
# We expose these as a slash-delimited path so the UI can drive a single
# breadcrumb / tree picker and the backend can prefix-match at any depth.

_CLASSIFICATION_DEPTHS: tuple[str, ...] = (
    "collection",
    "department",
    "section",
    "subsection",
)


def _split_classification_path(path: str) -> list[str | None]:
    """‌⁠‍Split a slash-delimited prefix path into per-depth filters.

    Empty path → empty list (no filter).
    Empty segments in the middle (``"Buildings//Walls"``) → ``None`` for
    that depth, meaning "match anything at this depth".
    Trailing/leading slashes are stripped before splitting.
    Trailing depths that aren't in the path are unconstrained.
    """
    cleaned = path.strip().strip("/")
    if not cleaned:
        return []
    parts: list[str | None] = []
    for raw in cleaned.split("/"):
        seg = raw.strip()
        parts.append(seg if seg else None)
    # Drop trailing empty segments — they add no filter and would force
    # an unnecessary IS NOT NULL when the user just typed "X/".
    while parts and parts[-1] is None:
        parts.pop()
    # Cap at the four real depths; anything deeper is meaningless.
    return parts[: len(_CLASSIFICATION_DEPTHS)]


def _classification_expr(depth_key: str) -> Any:
    """‌⁠‍Return a dialect-aware SQL expression that extracts classification[depth].

    Uses ``json_extract`` on SQLite and the ``->>`` operator on PostgreSQL,
    mirroring the existing ``category`` filter path so the same data
    behaves identically across dev (SQLite) and prod (Postgres).
    """
    from app.database import engine as _engine

    if "sqlite" in str(_engine.url):
        return func.json_extract(CostItem.classification, f"$.{depth_key}")
    return CostItem.classification[depth_key].as_string()


class CostItemRepository:
    """Data access for CostItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> CostItem | None:
        """Get cost item by ID."""
        return await self.session.get(CostItem, item_id)

    async def get_by_code(self, code: str, region: str | None = None) -> CostItem | None:
        """Get cost item by code and optional region.

        The DB unique constraint is on (code, region), so the same code can
        exist for different regions.  When *region* is None the query matches
        rows where region IS NULL.
        """
        stmt = select(CostItem).where(CostItem.code == code)
        if region is None:
            stmt = stmt.where(CostItem.region.is_(None))
        else:
            stmt = stmt.where(CostItem.region == region)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_codes(self, codes: list[str]) -> list[CostItem]:
        """Get multiple cost items by their codes."""
        if not codes:
            return []
        stmt = select(CostItem).where(CostItem.code.in_(codes))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        q: str | None = None,
    ) -> tuple[list[CostItem], int]:
        """List cost items with pagination and optional text search.

        Args:
            offset: Number of items to skip.
            limit: Maximum number of items to return.
            q: Optional text search query (LIKE on code and description).

        Returns:
            Tuple of (items, total_count).
        """
        base = select(CostItem).where(CostItem.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(CostItem.code.ilike(pattern) | CostItem.description.ilike(pattern))

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Fetch
        stmt = base.order_by(CostItem.code).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: CostItem) -> CostItem:
        """Insert a new cost item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a cost item."""
        stmt = update(CostItem).where(CostItem.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        self.session.expire_all()

    async def bulk_create(self, items: list[CostItem]) -> list[CostItem]:
        """Insert multiple cost items at once."""
        self.session.add_all(items)
        await self.session.flush()
        return items

    async def count(self) -> int:
        """Total number of active cost items."""
        stmt = select(func.count()).select_from(select(CostItem).where(CostItem.is_active.is_(True)).subquery())
        return (await self.session.execute(stmt)).scalar_one()

    async def search(
        self,
        *,
        q: str | None = None,
        name: str | None = None,
        description: str | None = None,
        unit: str | None = None,
        source: str | None = None,
        region: str | None = None,
        category: str | None = None,
        classification_path: str | None = None,
        min_rate: Decimal | float | None = None,
        max_rate: Decimal | float | None = None,
        offset: int = 0,
        limit: int = 50,
        cursor: tuple[str, str] | None = None,
        skip_count: bool = False,
    ) -> tuple[list[CostItem], int | None, bool]:
        """Advanced search with multiple filters and keyset pagination.

        Args:
            q: Text search on code OR description (canonical free-text param).
                SQL ``ILIKE '%q%'`` cross-dialect via ``column.ilike()`` —
                Postgres uses native ILIKE, SQLite uses case-insensitive
                LIKE because the SQLite LIKE is itself case-insensitive
                for ASCII by default. Always returns substring matches; the
                vector layer is a best-effort re-ranker on top, never the
                only source of recall.
            name: Substring filter against ``code`` only. CostItem rows
                have no separate ``name`` column — ``code`` is the catalog
                identifier clients call "name", so this aliases there.
            description: Substring filter against ``description`` only.
                AND-combined with ``q`` and ``name`` so callers can
                narrow further on a long description.
            unit: Filter by unit (exact match).
            source: Filter by source (exact match).
            region: Filter by region (exact match, e.g. "DE_BERLIN").
            category: Filter by classification.collection value (exact match).
            classification_path: Slash-delimited prefix path
                (collection/department/section/subsection). Empty middle
                segments act as wildcards. AND-combined with all other
                filters.
            min_rate: Minimum rate (inclusive). Compares as float via CAST.
            max_rate: Maximum rate (inclusive). Compares as float via CAST.
            offset: Number of items to skip (ignored when *cursor* is set).
            limit: Maximum number of items to return.
            cursor: Decoded ``(code, id_str)`` tuple from a previous page.
                When supplied, results resume strictly after that pair on
                the ``(code ASC, id ASC)`` ordering.
            skip_count: When True, the total-count query is skipped and
                the second tuple element is ``None``. The router uses this
                for cursor-paginated requests to avoid the count cost.

        Returns:
            Tuple of (items, total_count_or_None, has_more).
        """
        from sqlalchemy import Float

        base = select(CostItem).where(CostItem.is_active.is_(True))

        if q:
            pattern = f"%{q}%"
            base = base.where(CostItem.code.ilike(pattern) | CostItem.description.ilike(pattern))

        if name:
            base = base.where(CostItem.code.ilike(f"%{name}%"))

        if description:
            base = base.where(CostItem.description.ilike(f"%{description}%"))

        if unit:
            base = base.where(CostItem.unit == unit)

        if source:
            base = base.where(CostItem.source == source)

        if region:
            base = base.where(CostItem.region == region)

        if category:
            # Use database-agnostic JSON access: json_extract for SQLite,
            # ->> operator for PostgreSQL.  Both are handled via SQLAlchemy's
            # generic JSON subscript when we fall back to text matching.
            from app.database import engine as _engine

            _url = str(_engine.url)
            if "sqlite" in _url:
                collection_expr = func.json_extract(CostItem.classification, "$.collection")
                base = base.where(collection_expr == category)
            else:
                # PostgreSQL: use the ->> operator via SQLAlchemy column subscript
                base = base.where(CostItem.classification["collection"].as_string() == category)

        if classification_path:
            # Prefix-filter at every depth supplied. Empty middle segments
            # ⇒ no filter at that depth (wildcard). Reuses the same
            # dialect-aware extractor as ``category`` so semantics match.
            for depth_idx, segment in enumerate(_split_classification_path(classification_path)):
                if segment is None:
                    continue
                expr = _classification_expr(_CLASSIFICATION_DEPTHS[depth_idx])
                base = base.where(expr == segment)

        # Cast to Float for cross-dialect comparison — the rate column is
        # String(50) for SQLite Decimal compat (see models.py). Pre-cast
        # the bound so Decimal inputs (Round-7) don't end up with mixed
        # precision under PostgreSQL's stricter type promotion.
        if min_rate is not None:
            base = base.where(cast(CostItem.rate, Float) >= float(min_rate))

        if max_rate is not None:
            base = base.where(cast(CostItem.rate, Float) <= float(max_rate))

        # Total count — only when explicitly requested. Cursor-paginated
        # queries skip this since counting on every page is wasteful and
        # the frontend doesn't show a total beyond the first page.
        total: int | None
        if skip_count:
            total = None
        else:
            count_stmt = select(func.count()).select_from(base.subquery())
            total = (await self.session.execute(count_stmt)).scalar_one()

        # Apply keyset filter AFTER the count query so the total reflects
        # the full result set, not the post-cursor remainder.
        page_stmt = base
        if cursor is not None:
            cursor_code, cursor_id = cursor
            # Cast UUID column to text for the tiebreaker comparison —
            # SQLite stores UUIDs as VARCHAR(36) via the ``GUID`` type
            # decorator, and PostgreSQL has a built-in UUID → text cast.
            # Comparing on the string form keeps the ordering consistent
            # with what the encoded cursor carries.
            id_text = cast(CostItem.id, String)
            page_stmt = page_stmt.where(
                or_(
                    CostItem.code > cursor_code,
                    and_(CostItem.code == cursor_code, id_text > cursor_id),
                )
            )

        # Fetch limit+1 to detect "has_more" without an extra count query.
        # Order by the SAME ``cast(id, String)`` expression we use in the
        # keyset filter so the lexicographic ordering of cursor.id matches
        # the ORDER BY at the database — both SQLite (string-stored UUID)
        # and Postgres (UUID-with-text-cast) sort identically that way.
        page_stmt = (
            page_stmt.order_by(CostItem.code.asc(), cast(CostItem.id, String).asc())
            .offset(offset if cursor is None else 0)
            .limit(limit + 1)
        )
        result = await self.session.execute(page_stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]

        return items, total, has_more

    async def search_for_autocomplete(
        self,
        *,
        q: str,
        region: str | None = None,
        limit: int = 8,
    ) -> list[CostItem]:
        """Autocomplete-tuned search: ORDER BY components-first IN SQL.

        Hot path for ``/v1/costs/autocomplete/``. The previous
        implementation fetched ``limit*3`` rows via the generic
        :meth:`search` then resorted them in Python by "items with
        components first" (richer cards for the estimator). On a 110k-row
        catalogue this issued a 24-row fetch + Python sort per keystroke
        when the user only ever saw 8 — pure waste.

        Pushing the priority into the ORDER BY uses the same single index
        the generic search already exploits (``ix_costs_active_code``)
        for the WHERE clause, then leans on the planner's tiebreaker
        sort over a tiny post-filter set. Result: 1 query, ``limit``
        rows returned, no Python-side resort.

        The "has components" predicate is encoded as a CASE expression so
        it compiles identically on SQLite (json_array_length) and
        PostgreSQL (jsonb_array_length). Empty JSON arrays sort AFTER
        non-empty ones (DESC on the CASE) which matches the legacy
        Python order ``(0 if has else 1, code)``.

        Args:
            q: Substring match against code OR description (ILIKE).
                Required — no q means use the generic listing endpoint.
            region: Optional region filter (e.g. ``"DE_BERLIN"``).
            limit: Hard cap on returned rows (matches the public endpoint
                cap of 20).

        Returns:
            Up to ``limit`` ``CostItem`` rows, items-with-components
            first then code-ascending.
        """
        from app.database import engine as _engine

        base = select(CostItem).where(CostItem.is_active.is_(True))

        pattern = f"%{q}%"
        base = base.where(
            CostItem.code.ilike(pattern) | CostItem.description.ilike(pattern),
        )

        if region:
            base = base.where(CostItem.region == region)

        # Dialect-aware "has components" predicate. We treat any non-empty
        # JSON array as 1, empty/NULL as 0 — matches the Python ``_has_components``
        # helper the router used to call. Postgres ships JSONB whose
        # ``jsonb_array_length`` is the canonical helper; SQLite has
        # ``json_array_length`` which mirrors it semantically (both return
        # 0 for ``[]`` and NULL for non-arrays / NULL).
        if "sqlite" in str(_engine.url):
            comp_len = func.coalesce(func.json_array_length(CostItem.components), 0)
        else:
            # ``jsonb_array_length`` on a TEXT JSON column requires an
            # explicit cast on Postgres; CostItem.components is declared
            # as plain ``JSON`` so we route through ``json_array_length``
            # which works on json (text-domain) and reuse the same
            # coalesce semantics so NULL rows sort AFTER empty arrays.
            comp_len = func.coalesce(func.json_array_length(CostItem.components), 0)

        # CASE(comp_len > 0 → 1 else 0) — items WITH components first.
        # DESC so the "1" rows lead.
        from sqlalchemy import case

        priority = case((comp_len > 0, 1), else_=0).label("priority")

        stmt = base.order_by(priority.desc(), CostItem.code.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def category_tree(
        self,
        region: str | None = None,
        depth: int = 4,
        parent_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate cost items into a classification tree.

        Runs a single GROUP BY across the requested classification depths
        and nests the resulting flat rows in Python. NULL / empty values
        at any depth coalesce into the :data:`UNSPECIFIED_CATEGORY`
        sentinel so the frontend can localize the label.

        Args:
            region: Optional region filter (e.g. ``"DE_BERLIN"``). When
                ``None``, every active region contributes.
            depth: How many classification levels to return (1..4). Lower
                depth = much cheaper query (fewer GROUP BY columns and
                fewer output rows). The modal opens with ``depth=2`` to
                paint the sidebar within ~150 ms even on cold catalogs;
                deeper levels are reachable via ``classification_path``
                filtering on the search query, which doesn't need them
                pre-aggregated.
            parent_path: Optional slash-delimited prefix to scope the
                aggregation to a sub-branch (e.g. ``"Concrete/Walls"``).
                Reuses :func:`_split_classification_path` for empty-segment
                wildcard semantics. Returned nodes start at ``depth+1``
                relative to the root, but the caller renders them as if
                they were a fresh top-level — combine with the existing
                cached top-level tree on the client to lazily extend.

        Returns:
            A list of root nodes, each shaped as
            ``{"name": str, "count": int, "children": [...]}``.
        """
        depth = max(1, min(4, depth))

        # Build the extracted expressions and label them so we can access
        # by name on the result rows. coalesce() doesn't help here
        # (json_extract returns NULL for missing keys, which IS what we
        # want to detect) — we coerce in Python instead so empty strings
        # and missing keys collapse into the same sentinel.
        all_cols = [_classification_expr(key).label(key) for key in _CLASSIFICATION_DEPTHS]
        cnt = func.count(CostItem.id).label("cnt")

        # Slice to requested depth.  The GROUP BY label list and the row
        # tuple length follow the same slice so the Python loop below
        # iterates the correct number of segments per row.
        active_cols = all_cols[:depth]
        active_keys = list(_CLASSIFICATION_DEPTHS[:depth])

        stmt = select(*active_cols, cnt).where(CostItem.is_active.is_(True)).group_by(*active_keys)
        if region:
            stmt = stmt.where(CostItem.region == region)

        # When a parent prefix is supplied, AND in equality filters at the
        # appropriate depths so we only aggregate the sub-branch.
        if parent_path:
            for depth_idx, segment in enumerate(_split_classification_path(parent_path)):
                if segment is None:
                    continue
                expr = _classification_expr(_CLASSIFICATION_DEPTHS[depth_idx])
                stmt = stmt.where(expr == segment)

        result = await self.session.execute(stmt)
        rows = result.all()

        # Nested dict accumulator: {collection: {"count": N, "children":
        # {department: {"count": N, "children": {section: {...}}}}}}
        tree: dict[str, dict[str, Any]] = {}

        def _norm(val: object) -> str:
            if val is None:
                return UNSPECIFIED_CATEGORY
            text = str(val).strip()
            return text if text else UNSPECIFIED_CATEGORY

        for row in rows:
            path = tuple(_norm(getattr(row, key)) for key in active_keys)
            count = int(row.cnt)
            level: dict[str, dict[str, Any]] = tree
            for segment in path:
                node = level.setdefault(segment, {"count": 0, "children": {}})
                node["count"] += count
                level = node["children"]

        # Convert nested dicts to the public list-of-nodes shape, sorted
        # alphabetically at each level for stable output (the sentinel
        # sorts last to keep "real" labels at the top).
        def _to_list(level_dict: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
            sorted_items = sorted(
                level_dict.items(),
                key=lambda kv: (kv[0] == UNSPECIFIED_CATEGORY, kv[0].lower()),
            )
            return [
                {
                    "name": name,
                    "count": node["count"],
                    "children": _to_list(node["children"]),
                }
                for name, node in sorted_items
            ]

        return _to_list(tree)
