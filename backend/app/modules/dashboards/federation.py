# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Multi-Source Project Federation (T10 / task #193).

Federation lets a single dashboard query span N snapshots — one or more
per project — and aggregate rows across all of them while preserving the
``project_id`` + ``snapshot_id`` provenance on every row.

Wire shape
----------
The router endpoints take ``snapshot_ids: list[str]`` plus an optional
``schema_align`` mode and either:

* :func:`build_federated_view` — register a ``UNION ALL`` view across
  the snapshots' Parquet files inside an isolated DuckDB connection,
  return a :class:`FederatedView` handle (view name + merged schema).
* :func:`federated_query` — run a whitelisted SELECT over the
  pre-built view.
* :func:`federated_aggregate` — high-level rollup helper (no raw SQL),
  typically what the UI calls.

Schema alignment
----------------
``schema_align`` controls how heterogeneous snapshot schemas are
combined into one view:

* ``"intersect"`` — keep only columns common to *every* snapshot.
* ``"union"``     — keep all columns; SELECT NULL for any snapshot
                    that lacks a given column.
* ``"strict"``    — fail with :class:`SchemaMismatchError` (422) if any
                    snapshot's schema disagrees with the others.

Every output view always carries two extra columns:

* ``__project_id``  — the snapshot's owning project (UUID string)
* ``__snapshot_id`` — the snapshot id (UUID string)

These are reserved names — federated SQL must not declare them in
SELECT lists; they're added on the federation side so the user can
drill back to source.

SQL whitelist
-------------
:func:`federated_query` enforces a defence-in-depth SQL whitelist:

* the trimmed statement must start with ``SELECT`` or ``WITH``
* no semicolons (single-statement only)
* a curated denylist of risky keywords (``ATTACH``, ``INSTALL``,
  ``COPY INTO``, ``LOAD``, ``DROP``, ``CREATE``, ``DELETE``, ``INSERT``,
  ``UPDATE``, ``CALL``, ``PRAGMA``, ``EXPORT``, ``SET ``)

This is intentionally conservative — it's complementary to DuckDB's
parameter binding, not a replacement.

DuckDB usage
------------
Federation does *not* reuse :class:`~app.modules.dashboards.duckdb_pool.DuckDBPool`
because the pool keys connections by single ``snapshot_id`` and pins one
view named ``entities`` per connection. A federated view spans many
snapshots and lives only for the duration of the enclosing request, so
we open a fresh in-memory connection per :func:`build_federated_view`
call and tear it down with :meth:`FederatedView.close`.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.modules.dashboards.snapshot_storage import resolve_local_parquet_path

if TYPE_CHECKING:
    import duckdb

logger = logging.getLogger(__name__)


# ── Public types ────────────────────────────────────────────────────────────


SchemaAlignMode = Literal["intersect", "union", "strict"]
"""How to reconcile heterogeneous snapshot schemas across a federation."""


PROVENANCE_PROJECT_COL = "__project_id"
"""Reserved provenance column carrying the source snapshot's project id.

Underscored prefix mirrors DuckDB's convention for system/internal
columns and keeps the federation columns from colliding with user
columns whose names happen to be ``project_id``."""

PROVENANCE_SNAPSHOT_COL = "__snapshot_id"
"""Reserved provenance column carrying the source snapshot's id."""

_RESERVED_PROVENANCE_COLUMNS: frozenset[str] = frozenset(
    {PROVENANCE_PROJECT_COL, PROVENANCE_SNAPSHOT_COL},
)


_VIEW_NAME_PREFIX = "federated_"
"""Prefix of the dynamically-generated DuckDB view name. Each view ends
with a UUID4 hex so concurrent federations on the same connection can't
collide. The connection itself is per-call so the suffix is mostly a
defensive measure."""


_MAX_SNAPSHOTS = 32
"""Hard cap on the number of snapshots per federation. The UNION ALL
SQL grows linearly with this — beyond 32 the request is almost
certainly malformed."""


@dataclass(frozen=True)
class FederatedSnapshotRef:
    """Identifies one snapshot inside a federation request."""

    snapshot_id: str
    project_id: str


@dataclass
class FederatedView:
    """Handle to a federated UNION ALL view.

    The DuckDB connection is bound to this view; closing the view also
    closes the connection so callers don't have to track both.
    Designed for the **per-request** lifecycle: build → query / aggregate
    → close. Federation is not pooled because schema-alignment, view
    construction and column reconciliation make a long-lived warm cache
    not worth the complexity for the v1 cut.
    """

    view_name: str
    columns: list[str]
    """Column names exposed by the federated view, in the order they
    appear in the underlying SELECT (provenance columns last)."""
    dtypes: dict[str, str]
    """Resolved DuckDB type per column. Best-effort — for ``"union"``
    mode we surface the dtype that the *first* snapshot reported for
    that column; columns that conflict surface as ``"VARCHAR"``."""
    snapshots: list[FederatedSnapshotRef] = field(default_factory=list)
    project_count: int = 0
    snapshot_count: int = 0
    row_count: int = 0
    schema_align: SchemaAlignMode = "intersect"
    _conn: Any | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "view_name": self.view_name,
            "columns": list(self.columns),
            "dtypes": dict(self.dtypes),
            "project_count": self.project_count,
            "snapshot_count": self.snapshot_count,
            "row_count": self.row_count,
            "schema_align": self.schema_align,
            "snapshots": [
                {"snapshot_id": s.snapshot_id, "project_id": s.project_id}
                for s in self.snapshots
            ],
        }

    async def close(self) -> None:
        """Close the underlying DuckDB connection. Idempotent."""
        if self._closed or self._conn is None:
            self._closed = True
            return
        try:
            await asyncio.to_thread(self._conn.close)
        except Exception as exc:  # pragma: no cover — last-ditch
            logger.warning(
                "federation.close failed view=%s: %s",
                self.view_name, type(exc).__name__,
            )
        self._closed = True


# ── Errors ──────────────────────────────────────────────────────────────────


class FederationError(RuntimeError):
    """Base class for federation-level failures. The router converts
    these into HTTP status codes."""

    http_status: int = 500
    message_key: str = "common.unknown_error"


class EmptySnapshotListError(FederationError):
    """Raised when the snapshot id list is empty."""

    http_status = 422
    message_key = "federation.snapshot_ids.empty"


class TooManySnapshotsError(FederationError):
    """Raised when more than :data:`_MAX_SNAPSHOTS` snapshots are passed."""

    http_status = 422
    message_key = "federation.snapshot_ids.too_many"


class SchemaMismatchError(FederationError):
    """Raised under ``schema_align="strict"`` when columns don't match."""

    http_status = 422
    message_key = "federation.schema.mismatch"


class FederationSqlError(FederationError):
    """Raised when a user-supplied SQL fails the whitelist."""

    http_status = 422
    message_key = "federation.sql.rejected"


class FederationParquetError(FederationError):
    """Raised when one of the snapshot's parquet files cannot be opened."""

    http_status = 404
    message_key = "snapshot.parquet.missing_entities"


# ── Validation helpers ─────────────────────────────────────────────────────


_VALID_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
)


def _validate_snapshot_ids(snapshot_ids: list[str]) -> list[str]:
    """Coerce input into a clean list of UUID strings."""
    if not snapshot_ids:
        raise EmptySnapshotListError("snapshot_ids must not be empty")
    cleaned: list[str] = []
    for raw in snapshot_ids:
        s = str(raw or "").strip()
        if not s or not _VALID_UUID_RE.match(s):
            raise EmptySnapshotListError(
                f"Invalid snapshot id: {raw!r}",
            )
        cleaned.append(s)
    if len(cleaned) > _MAX_SNAPSHOTS:
        raise TooManySnapshotsError(
            f"At most {_MAX_SNAPSHOTS} snapshots per federation "
            f"(got {len(cleaned)})",
        )
    return cleaned


# ── SQL whitelist ──────────────────────────────────────────────────────────


# Tokens that must NOT appear anywhere in a federated SQL — even inside a
# CTE or a sub-SELECT. We compile them as word-boundary regexes so harmless
# substrings (e.g. ``copy_id``) don't trip the filter.
_DENY_TOKENS: tuple[str, ...] = (
    "ATTACH",
    "DETACH",
    "INSTALL",
    "LOAD",
    "DROP",
    "CREATE",
    "DELETE",
    "INSERT",
    "UPDATE",
    "ALTER",
    "MERGE",
    "TRUNCATE",
    "GRANT",
    "REVOKE",
    "CALL",
    "PRAGMA",
    "EXPORT",
    "IMPORT",
    "VACUUM",
    "COPY",
    "USE",
)
_DENY_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _DENY_TOKENS) + r")\b",
    re.IGNORECASE,
)
_SET_RE = re.compile(r"^\s*SET\b", re.IGNORECASE | re.MULTILINE)


def _strip_comments(sql: str) -> str:
    """Remove ``-- ...`` and ``/* ... */`` comments before whitelist checks."""
    # Block comments first (greedy across lines).
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Then line comments.
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line


def _enforce_select_only(sql: str) -> None:
    """Validate that ``sql`` is a single SELECT/WITH statement.

    Raises :class:`FederationSqlError` on any whitelist violation.
    """
    if not sql or not sql.strip():
        raise FederationSqlError("SQL must not be empty")
    cleaned = _strip_comments(sql)
    # No multi-statement payloads. ``;`` at the very end is tolerated
    # because DuckDB's parser strips the trailing semicolon either way.
    if ";" in cleaned.strip().rstrip(";"):
        raise FederationSqlError("Multiple statements are not allowed")
    head = cleaned.lstrip()
    head_token = head.split(None, 1)[0].upper() if head else ""
    if head_token not in {"SELECT", "WITH"}:
        raise FederationSqlError(
            "Federated SQL must start with SELECT or WITH",
        )
    if _DENY_RE.search(cleaned):
        raise FederationSqlError(
            "SQL contains a disallowed keyword (DDL/DML/admin)",
        )
    if _SET_RE.search(cleaned):
        raise FederationSqlError("SQL contains a disallowed SET clause")


# ── Identifier sanitisation ────────────────────────────────────────────────


_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


def _is_safe_identifier(name: str) -> bool:
    """A column/identifier we're willing to splice into raw SQL.

    Anything not matching :data:`_IDENT_RE` is rejected — callers must
    pass it as a parameter instead.
    """
    return bool(_IDENT_RE.match(name or ""))


def _quote_ident(name: str) -> str:
    if not _is_safe_identifier(name):
        raise FederationSqlError(f"Unsafe identifier: {name!r}")
    return f'"{name}"'


# ── Schema introspection ───────────────────────────────────────────────────


async def _read_snapshot_schema(
    project_id: str, snapshot_id: str,
) -> tuple[str, list[tuple[str, str]]]:
    """Return ``(parquet_path, [(col_name, col_dtype), ...])`` for a snapshot.

    The dtype list is read with pyarrow so we don't depend on a live
    DuckDB connection here. If the parquet is missing or unreadable we
    raise :class:`FederationParquetError`.
    """
    try:
        path = await resolve_local_parquet_path(
            project_id, snapshot_id, "entities",
        )
    except FileNotFoundError as exc:
        raise FederationParquetError(
            f"Snapshot {snapshot_id} has no entities parquet",
        ) from exc

    def _read() -> list[tuple[str, str]]:
        import pyarrow.parquet as pq

        schema = pq.read_schema(path)
        return [(f.name, str(f.type)) for f in schema]

    try:
        cols = await asyncio.to_thread(_read)
    except FederationError:
        raise
    except Exception as exc:
        raise FederationParquetError(
            f"Could not read schema for snapshot {snapshot_id}: {exc}",
        ) from exc
    return path, cols


def _resolve_columns(
    per_snapshot: list[list[tuple[str, str]]],
    *,
    schema_align: SchemaAlignMode,
) -> tuple[list[str], dict[str, str]]:
    """Reconcile per-snapshot column lists into a single column set.

    Returns ``(ordered_columns, dtypes)``. Provenance columns are NOT
    added here — the caller appends them after this resolution.
    """
    if not per_snapshot:
        return [], {}

    name_to_dtype: list[dict[str, str]] = [
        {col: dtype for col, dtype in cols if col not in _RESERVED_PROVENANCE_COLUMNS}
        for cols in per_snapshot
    ]
    name_sets: list[set[str]] = [set(d.keys()) for d in name_to_dtype]

    if schema_align == "strict":
        first = name_sets[0]
        for idx, ns in enumerate(name_sets[1:], start=1):
            if ns != first:
                missing = sorted(first - ns)
                extra = sorted(ns - first)
                raise SchemaMismatchError(
                    f"Snapshot #{idx} schema differs from snapshot #0 — "
                    f"missing={missing!r}, extra={extra!r}",
                )
        ordered = [c for c, _ in per_snapshot[0] if c not in _RESERVED_PROVENANCE_COLUMNS]
        dtypes = dict(name_to_dtype[0])
        return ordered, dtypes

    if schema_align == "intersect":
        common = name_sets[0].copy()
        for ns in name_sets[1:]:
            common &= ns
        # Preserve first-snapshot's column order so users see a stable
        # layout regardless of how many later snapshots they pile on.
        ordered = [
            c for c, _ in per_snapshot[0]
            if c in common and c not in _RESERVED_PROVENANCE_COLUMNS
        ]
        dtypes = {c: name_to_dtype[0][c] for c in ordered}
        return ordered, dtypes

    if schema_align == "union":
        seen: list[str] = []
        seen_set: set[str] = set()
        for cols in per_snapshot:
            for c, _ in cols:
                if c in _RESERVED_PROVENANCE_COLUMNS:
                    continue
                if c not in seen_set:
                    seen.append(c)
                    seen_set.add(c)
        # For dtype: take the first snapshot that reports the column;
        # if any other snapshot reports a *different* dtype, fall back
        # to VARCHAR so the union is monotonically representable.
        union_dtypes: dict[str, str] = {}
        for c in seen:
            chosen: str | None = None
            for d in name_to_dtype:
                if c in d:
                    if chosen is None:
                        chosen = d[c]
                    elif d[c] != chosen:
                        chosen = "VARCHAR"
                        break
            union_dtypes[c] = chosen or "VARCHAR"
        return seen, union_dtypes

    raise FederationSqlError(f"Unknown schema_align mode: {schema_align!r}")


# ── DuckDB connection helper ───────────────────────────────────────────────


async def _open_isolated_connection() -> duckdb.DuckDBPyConnection:
    """Open a fresh in-memory DuckDB connection. Used per-federation so
    the lifecycle is bounded by :class:`FederatedView`."""
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover — base dep after v2.5.0
        raise FederationError(
            "DuckDB is required for federated dashboards.",
        ) from exc

    def _connect() -> duckdb.DuckDBPyConnection:
        return duckdb.connect(":memory:", read_only=False)

    return await asyncio.to_thread(_connect)


# ── Public entry points ────────────────────────────────────────────────────


async def build_federated_view(
    snapshot_ids: list[str],
    *,
    project_id_for: dict[str, str] | None = None,
    schema_align: SchemaAlignMode = "intersect",
) -> FederatedView:
    """Construct a federated UNION ALL view across ``snapshot_ids``.

    Parameters
    ----------
    snapshot_ids
        The snapshots to federate. Order is preserved in the resulting
        view.
    project_id_for
        Map of ``snapshot_id -> project_id``. Required: the federation
        cannot derive a project from a snapshot_id alone (the snapshot
        registry lives in a SQL DB; this module is purposely DuckDB-only).
        The router supplies this map after looking up each snapshot
        through :class:`SnapshotRepository`.
    schema_align
        See :data:`SchemaAlignMode`.

    Returns
    -------
    :class:`FederatedView`
        A handle exposing the view name + reconciled schema. Caller MUST
        call :meth:`FederatedView.close` (or use ``async with`` if they
        wrap it) to release the underlying DuckDB connection.

    Raises
    ------
    EmptySnapshotListError
        If ``snapshot_ids`` is empty.
    TooManySnapshotsError
        If more than 32 snapshots are passed.
    FederationParquetError
        If any snapshot's entities parquet is missing.
    SchemaMismatchError
        Under ``"strict"`` alignment when schemas disagree.
    """
    cleaned_ids = _validate_snapshot_ids(snapshot_ids)
    project_id_for = project_id_for or {}

    refs: list[FederatedSnapshotRef] = []
    for sid in cleaned_ids:
        pid = project_id_for.get(sid)
        if not pid or not _VALID_UUID_RE.match(str(pid)):
            raise EmptySnapshotListError(
                f"Missing or invalid project_id for snapshot {sid}",
            )
        refs.append(FederatedSnapshotRef(snapshot_id=sid, project_id=str(pid)))

    # Probe schemas (and validate parquet presence) up front.
    per_snapshot: list[list[tuple[str, str]]] = []
    paths: list[str] = []
    for ref in refs:
        path, cols = await _read_snapshot_schema(ref.project_id, ref.snapshot_id)
        per_snapshot.append(cols)
        paths.append(path)

    columns, dtypes = _resolve_columns(per_snapshot, schema_align=schema_align)

    # Append provenance columns last — same position in every part of
    # the UNION so the column order matches across legs.
    final_columns = [*columns, PROVENANCE_PROJECT_COL, PROVENANCE_SNAPSHOT_COL]
    final_dtypes = {**dtypes, PROVENANCE_PROJECT_COL: "VARCHAR", PROVENANCE_SNAPSHOT_COL: "VARCHAR"}

    conn = await _open_isolated_connection()

    view_name = f"{_VIEW_NAME_PREFIX}{uuid.uuid4().hex}"
    union_sql = _compose_union_sql(
        view_name=view_name,
        refs=refs,
        paths=paths,
        per_snapshot_cols=per_snapshot,
        resolved_columns=columns,
        schema_align=schema_align,
    )

    try:
        await asyncio.to_thread(conn.execute, union_sql)
    except Exception as exc:
        # Tear down the orphan connection on failure.
        try:
            await asyncio.to_thread(conn.close)
        except Exception:  # pragma: no cover
            pass
        raise FederationError(
            f"Failed to register federated view: {exc}",
        ) from exc

    # Row-count probe — small enough query that it's worth doing eagerly
    # so the response payload can include the headline number without a
    # follow-up round-trip.
    try:
        rows = await asyncio.to_thread(
            lambda: conn.execute(
                f'SELECT COUNT(*) FROM "{view_name}"',
            ).fetchall(),
        )
        row_count = int(rows[0][0]) if rows else 0
    except Exception as exc:
        try:
            await asyncio.to_thread(conn.close)
        except Exception:  # pragma: no cover
            pass
        raise FederationError(
            f"Failed to count federated rows: {exc}",
        ) from exc

    project_count = len({ref.project_id for ref in refs})

    return FederatedView(
        view_name=view_name,
        columns=final_columns,
        dtypes=final_dtypes,
        snapshots=refs,
        project_count=project_count,
        snapshot_count=len(refs),
        row_count=row_count,
        schema_align=schema_align,
        _conn=conn,
    )


def _compose_union_sql(
    *,
    view_name: str,
    refs: list[FederatedSnapshotRef],
    paths: list[str],
    per_snapshot_cols: list[list[tuple[str, str]]],
    resolved_columns: list[str],
    schema_align: SchemaAlignMode,
) -> str:
    """Build the ``CREATE OR REPLACE VIEW … AS SELECT … UNION ALL …`` text.

    Each leg pulls from ``read_parquet('<path>')``. Resolved columns are
    selected by name; under ``"union"`` mode any column missing from
    a given snapshot is replaced with ``NULL AS "<name>"``. Provenance
    columns are stamped as string literals so DuckDB never has to bind
    them to runtime parameters.
    """
    if not _is_safe_identifier(view_name):
        raise FederationSqlError(f"Generated view name is unsafe: {view_name!r}")

    legs: list[str] = []
    for ref, path, cols in zip(refs, paths, per_snapshot_cols, strict=True):
        present = {c for c, _ in cols}

        # Quote columns. Each name was just read from the parquet
        # schema, so it MUST satisfy ``_is_safe_identifier`` — defensive
        # check guards against a malformed parquet leaking exotic names
        # (e.g. with embedded quotes) into raw SQL.
        select_parts: list[str] = []
        for col in resolved_columns:
            if col in present:
                if not _is_safe_identifier(col):
                    raise FederationSqlError(
                        f"Unsafe column name in snapshot {ref.snapshot_id}: {col!r}",
                    )
                select_parts.append(f'"{col}"')
            elif schema_align == "union":
                # Column missing from this leg — fill with NULL.
                select_parts.append(f'NULL AS "{col}"')
            else:
                # In intersect/strict modes the missing-column case must
                # not happen — _resolve_columns already filtered out
                # columns the leg doesn't have (intersect) or rejected
                # the request (strict).
                raise FederationSqlError(
                    f"Internal: column {col!r} missing from snapshot "
                    f"{ref.snapshot_id} under schema_align={schema_align!r}",
                )

        # Provenance literals — SQL-escape the single quote in case a
        # pathological UUID library ever lets one slip through.
        pid_lit = ref.project_id.replace("'", "''")
        sid_lit = ref.snapshot_id.replace("'", "''")
        select_parts.append(f"'{pid_lit}' AS \"{PROVENANCE_PROJECT_COL}\"")
        select_parts.append(f"'{sid_lit}' AS \"{PROVENANCE_SNAPSHOT_COL}\"")

        # Path literal: same escaping rule the duckdb_pool uses.
        escaped_path = path.replace("'", "''")
        legs.append(
            "SELECT " + ", ".join(select_parts)
            + f" FROM read_parquet('{escaped_path}')",
        )

    union_body = "\nUNION ALL\n".join(legs)
    return f'CREATE OR REPLACE VIEW "{view_name}" AS\n{union_body}'


async def federated_query(
    view: FederatedView,
    sql: str,
    *,
    parameters: list[Any] | tuple[Any, ...] | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Run a whitelisted SELECT over a pre-built federated view.

    The caller's SQL must reference the view by its ``view_name`` field —
    we don't rewrite identifiers or implicitly substitute ``entities``
    for the federated view, otherwise we'd be encouraging callers to
    paste snapshot-scoped SQL verbatim.

    ``limit`` is enforced even when the SQL already has a ``LIMIT``
    clause — DuckDB handles redundant LIMIT cleanly, and this gives the
    server-side a hard ceiling.
    """
    conn = view._conn
    if view._closed or conn is None:
        raise FederationError("Federated view is already closed")
    _enforce_select_only(sql)

    if limit <= 0 or limit > 100_000:
        raise FederationSqlError("limit must be between 1 and 100000")

    wrapped = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS _fed LIMIT {int(limit)}"

    def _run() -> list[dict[str, Any]]:
        cursor = conn.execute(wrapped, parameters or [])
        col_names = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(col_names, r, strict=True)) for r in rows]

    try:
        return await asyncio.to_thread(_run)
    except FederationError:
        raise
    except Exception as exc:
        raise FederationSqlError(f"Federated query failed: {exc}") from exc


async def federated_aggregate(
    view: FederatedView,
    *,
    group_by: list[str],
    measure: str,
    agg: str = "count",
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """High-level rollup helper without raw SQL.

    Always includes the provenance columns in the group-by so the user
    can pivot rollups per project / per snapshot without re-issuing
    the query. Empty ``group_by`` is allowed — it produces a single
    row per (project, snapshot) combination.

    Supported ``agg`` values: ``"count"`` (rows; ``measure`` may be
    ``"*"``), ``"sum"``, ``"avg"``, ``"min"``, ``"max"``.
    """
    conn = view._conn
    if view._closed or conn is None:
        raise FederationError("Federated view is already closed")

    agg = (agg or "count").lower().strip()
    if agg not in {"count", "sum", "avg", "min", "max"}:
        raise FederationSqlError(f"Unsupported agg: {agg!r}")

    # Validate identifiers eagerly — group-by leaks straight into SQL.
    for col in group_by:
        if not _is_safe_identifier(col):
            raise FederationSqlError(f"Unsafe group_by column: {col!r}")
        if col not in view.columns:
            raise FederationSqlError(f"Unknown group_by column: {col!r}")

    if agg == "count":
        if measure not in {"*"} and not _is_safe_identifier(measure):
            raise FederationSqlError(f"Unsafe measure: {measure!r}")
        if measure != "*" and measure not in view.columns:
            raise FederationSqlError(f"Unknown measure column: {measure!r}")
        measure_expr = "*" if measure == "*" else f'"{measure}"'
        select_measure = f"COUNT({measure_expr}) AS measure_value"
    else:
        if not _is_safe_identifier(measure):
            raise FederationSqlError(f"Unsafe measure: {measure!r}")
        if measure not in view.columns:
            raise FederationSqlError(f"Unknown measure column: {measure!r}")
        # Cast to DOUBLE so non-numeric snapshots don't crash the
        # aggregate — DuckDB silently returns NULL for unparseable
        # values rather than raising on the SUM.
        measure_expr = f'TRY_CAST("{measure}" AS DOUBLE)'
        select_measure = f"{agg.upper()}({measure_expr}) AS measure_value"

    # Always pivot by provenance — that's the whole point of the
    # federation result shape.
    full_group: list[str] = [
        PROVENANCE_PROJECT_COL,
        PROVENANCE_SNAPSHOT_COL,
        *[c for c in group_by if c not in _RESERVED_PROVENANCE_COLUMNS],
    ]
    select_cols = ", ".join(_quote_ident(c) for c in full_group)
    group_cols = ", ".join(_quote_ident(c) for c in full_group)

    if limit <= 0 or limit > 100_000:
        raise FederationSqlError("limit must be between 1 and 100000")

    sql = (
        f"SELECT {select_cols}, {select_measure} "
        f'FROM "{view.view_name}" '
        f"GROUP BY {group_cols} "
        f"ORDER BY measure_value DESC "
        f"LIMIT {int(limit)}"
    )

    def _run() -> list[dict[str, Any]]:
        cursor = conn.execute(sql)
        col_names = [d[0] for d in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(col_names, r, strict=True)) for r in rows]

    try:
        return await asyncio.to_thread(_run)
    except FederationError:
        raise
    except Exception as exc:
        raise FederationSqlError(
            f"Federated aggregate failed: {exc}",
        ) from exc


__all__ = [
    "EmptySnapshotListError",
    "FederatedSnapshotRef",
    "FederatedView",
    "FederationError",
    "FederationParquetError",
    "FederationSqlError",
    "PROVENANCE_PROJECT_COL",
    "PROVENANCE_SNAPSHOT_COL",
    "SchemaAlignMode",
    "SchemaMismatchError",
    "TooManySnapshotsError",
    "build_federated_view",
    "federated_aggregate",
    "federated_query",
]
