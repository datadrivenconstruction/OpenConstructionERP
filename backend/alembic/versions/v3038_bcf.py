# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BCF module — persistent Topic / Comment / Viewpoint tables.

Backs the ``oe_bcf`` module: server-side BCF 2.1 / 3.0 issue tracking
with a lossless ``.bcfzip`` roundtrip.

* ``oe_bcf_topic``      — a BCF Topic (issue) scoped to a project, with
  the verbatim BCF ``Topic/@Guid`` preserved alongside the surrogate PK
  so an imported topic survives an export-import roundtrip.
* ``oe_bcf_comment``    — a comment on a topic (``Comment/@Guid`` kept).
* ``oe_bcf_viewpoint``  — a viewpoint: camera + component selection /
  visibility GUID lists + clipping planes; the PNG snapshot lives behind
  the storage abstraction, only ``snapshot_key`` is persisted here.

Idempotent: each table is guarded by an inspector so re-running after
SQLite's ``Base.metadata.create_all`` (dev) is a no-op; Postgres prod
gets the DDL. All ``id`` / ``*_id`` columns are ``String(36)`` to match
the platform's ``GUID`` TypeDecorator on SQLite + PostgreSQL.

Revision ID: v3038_bcf
Revises: v3037_pipelines
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3038_bcf"
down_revision: Union[str, Sequence[str], None] = "v3037_pipelines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _ts_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Create the three BCF tables (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. oe_bcf_topic ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_bcf_topic"):
        op.create_table(
            "oe_bcf_topic",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column("guid", sa.String(length=36), nullable=False),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("bim_model_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("topic_type", sa.String(length=100), nullable=True),
            sa.Column(
                "topic_status",
                sa.String(length=100),
                nullable=False,
                server_default="Open",
            ),
            sa.Column("priority", sa.String(length=100), nullable=True),
            sa.Column("stage", sa.String(length=100), nullable=True),
            sa.Column("topic_index", sa.Integer(), nullable=True),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "reference_links",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("creation_author", sa.String(length=255), nullable=True),
            sa.Column("creation_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("modified_author", sa.String(length=255), nullable=True),
            sa.Column("modified_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("project_id", "guid", name="uq_bcf_topic_project_guid"),
        )
        op.create_index("ix_bcf_topic_project", "oe_bcf_topic", ["project_id"])
        op.create_index("ix_bcf_topic_guid", "oe_bcf_topic", ["guid"])
        op.create_index(
            "ix_oe_bcf_topic_bim_model_id",
            "oe_bcf_topic",
            ["bim_model_id"],
        )

    # ── 2. oe_bcf_comment ────────────────────────────────────────────
    if not _has_table(inspector, "oe_bcf_comment"):
        op.create_table(
            "oe_bcf_comment",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column("guid", sa.String(length=36), nullable=False),
            sa.Column(
                "topic_id",
                sa.String(length=36),
                sa.ForeignKey("oe_bcf_topic.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("comment_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("author", sa.String(length=255), nullable=True),
            sa.Column("date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("modified_author", sa.String(length=255), nullable=True),
            sa.Column("modified_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("viewpoint_guid", sa.String(length=36), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("topic_id", "guid", name="uq_bcf_comment_topic_guid"),
        )
        op.create_index("ix_bcf_comment_topic", "oe_bcf_comment", ["topic_id"])
        op.create_index("ix_bcf_comment_guid", "oe_bcf_comment", ["guid"])

    # ── 3. oe_bcf_viewpoint ──────────────────────────────────────────
    if not _has_table(inspector, "oe_bcf_viewpoint"):
        op.create_table(
            "oe_bcf_viewpoint",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column("guid", sa.String(length=36), nullable=False),
            sa.Column(
                "topic_id",
                sa.String(length=36),
                sa.ForeignKey("oe_bcf_topic.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "vp_index",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "camera_type",
                sa.String(length=20),
                nullable=False,
                server_default="",
            ),
            sa.Column("camera", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("components", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("lines", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "clipping_planes",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "element_stable_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("snapshot_key", sa.String(length=500), nullable=True),
            sa.Column("snapshot_type", sa.String(length=20), nullable=True),
            sa.Column("field_of_view", sa.Float(), nullable=True),
            sa.Column("view_to_world_scale", sa.Float(), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("topic_id", "guid", name="uq_bcf_viewpoint_topic_guid"),
        )
        op.create_index("ix_bcf_viewpoint_topic", "oe_bcf_viewpoint", ["topic_id"])
        op.create_index("ix_bcf_viewpoint_guid", "oe_bcf_viewpoint", ["guid"])


def downgrade() -> None:
    """Drop the three BCF tables (reverse FK order)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "oe_bcf_viewpoint",
        "oe_bcf_comment",
        "oe_bcf_topic",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
