# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File versioning + recycle bin — oe_file_version + oe_file_trash tables.

Adds two new tables to back the W1/W2 file-manager waves:

* ``oe_file_version`` — polymorphic per-file version chain (the
  file_versions module). One row per upload, with ``is_current``
  identifying the active row in a ``(project_id, file_kind,
  canonical_name)`` chain. ``file_id`` is a String — no FK — because
  the chain spans 8 file-kind tables.

* ``oe_file_trash`` — centralised soft-delete snapshot for all 8
  file kinds. The original kind table loses the row; the snapshot
  carries the full JSON payload so restore is loss-less. A
  ``restore_token`` gates the hard-purge endpoint.

Both tables get composite indexes:

    oe_file_version (project_id, file_kind, canonical_name, is_current)
    oe_file_version (file_id)
    oe_file_trash   (project_id, trashed_at)
    oe_file_trash   (original_kind, original_id)

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL.

Revision ID: v3060_file_versions_trash
Revises: v3047_clash_severity_delta
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3060_file_versions_trash"
down_revision: Union[str, Sequence[str], None] = "v3047_clash_severity_delta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VERSION = "oe_file_version"
_TRASH = "oe_file_trash"

_VERSION_CHAIN_IDX = "ix_file_version_chain"
_VERSION_FILE_IDX = "ix_file_version_file_id"
_TRASH_PROJECT_IDX = "ix_file_trash_project_trashed"
_TRASH_ORIGIN_IDX = "ix_file_trash_origin"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_file_version ───────────────────────────────────────────────
    if not _has_table(inspector, _VERSION):
        op.create_table(
            _VERSION,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_kind", sa.String(length=32), nullable=False),
            sa.Column("file_id", sa.String(length=64), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("canonical_name", sa.String(length=255), nullable=False),
            sa.Column("previous_version_id", sa.String(length=36), nullable=True),
            sa.Column(
                "is_current",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_by_id", sa.String(length=36), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "uploaded_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("checksum", sa.String(length=64), nullable=True),
        )

    existing_version_idx = (
        {ix["name"] for ix in inspector.get_indexes(_VERSION)} if _has_table(inspector, _VERSION) else set()
    )
    if _VERSION_CHAIN_IDX not in existing_version_idx:
        op.create_index(
            _VERSION_CHAIN_IDX,
            _VERSION,
            ["project_id", "file_kind", "canonical_name", "is_current"],
        )
    if _VERSION_FILE_IDX not in existing_version_idx:
        op.create_index(_VERSION_FILE_IDX, _VERSION, ["file_id"])

    # ── oe_file_trash ─────────────────────────────────────────────────
    if not _has_table(inspector, _TRASH):
        op.create_table(
            _TRASH,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("original_kind", sa.String(length=32), nullable=False),
            sa.Column("original_id", sa.String(length=64), nullable=False),
            sa.Column(
                "canonical_name",
                sa.String(length=255),
                nullable=False,
                server_default="",
            ),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "trashed_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "retention_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "restored_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("restore_token", sa.String(length=64), nullable=False),
        )

    existing_trash_idx = (
        {ix["name"] for ix in inspector.get_indexes(_TRASH)} if _has_table(inspector, _TRASH) else set()
    )
    if _TRASH_PROJECT_IDX not in existing_trash_idx:
        op.create_index(_TRASH_PROJECT_IDX, _TRASH, ["project_id", "trashed_at"])
    if _TRASH_ORIGIN_IDX not in existing_trash_idx:
        op.create_index(_TRASH_ORIGIN_IDX, _TRASH, ["original_kind", "original_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TRASH):
        existing_trash_idx = {ix["name"] for ix in inspector.get_indexes(_TRASH)}
        if _TRASH_ORIGIN_IDX in existing_trash_idx:
            op.drop_index(_TRASH_ORIGIN_IDX, table_name=_TRASH)
        if _TRASH_PROJECT_IDX in existing_trash_idx:
            op.drop_index(_TRASH_PROJECT_IDX, table_name=_TRASH)
        op.drop_table(_TRASH)

    if _has_table(inspector, _VERSION):
        existing_version_idx = {ix["name"] for ix in inspector.get_indexes(_VERSION)}
        if _VERSION_FILE_IDX in existing_version_idx:
            op.drop_index(_VERSION_FILE_IDX, table_name=_VERSION)
        if _VERSION_CHAIN_IDX in existing_version_idx:
            op.drop_index(_VERSION_CHAIN_IDX, table_name=_VERSION)
        op.drop_table(_VERSION)
