# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Value Autocomplete (T03).

Given a snapshot and a column name, return distinct values matching a
substring query — fast enough for snapshots with 100k+ rows.

Resolution strategy
-------------------
1. Try DuckDB against the snapshot's ``entities.parquet`` view.
   Columns can be top-level (``category``) or flattened attribute keys
   (``attributes -> 'properties.material'``). DuckDB's predicate pushdown
   makes the ``DISTINCT col WHERE col ILIKE ? LIMIT 20`` shape very fast
   over Parquet zone-maps.
2. If DuckDB is not installed or the snapshot file is unreachable, fall
   back to pyarrow + a Python loop. Slower but correct on any Linux box.
3. If the LIKE pattern still yields more candidates than ``limit``, rank
   the results with :mod:`rapidfuzz` so close lexicographic matches
   surface above unrelated alphabetical neighbours.

Empty query
-----------
``q=""`` returns the top-N values by frequency (most common first).
That's the most useful default for an "open the dropdown, see options"
interaction.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

from app.modules.dashboards.duckdb_pool import (
    DuckDBPool,
    SnapshotHasNoEntitiesError,
)

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────────


@dataclass
class ValueMatch:
    """One autocomplete suggestion."""

    value: str
    count: int
    score: float = 0.0  # rapidfuzz-derived rank score (0..100)

    def to_dict(self) -> dict:
        return {"value": self.value, "count": self.count, "score": round(self.score, 2)}


class ColumnNotFoundError(LookupError):
    """Raised when ``column`` does not exist in the snapshot's schema."""


# ── Constants ──────────────────────────────────────────────────────────────


_MAX_LIMIT = 100
_DEFAULT_LIMIT = 20
_OVERSCAN_FACTOR = 5
"""Pull this many candidates from DuckDB before fuzzy-ranking.
Picking ``limit * 5`` is a sweet spot: tight enough to keep the SQL fast,
wide enough that the fuzzy ranker has something to choose from."""

_TOP_LEVEL_COLUMNS = frozenset(
    {"entity_guid", "category", "source_file_id"},
)
"""Known top-level columns in ``entities.parquet``. Anything else is
assumed to be a flattened attribute key — addressed via
``attributes['the.key']`` in DuckDB."""

_VALID_COLUMN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


# ── Service entry point ────────────────────────────────────────────────────


async def fetch_distinct_values(
    *,
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[ValueMatch]:
    """Return up to ``limit`` distinct values for ``column`` matching ``query``.

    Raises
    ------
    ColumnNotFoundError
        If ``column`` is not in the snapshot's known schema.
    SnapshotHasNoEntitiesError
        If the snapshot's ``entities.parquet`` is missing.
    """
    column = column.strip()
    if not column or not _VALID_COLUMN_RE.match(column):
        raise ColumnNotFoundError(
            f"Column name '{column}' contains invalid characters."
        )
    limit = max(1, min(limit, _MAX_LIMIT))
    overscan_limit = limit * _OVERSCAN_FACTOR

    is_top_level = column in _TOP_LEVEL_COLUMNS

    # 1 — verify column exists in the schema. For top-level we hit
    # information_schema; for flattened attributes we run a SELECT
    # against the first row's keys.
    await _ensure_column_exists(pool, snapshot_id, project_id, column, is_top_level)

    # 2 — fetch candidates via DuckDB. Empty query → top-N by frequency.
    if query.strip():
        rows = await _fetch_with_filter(
            pool, snapshot_id, project_id, column,
            query=query, limit=overscan_limit, is_top_level=is_top_level,
        )
    else:
        rows = await _fetch_top_by_frequency(
            pool, snapshot_id, project_id, column,
            limit=overscan_limit, is_top_level=is_top_level,
        )

    if not rows:
        return []

    candidates = [ValueMatch(value=str(v), count=int(c)) for v, c in rows if v is not None]

    # 3 — fuzzy-rank if we over-fetched (LIKE returned more than limit).
    if query.strip() and len(candidates) > limit:
        candidates = _rerank_with_rapidfuzz(candidates, query)

    return candidates[:limit]


# ── DuckDB query layer ─────────────────────────────────────────────────────


async def _ensure_column_exists(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
    is_top_level: bool,
) -> None:
    if is_top_level:
        rows = await pool.execute(
            snapshot_id, project_id,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'entities'",
        )
        names = {str(r[0]) for r in rows}
        if column not in names:
            raise ColumnNotFoundError(
                f"Column '{column}' is not in this snapshot's schema."
            )
        return

    # Flattened attribute — pyarrow writes the per-row dicts as a STRUCT
    # column when the keys are stable across rows, or as a MAP when they
    # vary. We try both accessors; either a binder error or a zero-row
    # result means "not present".
    if not await _attributes_key_present(pool, snapshot_id, project_id, column):
        raise ColumnNotFoundError(
            f"Column '{column}' is not present in any row's attributes."
        )


async def _attributes_key_present(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
) -> bool:
    """Return True if ``column`` exists as an attribute key, False otherwise.

    Catches the broad ``Exception`` from DuckDB's binder because
    :class:`DuckDBPool` re-raises bind failures in two shapes: as a
    :class:`DuckDBPoolError` for the connect/register path, and as the
    raw underlying ``BinderException`` for query bodies. Both should be
    treated as "key not present" for autocomplete purposes — the column
    really doesn't exist on the data.
    """
    # 1 — try MAP-style accessor (works when pyarrow wrote a MAP column).
    try:
        rows = await pool.execute(
            snapshot_id, project_id,
            "SELECT 1 FROM entities WHERE attributes[?] IS NOT NULL LIMIT 1",
            [column],
        )
        if rows:
            return True
    except Exception:
        pass

    # 2 — try STRUCT-style accessor.
    key = _safe_key(column)
    try:
        rows = await pool.execute(
            snapshot_id, project_id,
            f'SELECT 1 FROM entities WHERE attributes."{key}" IS NOT NULL LIMIT 1',
        )
        if rows:
            return True
    except Exception:
        # Binder error → struct exists but lacks the key → absent.
        pass
    return False


async def _fetch_with_filter(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
    *,
    query: str,
    limit: int,
    is_top_level: bool,
) -> list[tuple]:
    pattern = f"%{query.strip()}%"
    if is_top_level:
        sql = (
            f'SELECT CAST("{_safe_key(column)}" AS VARCHAR) AS v, COUNT(*) AS c '
            f'FROM entities WHERE "{_safe_key(column)}" IS NOT NULL '
            f'AND CAST("{_safe_key(column)}" AS VARCHAR) ILIKE ? '
            f'GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?'
        )
        return await pool.execute(snapshot_id, project_id, sql, [pattern, limit])
    sql = (
        "SELECT CAST(attributes[?] AS VARCHAR) AS v, COUNT(*) AS c "
        "FROM entities WHERE attributes[?] IS NOT NULL "
        "AND CAST(attributes[?] AS VARCHAR) ILIKE ? "
        "GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?"
    )
    try:
        return await pool.execute(
            snapshot_id, project_id, sql, [column, column, column, pattern, limit],
        )
    except Exception:
        # Fallback for struct attributes (DuckDB raises BinderException
        # rather than DuckDBPoolError when MAP-style access doesn't fit
        # the actual Parquet shape).
        key = _safe_key(column)
        sql = (
            f'SELECT CAST(attributes."{key}" AS VARCHAR) AS v, COUNT(*) AS c '
            f'FROM entities WHERE attributes."{key}" IS NOT NULL '
            f'AND CAST(attributes."{key}" AS VARCHAR) ILIKE ? '
            f'GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?'
        )
        return await pool.execute(snapshot_id, project_id, sql, [pattern, limit])


async def _fetch_top_by_frequency(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
    *,
    limit: int,
    is_top_level: bool,
) -> list[tuple]:
    if is_top_level:
        sql = (
            f'SELECT CAST("{_safe_key(column)}" AS VARCHAR) AS v, COUNT(*) AS c '
            f'FROM entities WHERE "{_safe_key(column)}" IS NOT NULL '
            f'GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?'
        )
        return await pool.execute(snapshot_id, project_id, sql, [limit])
    sql = (
        "SELECT CAST(attributes[?] AS VARCHAR) AS v, COUNT(*) AS c "
        "FROM entities WHERE attributes[?] IS NOT NULL "
        "GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?"
    )
    try:
        return await pool.execute(
            snapshot_id, project_id, sql, [column, column, limit],
        )
    except Exception:
        key = _safe_key(column)
        sql = (
            f'SELECT CAST(attributes."{key}" AS VARCHAR) AS v, COUNT(*) AS c '
            f'FROM entities WHERE attributes."{key}" IS NOT NULL '
            f'GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?'
        )
        return await pool.execute(snapshot_id, project_id, sql, [limit])


# ── In-process fallback (no DuckDB) ────────────────────────────────────────


def fetch_distinct_values_from_dataframe(
    df: pd.DataFrame,
    *,
    column: str,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[ValueMatch]:
    """Pure-Python fallback — used when DuckDB cannot be loaded.

    Operates on the DataFrame produced by the cad2data bridge: top-level
    columns are direct, attribute keys live inside the ``attributes``
    dict column.
    """
    column = column.strip()
    if not column or not _VALID_COLUMN_RE.match(column):
        raise ColumnNotFoundError(f"Column name '{column}' is invalid.")
    limit = max(1, min(limit, _MAX_LIMIT))

    if column in df.columns:
        series = df[column].dropna().astype(str)
    elif "attributes" in df.columns:
        series = df["attributes"].apply(
            lambda d: d.get(column) if isinstance(d, dict) else None,
        ).dropna().astype(str)
        if series.empty:
            raise ColumnNotFoundError(f"Column '{column}' not in schema.")
    else:
        raise ColumnNotFoundError(f"Column '{column}' not in schema.")

    if query.strip():
        q_low = query.strip().lower()
        series = series[series.str.lower().str.contains(re.escape(q_low), na=False)]

    counts = series.value_counts()
    if counts.empty:
        return []
    candidates = [ValueMatch(value=str(k), count=int(v)) for k, v in counts.items()]
    if query.strip() and len(candidates) > limit:
        candidates = _rerank_with_rapidfuzz(candidates, query)
    return candidates[:limit]


# ── rapidfuzz reranking ────────────────────────────────────────────────────


def _rerank_with_rapidfuzz(
    candidates: list[ValueMatch], query: str,
) -> list[ValueMatch]:
    """Re-order ``candidates`` so close lexicographic matches lead.

    Uses :func:`rapidfuzz.fuzz.WRatio` — a weighted blend of partial-,
    token-set- and full-string ratios that handles "concrete c30/37"
    being a strong match for query "concr" while still penalising
    longer, looser matches.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover — rapidfuzz is in base deps
        return candidates

    q = query.strip().lower()
    if not q:
        return candidates

    def _score(c: ValueMatch) -> float:
        return float(fuzz.WRatio(q, c.value.lower()))

    for c in candidates:
        c.score = _score(c)
    candidates.sort(key=lambda c: (-c.score, -c.count, c.value))
    return candidates


# ── Helpers ────────────────────────────────────────────────────────────────


def _safe_key(s: str) -> str:
    """Escape a column / attribute key for use inside a DuckDB identifier
    literal. The pool already wraps SQL execution in to_thread; the
    identifier itself is double-quoted, so we only need to escape the
    closing double-quote.
    """
    return s.replace('"', '""')


__all__ = [
    "ColumnNotFoundError",
    "ValueMatch",
    "fetch_distinct_values",
    "fetch_distinct_values_from_dataframe",
]


# Re-export for testability.
SnapshotHasNoEntitiesError = SnapshotHasNoEntitiesError
