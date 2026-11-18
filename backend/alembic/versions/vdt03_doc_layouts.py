# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""doc_templates - block layouts of record documents, their versions and the clause library.

Three new tables: ``oe_doc_templates_layout`` (model ``DocLayout``: kind, scope
``workspace`` or ``project:<uuid>``, variant, draft, published version pointer),
``oe_doc_templates_layout_version`` (model ``DocLayoutVersion``: immutable
published layouts) and ``oe_doc_templates_clause`` (model ``DocClause``).

This one does NOT need running by hand. It adds tables and nothing else, and
``Base.metadata.create_all`` creates them on a running install from the
models. Inspector-guarded, so a re-run or a downgrade on a database without
the tables changes nothing.

Revision ID: vdt03_doc_layouts
Revises: vcnf01_china_fee_profile
Create Date: 2026-11-18
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vdt03_doc_layouts"
down_revision: Union[str, Sequence[str], None] = "vcnf01_china_fee_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LAYOUT = "oe_doc_templates_layout"
_VERSION = "oe_doc_templates_layout_version"
_CLAUSE = "oe_doc_templates_clause"
_GUID = sa.String(36)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Create the layout, layout version and clause tables."""
    existing = _tables()
    if _LAYOUT not in existing:
        op.create_table(
            _LAYOUT,
            *_stamps(),
            sa.Column("kind", sa.String(120), nullable=False),
            sa.Column("scope", sa.String(60), nullable=False, server_default="workspace"),
            sa.Column("variant", sa.String(40), nullable=False, server_default="standard"),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("draft", sa.JSON(), nullable=True),
            sa.Column("draft_updated_by", sa.String(36), nullable=True),
            sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_version_id", _GUID, nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_LAYOUT}"),
            sa.UniqueConstraint("kind", "scope", "variant", name="uq_doc_templates_layout_kind_scope_variant"),
        )
        op.create_index(f"ix_{_LAYOUT}_kind", _LAYOUT, ["kind"])
    if _VERSION not in existing:
        op.create_table(
            _VERSION,
            *_stamps(),
            sa.Column("layout_id", _GUID, nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("document", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("action", sa.String(20), nullable=False, server_default="publish"),
            sa.Column("note", sa.String(500), nullable=False, server_default=""),
            sa.Column("author_id", sa.String(36), nullable=True),
            sa.Column("author_name", sa.String(255), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_VERSION}"),
            sa.ForeignKeyConstraint(
                ["layout_id"],
                [f"{_LAYOUT}.id"],
                name=f"fk_{_VERSION}_layout_id_{_LAYOUT}",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("layout_id", "number", name="uq_doc_templates_layout_version_number"),
        )
        op.create_index(f"ix_{_VERSION}_layout_id", _VERSION, ["layout_id"])
    if _CLAUSE not in existing:
        op.create_table(
            _CLAUSE,
            *_stamps(),
            sa.Column("key", sa.String(40), nullable=False),
            sa.Column("category", sa.String(40), nullable=False, server_default=""),
            sa.Column("title", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("text", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_CLAUSE}"),
            sa.UniqueConstraint("key", name="uq_doc_templates_clause_key"),
        )


def downgrade() -> None:
    """Drop the three tables."""
    existing = _tables()
    if _CLAUSE in existing:
        op.drop_table(_CLAUSE)
    if _VERSION in existing:
        op.drop_index(f"ix_{_VERSION}_layout_id", table_name=_VERSION)
        op.drop_table(_VERSION)
    if _LAYOUT in existing:
        op.drop_index(f"ix_{_LAYOUT}_kind", table_name=_LAYOUT)
        op.drop_table(_LAYOUT)
