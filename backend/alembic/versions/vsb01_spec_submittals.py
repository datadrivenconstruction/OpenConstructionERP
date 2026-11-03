# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""spec book imports and proposed submittals

Creates ``oe_submittals_spec_import`` (one parse of a specification book) and
``oe_submittals_spec_proposal`` (a proposed submittal with a confidence and a
decision; nothing reaches the register until a person confirms it).

Revision ID: vsb01_spec_submittals
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsb01_spec_submittals"
down_revision: str | Sequence[str] | None = "vai01_doc_assistant_agent_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMPORT = "oe_submittals_spec_import"
_PROPOSAL = "oe_submittals_spec_proposal"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _IMPORT not in tables:
        op.create_table(
            _IMPORT,
            *_base(),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("document_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="uploaded"),
            sa.Column("parser_version", sa.String(20), nullable=False, server_default=""),
            sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pages_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pages_done", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_code", sa.String(50), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index(f"ix_{_IMPORT}_project_id", _IMPORT, ["project_id"])
        op.create_index(f"ix_{_IMPORT}_document_id", _IMPORT, ["document_id"])
    if _PROPOSAL not in tables:
        op.create_table(
            _PROPOSAL,
            *_base(),
            sa.Column(
                "import_id",
                sa.String(36),
                sa.ForeignKey(f"{_IMPORT}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("spec_section", sa.String(100), nullable=False, server_default=""),
            sa.Column("section_title", sa.String(500), nullable=False, server_default=""),
            sa.Column("kind", sa.String(30), nullable=False, server_default=""),
            sa.Column("submittal_type", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("source_page", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_excerpt", sa.String(2000), nullable=False, server_default=""),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("decision", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("submittal_id", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_PROPOSAL}_import_id", _PROPOSAL, ["import_id"])
        op.create_index(f"ix_{_PROPOSAL}_project_id", _PROPOSAL, ["project_id"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_PROPOSAL, _IMPORT):
        if table in tables:
            op.drop_table(table)
