# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cascade Filter Engine (T04).

When a user picks a value for one filter (``category = "Concrete"``), the
*other* filter pickers should narrow to only the values that co-occur
with that selection. This is the "Tableau cascade filter" / "Power BI
relative filter" pattern.

Wire-level shape
----------------
The endpoint receives a ``selected`` map (column -> list of allowed
values), a ``target_column`` (the picker the user is now opening), and
an optional ``q`` string for substring filtering on the target column's
values. The response is a list of distinct values of ``target_column``
whose row-set is consistent with every ``selected`` constraint AND
matches ``q``.

Two analytical helpers are exposed:

* :func:`fetch_cascade_values` — distinct-value cascade (the picker UI).
* :func:`count_filtered_rows` — row-level rollup ("X of Y rows match"),
  used by the live counter chip above the picker stack.

Both reuse the snapshot's pinned DuckDB connection. They reuse the
column-classification logic from :mod:`smart_values` (top-level vs
flattened-attribute key) so the two systems agree on how a given column
is addressed inside the Parquet file.

Empty-selection contract
------------------------
An entry ``selected["category"] = []`` is treated as **no filter** on
that column — never as ``WHERE category IN ()`` (DuckDB rejects that
shape with a parser error). This matches Tableau's behaviour: dragging
all chips off a filter card removes the constraint instead of producing
"the empty intersection".

Pyarrow fallback
----------------
If DuckDB is unavailable (rare since v2.5.0), :func:`fetch_cascade_values`
delegates to a pyarrow-backed in-memory implementation that mirrors the
SQL semantics line-for-line. Same answer, slower on the big-snapshot
end of the spectrum.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.modules.dashboards.duckdb_pool import DuckDBPool
from app.modules.dashboards.smart_values import (
    _TOP_LEVEL_COLUMNS,
    _VALID_COLUMN_RE,
    ColumnNotFoundError,
    ValueMatch,
    _attributes_key_present,
    _safe_key,
)

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────────


@dataclass
class CascadeMatch:
    """One distinct value plus its row count under the active selection."""

    value: str
    count: int

    def to_dict(self) -> dict:
        return {"value": self.value, "count": self.count}


class InvalidSelectedColumnError(ValueError):
    """Raised when one of the ``selected`` keys is not in the snapshot.

    Distinct from :class:`ColumnNotFoundError` so the router can map it
    to a 422 (the request body referenced an unknown column) while
    target-column misses still 404 (the URL targets the unknown column).
    """


# ── Constants ──────────────────────────────────────────────────────────────


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_MAX_COLUMNS_IN_SELECTED = 32
"""Hard upper bound on the number of filter columns in a single request.
Keeps the generated SQL bounded — no realistic dashboard exposes 32
filter cards at once. Anything larger is almost certainly a malformed
request."""

_MAX_VALUES_PER_COLUMN = 500
"""Cap on the number of allowed values per column. The IN-list grows
linearly with this; 500 already covers "select 90% of a long-tailed
category column"."""


# ── Service entry points ───────────────────────────────────────────────────


async def fetch_cascade_values(
    *,
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    selected: dict[str, list[str]],
    target_column: str,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[CascadeMatch]:
    """Return distinct values of ``target_column`` consistent with ``selected``.

    Parameters
    ----------
    selected:
        Mapping of column -> allowed values. Empty lists are silently
        ignored (no filter on that column). Unknown columns raise
        :class:`InvalidSelectedColumnError`. The target column is
        excluded from the WHERE clause even if present in ``selected``
        — a filter doesn't constrain its own picker.
    target_column:
        The column whose distinct values are being shown to the user.
    query:
        Optional case-insensitive substring filter on the target
        column's values (LIKE ``%q%``).
    limit:
        Maximum rows returned. Capped at :data:`_MAX_LIMIT`.
    """
    target_column = _validate_column(target_column)
    limit = max(1, min(limit, _MAX_LIMIT))

    cleaned = _validate_and_clean_selected(selected, exclude=target_column)

    target_is_top_level = target_column in _TOP_LEVEL_COLUMNS
    await _ensure_target_exists(
        pool, snapshot_id, project_id, target_column, target_is_top_level,
    )
    await _ensure_selected_exist(pool, snapshot_id, project_id, cleaned)

    sql, params = _build_cascade_sql(
        cleaned=cleaned,
        target_column=target_column,
        target_is_top_level=target_is_top_level,
        query=query,
        limit=limit,
    )
    rows = await pool.execute(snapshot_id, project_id, sql, params)
    return [
        CascadeMatch(value=str(v), count=int(c))
        for v, c in rows
        if v is not None
    ]


async def count_filtered_rows(
    *,
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    selected: dict[str, list[str]],
) -> tuple[int, int]:
    """Return ``(matched, total)`` row counts under the active selection.

    The frontend pairs these to render "X of Y rows match" above the
    cascade panel — a quick gut-check that the filters do something.
    """
    cleaned = _validate_and_clean_selected(selected, exclude=None)
    await _ensure_selected_exist(pool, snapshot_id, project_id, cleaned)

    total_rows = await pool.execute(
        snapshot_id, project_id, "SELECT COUNT(*) FROM entities",
    )
    total = int(total_rows[0][0]) if total_rows else 0

    if not cleaned:
        return (total, total)

    where_sql, params = _build_where_clause(cleaned)
    matched_rows = await pool.execute(
        snapshot_id,
        project_id,
        f"SELECT COUNT(*) FROM entities WHERE {where_sql}",
        params,
    )
    matched = int(matched_rows[0][0]) if matched_rows else 0
    return (matched, total)


# ── DataFrame fallback ─────────────────────────────────────────────────────


def fetch_cascade_values_from_dataframe(
    df: pd.DataFrame,
    *,
    selected: dict[str, list[str]],
    target_column: str,
    query: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> list[CascadeMatch]:
    """Pure-Python fallback used when DuckDB cannot be loaded.

    Mirrors the SQL semantics row-for-row: empty selections drop, target
    column is excluded from constraints, q is a case-insensitive
    substring filter. Same tie-breaks as the SQL path: count DESC, then
    value ASC.
    """
    target_column = _validate_column(target_column)
    limit = max(1, min(limit, _MAX_LIMIT))

    cleaned = _validate_and_clean_selected(selected, exclude=target_column)

    # Materialise the target series (top-level or attribute-key).
    target_series = _series_for_column(df, target_column)
    if target_series is None:
        raise ColumnNotFoundError(
            f"Column '{target_column}' is not present in the snapshot.",
        )

    # Build a row-mask from the cleaned selections.
    mask = None
    for col, allowed in cleaned.items():
        col_series = _series_for_column(df, col)
        if col_series is None:
            raise InvalidSelectedColumnError(
                f"Selected column '{col}' is not present in the snapshot.",
            )
        col_mask = col_series.astype(str).isin([str(v) for v in allowed])
        mask = col_mask if mask is None else (mask & col_mask)

    if mask is not None:
        target_series = target_series[mask]

    target_series = target_series.dropna().astype(str)
    if query.strip():
        q = query.strip().lower()
        target_series = target_series[target_series.str.lower().str.contains(q, regex=False)]

    counts = target_series.value_counts()
    if counts.empty:
        return []
    matches = [CascadeMatch(value=str(k), count=int(v)) for k, v in counts.items()]
    matches.sort(key=lambda m: (-m.count, m.value))
    return matches[:limit]


# ── Validation helpers ─────────────────────────────────────────────────────


def _validate_column(column: str) -> str:
    column = (column or "").strip()
    if not column or not _VALID_COLUMN_RE.match(column):
        raise ColumnNotFoundError(
            f"Column name '{column}' contains invalid characters.",
        )
    return column


def _validate_and_clean_selected(
    selected: dict[str, list[str]] | None,
    *,
    exclude: str | None,
) -> dict[str, list[str]]:
    """Drop empty-array entries, sanity-check sizes, validate identifiers.

    The exclude argument removes the target column from the constraint
    set — its own picker shouldn't gate its own values, otherwise
    re-opening a column always shows only the chips you've already
    picked.
    """
    if not selected:
        return {}
    if not isinstance(selected, dict):
        raise InvalidSelectedColumnError("selected must be an object/dict.")
    if len(selected) > _MAX_COLUMNS_IN_SELECTED:
        raise InvalidSelectedColumnError(
            f"selected may contain at most {_MAX_COLUMNS_IN_SELECTED} columns.",
        )

    cleaned: dict[str, list[str]] = {}
    for raw_col, raw_values in selected.items():
        if exclude is not None and raw_col == exclude:
            continue
        col = (raw_col or "").strip()
        if not col or not _VALID_COLUMN_RE.match(col):
            raise InvalidSelectedColumnError(
                f"Selected column '{raw_col}' has an invalid identifier.",
            )
        if not isinstance(raw_values, list):
            raise InvalidSelectedColumnError(
                f"Selected['{col}'] must be a list of strings.",
            )
        # Empty list → no filter on this column. Drop it before SQL.
        if len(raw_values) == 0:
            continue
        if len(raw_values) > _MAX_VALUES_PER_COLUMN:
            raise InvalidSelectedColumnError(
                f"Selected['{col}'] contains more than "
                f"{_MAX_VALUES_PER_COLUMN} values.",
            )
        # Coerce to strings; the underlying Parquet column is CAST to
        # VARCHAR before comparison so heterogenous types (int, bool)
        # compare cleanly.
        cleaned[col] = [str(v) for v in raw_values]
    return cleaned


async def _ensure_target_exists(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    column: str,
    is_top_level: bool,
) -> None:
    if is_top_level:
        rows = await pool.execute(
            snapshot_id,
            project_id,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'entities'",
        )
        names = {str(r[0]) for r in rows}
        if column not in names:
            raise ColumnNotFoundError(
                f"Column '{column}' is not in this snapshot's schema.",
            )
        return
    if not await _attributes_key_present(pool, snapshot_id, project_id, column):
        raise ColumnNotFoundError(
            f"Column '{column}' is not present in any row's attributes.",
        )


async def _ensure_selected_exist(
    pool: DuckDBPool,
    snapshot_id: str,
    project_id: str,
    cleaned: dict[str, list[str]],
) -> None:
    """Verify every selected column exists. Wrong columns → 422."""
    if not cleaned:
        return
    top_level_names: set[str] | None = None
    for col in cleaned:
        if col in _TOP_LEVEL_COLUMNS:
            if top_level_names is None:
                rows = await pool.execute(
                    snapshot_id,
                    project_id,
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'entities'",
                )
                top_level_names = {str(r[0]) for r in rows}
            if col not in top_level_names:
                raise InvalidSelectedColumnError(
                    f"Selected column '{col}' is not in this snapshot's schema.",
                )
            continue
        if not await _attributes_key_present(pool, snapshot_id, project_id, col):
            raise InvalidSelectedColumnError(
                f"Selected column '{col}' is not present in any row's attributes.",
            )


# ── SQL generation ─────────────────────────────────────────────────────────


def _build_where_clause(
    cleaned: dict[str, list[str]],
) -> tuple[str, list]:
    """Render the parameterised WHERE clause for a selection map.

    Each predicate uses ``CAST(... AS VARCHAR) IN (?, ?, ...)`` with one
    bound parameter per allowed value. Empty selections were already
    dropped by :func:`_validate_and_clean_selected`, so the placeholder
    list is never empty.
    """
    predicates: list[str] = []
    params: list = []
    for col, values in cleaned.items():
        if not values:
            # Defensive — should have been dropped already, but never
            # ship an empty IN-list to DuckDB.
            continue
        placeholders = ", ".join(["?"] * len(values))
        if col in _TOP_LEVEL_COLUMNS:
            predicates.append(
                f'CAST("{_safe_key(col)}" AS VARCHAR) IN ({placeholders})',
            )
        else:
            # Use the MAP-style accessor; the column-existence check
            # already verified the key is present in *some* form.
            key = _safe_key(col)
            predicates.append(
                f'CAST(attributes[\'{key}\'] AS VARCHAR) IN ({placeholders})',
            )
        params.extend(values)
    if not predicates:
        # Shouldn't reach here — callers branch on cleaned-dict
        # emptiness — but keep the function total.
        return ("1=1", [])
    return (" AND ".join(predicates), params)


def _build_cascade_sql(
    *,
    cleaned: dict[str, list[str]],
    target_column: str,
    target_is_top_level: bool,
    query: str,
    limit: int,
) -> tuple[str, list]:
    """Build the cascade SELECT.

    Shape::

        SELECT CAST(target AS VARCHAR) AS v, COUNT(*) AS c
          FROM entities
         WHERE target IS NOT NULL
           [AND target ILIKE ?]
           [AND <selection predicates>]
         GROUP BY 1
         ORDER BY c DESC, v ASC
         LIMIT ?
    """
    if target_is_top_level:
        target_expr = f'"{_safe_key(target_column)}"'
    else:
        target_expr = f"attributes['{_safe_key(target_column)}']"

    where_parts = [f"{target_expr} IS NOT NULL"]
    params: list = []

    if query.strip():
        where_parts.append(f"CAST({target_expr} AS VARCHAR) ILIKE ?")
        params.append(f"%{query.strip()}%")

    if cleaned:
        sel_sql, sel_params = _build_where_clause(cleaned)
        where_parts.append(sel_sql)
        params.extend(sel_params)

    sql = (
        f"SELECT CAST({target_expr} AS VARCHAR) AS v, COUNT(*) AS c "
        f"FROM entities "
        f"WHERE {' AND '.join(where_parts)} "
        f"GROUP BY 1 ORDER BY c DESC, v ASC LIMIT ?"
    )
    params.append(limit)
    return sql, params


# ── Local helpers ──────────────────────────────────────────────────────────


def _series_for_column(df: pd.DataFrame, column: str):
    """Return the ``pandas.Series`` for a top-level or attribute-key column.

    Returns ``None`` if the column cannot be located. Callers turn that
    into the appropriate 404/422.
    """
    if column in df.columns:
        return df[column]
    if "attributes" in df.columns:
        series = df["attributes"].apply(
            lambda d: d.get(column) if isinstance(d, dict) else None,
        )
        # If every row produced None, the key truly isn't present.
        if series.dropna().empty:
            return None
        return series
    return None


__all__ = [
    "CascadeMatch",
    "InvalidSelectedColumnError",
    "ValueMatch",  # re-export for convenience
    "count_filtered_rows",
    "fetch_cascade_values",
    "fetch_cascade_values_from_dataframe",
]
