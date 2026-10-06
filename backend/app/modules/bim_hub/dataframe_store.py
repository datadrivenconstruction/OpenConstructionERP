# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, NamedTuple

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


def _data_root() -> Path:
    """Active BIM data root, resolved PER CALL (never bound at import).

    Mirrors :func:`app.modules.bim_hub.service._bim_data_dir`: the path is
    derived from :func:`app.core.storage.resolve_data_dir` (which honours
    ``OE_DATA_DIR`` / ``DATA_DIR`` / ``OE_CLI_DATA_DIR`` before the
    package-relative default), so the Parquet sidecar always lands beside the
    geometry the storage backend wrote -- regardless of the service CWD
    (systemd/launchd run with CWD=``/``) or whether an operator set
    ``OE_DATA_DIR``. Resolving lazily also lets test env overrides take effect.

    WRITES always use this active root; READS may additionally probe the
    back-compat roots via :func:`_existing_parquet_path`.
    """
    from app.core.storage import resolve_data_dir

    return resolve_data_dir() / "bim"


def _existing_parquet_path(
    project_id: str,
    model_id: str,
    data_root: Path | None,
) -> Path | None:
    """Resolve the elements Parquet path, with a read-only back-compat fallback.

    The active root (``data_root`` when given, else :func:`_data_root`) is tried
    first. When the sidecar is absent there, every OTHER platform-owned data
    root (see :func:`app.core.storage.safe_data_roots`) is probed for the same
    ``bim/{project}/{model}/elements.parquet`` key. This is what lets a model
    whose Parquet was written under a DIFFERENT data-dir resolution -- e.g.
    before ``OE_DATA_DIR`` was honoured here, or under the CWD-relative
    ``data/bim`` literal a previous build used -- still serve element tables and
    property filters instead of returning ``[]``.

    Reads fall back; WRITES never do. Containment is re-checked against each
    candidate root with ``relative_to`` so a crafted id can never escape a root.
    Returns ``None`` when the sidecar exists nowhere.
    """
    # ``active`` is the BIM-level root (``<data-dir>/bim``). ``rel_parts`` is the
    # key relative to a BIM-level root, so it must NOT re-prepend "bim".
    active = (data_root if data_root is not None else _data_root()).resolve()
    rel_parts = (project_id, model_id, "elements.parquet")

    def _candidate(base: Path) -> Path | None:
        try:
            cand = base.joinpath(*rel_parts).resolve()
            cand.relative_to(base)
        except (OSError, ValueError):
            return None
        return cand

    primary = _candidate(active)
    if primary is not None and primary.is_file():
        return primary

    from app.core.storage import safe_data_roots

    for root in safe_data_roots():
        # safe_data_roots() entries are data-dir level; the BIM sidecars live
        # under their ``bim/`` subdir.
        try:
            base = (root / "bim").resolve()
        except OSError:
            continue
        if base == active:
            continue
        cand = _candidate(base)
        if cand is not None and cand.is_file():
            logger.info(
                "bim parquet: sidecar for %s/%s absent under active root %s; served from back-compat data root %s",
                project_id,
                model_id,
                active,
                base,
            )
            return cand
    return None


def _json_safe(value: Any) -> Any:
    """Recursively replace NaN / Infinity floats with None.

    Parquet numeric columns can hold NaN or +/-Infinity (e.g. a divide-by-zero
    derived quantity). These are valid Python floats but are NOT valid in
    strict JSON, so they make ``json.dumps(..., allow_nan=False)`` and the
    default FastAPI response encoder raise. Converting them to ``None`` keeps
    the row JSON-serialisable while leaving every finite value untouched.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class ParquetWriteError(RuntimeError):
    """Raised when a Parquet sidecar write fails for a BIM model.

    Wraps the underlying exception so the background ingester can surface
    it in structured form (project_id, model_id, original cause) without
    leaking the bare exception type to callers.  The original exception is
    chained via ``__cause__``.
    """


class DataframeQueryError(ValueError):
    """A property search the store refuses, with a code the client translates.

    The message stays English for logs and API clients; the UI shows its own
    text for ``code`` instead, so a server sentence never reaches a reader in
    another language. ``params`` carries what that text needs (column, op).

    Codes: ``unknown_column``, ``bad_filter``, ``needs_list``,
    ``needs_single_value``, ``needs_number``, ``unsupported_operator``,
    ``query_failed``.
    """

    def __init__(self, code: str, message: str, **params: str) -> None:
        super().__init__(message)
        self.code = code
        self.params = params


# Operators that take no value (unary predicates).
_UNARY_OPS = frozenset({"IS NULL", "IS NOT NULL"})

# Operators that compare text (case-insensitive, trimmed, numeric when both
# sides read as numbers). ``LIKE`` is the property panel's "contains".
_TEXT_OPS = frozenset({"=", "!=", "LIKE", "IN", "NOT IN"})

# Operators that only make sense on numbers.
_NUMERIC_OPS = frozenset({">", "<", ">=", "<="})

# Parquet schema metadata key holding ``{column key: original header text}``.
# DDC Excel headers are lowercased on import (``parse_cad_excel``) because
# every downstream lookup and every saved rule keys on the lowercase name; the
# label map is how the property panel still shows "Phase Created" for the
# column ``phase created``. Sidecars written without it (older models, the
# retry and ensure paths that rebuild rows from the database) fall back to the
# key itself.
_LABELS_METADATA_KEY = b"oe_column_labels"
# Who wrote the rows. Only the database rebuild says so: its rows hold at most
# the 30 properties per element the import keeps, see ``sidecar_state``.
_SOURCE_METADATA_KEY = b"oe_source"
SOURCE_DATABASE = "database"


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_dataframe(
    project_id: str,
    model_id: str,
    rows: list[dict[str, Any]],
    data_root: Path | None = None,
    labels: dict[str, str] | None = None,
    source: str | None = None,
) -> Path:
    """Write a list of element dicts as a Parquet file.

    Each dict is one row (one BIM element).  Keys become columns.
    Missing keys become null.  ZSTD compression, row groups of 50 000.

    ``labels`` maps a column key to the header text the user knows it by
    (``{"phase created": "Phase Created"}``). It is stored in the Parquet
    schema metadata and returned by :func:`read_schema`; keys without a label
    are shown as themselves.

    ``source`` is stored the same way; :data:`SOURCE_DATABASE` marks a sidecar
    rebuilt from the database rows (see :func:`sidecar_state`).

    Returns the path to the written ``.parquet`` file.

    ``data_root`` defaults to the active :func:`_data_root` (resolved lazily).
    WRITES never fall back to a back-compat root.
    """
    if data_root is None:
        data_root = _data_root()
    dest_dir = data_root / project_id / model_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = dest_dir / "elements.parquet"

    # pyarrow.Table.from_pylist infers the schema from the FIRST dict
    # only - keys that appear in later dicts but not the first are
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
    metadata: dict[bytes, bytes] = {}
    if labels:
        kept = {k: str(labels[k]) for k in all_keys if labels.get(k)}
        if kept:
            metadata[_LABELS_METADATA_KEY] = json.dumps(kept, ensure_ascii=False).encode("utf-8")
    if source:
        metadata[_SOURCE_METADATA_KEY] = source.encode("utf-8")
    if metadata:
        schema = schema.with_metadata(metadata)
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


def _column_labels(schema: pa.Schema) -> dict[str, str]:
    """Read the ``{key: label}`` map a sidecar was written with, if any."""
    raw = (schema.metadata or {}).get(_LABELS_METADATA_KEY)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): str(v) for k, v in parsed.items() if isinstance(v, str) and v.strip()}


def read_schema(
    project_id: str,
    model_id: str,
    data_root: Path | None = None,
) -> list[dict[str, str]]:
    """Return column names, Arrow types and display labels from the Parquet schema.

    Used by the frontend to build dynamic filter dropdowns.
    Returns ``[{"name": "fire rating", "type": "string", "label": "Fire Rating"}, ...]``.
    ``name`` is the key every query uses; ``label`` is what the user sees and
    equals ``name`` when the sidecar carries no label for the column.
    """
    parquet_path = _existing_parquet_path(project_id, model_id, data_root)
    if parquet_path is None:
        return []

    schema = pq.read_schema(parquet_path)
    labels = _column_labels(schema)
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
        result.append({"name": field.name, "type": dtype, "label": labels.get(field.name) or field.name})
    return result


# ---------------------------------------------------------------------------
# Query (DuckDB with pyarrow fallback)
# ---------------------------------------------------------------------------
#
# Every sidecar column is text, so each operator states what it does with text
# that came out of a CAD export. Both engines implement the same rules, and
# ``tests/unit/test_bim_dataframe_query_semantics.py`` runs every case on both:
#
# * ``LIKE`` - "contains": case-insensitive substring of the trimmed value.
#   ``%`` and ``_`` typed by the user are literal characters, not wildcards.
# * ``=`` - trimmed, case-insensitive text equality, OR numeric equality when
#   the filter value reads as a number ("8" matches "8.0", "12,5" matches 12.5).
# * ``!=`` - the negation of ``=``, and it INCLUDES elements where the property
#   is empty: "phase is not Progetto" keeps an element with no phase at all.
# * ``>`` ``>=`` ``<`` ``<=`` - numeric, a decimal comma accepted on either
#   side. Text that does not read as a number never matches; a filter value
#   that is not a number is refused.
# * ``IN`` / ``NOT IN`` - ``=`` / ``!=`` against any of the listed values.
# * ``IS NULL`` / ``IS NOT NULL`` - an empty or whitespace-only value is empty.
#
# A decimal comma is read by replacing "," with ".", so "1,234.5" (a thousands
# separator) does not read as a number and simply does not match. A number is
# what DuckDB's ``TRY_CAST(... AS DOUBLE)`` accepts: ASCII digits only, a
# single ``_`` between digits allowed ("1_000"), no hex, no infinity or NaN.
# Padding is the ``_TRIM_CHARS`` set and lower-casing is one character at a
# time (DuckDB's ``lower``), on both engines and on both sides of a compare.
#
# DuckDB is authoritative; the pyarrow fallback agrees with it on every case
# ``tests/unit/test_bim_dataframe_hostile_headers.py`` knows, except the ones
# it lists in ``KNOWN_DIFFERENCES`` ("+-1" reads as -1 in DuckDB only).
#
# Column names are CAD headers, i.e. text the model's author chose. Values bind
# as parameters; names are interpolated, always through ``_quote_ident``.
# DuckDB resolves names case-insensitively and cannot name an empty column, so
# a query touching such a column runs on the pyarrow engine instead.

_TRIM_CHARS = " \t\n\r\x0b\x0c "
_SQL_TRIM_CHARS = "(" + " || ".join(f"chr({ord(c)})" for c in _TRIM_CHARS) + ")"
_NUMBER_RE = re.compile(r"[+-]?([0-9](_?[0-9])*(\.([0-9](_?[0-9])*)?)?|\.[0-9](_?[0-9])*)([eE][+-]?[0-9](_?[0-9])*)?")


def _quote_ident(name: str) -> str:
    """A column name as a DuckDB identifier: wrapped in ``"``, inner ``"`` doubled."""
    return '"' + name.replace('"', '""') + '"'


def _simple_lower(text: str) -> str:
    """Lower-case one character at a time, the way DuckDB's ``lower`` does.

    ``str.lower`` turns "İ" into "i" plus a combining dot and a word-final "Σ"
    into "ς"; DuckDB gives "i" and "σ". The engines must agree, and a value
    picked from the dropdown must find its own cell.
    """
    if text.isascii():
        return text.lower()
    return "".join("i" if ch == "İ" else ch.lower() for ch in text)


def _duckdb_unaddressable(known: set[str]) -> set[str]:
    """Columns DuckDB cannot name exactly: empty, or one of a case-only twin pair."""
    by_fold: dict[str, list[str]] = {}
    for name in known:
        by_fold.setdefault(name.casefold(), []).append(name)
    out = {name for name in known if not name}
    for names in by_fold.values():
        if len(names) > 1:
            out.update(names)
    return out


def _validate_column_name(name: str, known_columns: set[str]) -> None:
    """Raise ``ValueError`` if *name* is not in the Parquet schema.

    A readable 400 instead of a DuckDB binder error. It is NOT what keeps SQL
    out of the query: a known column is still a CAD header the model's author
    wrote, and ``_quote_ident`` is what makes it safe to interpolate.
    """
    if name not in known_columns:
        raise DataframeQueryError(
            "unknown_column", f"Unknown column: {name!r}. The model has no property with that name.", column=name
        )


def _parquet_columns(parquet_path: Path) -> set[str]:
    """Return the set of column names present in *parquet_path*."""
    return {f.name for f in pq.read_schema(parquet_path)}


def _as_text(value: Any) -> str | None:
    """Trimmed, lowercased text of a cell or filter value; ``None`` when empty."""
    if value is None:
        return None
    text = _simple_lower(str(value).strip(_TRIM_CHARS))
    return text or None


def _as_number(value: Any) -> float | None:
    """Read a cell or filter value as a finite number, accepting a decimal comma."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip(_TRIM_CHARS).replace(",", ".")
        if not text or not _NUMBER_RE.fullmatch(text):
            return None
        number = float(text.replace("_", ""))
    return number if math.isfinite(number) else None


def _escape_like(text: str) -> str:
    """Escape ``\\``, ``%`` and ``_`` so they are literal inside a LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class _ReadValue(NamedTuple):
    """An ``=`` / ``!=`` value whose number the client has already read.

    The panel reads typed numbers in the user's convention ("1.500" is 1500 in
    Italian) and sends that reading as ``number`` beside the text. The text
    then matches as text only and is never read as a number here, dot-decimal;
    ``number`` is ``None`` when the text is no number.
    """

    text: Any
    number: float | None


def _client_number(raw: Any, op: str) -> float | None:
    """The ``number`` of an ``=`` / ``!=`` filter: a finite JSON number, or null."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise DataframeQueryError("needs_number", f"The {op} filter's number must be a number, got {raw!r}.", op=op)
    return float(raw)


def _normalise_filters(filters: list[dict[str, Any]] | None, known: set[str]) -> list[tuple[str, str, Any]]:
    """Validate every filter and return ``(column, op, value)`` triples."""
    out: list[tuple[str, str, Any]] = []
    for f in filters or []:
        if not isinstance(f, dict) or "column" not in f or "op" not in f:
            raise DataframeQueryError("bad_filter", "Each filter needs a column and an operator.")
        col = str(f["column"])
        _validate_column_name(col, known)
        op = str(f["op"]).upper().strip()
        val = f.get("value")
        if op in _UNARY_OPS:
            out.append((col, op, None))
        elif op in ("IN", "NOT IN"):
            if not isinstance(val, list):
                raise DataframeQueryError("needs_list", f"The {op} operator needs a list of values.", op=op)
            out.append((col, op, val))
        elif op in _TEXT_OPS:
            if val is None or isinstance(val, (list, dict)):
                raise DataframeQueryError("needs_single_value", f"The {op} operator needs a single value.", op=op)
            if op in ("=", "!=") and "number" in f:
                out.append((col, op, _ReadValue(val, _client_number(f["number"], op))))
            else:
                out.append((col, op, val))
        elif op in _NUMERIC_OPS:
            if _as_number(val) is None:
                raise DataframeQueryError("needs_number", f"The {op} operator needs a number, got {val!r}.", op=op)
            out.append((col, op, val))
        else:
            raise DataframeQueryError("unsupported_operator", f"Unsupported filter operator: {op!r}", op=op)
    return out


# ── DuckDB ────────────────────────────────────────────────────────────────


def _sql_trimmed(expr: str) -> str:
    return f"trim({expr}, {_SQL_TRIM_CHARS})"


def _sql_text(col: str) -> str:
    return f"NULLIF(lower({_sql_trimmed(f'CAST({_quote_ident(col)} AS VARCHAR)')}), '')"


def _sql_number(col: str) -> str:
    # ``isfinite`` keeps a literal "nan"/"inf" cell out of numeric comparisons,
    # matching ``_as_number`` (DuckDB sorts NaN above every number otherwise).
    raw = f"TRY_CAST(replace({_sql_trimmed(f'CAST({_quote_ident(col)} AS VARCHAR)')}, ',', '.') AS DOUBLE)"
    return f"(CASE WHEN isfinite({raw}) THEN {raw} END)"


def _equals_operands(value: Any) -> tuple[Any, str | None, float | None]:
    """The raw text, its match form and the number an ``=`` value compares by.

    Both engines take their operands from here. A :class:`_ReadValue` brings
    its number from the client; any other value is read here, as before.
    """
    if isinstance(value, _ReadValue):
        return value.text, _as_text(value.text), value.number
    return value, _as_text(value), _as_number(value)


def _sql_equals(col: str, value: Any, params: list[Any]) -> str:
    """SQL for the ``=`` rule, appending its parameters to *params*."""
    raw, text, number = _equals_operands(value)
    clauses: list[str] = []
    if text is not None:
        # DuckDB lowers the value too, so a cell and the same text typed or
        # picked from the dropdown always lower the same way.
        clauses.append(f"{_sql_text(col)} = lower({_sql_trimmed('?')})")
        params.append(str(raw))
    if number is not None:
        clauses.append(f"{_sql_number(col)} = ?")
        params.append(number)
    if not clauses:
        return "FALSE"
    return "(" + " OR ".join(clauses) + ")"


def _sql_predicate(col: str, op: str, val: Any, params: list[Any]) -> str:
    if op == "IS NULL":
        return f"{_sql_text(col)} IS NULL"
    if op == "IS NOT NULL":
        return f"{_sql_text(col)} IS NOT NULL"
    if op == "LIKE":
        # Escaping is unaffected by lower-casing, so DuckDB may lower the pattern.
        params.append("%" + _escape_like(str(val).strip(_TRIM_CHARS)) + "%")
        return f"{_sql_text(col)} LIKE lower(?) ESCAPE '\\'"
    if op == "=":
        return f"coalesce({_sql_equals(col, val, params)}, FALSE)"
    if op == "!=":
        return f"NOT coalesce({_sql_equals(col, val, params)}, FALSE)"
    if op in ("IN", "NOT IN"):
        parts = [_sql_equals(col, v, params) for v in val] or ["FALSE"]
        any_of = "coalesce(" + " OR ".join(parts) + ", FALSE)"
        return any_of if op == "IN" else f"NOT {any_of}"
    # Numeric comparators, value already validated as a number.
    params.append(_as_number(val))
    return f"{_sql_number(col)} {op} ?"


def _duckdb_error_message(exc: Exception) -> str:
    first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return f"The property search could not run: {first}"


def _duckdb_query(
    duckdb: Any,
    parquet_path: Path,
    columns: list[str] | None,
    filters: list[tuple[str, str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    select_clause = ", ".join(_quote_ident(c) for c in columns) if columns else "*"
    params: list[Any] = []
    where_clauses = [_sql_predicate(col, op, val, params) for col, op, val in filters]
    where = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = f"SELECT {select_clause} FROM read_parquet(?) WHERE {where} LIMIT ?"

    conn = duckdb.connect()
    try:
        try:
            result = conn.execute(sql, [str(parquet_path), *params, limit]).fetchall()
        except duckdb.Error as exc:
            raise DataframeQueryError("query_failed", _duckdb_error_message(exc)) from exc
        col_names = [desc[0] for desc in conn.description]
        return [_json_safe(dict(zip(col_names, row, strict=False))) for row in result]
    finally:
        conn.close()


# ── Shared row predicate (pyarrow fallback) ───────────────────────────────


def _row_equals(cell: Any, value: Any) -> bool:
    _raw, text, number = _equals_operands(value)
    if text is not None and _as_text(cell) == text:
        return True
    return number is not None and _as_number(cell) == number


def _row_matches(cell: Any, op: str, val: Any) -> bool:  # noqa: PLR0911 - one branch per operator
    if op == "IS NULL":
        return _as_text(cell) is None
    if op == "IS NOT NULL":
        return _as_text(cell) is not None
    if op == "LIKE":
        text = _as_text(cell)
        return text is not None and (_as_text(val) or "") in text
    if op == "=":
        return _row_equals(cell, val)
    if op == "!=":
        return not _row_equals(cell, val)
    if op == "IN":
        return any(_row_equals(cell, v) for v in val)
    if op == "NOT IN":
        return not any(_row_equals(cell, v) for v in val)
    number = _as_number(cell)
    target = _as_number(val)
    if number is None or target is None:
        return False
    if op == ">":
        return number > target
    if op == "<":
        return number < target
    if op == ">=":
        return number >= target
    return number <= target


def _fallback_pyarrow_query(
    parquet_path: Path,
    columns: list[str] | None,
    filters: list[tuple[str, str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    """Row-level filter using pyarrow when duckdb is not installed.

    Reads the selected columns PLUS every filtered column (a filter on a column
    the caller did not select must still see its values), filters with the same
    rules as the DuckDB path, then projects back to the selection.
    """
    read_cols: list[str] | None = None
    if columns:
        read_cols = list(dict.fromkeys([*columns, *(col for col, _op, _val in filters)]))
    rows = pq.read_table(parquet_path, columns=read_cols).to_pylist()

    out: list[dict[str, Any]] = []
    for row in rows:
        if all(_row_matches(row.get(col), op, val) for col, op, val in filters):
            out.append({c: row.get(c) for c in columns} if columns else row)
            if len(out) >= limit:
                break
    return [_json_safe(r) for r in out]


def query_parquet(
    project_id: str,
    model_id: str,
    columns: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    limit: int = 10_000,
    data_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Query the Parquet file via DuckDB SQL (pyarrow when DuckDB is missing).

    Args:
        columns: Which columns to ``SELECT``.  ``None`` = all.
        filters: List of filter predicates, each a dict::

            {"column": "fire rating", "op": "=", "value": "F90"}

            Supported ops: ``=``, ``!=``, ``>``, ``<``, ``>=``, ``<=``,
            ``LIKE`` (contains), ``IN``, ``NOT IN``, ``IS NULL``,
            ``IS NOT NULL``. See the operator rules above.
        limit: Maximum rows to return (capped at 50 000 by the router).

    Returns:
        List of dicts (one per matching row).

    Raises:
        ValueError: unknown column, unsupported operator, a value the operator
            cannot use, or a query DuckDB refuses. The message is readable and
            the router returns it as a 400.
    """
    parquet_path = _existing_parquet_path(project_id, model_id, data_root)
    if parquet_path is None:
        return []

    # Validate column names against the actual schema to prevent injection.
    known = _parquet_columns(parquet_path)
    if columns:
        for c in columns:
            _validate_column_name(c, known)
    normalised = _normalise_filters(filters, known)

    unaddressable = _duckdb_unaddressable(known)
    touched = set(columns) if columns else known
    touched |= {col for col, _op, _val in normalised}
    if touched & unaddressable:
        return _fallback_pyarrow_query(parquet_path, columns, normalised, limit)

    try:
        import duckdb  # noqa: F811
    except ImportError:
        logger.info("duckdb not installed -- falling back to pyarrow filter")
        return _fallback_pyarrow_query(parquet_path, columns, normalised, limit)

    return _duckdb_query(duckdb, parquet_path, columns, normalised, limit)


# ---------------------------------------------------------------------------
# Column value counts (filter dropdowns)
# ---------------------------------------------------------------------------


def column_value_counts(
    project_id: str,
    model_id: str,
    column: str,
    limit: int = 100,
    data_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Compatibility adapter for the original path-based value endpoint."""
    return column_value_counts_page(project_id, model_id, column, limit, data_root)["items"]


def column_value_counts_page(
    project_id: str,
    model_id: str,
    column: str,
    limit: int = 100,
    data_root: Path | None = None,
    *,
    offset: int = 0,
) -> dict[str, Any]:
    """Return value counts for a single column (for filter autocomplete).

    Returns ``[{"value": "F90", "count": 42}, ...]`` sorted by count desc,
    then by value, so both engines list ties in the same order. Empty values
    are left out.
    """
    if limit < 1 or limit > 1000 or offset < 0:
        raise ValueError("limit must be between 1 and 1000 and offset must be nonnegative")

    def page(items: list[dict[str, Any]], total: int) -> dict[str, Any]:
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    parquet_path = _existing_parquet_path(project_id, model_id, data_root)
    if parquet_path is None:
        return page([], 0)

    # Validate column name.
    known = _parquet_columns(parquet_path)
    _validate_column_name(column, known)

    try:
        import duckdb
    except ImportError:
        duckdb = None

    if duckdb is not None and column not in _duckdb_unaddressable(known):
        conn = duckdb.connect()
        try:
            sql = (
                f"SELECT CAST({_quote_ident(column)} AS VARCHAR) AS value, COUNT(*) AS count "
                f"FROM read_parquet(?) "
                f"WHERE {_sql_text(column)} IS NOT NULL "
                f"GROUP BY 1 "
                f"ORDER BY count DESC, value ASC "
            )
            try:
                total = conn.execute(f"SELECT COUNT(*) FROM ({sql}) AS grouped", [str(parquet_path)]).fetchone()[0]
                result = conn.execute(sql + " LIMIT ? OFFSET ?", [str(parquet_path), limit, offset]).fetchall()
            except duckdb.Error as exc:
                raise DataframeQueryError("query_failed", _duckdb_error_message(exc)) from exc
            return page([{"value": r[0], "count": r[1]} for r in result], total)
        finally:
            conn.close()

    # Fallback: read just the one column via pyarrow.
    counts: dict[str, int] = {}
    for cell in pq.read_table(parquet_path, columns=[column]).column(column).to_pylist():
        if _as_text(cell) is None:
            continue
        key = str(cell)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return page([{"value": v, "count": c} for v, c in ordered[offset : offset + limit]], len(ordered))


# ---------------------------------------------------------------------------
# A few cells for the rule engine
# ---------------------------------------------------------------------------

# Same names, same order as ``PARQUET_ID_COLUMNS`` in
# frontend/src/features/bim/propertySearch.ts. ``stable_id`` comes last: a
# sidecar rebuilt by the Parquet retry carries no other id.
_ID_COLUMNS = ("id", "Id", "ID", "ElementId", "Element ID", "element_id", "stable_id")


def sidecar_state(project_id: str, model_id: str, data_root: Path | None = None) -> str:
    """Whether a model's sidecar still holds the properties the import capped.

    ``"full"``: written by the converter, every column is there.
    ``"rebuilt"``: written from the database rows (the Parquet retry, or the
    backfill for a model without one), so a property the import's
    30-per-element cap left out is gone until a re-import. Such a sidecar
    carries :data:`SOURCE_DATABASE`; an older one is told by its columns, as
    the retry used to write ``stable_id`` and no other id.
    ``"missing"``: no sidecar at all.
    """
    path = _existing_parquet_path(project_id, model_id, data_root)
    if path is None:
        return "missing"
    try:
        schema = pq.read_schema(path)
    except (OSError, pa.ArrowException):
        return "missing"
    if (schema.metadata or {}).get(_SOURCE_METADATA_KEY) == SOURCE_DATABASE.encode("utf-8"):
        return "rebuilt"
    names = set(schema.names)
    if "stable_id" in names and not names.intersection(_ID_COLUMNS[:-1]):
        return "rebuilt"
    return "full"


def _resolve_column(key: str, names: list[str]) -> str | None:
    """*key* as a column name the way rule keys resolve: exact, then trimmed and case-insensitive."""
    if key in names:
        return key
    wanted = key.strip().lower()
    return next((name for name in names if name.strip().lower() == wanted), None)


def read_element_cells(
    project_id: str,
    model_id: str,
    keys: list[str],
    ids: list[str],
    data_root: Path | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Cells of a few property columns for a few elements, for the rule engine.

    An element row in the database keeps at most 30 properties (the import caps
    them); the sidecar keeps every column. A quantity rule or a dynamic group
    naming a property the cap dropped reads it back from here.

    Keys resolve the way rule keys do (``smart_views._lookup_key``): the exact
    column name first, then trimmed and case-insensitive. Only the id column
    and the resolved columns are read, and only rows whose trimmed id is in
    *ids* come back, so the cost is bounded by what the caller asks for.

    Returns ``(columns, cells)``: ``columns`` maps each key that resolved to
    its column, ``cells`` maps a row id to ``{column: value}``. Both are empty
    when the model has no sidecar or the sidecar has no id column. A sidecar
    that cannot be read is logged and treated as absent: it is a second
    source, never a reason for a rule run to fail.
    """
    parquet_path = _existing_parquet_path(project_id, model_id, data_root)
    if parquet_path is None or not keys or not ids:
        return {}, {}
    try:
        names = list(pq.read_schema(parquet_path).names)
        id_column = next((c for c in _ID_COLUMNS if c in names), None)
        if id_column is None:
            return {}, {}
        columns: dict[str, str] = {}
        for key in keys:
            column = _resolve_column(key, names)
            if column is not None and column != id_column:
                columns[key] = column
        if not columns:
            return {}, {}
        read = list(dict.fromkeys(columns.values()))
        table = pq.read_table(parquet_path, columns=[id_column, *read])
        row_ids = pc.utf8_trim_whitespace(pc.cast(table.column(id_column), pa.string()))
        wanted = pa.array(sorted({str(i).strip() for i in ids}), type=pa.string())
        rows = table.filter(pc.is_in(row_ids, value_set=wanted)).to_pylist()
    except (OSError, pa.ArrowException) as exc:
        logger.warning("bim parquet: could not read cells from %s: %s", parquet_path, exc)
        return {}, {}
    cells: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_id = str(row.pop(id_column)).strip()
        cells.setdefault(row_id, row)
    return columns, cells
