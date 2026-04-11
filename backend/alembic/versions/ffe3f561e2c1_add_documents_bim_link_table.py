"""add documents_bim_link table

Creates ``oe_documents_bim_link`` — links between Documents and BIM elements
so drawings, specs, and photos can be referenced from the 3D viewer and from
the Documents hub. Mirrors the ``oe_bim_boq_link`` pattern.

Uses the same idempotent ``CREATE TABLE IF NOT EXISTS`` helper as the v090
and bim_element_group migrations so it is safe to re-run against dev SQLite
databases where ``Base.metadata.create_all`` may already have created the
table.

Revision ID: ffe3f561e2c1
Revises: f22fa2934807
Create Date: 2026-04-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ffe3f561e2c1"
down_revision: Union[str, None] = "f22fa2934807"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
        "oe_documents_bim_link",
        _pk(),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("oe_documents_document.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "bim_element_id",
            sa.String(36),
            sa.ForeignKey("oe_bim_element.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "link_type",
            sa.String(50),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("confidence", sa.String(10), nullable=True),
        sa.Column("region_bbox", sa.JSON, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        _meta(),
        *_timestamps(),
        sa.UniqueConstraint(
            "document_id",
            "bim_element_id",
            name="uq_documents_bim_link_doc_elem",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "oe_documents_bim_link" in insp.get_table_names():
        op.drop_table("oe_documents_bim_link")
