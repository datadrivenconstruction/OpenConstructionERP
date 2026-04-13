"""add bim_element_group table

Creates ``oe_bim_element_group`` — saved/named selections of BIM elements
that can be referenced from BOQ, schedule, validation, etc. Uses the same
idempotent ``CREATE TABLE IF NOT EXISTS`` pattern as the v090 migration so
it is safe to re-run against dev SQLite databases where ``Base.metadata
.create_all`` may already have created the table.

Revision ID: f22fa2934807
Revises: v090_new_modules
Create Date: 2026-04-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f22fa2934807"
down_revision: Union[str, None] = "v090_new_modules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


# ---------------------------------------------------------------------------
# Helpers (mirrored from v090_add_all_new_modules for idempotent DDL)
# ---------------------------------------------------------------------------


def _create_if_not_exists(table_name: str, *columns: sa.Column, **kw) -> None:  # noqa: ANN003
    """Create a table only if it does not already exist."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table_name not in insp.get_table_names():
        op.create_table(table_name, *columns, **kw)


def _pk() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _meta() -> sa.Column:
    return sa.Column("metadata", sa.JSON, nullable=False, server_default="{}")


def upgrade() -> None:
    _create_if_not_exists(
        "oe_bim_element_group",
        _pk(),
        sa.Column("project_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "model_id",
            sa.String(36),
            sa.ForeignKey("oe_bim_model.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_dynamic", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("filter_criteria", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("element_ids", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("element_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        _meta(),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "name", name="uq_bim_element_group_project_name"),
        sa.Index("ix_bim_element_group_project", "project_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "oe_bim_element_group" in insp.get_table_names():
        op.drop_table("oe_bim_element_group")
