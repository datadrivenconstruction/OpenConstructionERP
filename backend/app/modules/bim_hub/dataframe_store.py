"""Parquet-based dataframe storage for BIM element properties.

Writes the full DDC converter output (1000+ columns) as a compressed
Parquet file alongside the model's geometry and original upload.  DuckDB
queries the Parquet directly for analytical filtering -- no import step,
no separate database, no new server process.

File layout::

    data/bim/{project_id}/{model_id}/elements.parquet

Dependencies:
    * **pyarrow** -- already in base deps (used by pandas / BIM Excel parser).
    * **duckdb** -- new *optional* dep.  When missing the module falls back
      to pure-pyarrow row-level filtering (slower but functional).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# Default storage root -- matches existing BIM file storage layout.
_DATA_ROOT = Path("data/bim")

# Operators that take no value (unary predicates).
_UNARY_OPS = frozenset({"IS NULL", "IS NOT NULL"})

# Allowed binary/set operators (prevents injection via the ``op`` field).
_BINARY_OPS = frozenset({"=", "!=", ">", "<", ">=", "<=", "LIKE", "IN"})


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def write_dataframe(
    project_id: str,
    model_id: str,
    rows: list[dict[str, Any]],
    data_root: Path = _DATA_ROOT,
) -> Path:
    """Write a list of element dicts as a Parquet file.

    Each dict is one row (one BIM element).  Keys become columns.
    Missing keys become null.  ZSTD compression, row groups of 50 000.

    Returns the path to the written ``.parquet`` file.
    """
    dest_dir = data_root / project_id / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = dest_dir / "elements.parquet"

    # pyarrow.Table.from_pylist infers the schema from the FIRST dict
    # only — keys that appear in later dicts but not the first are
    # silently dropped.  DDC Excel rows are sparse (a Material element
    # has 6 keys, a Wall has 21, a Door has 35), so we must collect
    # ALL keys first and normalise every row to include them all.
    all_keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for k in row:
            if k not in seen:
                seen.add(k)
                all_keys.append(k)

    # Normalise: ensure every row has every key (None for missing).
    # Also sanitise values: DDC Excel sometimes puts non-breaking spaces
    # (\xa0) in numeric cells which crashes pyarrow type inference.
    def _clean(v: Any) -> Any:
        if isinstance(v, str):
            v = v.replace("\xa0", " ").strip()
            if not v or v.lower() in ("none", "null"):
                return None
        return v

    normalised = [{k: _clean(row.get(k)) for k in all_keys} for row in rows]

    # Force all columns to string to avoid type-inference crashes on
    # mixed int/str/float columns (e.g. "Volume" is float for walls
    # but the literal string "None" for materials).
    schema = pa.schema([(k, pa.string()) for k in all_keys])
    str_rows = [{k: str(v) if v is not None else None for k, v in row.items()} for row in normalised]
    table = pa.Table.from_pylist(str_rows, schema=schema)

    pq.write_table(
        table,
        parquet_path,
        compression="zstd",
        row_group_size=50_000,
        write_statistics=True,  # enables predicate pushdown
    )

    logger.info(
        "Wrote Parquet: %s (%d rows, %d cols, %.1f MB)",
        parquet_path,
        table.num_rows,
        table.num_columns,
        parquet_path.stat().st_size / 1024 / 1024,
    )
    return parquet_path


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------

def read_schema(
    project_id: str,
    model_id: str,
    data_root: Path = _DATA_ROOT,
) -> list[dict[str, str]]:
    """Return column names and Arrow types from the Parquet schema.

    Used by the frontend to build dynamic filter dropdowns.
    Returns ``[{"name": "Fire Rating", "type": "string"}, ...]``.
    """
    parquet_path = data_root / project_id / model_id / "elements.parquet"
    if not parquet_path.exists():
        return []

    schema = pq.read_schema(parquet_path)
    result: list[dict[str, str]] = []
    for field in schema:
        pa_type = field.type
        if pa.types.is_string(pa_type) or pa.types.is_large_string(pa_type):
            dtype = "string"
        elif pa.types.is_floating(pa_type):
            dtype = "float"
        elif pa.types.is_integer(pa_type):
            dtype = "integer"
        elif pa.types.is_boolean(pa_type):
            dtype = "boolean"
        else:
            dtype = str(pa_type)
        result.append({"name": field.name, "type": dtype})
    return result


# ---------------------------------------------------------------------------
# Query (DuckDB with pyarrow fallback)
# ---------------------------------------------------------------------------

def _validate_column_name(name: str, known_columns: set[str]) -> None:
    """Raise ``ValueError`` if *name* is not in the Parquet schema.

    This prevents SQL injection through the ``column`` field -- values
    are parameterised, but column names must be interpolated.
    """
    if name not in known_columns:
        raise ValueError(f"Unknown column: {name!r}")


def _parquet_columns(parquet_path: Path) -> set[str]:
    """Return the set of column names present in *parquet_path*."""
    return {f.name for f in pq.read_schema(parquet_path)}


def query_parquet(
    project_id: str,
    model_id: str,
    columns: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 10_000,
    data_root: Path = _DATA_ROOT,
) -> list[dict[str, Any]]:
    """Query the Parquet file via DuckDB SQL.

    Args:
        columns: Which columns to ``SELECT``.  ``None`` = all.
        filters: List of filter predicates, each a dict::

            {"column": "Fire Rating", "op": "=", "value": "F90"}

            Supported ops: ``=``, ``!=``, ``>``, ``<``, ``>=``, ``<=``,
            ``LIKE``, ``IN``, ``IS NULL``, ``IS NOT NULL``.
        limit: Maximum rows to return (capped at 50 000 by the router).

    Returns:
        List of dicts (one per matching row).
    """
    parquet_path = data_root / project_id / model_id / "elements.parquet"
    if not parquet_path.exists():
        return []

    try:
        import duckdb  # noqa: F811
    except ImportError:
        logger.info("duckdb not installed -- falling back to pyarrow filter")
        return _fallback_pyarrow_query(parquet_path, columns, filters, limit)

    # Validate column names against the actual schema to prevent injection.
    known = _parquet_columns(parquet_path)
    if columns:
        for c in columns:
            _validate_column_name(c, known)

    select_clause = ", ".join(f'"{c}"' for c in columns) if columns else "*"
    where_clauses: list[str] = []
    params: list[Any] = []

    for f in filters or []:
        col = f["column"]
        _validate_column_name(col, known)
        op = f["op"].upper().strip()
        val = f.get("value")

        if op in _UNARY_OPS:
            where_clauses.append(f'"{col}" {op}')
        elif op == "IN":
            if not isinstance(val, list):
                raise ValueError("IN operator requires a list value")
            placeholders = ", ".join("?" for _ in val)
            where_clauses.append(f'"{col}" IN ({placeholders})')
            params.extend(val)
        elif op in _BINARY_OPS:
            where_clauses.append(f'"{col}" {op} ?')
            params.append(val)
        else:
            raise ValueError(f"Unsupported filter operator: {op!r}")

    where = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = f"SELECT {select_clause} FROM read_parquet(?) WHERE {where} LIMIT ?"
    params = [str(parquet_path), *params, limit]

    conn = duckdb.connect()
    try:
        result = conn.execute(sql, params).fetchall()
        col_names = [desc[0] for desc in conn.description]
        return [dict(zip(col_names, row, strict=False)) for row in result]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Column value counts (filter dropdowns)
# ---------------------------------------------------------------------------

def column_value_counts(
    project_id: str,
    model_id: str,
    column: str,
    limit: int = 100,
    data_root: Path = _DATA_ROOT,
) -> list[dict[str, Any]]:
    """Return value counts for a single column (for filter autocomplete).

    Returns ``[{"value": "F90", "count": 42}, ...]`` sorted by count desc.
    """
    parquet_path = data_root / project_id / model_id / "elements.parquet"
    if not parquet_path.exists():
        return []

    # Validate column name.
    known = _parquet_columns(parquet_path)
    _validate_column_name(column, known)

    try:
        import duckdb

        conn = duckdb.connect()
        try:
            sql = (
                f'SELECT "{column}" AS value, COUNT(*) AS count '
                f"FROM read_parquet(?) "
                f'WHERE "{column}" IS NOT NULL '
                f"GROUP BY \"{column}\" "
                f"ORDER BY count DESC "
                f"LIMIT ?"
            )
            result = conn.execute(sql, [str(parquet_path), limit]).fetchall()
            return [{"value": r[0], "count": r[1]} for r in result]
        finally:
            conn.close()
    except ImportError:
        # Fallback: read just the one column via pyarrow.
        table = pq.read_table(parquet_path, columns=[column])
        col_data = table.column(column).drop_null()
        counts = col_data.value_counts()
        items = counts.to_pylist()
        # pyarrow value_counts returns [{"values": v, "counts": c}, ...]
        out = [{"value": item["values"], "count": item["counts"]} for item in items]
        out.sort(key=lambda x: x["count"], reverse=True)
        return out[:limit]


# ---------------------------------------------------------------------------
# Fallback: pure-pyarrow query (when duckdb is not installed)
# ---------------------------------------------------------------------------

def _fallback_pyarrow_query(
    parquet_path: Path,
    columns: list[str] | None,
    filters: list[dict[str, Any]] | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Row-level filter using pyarrow when duckdb is not installed."""
    table = pq.read_table(parquet_path, columns=columns)
    rows = table.to_pylist()

    if filters:
        for f in filters:
            col, op, val = f["column"], f["op"].upper().strip(), f.get("value")
            if op == "=":
                rows = [r for r in rows if r.get(col) == val]
            elif op == "!=":
                rows = [r for r in rows if r.get(col) != val]
            elif op == ">":
                rows = [r for r in rows if r.get(col) is not None and r[col] > val]
            elif op == "<":
                rows = [r for r in rows if r.get(col) is not None and r[col] < val]
            elif op == ">=":
                rows = [r for r in rows if r.get(col) is not None and r[col] >= val]
            elif op == "<=":
                rows = [r for r in rows if r.get(col) is not None and r[col] <= val]
            elif op == "LIKE":
                pattern = re.escape(val).replace(r"\%", ".*").replace(r"\_", ".")
                rx = re.compile(f"^{pattern}$", re.IGNORECASE)
                rows = [r for r in rows if r.get(col) and rx.search(str(r[col]))]
            elif op == "IN":
                val_set = set(val) if isinstance(val, list) else {val}
                rows = [r for r in rows if r.get(col) in val_set]
            elif op == "IS NOT NULL":
                rows = [r for r in rows if r.get(col) is not None]
            elif op == "IS NULL":
                rows = [r for r in rows if r.get(col) is None]

    return rows[:limit]
