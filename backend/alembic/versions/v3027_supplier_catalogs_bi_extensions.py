# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""supplier_catalogs + bi_dashboards extensions for the 18-module deep-research pass.

Adds:

* ``oe_supplier_catalogs_commodity_code`` — UNSPSC/eClass/CPV lookup
* ``oe_supplier_catalogs_tolerance_profile`` — per-tenant 3-way match config
* ``oe_supplier_catalogs_kyc_document`` — region-aware vendor KYC docs
* ``oe_supplier_catalogs_scorecard`` — vendor performance scorecards
* ``oe_supplier_catalogs_invoice_line`` — line-level invoices (PEPPOL ingest)
* New columns on existing tables:
    - ``oe_supplier_catalogs_vendor.tolerance_profile_name``
    - ``oe_supplier_catalogs_catalog_item.gtin / commodity_code / commodity_scheme``
    - ``oe_supplier_catalogs_invoice.source / peppol_message_id / line_level_match_json``
    - ``oe_bi_dashboards_alert_rule.expression_json`` (composite alert DSL)
    - ``oe_bi_dashboards_saved_filter.shared_with_user_ids_json``
* New table:
    - ``oe_bi_dashboards_report_run`` — report execution audit + downloads

Idempotent — re-applying after ``Base.metadata.create_all`` has run is a
no-op. New columns are added with ``ALTER TABLE … ADD COLUMN`` guarded by
column-existence checks for SQLite portability.

Revision ID: v3027_supplier_catalogs_bi_extensions
Revises: v3026_bi_dashboards
Create Date: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3027_supplier_catalogs_bi_extensions"
down_revision: Union[str, Sequence[str], None] = "v3026_bi_dashboards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Helpers ─────────────────────────────────────────────────────────────


def _has_table(inspector: sa.engine.Inspector, name: str) -> bool:
    try:
        return name in inspector.get_table_names()
    except Exception:
        return False


def _has_column(
    inspector: sa.engine.Inspector,
    table: str,
    column: str,
) -> bool:
    try:
        return column in {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return False


def _add_column_safe(
    inspector: sa.engine.Inspector,
    table: str,
    column: sa.Column,
) -> None:
    if not _has_table(inspector, table):
        return
    if _has_column(inspector, table, column.name):
        return
    op.add_column(table, column)


def _create_index_safe(
    inspector: sa.engine.Inspector,
    name: str,
    table: str,
    columns: list[str],
    unique: bool = False,
) -> None:
    if not _has_table(inspector, table):
        return
    existing = {i.get("name") for i in inspector.get_indexes(table)}
    if name in existing:
        return
    try:
        op.create_index(name, table, columns, unique=unique)
    except sa.exc.OperationalError:
        pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Commodity codes ────────────────────────────────────────────
    if not _has_table(inspector, "oe_supplier_catalogs_commodity_code"):
        op.create_table(
            "oe_supplier_catalogs_commodity_code",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "scheme",
                sa.String(16),
                nullable=False,
                server_default="unspsc",
            ),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parent_code", sa.String(32), nullable=True),
            sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint(
                "scheme",
                "code",
                name="uq_supplier_catalogs_commodity_scheme_code",
            ),
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_commodity_scheme",
            "oe_supplier_catalogs_commodity_code",
            ["scheme"],
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_commodity_code_lookup",
            "oe_supplier_catalogs_commodity_code",
            ["code"],
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_commodity_parent",
            "oe_supplier_catalogs_commodity_code",
            ["parent_code"],
        )

    # ── Tolerance profiles ─────────────────────────────────────────
    if not _has_table(inspector, "oe_supplier_catalogs_tolerance_profile"):
        op.create_table(
            "oe_supplier_catalogs_tolerance_profile",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(64), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "price_tolerance_pct",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="2.0",
            ),
            sa.Column(
                "price_tolerance_abs",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "qty_tolerance_pct",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "period_tolerance_days",
                sa.Integer(),
                nullable=False,
                server_default="7",
            ),
            sa.Column(
                "require_gr",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )

    # ── KYC documents ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_supplier_catalogs_kyc_document"):
        op.create_table(
            "oe_supplier_catalogs_kyc_document",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("vendor_id", sa.String(36), nullable=False),
            sa.Column("doc_type", sa.String(32), nullable=False),
            sa.Column("document_number", sa.String(100), nullable=True),
            sa.Column("issued_on", sa.Date(), nullable=True),
            sa.Column("expires_on", sa.Date(), nullable=True),
            sa.Column("issuing_country", sa.String(8), nullable=True),
            sa.Column("issuing_authority", sa.String(255), nullable=True),
            sa.Column("file_url", sa.String(500), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="active",
            ),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_by", sa.String(36), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["oe_supplier_catalogs_vendor.id"],
                ondelete="CASCADE",
            ),
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_kyc_vendor",
            "oe_supplier_catalogs_kyc_document",
            ["vendor_id"],
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_kyc_expiry",
            "oe_supplier_catalogs_kyc_document",
            ["expires_on"],
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_kyc_status",
            "oe_supplier_catalogs_kyc_document",
            ["status"],
        )

    # ── Scorecards ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_supplier_catalogs_scorecard"):
        op.create_table(
            "oe_supplier_catalogs_scorecard",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("vendor_id", sa.String(36), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column(
                "delivery_score",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "quality_score",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "price_score",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "esg_score",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "composite_score",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "inputs_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "weights_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "computed_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["oe_supplier_catalogs_vendor.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "vendor_id",
                "period_start",
                "period_end",
                name="uq_supplier_catalogs_scorecard_vendor_period",
            ),
        )

    # ── Invoice lines ──────────────────────────────────────────────
    if not _has_table(inspector, "oe_supplier_catalogs_invoice_line"):
        op.create_table(
            "oe_supplier_catalogs_invoice_line",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("invoice_id", sa.String(36), nullable=False),
            sa.Column("po_line_id", sa.String(36), nullable=True),
            sa.Column("description", sa.String(500), nullable=False),
            sa.Column(
                "quantity",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "unit_of_measure",
                sa.String(20),
                nullable=False,
                server_default="pcs",
            ),
            sa.Column(
                "unit_price",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "line_total",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("vendor_sku", sa.String(100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["invoice_id"],
                ["oe_supplier_catalogs_invoice.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["po_line_id"],
                ["oe_supplier_catalogs_po_line.id"],
                ondelete="SET NULL",
            ),
        )
        _create_index_safe(
            inspector,
            "ix_supplier_catalogs_invoice_line_invoice",
            "oe_supplier_catalogs_invoice_line",
            ["invoice_id"],
        )

    # ── New columns on existing tables ─────────────────────────────
    inspector = sa.inspect(bind)  # refresh — we may have just created tables

    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_vendor",
        sa.Column(
            "tolerance_profile_name",
            sa.String(64),
            nullable=False,
            server_default="default",
        ),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_catalog_item",
        sa.Column("gtin", sa.String(20), nullable=True),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_catalog_item",
        sa.Column("commodity_code", sa.String(32), nullable=True),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_catalog_item",
        sa.Column(
            "commodity_scheme",
            sa.String(16),
            nullable=False,
            server_default="unspsc",
        ),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_invoice",
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="manual",
        ),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_invoice",
        sa.Column("peppol_message_id", sa.String(255), nullable=True),
    )
    _add_column_safe(
        inspector,
        "oe_supplier_catalogs_invoice",
        sa.Column(
            "line_level_match_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )

    # ── BI extensions ──────────────────────────────────────────────
    _add_column_safe(
        inspector,
        "oe_bi_dashboards_alert_rule",
        sa.Column(
            "expression_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    _add_column_safe(
        inspector,
        "oe_bi_dashboards_saved_filter",
        sa.Column(
            "shared_with_user_ids_json",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )

    if not _has_table(inspector, "oe_bi_dashboards_report_run"):
        op.create_table(
            "oe_bi_dashboards_report_run",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "report_definition_id",
                sa.String(36),
                nullable=False,
            ),
            sa.Column("schedule_id", sa.String(36), nullable=True),
            sa.Column(
                "triggered_by_user_id",
                sa.String(36),
                nullable=True,
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "finished_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "output_format",
                sa.String(16),
                nullable=False,
                server_default="pdf",
            ),
            sa.Column("file_path", sa.String(500), nullable=True),
            sa.Column(
                "file_size_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "row_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(16),
                nullable=False,
                server_default="running",
            ),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["report_definition_id"],
                ["oe_bi_dashboards_report_definition.id"],
                ondelete="CASCADE",
            ),
        )
        _create_index_safe(
            inspector,
            "ix_bi_dashboards_report_run_status",
            "oe_bi_dashboards_report_run",
            ["status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for tbl in (
        "oe_bi_dashboards_report_run",
        "oe_supplier_catalogs_invoice_line",
        "oe_supplier_catalogs_scorecard",
        "oe_supplier_catalogs_kyc_document",
        "oe_supplier_catalogs_tolerance_profile",
        "oe_supplier_catalogs_commodity_code",
    ):
        if _has_table(inspector, tbl):
            try:
                op.drop_table(tbl)
            except sa.exc.OperationalError:
                pass
