# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""procurement - requisition approvals, order owner, external orders and change feed.

Additive only, no data rewrite (issue #516):

* ``oe_procurement_requisition`` gains five nullable columns: ``order_owner`` (``ocerp`` or ``external``,
  null reads as ``ocerp``), ``approval_chain`` (designated approvers in order), ``approval_step`` (how many
  of them approved this round), ``row_version`` (bumped with every change feed entry) and
  ``client_request_id`` (indexed, makes a create idempotent).
* ``oe_procurement_project_settings``: one row per project with its order owner and default approvers. A
  project without a row reads as ``ocerp`` with no designated approvers.
* ``oe_procurement_req_ext_line``: order lines an external purchasing system reported against a
  requisition line. No purchase order or commitment is created for them.
* ``oe_procurement_req_change``: the replayable change feed, written in the transaction of each change.

Pip and desktop installs never run this revision: ``create_all`` builds the tables and the boot heal adds
the nullable columns. Every step is inspector-guarded, so a database that already has them reaches this
revision without error.

Revision ID: v96_requisition_orders_approvals_feed
Revises: v95_costmodel_forecast_documentation
Create Date: 2026-10-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v96_requisition_orders_approvals_feed"
down_revision: str | Sequence[str] | None = "v95_costmodel_forecast_documentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQ = "oe_procurement_requisition"
_ITEM = "oe_procurement_req_item"
_SETTINGS = "oe_procurement_project_settings"
_EXT = "oe_procurement_req_ext_line"
_CHANGE = "oe_procurement_req_change"

#: (column, type factory, index name or None) added to the requisition table.
_REQ_COLUMNS: list[tuple[str, object, str | None]] = [
    ("order_owner", lambda: sa.String(length=20), None),
    ("approval_chain", sa.JSON, None),
    ("approval_step", sa.Integer, None),
    ("row_version", sa.Integer, None),
    ("client_request_id", lambda: sa.String(length=100), "ix_oe_procurement_requisition_client_request_id"),
]


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _ensure_indexes(bind: sa.engine.Connection, table: str, wanted: tuple[tuple[str, list[str], bool], ...]) -> None:
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes(table)}
    for name, cols, unique in wanted:
        if name not in existing:
            op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    """Add the requisition columns and create the three tables, each only when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if _REQ in tables:
        columns = {c["name"] for c in sa.inspect(bind).get_columns(_REQ)}
        for column, type_factory, index_name in _REQ_COLUMNS:
            if column not in columns:
                op.add_column(_REQ, sa.Column(column, type_factory(), nullable=True))  # type: ignore[operator]
            if index_name is not None:
                _ensure_indexes(bind, _REQ, ((index_name, [column], False),))

    if _SETTINGS not in tables:
        op.create_table(
            _SETTINGS,
            *_base_columns(),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("order_owner", sa.String(20), nullable=False, server_default="ocerp"),
            sa.Column("default_approval_chain", sa.JSON(), nullable=True),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_procurement_project_settings"),
        )
    _ensure_indexes(bind, _SETTINGS, (("ix_oe_procurement_project_settings_project_id", ["project_id"], True),))

    if _EXT not in tables and _REQ in tables and _ITEM in tables:
        op.create_table(
            _EXT,
            *_base_columns(),
            sa.Column(
                "requisition_id",
                GUID(),
                sa.ForeignKey(f"{_REQ}.id", ondelete="CASCADE", name="fk_oe_procurement_req_ext_line_req"),
                nullable=False,
            ),
            sa.Column(
                "requisition_item_id",
                GUID(),
                sa.ForeignKey(f"{_ITEM}.id", ondelete="CASCADE", name="fk_oe_procurement_req_ext_line_item"),
                nullable=False,
            ),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("external_system", sa.String(100), nullable=False),
            sa.Column("external_order_number", sa.String(100), nullable=False),
            sa.Column("external_line_ref", sa.String(100), nullable=False, server_default=""),
            sa.Column("status", sa.String(30), nullable=False, server_default="open"),
            sa.Column("quantity_ordered", sa.String(50), nullable=False, server_default="0"),
            sa.Column("quantity_received", sa.String(50), nullable=False, server_default="0"),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column("expected_delivery_date", sa.String(40), nullable=True),
            sa.Column("confirmed_delivery_date", sa.String(40), nullable=True),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_procurement_req_ext_line"),
            sa.UniqueConstraint(
                "requisition_item_id",
                "external_system",
                "external_order_number",
                "external_line_ref",
                name="uq_procurement_req_ext_line_key",
            ),
        )
    if _EXT in set(sa.inspect(bind).get_table_names()):
        _ensure_indexes(
            bind,
            _EXT,
            (
                ("ix_oe_procurement_req_ext_line_requisition_id", ["requisition_id"], False),
                ("ix_oe_procurement_req_ext_line_requisition_item_id", ["requisition_item_id"], False),
                ("ix_oe_procurement_req_ext_line_project_id", ["project_id"], False),
            ),
        )

    if _CHANGE not in tables:
        op.create_table(
            _CHANGE,
            *_base_columns(),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("requisition_id", GUID(), nullable=False),
            sa.Column("req_number", sa.String(50), nullable=True),
            sa.Column("event", sa.String(50), nullable=False),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.PrimaryKeyConstraint("id", name="pk_oe_procurement_req_change"),
        )
    _ensure_indexes(
        bind,
        _CHANGE,
        (
            ("ix_procurement_req_change_cursor", ["project_id", "created_at", "id"], False),
            ("ix_oe_procurement_req_change_requisition_id", ["requisition_id"], False),
        ),
    )


def downgrade() -> None:
    """Drop the three tables, then the requisition columns, each only when present."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for table in (_CHANGE, _EXT, _SETTINGS):
        if table in tables:
            op.drop_table(table)
    if _REQ not in tables:
        return
    for column, _type_factory, index_name in reversed(_REQ_COLUMNS):
        if index_name is not None and index_name in {ix["name"] for ix in sa.inspect(bind).get_indexes(_REQ)}:
            op.drop_index(index_name, table_name=_REQ)
        if column in {c["name"] for c in sa.inspect(bind).get_columns(_REQ)}:
            with op.batch_alter_table(_REQ) as batch:
                batch.drop_column(column)
