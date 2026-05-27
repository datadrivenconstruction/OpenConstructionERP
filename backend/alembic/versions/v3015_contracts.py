# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""contracts — Multi-type Contract Types Engine schema.

Adds ten tables that back the contract types engine:

    oe_contracts_contract                  — contract header
    oe_contracts_contract_line             — schedule of values lines
    oe_contracts_type_configuration        — per-type allowed-field catalog
    oe_contracts_retention_schedule        — retention accrual / release rules
    oe_contracts_fee_structure             — fee structures (cost-plus / T&M)
    oe_contracts_gainshare_configuration   — GMP gainshare / savings-split
    oe_contracts_ld_clause                 — liquidated-damages clauses
    oe_contracts_progress_claim            — periodic progress claims
    oe_contracts_progress_claim_line       — line-level claim breakdown
    oe_contracts_final_account             — close-out / final account

counterparty_id and milestone_id are deliberately plain GUID columns
(no SQLAlchemy ForeignKey at the migration level either), since they may
reference contacts OR subcontractors / planning OR tasks at runtime.

Idempotent — safe to re-run on a DB where Base.metadata.create_all has
already produced the tables. Every create_index call is wrapped in
try/except sa.exc.OperationalError to tolerate concurrent upgrades.

Revision ID: v3015_contracts
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3015_contracts"
down_revision: Union[str, Sequence[str], None] = "v3014_resources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _safe_create_index(
    inspector: sa.engine.reflection.Inspector,
    name: str,
    table: str,
    cols: list[str],
    unique: bool = False,
) -> None:
    if not _has_table(inspector, table):
        return
    if _has_index(inspector, table, name):
        return
    try:
        op.create_index(name, table, cols, unique=unique)
    except sa.exc.OperationalError:
        # Tolerate race with another upgrade or pre-existing index that
        # didn't show up in the cached inspector data.
        pass


_TABLE_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    # (index_name, table, cols, unique)
    ("ix_oe_contracts_contract_project_id", "oe_contracts_contract", ("project_id",), False),
    ("ix_oe_contracts_contract_status", "oe_contracts_contract", ("status",), False),
    ("ix_oe_contracts_contract_contract_type", "oe_contracts_contract", ("contract_type",), False),
    ("ix_oe_contracts_contract_counterparty_id", "oe_contracts_contract", ("counterparty_id",), False),
    ("ix_oe_contracts_contract_line_contract_id", "oe_contracts_contract_line", ("contract_id",), False),
    ("ix_oe_contracts_retention_schedule_contract_id", "oe_contracts_retention_schedule", ("contract_id",), False),
    ("ix_oe_contracts_fee_structure_contract_id", "oe_contracts_fee_structure", ("contract_id",), False),
    (
        "ix_oe_contracts_gainshare_configuration_contract_id",
        "oe_contracts_gainshare_configuration",
        ("contract_id",),
        False,
    ),
    ("ix_oe_contracts_ld_clause_contract_id", "oe_contracts_ld_clause", ("contract_id",), False),
    ("ix_oe_contracts_progress_claim_contract_id", "oe_contracts_progress_claim", ("contract_id",), False),
    ("ix_oe_contracts_progress_claim_status", "oe_contracts_progress_claim", ("status",), False),
    (
        "ix_oe_contracts_progress_claim_line_progress_claim_id",
        "oe_contracts_progress_claim_line",
        ("progress_claim_id",),
        False,
    ),
    ("ix_oe_contracts_final_account_status", "oe_contracts_final_account", ("status",), False),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    def _common_cols() -> list[sa.Column]:
        return [
            sa.Column("id", guid_type, primary_key=True),
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

    # ── oe_contracts_contract ─────────────────────────────────────────
    if not _has_table(inspector, "oe_contracts_contract"):
        op.create_table(
            "oe_contracts_contract",
            *_common_cols(),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column(
                "contract_type",
                sa.String(40),
                nullable=False,
                server_default="lump_sum",
            ),
            sa.Column(
                "counterparty_type",
                sa.String(40),
                nullable=False,
                server_default="client",
            ),
            sa.Column("counterparty_id", guid_type, nullable=True),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "parent_contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("start_date", sa.String(20), nullable=True),
            sa.Column("end_date", sa.String(20), nullable=True),
            sa.Column(
                "total_value",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column(
                "retention_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="5.00",
            ),
            sa.Column(
                "retention_release_event",
                sa.String(50),
                nullable=False,
                server_default="practical_completion",
            ),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("signed_at", sa.String(40), nullable=True),
            sa.Column(
                "terms",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint("code", name="uq_oe_contracts_contract_code"),
        )

    # ── oe_contracts_contract_line ────────────────────────────────────
    if not _has_table(inspector, "oe_contracts_contract_line"):
        op.create_table(
            "oe_contracts_contract_line",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "parent_line_id",
                guid_type,
                sa.ForeignKey(
                    "oe_contracts_contract_line.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("code", sa.String(80), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("scope_section", sa.String(255), nullable=True),
            sa.Column(
                "line_type",
                sa.String(40),
                nullable=False,
                server_default="work",
            ),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column(
                "quantity",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "unit_rate",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_value",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "order_index",
                sa.Integer(),
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

    # ── oe_contracts_type_configuration ───────────────────────────────
    if not _has_table(inspector, "oe_contracts_type_configuration"):
        op.create_table(
            "oe_contracts_type_configuration",
            *_common_cols(),
            sa.Column("contract_type", sa.String(40), nullable=False),
            sa.Column("display_name", sa.String(120), nullable=False),
            sa.Column(
                "allowed_fields",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "default_fee_structure",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "schema_version",
                sa.String(20),
                nullable=False,
                server_default="1.0",
            ),
            sa.UniqueConstraint(
                "contract_type",
                name="uq_oe_contracts_type_configuration_type",
            ),
        )

    # ── oe_contracts_retention_schedule ───────────────────────────────
    if not _has_table(inspector, "oe_contracts_retention_schedule"):
        op.create_table(
            "oe_contracts_retention_schedule",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "accrual_rule",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "release_rule",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )

    # ── oe_contracts_fee_structure ────────────────────────────────────
    if not _has_table(inspector, "oe_contracts_fee_structure"):
        op.create_table(
            "oe_contracts_fee_structure",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "fee_type",
                sa.String(40),
                nullable=False,
                server_default="percent_of_cost",
            ),
            sa.Column(
                "fee_percent",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("fee_fixed_amount", sa.Numeric(18, 4), nullable=True),
            sa.Column(
                "sliding_scale",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("max_fee", sa.Numeric(18, 4), nullable=True),
        )

    # ── oe_contracts_gainshare_configuration ──────────────────────────
    if not _has_table(inspector, "oe_contracts_gainshare_configuration"):
        op.create_table(
            "oe_contracts_gainshare_configuration",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "target_cost",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "gmp_cap",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "savings_split_owner_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="50.00",
            ),
            sa.Column(
                "savings_split_contractor_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="50.00",
            ),
            sa.Column(
                "overrun_responsibility",
                sa.String(40),
                nullable=False,
                server_default="contractor",
            ),
        )

    # ── oe_contracts_ld_clause ────────────────────────────────────────
    if not _has_table(inspector, "oe_contracts_ld_clause"):
        op.create_table(
            "oe_contracts_ld_clause",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "per_day_amount",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("max_amount", sa.Numeric(18, 4), nullable=True),
            # milestone_id is a plain UUID column — it may point at planning
            # tasks / schedule milestones, resolved at runtime.
            sa.Column("milestone_id", guid_type, nullable=True),
            sa.Column(
                "enforcement_status",
                sa.String(40),
                nullable=False,
                server_default="active",
            ),
        )

    # ── oe_contracts_progress_claim ───────────────────────────────────
    if not _has_table(inspector, "oe_contracts_progress_claim"):
        op.create_table(
            "oe_contracts_progress_claim",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "claim_number",
                sa.String(40),
                nullable=False,
                server_default="",
            ),
            sa.Column("period_start", sa.String(20), nullable=True),
            sa.Column("period_end", sa.String(20), nullable=True),
            sa.Column("claim_date", sa.String(20), nullable=True),
            sa.Column(
                "gross_amount",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "retention_amount",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "prior_claims_total",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "net_due",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("submitted_at", sa.String(40), nullable=True),
            sa.Column("approved_at", sa.String(40), nullable=True),
            sa.Column("paid_at", sa.String(40), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_contracts_progress_claim_line ──────────────────────────────
    if not _has_table(inspector, "oe_contracts_progress_claim_line"):
        op.create_table(
            "oe_contracts_progress_claim_line",
            *_common_cols(),
            sa.Column(
                "progress_claim_id",
                guid_type,
                sa.ForeignKey(
                    "oe_contracts_progress_claim.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "contract_line_id",
                guid_type,
                sa.ForeignKey(
                    "oe_contracts_contract_line.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "period_completed_qty",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "period_completed_value",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "period_completed_pct",
                sa.Numeric(7, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "cumulative_completed_value",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
        )

    # ── oe_contracts_final_account ────────────────────────────────────
    if not _has_table(inspector, "oe_contracts_final_account"):
        op.create_table(
            "oe_contracts_final_account",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "final_contract_value",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_paid",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "retention_held",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "retention_released",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "final_balance",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("sign_off_date", sa.String(20), nullable=True),
            sa.Column("sign_off_by", sa.String(36), nullable=True),
            sa.Column(
                "status",
                sa.String(40),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "contract_id",
                name="uq_oe_contracts_final_account_contract",
            ),
        )

    # Refresh inspector — table creation above invalidates the cached
    # metadata.
    inspector = sa.inspect(bind)
    for name, table, cols, unique in _TABLE_INDEXES:
        _safe_create_index(inspector, name, table, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table, _cols, _unique in _TABLE_INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    # Drop in reverse dependency order.
    for tbl in (
        "oe_contracts_progress_claim_line",
        "oe_contracts_progress_claim",
        "oe_contracts_final_account",
        "oe_contracts_ld_clause",
        "oe_contracts_gainshare_configuration",
        "oe_contracts_fee_structure",
        "oe_contracts_retention_schedule",
        "oe_contracts_contract_line",
        "oe_contracts_type_configuration",
        "oe_contracts_contract",
    ):
        if _has_table(inspector, tbl):
            try:
                op.drop_table(tbl)
            except sa.exc.OperationalError:
                pass
