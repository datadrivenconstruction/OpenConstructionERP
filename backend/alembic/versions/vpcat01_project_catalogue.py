# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""project catalogue: a project's own rates with provenance

Additive new table only, so a deploy that heals its schema at boot picks it up
without ``alembic upgrade``.

Revision ID: vpcat01_project_catalogue
Revises: vdt02_doc_template_issues
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpcat01_project_catalogue"
down_revision: str | Sequence[str] | None = "vdt02_doc_template_issues"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_project_catalogue_item"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False, server_default=""),
        sa.Column("item_type", sa.String(20), nullable=False, server_default="work"),
        sa.Column("rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("source_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("source_code", sa.String(100), nullable=False, server_default=""),
        sa.Column("source_rate", sa.Numeric(18, 4), nullable=True),
        sa.Column("source_currency", sa.String(10), nullable=False, server_default=""),
        sa.Column("source_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.UniqueConstraint("project_id", "source_type", "source_id", name="uq_oe_project_catalogue_item_source"),
    )
    op.create_index("ix_oe_project_catalogue_item_project_code", _T, ["project_id", "code"])


def downgrade() -> None:
    op.drop_index("ix_oe_project_catalogue_item_project_code", table_name=_T)
    op.drop_table(_T)
