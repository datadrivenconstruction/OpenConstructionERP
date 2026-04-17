"""v1.9.1 -- add oe_dwg_entity_group table for RFC 11.

Adds ``oe_dwg_entity_group`` — saved multi-entity selections on a DWG
drawing. Enables the new DWG group-to-BOQ linking flow introduced in
RFC 11. Uses the same idempotent ``CREATE TABLE IF NOT EXISTS`` pattern
as the v090 / bim_element_group migrations so it is safe to re-run
against SQLite dev databases where ``Base.metadata.create_all`` may
already have created the table.

Revision ID: v191_dwg_entity_groups
Revises: v191_meetings_document_ids
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v191_dwg_entity_groups"
down_revision: Union[str, None] = "v191_meetings_document_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_dwg_entity_group"


def _create_if_not_exists(table_name: str, *columns: sa.Column, **kw) -> None:  # noqa: ANN003
    """Create a table only if it does not already exist."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table_name not in insp.get_table_names():
        op.create_table(table_name, *columns, **kw)


def upgrade() -> None:
    _create_if_not_exists(
        TABLE_NAME,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "drawing_id",
            sa.String(36),
            sa.ForeignKey("oe_dwg_takeoff_drawing.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("entity_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Index("ix_dwg_entity_group_drawing", "drawing_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE_NAME in insp.get_table_names():
        op.drop_table(TABLE_NAME)
