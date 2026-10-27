# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""quote_capture​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: captured supplier and subcontractor quotes

Creates ``oe_quote_capture_quote``: one row per uploaded quote with the stored
document key, the extracted header, lines and conditions (values, confidences,
source anchors and the machine's own readings), the review state and the
confirmation record. New table only; nothing existing changes.

Revision ID: v3327_quote_capture
Revises: v3326_subcontractor_insurance_compliance
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v3327_quote_capture"
down_revision: str | Sequence[str] | None = "v3326_subcontractor_insurance_compliance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_quote_capture_quote"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("package_id", sa.String(36), nullable=True),
        sa.Column("boq_id", sa.String(36), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("source_kind", sa.String(20), nullable=False, server_default="text"),
        sa.Column("original_filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("extraction_engine", sa.String(20), nullable=False, server_default="rules"),
        sa.Column("locale", sa.String(10), nullable=False, server_default=""),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("quote_total", sa.String(50), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("header", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("lines", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("document", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confirmation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("document_text", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(f"ix_{_T}_project_id", _T, ["project_id"])
    op.create_index("ix_quote_capture_project_status", _T, ["project_id", "status"])
    op.create_index("ix_quote_capture_package", _T, ["package_id"])


def downgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_T)
