# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File search + tags (W3 + W4).

Three additive tables for the file-manager:

* ``oe_file_search_index``        — OCR-extracted full text per file.
                                    On Postgres the migration also adds
                                    a ``tsv_vector`` generated column
                                    (over ``content_text``) plus a GIN
                                    index for ``ts_rank`` queries; on
                                    SQLite that step is skipped (the
                                    service falls back to ``LIKE``).
* ``oe_file_tag``                 — project-scoped tag definitions.
                                    Unique on ``(project_id, name)``.
* ``oe_file_tag_assignment``      — polymorphic ``tag → (kind, file_id)``
                                    junction, FK to ``oe_file_tag`` with
                                    ``ON DELETE CASCADE``.

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL exactly once.

Revision ID: v3061_file_search_tags
Revises: v3047_clash_severity_delta
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3061_file_search_tags"
down_revision: Union[str, Sequence[str], None] = "v3047_clash_severity_delta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEARCH = "oe_file_search_index"
_TAG = "oe_file_tag"
_ASSIGN = "oe_file_tag_assignment"

_SEARCH_TSV_IDX = "ix_file_search_index_tsv"
_SEARCH_PROJECT_KIND_IDX = "ix_file_search_index_project_kind"
_SEARCH_FILE_IDX = "ix_file_search_index_file"
_SEARCH_UQ = "uq_file_search_index_project_kind_file"

_TAG_UQ = "uq_file_tag_project_name"
_TAG_CATEGORY_IDX = "ix_file_tag_project_category"

_ASSIGN_UQ = "uq_file_tag_assignment_tag_kind_file"
_ASSIGN_KIND_FILE_IDX = "ix_file_tag_assignment_kind_file"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    # ── oe_file_search_index ──────────────────────────────────────────
    if not _has_table(inspector, _SEARCH):
        op.create_table(
            _SEARCH,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_kind", sa.String(32), nullable=False),
            sa.Column("file_id", sa.String(64), nullable=False),
            sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("ocr_engine", sa.String(32), nullable=True),
            sa.Column("language", sa.String(8), nullable=True),
            sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("project_id", "file_kind", "file_id", name=_SEARCH_UQ),
        )
        op.create_index(_SEARCH_PROJECT_KIND_IDX, _SEARCH, ["project_id", "file_kind"])
        op.create_index(_SEARCH_FILE_IDX, _SEARCH, ["file_kind", "file_id"])

        # Postgres: add the generated tsvector column + GIN index.
        if is_postgres:
            op.execute(
                f"""
                ALTER TABLE {_SEARCH}
                ADD COLUMN tsv_vector tsvector
                GENERATED ALWAYS AS (
                    to_tsvector('simple', coalesce(content_text, ''))
                ) STORED
                """
            )
            op.execute(f"CREATE INDEX {_SEARCH_TSV_IDX} ON {_SEARCH} USING GIN (tsv_vector)")

    # ── oe_file_tag ───────────────────────────────────────────────────
    if not _has_table(inspector, _TAG):
        op.create_table(
            _TAG,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=False),
            sa.Column(
                "color",
                sa.String(7),
                nullable=False,
                server_default="#94a3b8",
            ),
            sa.Column("category", sa.String(32), nullable=True),
            sa.Column("created_by_id", sa.String(36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("project_id", "name", name=_TAG_UQ),
        )
        op.create_index(_TAG_CATEGORY_IDX, _TAG, ["project_id", "category"])

    # ── oe_file_tag_assignment ────────────────────────────────────────
    if not _has_table(inspector, _ASSIGN):
        op.create_table(
            _ASSIGN,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "tag_id",
                sa.String(36),
                sa.ForeignKey("oe_file_tag.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_kind", sa.String(32), nullable=False),
            sa.Column("file_id", sa.String(64), nullable=False),
            sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("assigned_by_id", sa.String(36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("tag_id", "file_kind", "file_id", name=_ASSIGN_UQ),
        )
        op.create_index(_ASSIGN_KIND_FILE_IDX, _ASSIGN, ["file_kind", "file_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    if _has_table(inspector, _ASSIGN):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_ASSIGN)}
        if _ASSIGN_KIND_FILE_IDX in existing_idx:
            op.drop_index(_ASSIGN_KIND_FILE_IDX, table_name=_ASSIGN)
        op.drop_table(_ASSIGN)

    if _has_table(inspector, _TAG):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_TAG)}
        if _TAG_CATEGORY_IDX in existing_idx:
            op.drop_index(_TAG_CATEGORY_IDX, table_name=_TAG)
        op.drop_table(_TAG)

    if _has_table(inspector, _SEARCH):
        if is_postgres:
            op.execute(f"DROP INDEX IF EXISTS {_SEARCH_TSV_IDX}")
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_SEARCH)}
        for idx in (_SEARCH_PROJECT_KIND_IDX, _SEARCH_FILE_IDX):
            if idx in existing_idx:
                op.drop_index(idx, table_name=_SEARCH)
        op.drop_table(_SEARCH)
