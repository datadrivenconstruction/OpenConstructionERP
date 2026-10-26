# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""drawing_compare - stored revision compares and their changed regions.

Additive only:

* new table ``oe_drawing_compare_comparison``: one compare of an older and a newer revision
  of a drawing (PDF sheet or DWG/DXF version), with alignment, settings and a summary;
* new table ``oe_drawing_compare_change``: one changed region of a compare, with the
  reviewer's status and comment, the RFI or markup raised from it and the takeoff
  measurements, annotations and BOQ positions flagged for re-measure.

Inspector-guarded, so a database whose tables ``create_all`` already built does nothing.

Revision ID: v201_drawing_revision_compare
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_drawing_revision_compare"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPARISON = "oe_drawing_compare_comparison"
_CHANGE = "oe_drawing_compare_change"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    """Create both tables when missing."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _COMPARISON not in tables:
        op.create_table(
            _COMPARISON,
            *_stamps(),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_kind", sa.String(8), nullable=False, server_default="pdf"),
            sa.Column("old_ref_id", sa.String(64), nullable=False),
            sa.Column("new_ref_id", sa.String(64), nullable=False),
            sa.Column("old_page", sa.Integer(), nullable=True),
            sa.Column("new_page", sa.Integer(), nullable=True),
            sa.Column("old_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("new_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("old_revision", sa.String(50), nullable=True),
            sa.Column("new_revision", sa.String(50), nullable=True),
            sa.Column("page_width", sa.Float(), nullable=True),
            sa.Column("page_height", sa.Float(), nullable=True),
            sa.Column("alignment", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index(f"ix_{_COMPARISON}_project_id", _COMPARISON, ["project_id"])
        op.create_index("ix_drawing_compare_refs", _COMPARISON, ["project_id", "old_ref_id", "new_ref_id"])
    if _CHANGE not in tables:
        op.create_table(
            _CHANGE,
            *_stamps(),
            sa.Column(
                "comparison_id",
                GUID(),
                sa.ForeignKey(f"{_COMPARISON}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("page", sa.Integer(), nullable=True),
            sa.Column("x", sa.Float(), nullable=False, server_default="0"),
            sa.Column("y", sa.Float(), nullable=False, server_default="0"),
            sa.Column("w", sa.Float(), nullable=False, server_default="0"),
            sa.Column("h", sa.Float(), nullable=False, server_default="0"),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("old_text", sa.Text(), nullable=True),
            sa.Column("new_text", sa.Text(), nullable=True),
            sa.Column("layer", sa.String(255), nullable=True),
            sa.Column("entity_type", sa.String(64), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("thumbnail", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("rfi_id", sa.String(36), nullable=True),
            sa.Column("markup_id", sa.String(36), nullable=True),
            sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("flagged_measurement_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("flagged_annotation_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("flagged_position_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_CHANGE}_comparison_id", _CHANGE, ["comparison_id"])


def downgrade() -> None:
    """Drop both tables."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _CHANGE in tables:
        op.drop_table(_CHANGE)
    if _COMPARISON in tables:
        op.drop_table(_COMPARISON)
