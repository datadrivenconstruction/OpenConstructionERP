# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""W6 + W9: file comments + cross-entity references + ISO 19650 violations.

Adds four tables backing the W6 (PDF Markup + Comments) and W9
(ISO 19650 naming + RFI/Issue linking) file-manager waves:

* ``oe_file_comment``           — polymorphic threaded comment on any
                                  file kind, optionally anchored to a
                                  PDF page + normalized (x, y) so the
                                  UI renders a pin.
* ``oe_file_comment_mention``   — resolved ``@username`` mentions with a
                                  ``notified_at`` watermark for the
                                  unread-mentions inbox.
* ``oe_file_naming_violation``  — per-file ISO 19650 violation rows
                                  written by ``service.scan_project``,
                                  upserted in place by re-scans.
* ``oe_file_reference``         — generic file → target entity link
                                  (RFI / issue / task / submittal / ...).

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL.

Revision ID: v3063_file_comments_references
Revises: v3047_clash_severity_delta
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3063_file_comments_references"
down_revision: Union[str, Sequence[str], None] = "v3047_clash_severity_delta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Table names ────────────────────────────────────────────────────────

_COMMENT = "oe_file_comment"
_MENTION = "oe_file_comment_mention"
_VIOLATION = "oe_file_naming_violation"
_REFERENCE = "oe_file_reference"


# ── Index names (kept under PG's 63-char identifier limit) ────────────

_COMMENT_PROJECT_FILE_IDX = "ix_oe_file_comment_project_file"
_COMMENT_PARENT_IDX = "ix_oe_file_comment_parent_id"
_COMMENT_PROJECT_IDX = "ix_oe_file_comment_project_id"

_MENTION_COMMENT_IDX = "ix_oe_file_comment_mention_comment_id"
_MENTION_USER_IDX = "ix_oe_file_comment_mention_user_id"
_MENTION_UNREAD_IDX = "ix_oe_file_comment_mention_user_unread"

_VIOLATION_PROJECT_IDX = "ix_oe_file_naming_violation_project_id"
_VIOLATION_PROJECT_ACK_IDX = "ix_oe_file_naming_violation_project_ack"

_REFERENCE_PROJECT_IDX = "ix_oe_file_reference_project_id"
_REFERENCE_FILE_IDX = "ix_oe_file_reference_file"
_REFERENCE_TARGET_IDX = "ix_oe_file_reference_target"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _index_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_file_comment ────────────────────────────────────────────
    if not _has_table(inspector, _COMMENT):
        op.create_table(
            _COMMENT,
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
            sa.Column("file_id", sa.String(length=255), nullable=False),
            sa.Column(
                "file_version_snapshot",
                sa.String(length=32),
                nullable=True,
            ),
            sa.Column(
                "parent_id",
                sa.String(length=36),
                sa.ForeignKey(f"{_COMMENT}.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "author_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("anchor_x", sa.Float(), nullable=True),
            sa.Column("anchor_y", sa.Float(), nullable=True),
            sa.Column(
                "resolved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "resolved_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    existing_idx = _index_names(inspector, _COMMENT)
    if _COMMENT_PROJECT_FILE_IDX not in existing_idx:
        op.create_index(
            _COMMENT_PROJECT_FILE_IDX,
            _COMMENT,
            ["project_id", "file_kind", "file_id"],
        )
    if _COMMENT_PARENT_IDX not in existing_idx:
        op.create_index(_COMMENT_PARENT_IDX, _COMMENT, ["parent_id"])
    if _COMMENT_PROJECT_IDX not in existing_idx:
        op.create_index(_COMMENT_PROJECT_IDX, _COMMENT, ["project_id"])

    # ── oe_file_comment_mention ────────────────────────────────────
    if not _has_table(inspector, _MENTION):
        op.create_table(
            _MENTION,
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
                "comment_id",
                sa.String(length=36),
                sa.ForeignKey(f"{_COMMENT}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "mentioned_user_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "comment_id",
                "mentioned_user_id",
                name="uq_oe_file_comment_mention_comment_user",
            ),
        )

    existing_idx = _index_names(inspector, _MENTION)
    if _MENTION_COMMENT_IDX not in existing_idx:
        op.create_index(_MENTION_COMMENT_IDX, _MENTION, ["comment_id"])
    if _MENTION_USER_IDX not in existing_idx:
        op.create_index(_MENTION_USER_IDX, _MENTION, ["mentioned_user_id"])
    if _MENTION_UNREAD_IDX not in existing_idx:
        # Inbox hot path: ``WHERE mentioned_user_id = ? AND notified_at IS NULL``
        op.create_index(
            _MENTION_UNREAD_IDX,
            _MENTION,
            ["mentioned_user_id", "notified_at"],
        )

    # ── oe_file_naming_violation ───────────────────────────────────
    if not _has_table(inspector, _VIOLATION):
        op.create_table(
            _VIOLATION,
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
            sa.Column(
                "rule_set",
                sa.String(length=32),
                nullable=False,
                server_default="iso19650",
            ),
            sa.Column("file_kind", sa.String(length=32), nullable=False),
            sa.Column("file_id", sa.String(length=255), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column(
                "violation_codes",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "acknowledged_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "acknowledged_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "project_id",
                "file_kind",
                "file_id",
                name="uq_oe_file_naming_violation_project_kind_file",
            ),
        )

    existing_idx = _index_names(inspector, _VIOLATION)
    if _VIOLATION_PROJECT_IDX not in existing_idx:
        op.create_index(_VIOLATION_PROJECT_IDX, _VIOLATION, ["project_id"])
    if _VIOLATION_PROJECT_ACK_IDX not in existing_idx:
        op.create_index(
            _VIOLATION_PROJECT_ACK_IDX,
            _VIOLATION,
            ["project_id", "acknowledged_at"],
        )

    # ── oe_file_reference ──────────────────────────────────────────
    if not _has_table(inspector, _REFERENCE):
        op.create_table(
            _REFERENCE,
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
            sa.Column("file_id", sa.String(length=255), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=255), nullable=False),
            sa.Column(
                "relation",
                sa.String(length=32),
                nullable=False,
                server_default="references",
            ),
            sa.Column("target_label", sa.String(length=255), nullable=True),
            sa.Column(
                "created_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "file_kind",
                "file_id",
                "target_type",
                "target_id",
                "relation",
                name="uq_oe_file_reference_file_target_relation",
            ),
        )

    existing_idx = _index_names(inspector, _REFERENCE)
    if _REFERENCE_PROJECT_IDX not in existing_idx:
        op.create_index(_REFERENCE_PROJECT_IDX, _REFERENCE, ["project_id"])
    if _REFERENCE_FILE_IDX not in existing_idx:
        op.create_index(_REFERENCE_FILE_IDX, _REFERENCE, ["file_kind", "file_id"])
    if _REFERENCE_TARGET_IDX not in existing_idx:
        op.create_index(
            _REFERENCE_TARGET_IDX,
            _REFERENCE,
            ["target_type", "target_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Reverse order — drop dependants first.

    if _has_table(inspector, _REFERENCE):
        existing_idx = _index_names(inspector, _REFERENCE)
        for idx in (
            _REFERENCE_TARGET_IDX,
            _REFERENCE_FILE_IDX,
            _REFERENCE_PROJECT_IDX,
        ):
            if idx in existing_idx:
                op.drop_index(idx, table_name=_REFERENCE)
        op.drop_table(_REFERENCE)

    if _has_table(inspector, _VIOLATION):
        existing_idx = _index_names(inspector, _VIOLATION)
        for idx in (_VIOLATION_PROJECT_ACK_IDX, _VIOLATION_PROJECT_IDX):
            if idx in existing_idx:
                op.drop_index(idx, table_name=_VIOLATION)
        op.drop_table(_VIOLATION)

    if _has_table(inspector, _MENTION):
        existing_idx = _index_names(inspector, _MENTION)
        for idx in (
            _MENTION_UNREAD_IDX,
            _MENTION_USER_IDX,
            _MENTION_COMMENT_IDX,
        ):
            if idx in existing_idx:
                op.drop_index(idx, table_name=_MENTION)
        op.drop_table(_MENTION)

    if _has_table(inspector, _COMMENT):
        existing_idx = _index_names(inspector, _COMMENT)
        for idx in (
            _COMMENT_PROJECT_IDX,
            _COMMENT_PARENT_IDX,
            _COMMENT_PROJECT_FILE_IDX,
        ):
            if idx in existing_idx:
                op.drop_index(idx, table_name=_COMMENT)
        op.drop_table(_COMMENT)
