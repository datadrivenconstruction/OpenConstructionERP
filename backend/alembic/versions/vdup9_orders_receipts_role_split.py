# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""one order and one receipt per delivery: event effects and stock identity on order lines

Creates ``oe_event_effect`` (once-only claims for event side effects), adds the
catalogue item and warehouse an order line is delivered against to
``oe_procurement_po_item``, and copies every supplier-catalogue order and
receipt into the procurement tables (``legacy_source``/``legacy_id`` identify a
copy, ``migrated_to_id`` points back). A row that cannot be mapped is written to
``oe_supplier_catalogs_migration_report`` and skipped. The legacy tables stay.

Revision ID: vdup9_orders_receipts_role_split
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdup9_orders_receipts_role_split"
down_revision: str | Sequence[str] | None = "vsci01_scim_provisioning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EFFECT = "oe_event_effect"
_ITEM = "oe_procurement_po_item"
_PO = "oe_procurement_po"
_GR = "oe_procurement_goods_receipt"
_REPORT = "oe_supplier_catalogs_migration_report"
_LEGACY_PO = "oe_supplier_catalogs_po"
_LEGACY_GR = "oe_supplier_catalogs_gr"
# procurement table -> name of its unique (legacy_source, legacy_id) constraint
_LEGACY_KEYS = {
    _PO: "uq_procurement_po_legacy",
    _ITEM: "uq_procurement_po_item_legacy",
    _GR: "uq_procurement_gr_legacy",
}


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _EFFECT not in insp.get_table_names():
        op.create_table(
            _EFFECT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("key", sa.String(200), nullable=False),
            sa.Column("effect", sa.String(100), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_event_effect_key", _EFFECT, ["key"], unique=True)

    have = _columns(_ITEM)
    if "catalog_item_id" not in have:
        op.add_column(_ITEM, sa.Column("catalog_item_id", sa.String(36), nullable=True))
        op.create_index("ix_oe_procurement_po_item_catalog_item_id", _ITEM, ["catalog_item_id"])
    if "warehouse_id" not in have:
        op.add_column(_ITEM, sa.Column("warehouse_id", sa.String(36), nullable=True))

    for table, constraint in _LEGACY_KEYS.items():
        cols = _columns(table)
        if "legacy_source" not in cols:
            op.add_column(table, sa.Column("legacy_source", sa.String(40), nullable=True))
        if "legacy_id" not in cols:
            op.add_column(table, sa.Column("legacy_id", sa.String(36), nullable=True))
        existing = {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints(table)}
        if constraint not in existing:
            op.create_unique_constraint(constraint, table, ["legacy_source", "legacy_id"])

    for table in (_LEGACY_PO, _LEGACY_GR):
        if "migrated_to_id" not in _columns(table):
            op.add_column(table, sa.Column("migrated_to_id", sa.String(36), nullable=True))
            op.create_index(f"ix_{table}_migrated_to_id", table, ["migrated_to_id"])

    if _REPORT not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            _REPORT,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(10), nullable=False),
            sa.Column("legacy_id", sa.String(36), nullable=False),
            sa.Column("reason", sa.Text, nullable=False, server_default=""),
            sa.UniqueConstraint("kind", "legacy_id", name="uq_sc_migration_report_row"),
        )
        op.create_index("ix_oe_supplier_catalogs_migration_report_project_id", _REPORT, ["project_id"])

    _copy_legacy_rows()


def _copy_legacy_rows() -> None:
    """One project at a time, each in its own savepoint: a bad project never stops the rest."""
    from app.modules.supplier_catalogs import legacy_migration as lm

    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if not {_LEGACY_PO, _LEGACY_GR, "oe_supplier_catalogs_vendor", "oe_supplier_catalogs_stock_movement"} <= tables:
        return
    for project_id in lm.pending_project_ids(conn):
        try:
            with conn.begin_nested():
                lm.migrate_project(conn, project_id)
        except Exception as exc:  # noqa: BLE001 - recorded, the other projects still run
            conn.execute(
                sa.text(
                    f"INSERT INTO {_REPORT} (id, project_id, kind, legacy_id, reason) "  # noqa: S608
                    "VALUES (:i, :p, 'project', :p, :r) ON CONFLICT (kind, legacy_id) DO NOTHING"
                ),
                {"i": str(uuid.uuid4()), "p": project_id, "r": str(exc)[:2000]},
            )


def downgrade() -> None:
    from app.modules.supplier_catalogs import legacy_migration as lm

    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if {_LEGACY_PO, _LEGACY_GR, "oe_supplier_catalogs_stock_movement"} <= tables and "legacy_source" in _columns(_PO):
        lm.revert_all(op.get_bind())
    if _REPORT in tables:
        op.drop_table(_REPORT)
    for table in (_LEGACY_PO, _LEGACY_GR):
        if "migrated_to_id" in _columns(table):
            op.drop_index(f"ix_{table}_migrated_to_id", table_name=table)
            op.drop_column(table, "migrated_to_id")
    for table, constraint in _LEGACY_KEYS.items():
        if "legacy_source" in _columns(table):
            op.drop_constraint(constraint, table, type_="unique")
            op.drop_column(table, "legacy_id")
            op.drop_column(table, "legacy_source")

    have = _columns(_ITEM)
    if "warehouse_id" in have:
        op.drop_column(_ITEM, "warehouse_id")
    if "catalog_item_id" in have:
        op.drop_index("ix_oe_procurement_po_item_catalog_item_id", table_name=_ITEM)
        op.drop_column(_ITEM, "catalog_item_id")
    if _EFFECT in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_EFFECT)
