# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — Broker + Escrow + PriceMatrix + Phase/Block hierarchy.

Adds eight new tables and four nullable Plot columns. Strictly additive
and inspector-guarded, so a fresh install with ``create_all`` already
applied is a no-op.

Tables:
    oe_property_dev_phase
    oe_property_dev_block
    oe_property_dev_broker
    oe_property_dev_commission_agreement
    oe_property_dev_commission_accrual
    oe_property_dev_escrow_account
    oe_property_dev_escrow_transaction
    oe_property_dev_price_matrix

Plot columns added (all nullable, default NULL):
    block_id, level_in_block, position_on_floor, computed_price

Down-revision: v3102_round5_merge.

Task #137 ships a sibling migration off the same v3102 head; the
ship-time merge step consolidates both into a single linear head.

Revision ID: v3104_propdev_broker_escrow_pricematrix_hierarchy
Revises: v3102_round5_merge
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3104_propdev_broker_escrow_pricematrix_hierarchy"
down_revision: Union[str, Sequence[str], None] = "v3102_round5_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Helpers ─────────────────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


# ── upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:  # noqa: C901 — sequential CREATE TABLEs, easier flat.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── Phase ───────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_phase"):
        op.create_table(
            "oe_property_dev_phase",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("planned_start", sa.String(20), nullable=True),
            sa.Column("planned_end", sa.String(20), nullable=True),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="planned",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "development_id",
                "code",
                name="uq_oe_property_dev_phase_dev_code",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_phase_development_id",
            "oe_property_dev_phase",
            ["development_id"],
        )
        op.create_index(
            "ix_oe_property_dev_phase_status",
            "oe_property_dev_phase",
            ["status"],
        )

    # ── Block ───────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_block"):
        op.create_table(
            "oe_property_dev_block",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "phase_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_phase.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "levels_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "units_per_level",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("orientation", sa.String(16), nullable=True),
            sa.Column("geo_coordinates", sa.JSON(), nullable=True),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="planned",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "phase_id",
                "code",
                name="uq_oe_property_dev_block_phase_code",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_block_phase_id",
            "oe_property_dev_block",
            ["phase_id"],
        )
        op.create_index(
            "ix_oe_property_dev_block_status",
            "oe_property_dev_block",
            ["status"],
        )

    # ── Broker ──────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_broker"):
        op.create_table(
            "oe_property_dev_broker",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("tenant_id", guid, nullable=True),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "license_number",
                sa.String(120),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "jurisdiction",
                sa.String(16),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "contact_email",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("contact_phone", sa.String(40), nullable=True),
            sa.Column(
                "default_commission_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "kyc_status",
                sa.String(20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "kyc_verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "license_number",
                name="uq_oe_property_dev_broker_tenant_license",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_broker_tenant_id",
            "oe_property_dev_broker",
            ["tenant_id"],
        )
        op.create_index(
            "ix_oe_property_dev_broker_license_number",
            "oe_property_dev_broker",
            ["license_number"],
        )
        op.create_index(
            "ix_oe_property_dev_broker_jurisdiction",
            "oe_property_dev_broker",
            ["jurisdiction"],
        )
        op.create_index(
            "ix_oe_property_dev_broker_kyc_status",
            "oe_property_dev_broker",
            ["kyc_status"],
        )
        op.create_index(
            "ix_oe_property_dev_broker_active",
            "oe_property_dev_broker",
            ["active"],
        )

    # ── CommissionAgreement ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_commission_agreement"):
        op.create_table(
            "oe_property_dev_commission_agreement",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "broker_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_broker.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=True,
            ),
            sa.Column("specific_plot_ids", sa.JSON(), nullable=True),
            sa.Column(
                "structure_type",
                sa.String(20),
                nullable=False,
                server_default="percent",
            ),
            sa.Column(
                "structure",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "accrual_trigger",
                sa.String(40),
                nullable=False,
                server_default="spa_signed",
            ),
            sa.Column(
                "payout_terms",
                sa.String(20),
                nullable=False,
                server_default="net30",
            ),
            sa.Column(
                "withholding_tax_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "effective_from",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column("effective_to", sa.String(20), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_commission_agreement_broker_id",
            "oe_property_dev_commission_agreement",
            ["broker_id"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_agreement_development_id",
            "oe_property_dev_commission_agreement",
            ["development_id"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_agreement_accrual_trigger",
            "oe_property_dev_commission_agreement",
            ["accrual_trigger"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_agreement_status",
            "oe_property_dev_commission_agreement",
            ["status"],
        )

    # ── CommissionAccrual ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_commission_accrual"):
        op.create_table(
            "oe_property_dev_commission_accrual",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "agreement_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_commission_agreement.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "broker_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_broker.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "trigger_event",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "trigger_entity_type",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
            sa.Column("trigger_entity_id", guid, nullable=True),
            sa.Column(
                "base_amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "commission_amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "state",
                sa.String(20),
                nullable=False,
                server_default="accrued",
            ),
            sa.Column(
                "accrued_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "approved_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("payment_ref", sa.String(255), nullable=True),
            sa.Column(
                "withholding_amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "net_payable",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_commission_accrual_agreement_id",
            "oe_property_dev_commission_accrual",
            ["agreement_id"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_accrual_broker_id",
            "oe_property_dev_commission_accrual",
            ["broker_id"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_accrual_state",
            "oe_property_dev_commission_accrual",
            ["state"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_accrual_trigger_event",
            "oe_property_dev_commission_accrual",
            ["trigger_event"],
        )
        op.create_index(
            "ix_oe_property_dev_commission_accrual_trigger_entity_id",
            "oe_property_dev_commission_accrual",
            ["trigger_entity_id"],
        )

    # ── EscrowAccount ───────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_escrow_account"):
        op.create_table(
            "oe_property_dev_escrow_account",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "regulator_ref",
                sa.String(40),
                nullable=False,
                server_default="other",
            ),
            sa.Column(
                "regulator_account_number",
                sa.String(120),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "bank_name",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("iban", sa.String(40), nullable=False, server_default=""),
            sa.Column(
                "swift_bic",
                sa.String(16),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "opened_at",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column("closed_at", sa.String(20), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "development_id",
                "currency",
                "regulator_ref",
                name="uq_oe_property_dev_escrow_dev_ccy_reg",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_escrow_account_development_id",
            "oe_property_dev_escrow_account",
            ["development_id"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_account_regulator_ref",
            "oe_property_dev_escrow_account",
            ["regulator_ref"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_account_is_active",
            "oe_property_dev_escrow_account",
            ["is_active"],
        )

    # ── EscrowTransaction ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_escrow_transaction"):
        op.create_table(
            "oe_property_dev_escrow_transaction",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "escrow_account_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_escrow_account.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "direction",
                sa.String(8),
                nullable=False,
                server_default="credit",
            ),
            sa.Column(
                "amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "source_type",
                sa.String(40),
                nullable=False,
                server_default="instalment",
            ),
            sa.Column("source_instalment_id", guid, nullable=True),
            sa.Column(
                "source_reference",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("bank_reference", sa.String(255), nullable=True),
            sa.Column(
                "transaction_date",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "reconciliation_state",
                sa.String(20),
                nullable=False,
                server_default="unreconciled",
            ),
            sa.Column(
                "reconciled_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("reconciled_by_user_id", guid, nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_escrow_transaction_escrow_account_id",
            "oe_property_dev_escrow_transaction",
            ["escrow_account_id"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_transaction_source_type",
            "oe_property_dev_escrow_transaction",
            ["source_type"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_transaction_source_instalment_id",
            "oe_property_dev_escrow_transaction",
            ["source_instalment_id"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_transaction_transaction_date",
            "oe_property_dev_escrow_transaction",
            ["transaction_date"],
        )
        op.create_index(
            "ix_oe_property_dev_escrow_transaction_reconciliation_state",
            "oe_property_dev_escrow_transaction",
            ["reconciliation_state"],
        )

    # ── PriceMatrix ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_price_matrix"):
        op.create_table(
            "oe_property_dev_price_matrix",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "base_price_per_m2",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "effective_from",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column("effective_to", sa.String(20), nullable=True),
            sa.Column(
                "rules",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        op.create_index(
            "ix_oe_property_dev_price_matrix_development_id",
            "oe_property_dev_price_matrix",
            ["development_id"],
        )
        op.create_index(
            "ix_oe_property_dev_price_matrix_effective_from",
            "oe_property_dev_price_matrix",
            ["effective_from"],
        )
        op.create_index(
            "ix_oe_property_dev_price_matrix_status",
            "oe_property_dev_price_matrix",
            ["status"],
        )

    # ── Plot columns (additive, nullable) ───────────────────────────────
    plot_table = "oe_property_dev_plot"
    if _has_table(inspector, plot_table):
        with op.batch_alter_table(plot_table) as batch_op:
            if not _has_column(inspector, plot_table, "block_id"):
                batch_op.add_column(sa.Column("block_id", guid, nullable=True))
            if not _has_column(inspector, plot_table, "level_in_block"):
                batch_op.add_column(sa.Column("level_in_block", sa.Integer(), nullable=True))
            if not _has_column(inspector, plot_table, "position_on_floor"):
                batch_op.add_column(sa.Column("position_on_floor", sa.String(40), nullable=True))
            if not _has_column(inspector, plot_table, "computed_price"):
                batch_op.add_column(sa.Column("computed_price", sa.Numeric(18, 2), nullable=True))
        # Refresh inspector cache after batch_alter — SQLAlchemy reuses the
        # old reflection until next inspect() call. Re-create the inspector
        # so the index guard below sees the freshly-added column.
        inspector = sa.inspect(op.get_bind())
        if _has_column(inspector, plot_table, "block_id") and not _has_index(
            inspector, plot_table, "ix_oe_property_dev_plot_block_id"
        ):
            op.create_index(
                "ix_oe_property_dev_plot_block_id",
                plot_table,
                ["block_id"],
            )


# ── downgrade ───────────────────────────────────────────────────────────


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Plot columns first — FK on block_id would otherwise block dropping
    # the block table.
    plot_table = "oe_property_dev_plot"
    if _has_index(inspector, plot_table, "ix_oe_property_dev_plot_block_id"):
        op.drop_index("ix_oe_property_dev_plot_block_id", table_name=plot_table)
    if _has_table(inspector, plot_table):
        with op.batch_alter_table(plot_table) as batch_op:
            if _has_column(inspector, plot_table, "computed_price"):
                batch_op.drop_column("computed_price")
            if _has_column(inspector, plot_table, "position_on_floor"):
                batch_op.drop_column("position_on_floor")
            if _has_column(inspector, plot_table, "level_in_block"):
                batch_op.drop_column("level_in_block")
            if _has_column(inspector, plot_table, "block_id"):
                batch_op.drop_column("block_id")

    inspector = sa.inspect(op.get_bind())
    for table in (
        "oe_property_dev_escrow_transaction",
        "oe_property_dev_escrow_account",
        "oe_property_dev_commission_accrual",
        "oe_property_dev_commission_agreement",
        "oe_property_dev_broker",
        "oe_property_dev_price_matrix",
        "oe_property_dev_block",
        "oe_property_dev_phase",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
