# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost Spine schema (v6.4 keystone).

Adds the two Cost Spine tables and the additive linkage columns that wire the
existing cost-domain entities to a single canonical cost line:

* ``oe_costmodel_control_account`` - the Cost Breakdown Structure tree.
* ``oe_costmodel_cost_line`` - one row per scope item; the join point for
  estimate / budget / committed / actual / claimed money.

Linkage columns (all nullable, indexed, additive):

* ``oe_costmodel_budget_line.cost_line_id`` + ``.control_account_id``
* ``oe_boq_position.cost_line_id``
* ``oe_procurement_po_item.cost_line_id``
* ``oe_procurement_req_item.cost_line_id``
* ``oe_contracts_contract_line.cost_line_id``
* ``oe_rfq_rfq.cost_line_ids`` (JSON array, NOT NULL, default ``[]``)

Every operation is guarded so the migration is safe to re-run on a partially
applied install, and a fresh install that boots the app first already has all
of this via ``Base.metadata.create_all``. The downgrade fully reverses the
upgrade so a stamp roundtrip leaves the schema unchanged.

Revision ID: v3151_cost_spine
Revises: v3150_file_favorites
Create Date: 2026-06-01
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3151_cost_spine"
down_revision: Union[str, None] = "v3150_file_favorites"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def _index_exists(bind: sa.engine.Connection, table: str, index: str) -> bool:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _column_exists(bind: sa.engine.Connection, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


# ── Linkage columns: (table, column, sqlalchemy column factory) ───────────────
# GUID columns map to String(36) (matching the GUID TypeDecorator impl); the
# RFQ link is a JSON array. All are nullable/additive except the RFQ array,
# which is NOT NULL with a ``[]`` server_default so existing rows are valid.
_LINKAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("oe_costmodel_budget_line", "cost_line_id"),
    ("oe_costmodel_budget_line", "control_account_id"),
    ("oe_boq_position", "cost_line_id"),
    ("oe_procurement_po_item", "cost_line_id"),
    ("oe_procurement_req_item", "cost_line_id"),
    ("oe_contracts_contract_line", "cost_line_id"),
)


def _linkage_index_name(table: str, column: str) -> str:
    return f"ix_{table}_{column}"


def upgrade() -> None:
    bind = op.get_bind()

    # ── Table 1: control accounts ────────────────────────────────────────
    if not _table_exists(bind, "oe_costmodel_control_account"):
        op.create_table(
            "oe_costmodel_control_account",
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
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "parent_id",
                sa.String(length=36),
                sa.ForeignKey("oe_costmodel_control_account.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column(
                "classification_standard",
                sa.String(length=40),
                nullable=False,
                server_default="",
            ),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "project_id",
                "code",
                name="uq_costmodel_ctrl_acct_project_code",
            ),
        )

    # ── Table 2: cost lines ──────────────────────────────────────────────
    if not _table_exists(bind, "oe_costmodel_cost_line"):
        op.create_table(
            "oe_costmodel_cost_line",
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
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "control_account_id",
                sa.String(length=36),
                sa.ForeignKey("oe_costmodel_control_account.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(length=20), nullable=True),
            sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
            sa.Column("boq_position_id", sa.String(length=36), nullable=True),
            sa.Column("boq_id", sa.String(length=36), nullable=True),
            sa.Column("estimate_quantity", sa.String(length=50), nullable=False, server_default="0"),
            sa.Column("estimate_unit_rate", sa.String(length=50), nullable=False, server_default="0"),
            sa.Column("estimate_amount", sa.String(length=50), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(length=10), nullable=False, server_default=""),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint(
                "project_id",
                "code",
                name="uq_costmodel_cost_line_project_code",
            ),
        )

    # ── Composite + single-column indexes on the new tables ──────────────
    if not _index_exists(bind, "oe_costmodel_control_account", "ix_costmodel_ctrl_acct_project_parent"):
        op.create_index(
            "ix_costmodel_ctrl_acct_project_parent",
            "oe_costmodel_control_account",
            ["project_id", "parent_id"],
        )
    if not _index_exists(bind, "oe_costmodel_control_account", "ix_costmodel_ctrl_acct_project_id"):
        op.create_index(
            "ix_costmodel_ctrl_acct_project_id",
            "oe_costmodel_control_account",
            ["project_id"],
        )
    if not _index_exists(bind, "oe_costmodel_control_account", "ix_costmodel_ctrl_acct_parent_id"):
        op.create_index(
            "ix_costmodel_ctrl_acct_parent_id",
            "oe_costmodel_control_account",
            ["parent_id"],
        )
    if not _index_exists(bind, "oe_costmodel_control_account", "ix_costmodel_ctrl_acct_status"):
        op.create_index(
            "ix_costmodel_ctrl_acct_status",
            "oe_costmodel_control_account",
            ["status"],
        )

    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_proj_acct"):
        op.create_index(
            "ix_costmodel_cost_line_proj_acct",
            "oe_costmodel_cost_line",
            ["project_id", "control_account_id"],
        )
    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_project_id"):
        op.create_index(
            "ix_costmodel_cost_line_project_id",
            "oe_costmodel_cost_line",
            ["project_id"],
        )
    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_control_account_id"):
        op.create_index(
            "ix_costmodel_cost_line_control_account_id",
            "oe_costmodel_cost_line",
            ["control_account_id"],
        )
    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_status"):
        op.create_index(
            "ix_costmodel_cost_line_status",
            "oe_costmodel_cost_line",
            ["status"],
        )
    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_source"):
        op.create_index(
            "ix_costmodel_cost_line_source",
            "oe_costmodel_cost_line",
            ["source"],
        )
    if not _index_exists(bind, "oe_costmodel_cost_line", "ix_costmodel_cost_line_boq_position_id"):
        op.create_index(
            "ix_costmodel_cost_line_boq_position_id",
            "oe_costmodel_cost_line",
            ["boq_position_id"],
        )

    # ── Additive single-FK linkage columns + their indexes ───────────────
    for table, column in _LINKAGE_COLUMNS:
        if not _column_exists(bind, table, column):
            op.add_column(
                table,
                sa.Column(column, sa.String(length=36), nullable=True),
            )
        index_name = _linkage_index_name(table, column)
        if not _index_exists(bind, table, index_name):
            op.create_index(index_name, table, [column])

    # ── RFQ many-valued linkage column (JSON array, NOT NULL default []) ──
    if not _column_exists(bind, "oe_rfq_rfq", "cost_line_ids"):
        op.add_column(
            "oe_rfq_rfq",
            sa.Column("cost_line_ids", sa.JSON(), nullable=False, server_default="[]"),
        )

    logger.info("v3151 cost_spine: control accounts + cost lines + linkage columns ensured")


def _drop_table(bind, table: str) -> None:
    """Drop ``table``; on PostgreSQL also the foreign keys later tables hold on it.

    A schema built from the models carries tables added after this revision that
    point at these two; a plain DROP would refuse, and those constraints go with
    the tables anyway when their own revisions are downgraded first.
    """
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f'DROP TABLE "{table}" CASCADE'))
    else:
        op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()

    # ── RFQ JSON linkage column ──────────────────────────────────────────
    if _column_exists(bind, "oe_rfq_rfq", "cost_line_ids"):
        with op.batch_alter_table("oe_rfq_rfq") as batch:
            batch.drop_column("cost_line_ids")

    # ── Single-FK linkage columns + indexes ──────────────────────────────
    for table, column in _LINKAGE_COLUMNS:
        index_name = _linkage_index_name(table, column)
        if _index_exists(bind, table, index_name):
            op.drop_index(index_name, table_name=table)
        if _column_exists(bind, table, column):
            # SQLite cannot DROP COLUMN without table rebuild; batch handles it.
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)

    # ── Cost lines table (drop indexes first, then the table) ────────────
    if _table_exists(bind, "oe_costmodel_cost_line"):
        for index_name in (
            "ix_costmodel_cost_line_boq_position_id",
            "ix_costmodel_cost_line_source",
            "ix_costmodel_cost_line_status",
            "ix_costmodel_cost_line_control_account_id",
            "ix_costmodel_cost_line_project_id",
            "ix_costmodel_cost_line_proj_acct",
        ):
            if _index_exists(bind, "oe_costmodel_cost_line", index_name):
                op.drop_index(index_name, table_name="oe_costmodel_cost_line")
        _drop_table(bind, "oe_costmodel_cost_line")

    # ── Control accounts table ───────────────────────────────────────────
    if _table_exists(bind, "oe_costmodel_control_account"):
        for index_name in (
            "ix_costmodel_ctrl_acct_status",
            "ix_costmodel_ctrl_acct_parent_id",
            "ix_costmodel_ctrl_acct_project_id",
            "ix_costmodel_ctrl_acct_project_parent",
        ):
            if _index_exists(bind, "oe_costmodel_control_account", index_name):
                op.drop_index(index_name, table_name="oe_costmodel_control_account")
        _drop_table(bind, "oe_costmodel_control_account")

    logger.info("v3151 cost_spine: reverted")
