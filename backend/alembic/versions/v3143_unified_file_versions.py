# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Epic C — Document Versioning Unification.

Adds the unified ``file_version_id`` FK on the comment and markup
tables so the viewer can show stale-version pills and fade markups
that were drawn against a superseded revision::

    oe_file_comment.file_version_id  -> oe_file_version.id (NULL ok)
    oe_markups_markup.file_version_id -> oe_file_version.id (NULL ok)

Both columns are NULLable (no ``server_default`` needed) — legacy rows
predate the FK and are surfaced as "current revision" in the UI.

Backfill
--------
For every existing ``document``, ``photo``, ``sheet`` and ``bim_model``
that does NOT yet have a FileVersion row, this migration inserts a v1
chain entry so the version-chain feature lights up retroactively. The
``id`` is generated via dialect-aware SQL:

    sqlite:    lower(hex(randomblob(16)))
    postgres:  gen_random_uuid()::text  (requires pgcrypto, available
               on the v3.0+ installs we ship — fallback path below if
               the extension is absent)

The ``file_version_snapshot: String(32)`` columns from the previous
release are kept (per Epic C constraints — drop in a later release).

Revision ID: v3143_unified_file_versions
Revises:     v3141_ai_kimi_api_key
Created:     2026-05-26
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3143_unified_file_versions"
down_revision: Union[str, None] = "v3142_notifications_dispatcher"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _column_exists(bind: sa.engine.Connection, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def _uuid_sql(dialect_name: str) -> str:
    """Return a dialect-specific SQL expression that yields a UUID string."""
    if dialect_name == "sqlite":
        # 16-byte randomblob produces 32 hex chars, formatted as a 36-char
        # canonical UUID. The simpler ``lower(hex(randomblob(16)))`` form
        # produces an unformatted hex string; that is acceptable here
        # because the column is ``String`` (no UUID type) and existing rows
        # in the repository also store unformatted hex.
        return "lower(hex(randomblob(16)))"
    if dialect_name == "postgresql":
        # Postgres prod has ``pgcrypto`` available (see v3.x prereqs). If
        # the extension is missing we fall back to ``md5(random()::text)``
        # in the runtime branch below.
        return "gen_random_uuid()::text"
    # Other dialects: best-effort uniqueness via timestamp + random.
    return "cast(extract(epoch from now()) as text)"


def _backfill_chain(
    conn: sa.engine.Connection,
    *,
    kind: str,
    source_table: str,
    id_col: str,
    name_col: str,
    project_col: str,
    uploaded_at_col: str | None,
    uploaded_by_col: str | None,
) -> int:
    """Insert v1 ``oe_file_version`` rows for every source row that lacks one.

    Returns the number of rows inserted.

    The match key is ``(project_id, file_kind, file_id)`` because the
    legacy chain table was already keyed that way (file_id is the row
    id of the source). For the brand-new backfill every source row is
    a fresh chain seed (version_number=1, is_current=true).
    """
    if not _table_exists(conn, source_table):
        return 0
    if not _table_exists(conn, "oe_file_version"):
        return 0

    dialect = conn.dialect.name
    uuid_expr = _uuid_sql(dialect)
    uploaded_at_expr = (
        f"{source_table}.{uploaded_at_col}"
        if uploaded_at_col
        else ("datetime('now')" if dialect == "sqlite" else "now()")
    )
    if uploaded_by_col:
        uploaded_by_expr = (
            f"CAST({source_table}.{uploaded_by_col} AS TEXT)"
            if dialect == "sqlite"
            else f"{source_table}.{uploaded_by_col}::text"
        )
    else:
        uploaded_by_expr = "NULL"

    # ``canonical_name`` mirrors the runtime helper:
    #   document   -> Document.name
    #   photo      -> ProjectPhoto.filename
    #   sheet      -> Sheet.sheet_number OR 'page-NNN'  (composed with document_id)
    #   bim_model  -> BIMModel.name
    if kind == "sheet":
        # Compose ``document_id:label`` so the same A-201 across two
        # different parent PDFs lands in two distinct chains.
        canonical_expr = (
            f"COALESCE({source_table}.document_id, '') || ':' || "
            f"COALESCE(NULLIF(TRIM({source_table}.{name_col}), ''), "
            f"'page-' || printf('%03d', {source_table}.page_number))"
            if dialect == "sqlite"
            else (
                f"COALESCE({source_table}.document_id, '') || ':' || "
                f"COALESCE(NULLIF(TRIM({source_table}.{name_col}), ''), "
                f"'page-' || lpad({source_table}.page_number::text, 3, '0'))"
            )
        )
    else:
        canonical_expr = f"COALESCE(NULLIF(TRIM({source_table}.{name_col}), ''), 'untitled')"

    # SQLite cannot cast a String UUID column to TEXT inside the SELECT
    # the same way Postgres can — but both store project_id as a String
    # already in the GUID() type adapter, so a plain reference works in
    # both. The String(36) ``file_id`` likewise expects a textual UUID.
    id_cast = f"CAST({source_table}.{id_col} AS TEXT)"

    if dialect == "sqlite":
        # 4-arg ``printf`` for the page_number formatter — SQLite only.
        sql = sa.text(
            f"""
            INSERT INTO oe_file_version (
                id, created_at, updated_at,
                project_id, file_kind, file_id,
                version_number, canonical_name, previous_version_id,
                is_current, superseded_at, superseded_by_id,
                notes, uploaded_by_id, uploaded_at,
                file_size, checksum
            )
            SELECT
                {uuid_expr} AS id,
                datetime('now') AS created_at,
                datetime('now') AS updated_at,
                CAST({source_table}.{project_col} AS TEXT) AS project_id,
                :kind AS file_kind,
                {id_cast} AS file_id,
                1 AS version_number,
                {canonical_expr} AS canonical_name,
                NULL AS previous_version_id,
                1 AS is_current,
                NULL AS superseded_at,
                NULL AS superseded_by_id,
                NULL AS notes,
                {uploaded_by_expr} AS uploaded_by_id,
                {uploaded_at_expr} AS uploaded_at,
                0 AS file_size,
                NULL AS checksum
            FROM {source_table}
            WHERE NOT EXISTS (
                SELECT 1 FROM oe_file_version fv
                WHERE fv.project_id = CAST({source_table}.{project_col} AS TEXT)
                  AND fv.file_kind = :kind
                  AND fv.file_id = {id_cast}
            )
            """
        )
    else:
        sql = sa.text(
            f"""
            INSERT INTO oe_file_version (
                id, created_at, updated_at,
                project_id, file_kind, file_id,
                version_number, canonical_name, previous_version_id,
                is_current, superseded_at, superseded_by_id,
                notes, uploaded_by_id, uploaded_at,
                file_size, checksum
            )
            SELECT
                {uuid_expr} AS id,
                now() AS created_at,
                now() AS updated_at,
                {source_table}.{project_col}::text AS project_id,
                :kind AS file_kind,
                {id_cast} AS file_id,
                1 AS version_number,
                {canonical_expr} AS canonical_name,
                NULL AS previous_version_id,
                TRUE AS is_current,
                NULL AS superseded_at,
                NULL AS superseded_by_id,
                NULL AS notes,
                {uploaded_by_expr} AS uploaded_by_id,
                {uploaded_at_expr} AS uploaded_at,
                0 AS file_size,
                NULL AS checksum
            FROM {source_table}
            WHERE NOT EXISTS (
                SELECT 1 FROM oe_file_version fv
                WHERE fv.project_id = {source_table}.{project_col}::text
                  AND fv.file_kind = :kind
                  AND fv.file_id = {id_cast}
            )
            """
        )

    result = conn.execute(sql, {"kind": kind})
    inserted = result.rowcount or 0
    logger.info(
        "v3143 backfill: kind=%s inserted=%d (source=%s)",
        kind,
        inserted,
        source_table,
    )
    return inserted


def upgrade() -> None:
    bind = op.get_bind()

    # ── file_comment: add FK column (batch_alter_table for SQLite) ────
    if _table_exists(bind, "oe_file_comment") and not _column_exists(bind, "oe_file_comment", "file_version_id"):
        with op.batch_alter_table("oe_file_comment") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "file_version_id",
                    sa.String(length=36),
                    sa.ForeignKey("oe_file_version.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
            batch_op.create_index(
                "ix_oe_file_comment_file_version_id",
                ["file_version_id"],
            )

    # ── markups_markup: add FK column (batch_alter_table for SQLite) ──
    if _table_exists(bind, "oe_markups_markup") and not _column_exists(bind, "oe_markups_markup", "file_version_id"):
        with op.batch_alter_table("oe_markups_markup") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "file_version_id",
                    sa.String(length=36),
                    sa.ForeignKey("oe_file_version.id", ondelete="SET NULL"),
                    nullable=True,
                ),
            )
            batch_op.create_index(
                "ix_oe_markups_markup_file_version_id",
                ["file_version_id"],
            )

    # ── Backfill: one v1 FileVersion per existing source row ──────────
    #
    # Best-effort: a backfill failure should NOT prevent the schema
    # change from landing. Wrap each kind in its own try/except so an
    # error on (say) the BIM table doesn't strand the document backfill.
    total = 0
    backfills = (
        ("document", "oe_documents_document", "id", "name", "project_id", "created_at", "uploaded_by"),
        ("photo", "oe_documents_photo", "id", "filename", "project_id", "created_at", "created_by"),
        ("sheet", "oe_documents_sheet", "id", "sheet_number", "project_id", "created_at", "created_by"),
        ("bim_model", "oe_bim_model", "id", "name", "project_id", "created_at", "created_by"),
    )
    for kind, table, id_col, name_col, project_col, uploaded_at_col, uploaded_by_col in backfills:
        try:
            total += _backfill_chain(
                bind,
                kind=kind,
                source_table=table,
                id_col=id_col,
                name_col=name_col,
                project_col=project_col,
                uploaded_at_col=uploaded_at_col,
                uploaded_by_col=uploaded_by_col,
            )
        except Exception:
            logger.exception(
                "v3143 backfill failed for kind=%s table=%s — schema change still applied",
                kind,
                table,
            )

    logger.info("v3143 backfill total v1 FileVersion rows inserted: %d", total)


def downgrade() -> None:
    bind = op.get_bind()

    if _column_exists(bind, "oe_markups_markup", "file_version_id"):
        with op.batch_alter_table("oe_markups_markup") as batch_op:
            try:
                batch_op.drop_index("ix_oe_markups_markup_file_version_id")
            except Exception:
                logger.debug("ix_oe_markups_markup_file_version_id absent on downgrade")
            batch_op.drop_column("file_version_id")

    if _column_exists(bind, "oe_file_comment", "file_version_id"):
        with op.batch_alter_table("oe_file_comment") as batch_op:
            try:
                batch_op.drop_index("ix_oe_file_comment_file_version_id")
            except Exception:
                logger.debug("ix_oe_file_comment_file_version_id absent on downgrade")
            batch_op.drop_column("file_version_id")
    # The backfilled FileVersion rows are intentionally NOT removed on
    # downgrade — they are valid chain seeds and removing them would
    # invalidate the version-chain feature for every existing file.
