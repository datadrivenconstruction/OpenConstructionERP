# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence initial schema.

Creates ``oe_comms_intelligence_analysis`` and
``oe_comms_intelligence_draft``. Idempotent and inspector-guarded so
re-runs on a partially-migrated DB are safe. SQLite-friendly.

Move this file into ``backend/alembic/versions/`` and set
``down_revision`` to the current head before running
``alembic upgrade head``.

Revision ID: oe_comms_intelligence_v0001_initial
Revises: <FILL_IN_CURRENT_HEAD>
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_comms_intelligence_v0001_initial"
down_revision: Union[str, Sequence[str], None] = None  # set to current head!
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ANALYSIS = "oe_comms_intelligence_analysis"
_DRAFT = "oe_comms_intelligence_draft"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _ANALYSIS):
        op.create_table(
            _ANALYSIS,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("correspondence_id", sa.String(36), nullable=False),
            sa.Column("reference_number", sa.String(50), nullable=False, server_default=""),
            sa.Column("category", sa.String(32), nullable=False, server_default="general"),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("extracted", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("suggestions", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("reply_needed", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="suggested"),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
            sa.Column("reviewed_at", sa.String(40), nullable=True),
            sa.Column("applied", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("source", sa.String(20), nullable=False, server_default="heuristic"),
            sa.Column("model_name", sa.String(128), nullable=False, server_default=""),
            sa.Column("prompt_version", sa.String(16), nullable=False, server_default="v1.0"),
            sa.Column("raw_response", sa.Text(), nullable=False, server_default=""),
            sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cost_usd_estimate", sa.Numeric(10, 4), nullable=False, server_default="0.0"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                "correspondence_id",
                name="uq_oe_comms_intelligence_analysis_correspondence",
            ),
            sa.CheckConstraint(
                "confidence >= 0.0 AND confidence <= 1.0",
                name="ck_comms_intel_analysis_confidence_range",
            ),
        )
        op.create_index(f"ix_{_ANALYSIS}_project_id", _ANALYSIS, ["project_id"])
        op.create_index(f"ix_{_ANALYSIS}_correspondence_id", _ANALYSIS, ["correspondence_id"])
        op.create_index(f"ix_{_ANALYSIS}_status", _ANALYSIS, ["status"])
        op.create_index("ix_comms_intel_analysis_project_status", _ANALYSIS, ["project_id", "status"])

    if not _has_table(inspector, _DRAFT):
        op.create_table(
            _DRAFT,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("correspondence_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(16), nullable=False, server_default="reply"),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("subject", sa.String(500), nullable=False, server_default=""),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="suggested"),
            sa.Column("source", sa.String(20), nullable=False, server_default="template"),
            sa.Column("model_name", sa.String(128), nullable=False, server_default=""),
            sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(f"ix_{_DRAFT}_project_id", _DRAFT, ["project_id"])
        op.create_index(f"ix_{_DRAFT}_correspondence_id", _DRAFT, ["correspondence_id"])
        op.create_index(
            "ix_comms_intel_draft_correspondence_created",
            _DRAFT,
            ["correspondence_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _DRAFT):
        op.drop_table(_DRAFT)
    if _has_table(inspector, _ANALYSIS):
        op.drop_table(_ANALYSIS)
