# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PostgreSQL scale optimizations: JSONB columns and performance indexes.

Two dialect-aware additions that are emitted by ``Base.metadata.create_all`` so
they reach fresh PostgreSQL installs (which are built via ``create_all``, not the
Alembic chain) while leaving SQLite completely unchanged:

1. **JSONB on PostgreSQL.** Every model uses the generic SQLAlchemy ``JSON``
   type for SQLite portability. A ``@compiles`` hook rewrites the *DDL* for that
   type to ``JSONB`` on the PostgreSQL dialect only. The Python bind/result
   processing is untouched (SQLAlchemy routes both ``json`` and ``jsonb`` through
   the engine's ``json_serializer`` / ``json_deserializer``), so reads and writes
   behave identically -- only the on-disk column type changes, which is what
   makes GIN indexing and fast containment queries possible.

2. **Performance indexes.** An ``after_create`` metadata event creates, once per
   ``create_all`` and idempotently (``checkfirst``):
     * a btree index on every foreign-key column not already the left-most column
       of an existing index (and not a PK / unique column);
     * composite ``(project_id, created_at)`` and ``(project_id, status)`` indexes
       wherever both columns exist;
     * GIN indexes on the JSON columns that are queried by path
       (``asset_info`` / ``classification``) -- PostgreSQL only, requires JSONB.

This module registers everything as an import side effect. It is imported once
from ``app.database`` after ``Base`` is defined, and is written so that a failure
here can never take down engine creation.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import JSON, Index, UniqueConstraint
from sqlalchemy import event as sa_event
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles

logger = logging.getLogger(__name__)

#: PostgreSQL identifier length limit. Index names longer than this are
#: deterministically shortened with a hash suffix.
PG_NAME_LIMIT = 63

#: JSON columns (by name) that the app filters by path and therefore benefits
#: from a GIN index on PostgreSQL.
GIN_JSON_COLUMNS = frozenset({"asset_info", "classification"})


# ---------------------------------------------------------------------------
# 1. JSON -> JSONB on PostgreSQL (DDL only)
# ---------------------------------------------------------------------------
@compiles(JSON, "postgresql")
def _compile_generic_json_as_jsonb(element, compiler, **kw):  # noqa: ANN001, ANN202
    """Render the generic ``JSON`` type as ``JSONB`` on PostgreSQL DDL."""
    return "JSONB"


@compiles(postgresql.JSON, "postgresql")
def _compile_pg_json_as_jsonb(element, compiler, **kw):  # noqa: ANN001, ANN202
    """Also catch the dialect-adapted ``postgresql.JSON`` (the generic type may be
    swapped for it by DDL compile time via the dialect colspecs).
    """
    return "JSONB"


# ---------------------------------------------------------------------------
# 2. Performance indexes via an after_create metadata event
# ---------------------------------------------------------------------------
def _index_name(table_name: str, columns: list[str], *, gin: bool = False) -> str:
    """Build a deterministic index name within the PostgreSQL 63-byte limit."""
    suffix = "_gin" if gin else ""
    name = f"ix_{table_name}_{'_'.join(columns)}{suffix}"
    if len(name) <= PG_NAME_LIMIT:
        return name
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=4).hexdigest()
    keep = PG_NAME_LIMIT - 1 - len(digest)
    return f"{name[:keep]}_{digest}"


def _existing_single_col_left(table) -> set[str]:  # noqa: ANN001
    """Names of columns that are already the left-most column of some index."""
    left: set[str] = set()
    for ix in table.indexes:
        cols = list(ix.columns)
        if cols:
            left.add(cols[0].name)
    # A column flagged index=True or unique=True gets its own index from create_all.
    for col in table.columns:
        if col.index or col.unique or col.primary_key:
            left.add(col.name)
    # A table-level UniqueConstraint is backed by a unique btree index in
    # PostgreSQL, so its left-most column is already served by it. Without this
    # a foreign key leading one got a second, redundant index.
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            cols = list(constraint.columns)
            if cols:
                left.add(cols[0].name)
    return left


def _desired_indexes(table):  # noqa: ANN001, ANN202
    """Yield ``Index`` objects that should exist on ``table`` but may not yet.

    Returns btree indexes (portable) and GIN indexes (PostgreSQL only, tagged
    via ``postgresql_using='gin'`` which create_all/checkfirst emit only on PG).
    """
    covered = _existing_single_col_left(table)
    colnames = {c.name for c in table.columns}

    # Index names already on the table -- including ones a PRIOR run of this
    # generator added (constructing ``Index(...)`` auto-attaches it to
    # ``table.indexes`` on the shared ``Base.metadata``). Guarding every yield by
    # name makes the generator idempotent: without it, a second ``create_all`` in
    # the same process re-yields the same composite/GIN names and ``create_all``
    # emits a duplicate ``CREATE INDEX`` ("relation ... already exists"). It also
    # avoids colliding with a model that already declares one of these names.
    existing_names = {ix.name for ix in table.indexes if ix.name}

    def _new(name, *cols, **kw):  # noqa: ANN001, ANN202
        if name in existing_names:
            return None
        existing_names.add(name)
        return Index(name, *cols, **kw)

    # Foreign-key columns -> btree, unless already covered.
    for col in table.columns:
        if not col.foreign_keys:
            continue
        if col.name in covered:
            continue
        covered.add(col.name)
        ix = _new(_index_name(table.name, [col.name]), col)
        if ix is not None:
            yield ix

    # Composite hot paths.
    if "project_id" in colnames and "created_at" in colnames:
        ix = _new(
            _index_name(table.name, ["project_id", "created_at"]),
            table.c["project_id"],
            table.c["created_at"],
        )
        if ix is not None:
            yield ix
    if "project_id" in colnames and "status" in colnames:
        ix = _new(
            _index_name(table.name, ["project_id", "status"]),
            table.c["project_id"],
            table.c["status"],
        )
        if ix is not None:
            yield ix

    # GIN on path-queried JSON columns (PostgreSQL only).
    for col in table.columns:
        if col.name in GIN_JSON_COLUMNS and isinstance(col.type, JSON):
            ix = _new(
                _index_name(table.name, [col.name], gin=True),
                col,
                postgresql_using="gin",
                # jsonb_path_ops: smaller and faster than the default jsonb_ops
                # for the ``@>`` containment queries the app actually runs on
                # these columns (it indexes only values/paths, not top-level
                # keys). It supports @>, @@ and @? -- exactly the containment
                # operators used -- at the cost of key-existence operators
                # (?, ?|, ?&), which the app does not use on these columns.
                postgresql_ops={col.name: "jsonb_path_ops"},
            )
            if ix is not None:
                yield ix


def _ensure_performance_indexes(target, connection, **kw):  # noqa: ANN001, ANN202
    """``after_create`` handler: create missing performance indexes idempotently.

    Only the tables that were just created are processed (``kw['tables']``), or
    all tables if that key is absent. GIN indexes are skipped on non-PostgreSQL
    backends. Every creation uses ``checkfirst=True`` so re-runs are safe, and the
    whole pass is wrapped so a single failure never aborts schema creation.
    """
    is_pg = connection.dialect.name == "postgresql"
    tables = kw.get("tables")
    if tables is None:
        tables = list(target.tables.values())

    created = 0
    for table in tables:
        for idx in _desired_indexes(table):
            is_gin = idx.dialect_options.get("postgresql", {}).get("using") == "gin"
            if is_gin and not is_pg:
                continue
            try:
                idx.create(bind=connection, checkfirst=True)
                created += 1
            except Exception as exc:  # noqa: BLE001 -- never abort create_all on one index
                logger.warning("performance index %s skipped: %r", idx.name, exc)
    if created:
        logger.info("performance_indexes: ensured %d indexes", created)


def register(base) -> None:  # noqa: ANN001
    """Register the after_create index event on ``base.metadata`` (idempotent)."""
    sa_event.listen(base.metadata, "after_create", _ensure_performance_indexes)
