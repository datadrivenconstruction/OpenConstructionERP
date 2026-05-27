# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Live model→BOQ quantity binding — oe_boq_quantity_link table.

Adds the single table backing the model→position quantity-link feature.
A row is the *extraction rule* binding a BOQ position numeric field to
the canonical quantities of one or more BIM model elements, plus the
provenance of the last human-confirmed pull. The current quantity always
lives on ``oe_boq_position``; this table never caches it — it states how
to re-derive it when the source model revises (CLAUDE.md §7: AI/derived
proposes, human confirms).

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the
DDL. All ``id`` / ``*_id`` columns are ``String(36)`` to match the
platform's ``GUID`` TypeDecorator on SQLite + PostgreSQL.

Revision ID: v3039_quantity_links
Revises: v3038_bcf
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3039_quantity_links"
down_revision: Union[str, Sequence[str], None] = "v3038_bcf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_boq_quantity_link"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    """Create the oe_boq_quantity_link table (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

    op.create_table(
        _TABLE,
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
            "position_id",
            sa.String(length=36),
            sa.ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "boq_id",
            sa.String(length=36),
            sa.ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column(
            "element_stable_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("quantity_field", sa.String(length=64), nullable=False),
        sa.Column(
            "target_field",
            sa.String(length=32),
            nullable=False,
            server_default="quantity",
        ),
        sa.Column(
            "aggregation",
            sa.String(length=16),
            nullable=False,
            server_default="sum",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("source_model_version", sa.String(length=20), nullable=True),
        sa.Column("last_applied_quantity", sa.String(length=50), nullable=True),
        sa.Column("last_pulled_at", sa.String(length=40), nullable=True),
        sa.Column("last_applied_at", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("applied_by", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_oe_boq_quantity_link_position_id",
        _TABLE,
        ["position_id"],
    )
    op.create_index(
        "ix_boq_quantity_link_boq",
        _TABLE,
        ["boq_id"],
    )
    op.create_index(
        "ix_oe_boq_quantity_link_model_id",
        _TABLE,
        ["model_id"],
    )
    op.create_index(
        "ix_boq_quantity_link_status",
        _TABLE,
        ["status"],
    )


def downgrade() -> None:
    """Drop the oe_boq_quantity_link table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)
