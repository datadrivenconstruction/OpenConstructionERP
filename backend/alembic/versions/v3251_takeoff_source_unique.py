# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff from-source idempotency: collapse duplicates, add unique index.

``POST /documents/from-source`` find-or-creates a takeoff document by
``(project_id, source_document_id)`` with an unlocked SELECT then INSERT, so two
concurrent opens of the same Project-Files PDF could both miss and both insert,
minting duplicate ``oe_takeoff_document`` rows for one source. Measurements and
AI plan-read runs reference the document by its string id, so a reader that
resolved to a different duplicate than a measurement was saved against saw the
measurement disappear - stranded on an unreachable row (issue #369).

This migration first merges any pre-existing duplicates - keep the oldest row
per ``(project_id, source_document_id)`` group as canonical, re-point its
measurements and AI runs, delete the newer duplicates and remove their orphaned
PDF files - then adds the unique index that prevents new ones. The merge has to
run before the index or the ``CREATE UNIQUE INDEX`` fails on the existing
duplicates.

A plain (non-partial) unique index is used on purpose: ``source_document_id`` is
NULL for direct uploads and PostgreSQL treats NULLs as distinct in a unique
index, so ordinary uploads never collide, and a plain index (unlike a partial
one) is also reconstructed by the startup ``postgres_auto_migrate`` heal on
embedded / stamped installs that never run this migration.

Every step is inspector-guarded and idempotent, so a re-run - or a database the
embedded runtime already healed - is a no-op. PostgreSQL-only. Chained after
v3250_merge_open_heads to keep a single linear head.

Revision ID: v3251_takeoff_source_unique
Revises: v3250_merge_open_heads
Create Date: 2026-07-19
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "v3251_takeoff_source_unique"
down_revision = "v3250_merge_open_heads"
branch_labels = None
depends_on = None

_DOC = "oe_takeoff_document"
_INDEX = "uq_takeoff_document_project_source"

# Canonical row per group = oldest (created_at ASC), row id as tie-breaker.
_RANKED = """
    SELECT id, project_id, source_document_id,
           first_value(id) OVER w AS canonical_id
    FROM oe_takeoff_document
    WHERE source_document_id IS NOT NULL
    WINDOW w AS (
        PARTITION BY project_id, source_document_id
        ORDER BY created_at ASC, id ASC
    )
"""


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(ix.get("name") == name for ix in insp.get_indexes(table))


def _collapse_duplicates() -> None:
    """Merge duplicate from-source documents into their canonical (oldest) row."""
    bind = op.get_bind()
    dupes = bind.execute(
        sa.text(
            """
            SELECT id, file_path
            FROM (
                SELECT id, file_path, row_number() OVER w AS rn
                FROM oe_takeoff_document
                WHERE source_document_id IS NOT NULL
                WINDOW w AS (
                    PARTITION BY project_id, source_document_id
                    ORDER BY created_at ASC, id ASC
                )
            ) ranked
            WHERE rn > 1
            """  # noqa: S608 - fixed table/column names, no user input
        )
    ).fetchall()
    if not dupes:
        return
    # Re-point children (both store the document id as a VARCHAR(36) string), then
    # delete the duplicates. Set-based so one statement covers every group.
    bind.execute(
        sa.text(
            f"UPDATE oe_takeoff_measurement AS m SET document_id = r.canonical_id "
            f"FROM ({_RANKED}) r WHERE m.document_id = r.id AND r.id <> r.canonical_id"  # noqa: S608
        )
    )
    bind.execute(
        sa.text(
            f"UPDATE oe_ai_takeoff_run AS a SET document_id = r.canonical_id "
            f"FROM ({_RANKED}) r WHERE a.document_id = r.id AND r.id <> r.canonical_id"  # noqa: S608
        )
    )
    bind.execute(
        sa.text(
            f"DELETE FROM oe_takeoff_document AS d USING ({_RANKED}) r WHERE d.id = r.id AND r.id <> r.canonical_id"  # noqa: S608
        )
    )
    for row in dupes:
        if row.file_path:
            with contextlib.suppress(OSError):
                Path(row.file_path).unlink()


def upgrade() -> None:
    """Collapse duplicate from-source documents, then add the unique index."""
    if not _has_table(_DOC):
        return
    _collapse_duplicates()
    if not _has_index(_DOC, _INDEX):
        op.create_index(_INDEX, _DOC, ["project_id", "source_document_id"], unique=True)


def downgrade() -> None:
    """Drop the unique index (the merged duplicates are not restored)."""
    if _has_table(_DOC) and _has_index(_DOC, _INDEX):
        op.drop_index(_INDEX, table_name=_DOC)
