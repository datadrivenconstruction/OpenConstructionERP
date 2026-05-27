"""‌⁠‍Contracts ORM models.

Tables:
    oe_contracts_contract                  — contract header with type-specific terms
    oe_contracts_contract_line             — schedule of values (SoV) line items
    oe_contracts_type_configuration        — type-specific allowed-field catalog
    oe_contracts_retention_schedule        — retention accrual/release rules
    oe_contracts_fee_structure             — fee-structure config (cost-plus / T&M)
    oe_contracts_gainshare_configuration   — GMP gainshare / savings-split config
    oe_contracts_ld_clause                 — liquidated-damages clauses
    oe_contracts_progress_claim            — periodic payment / progress claims
    oe_contracts_progress_claim_line       — line-level claim breakdown
    oe_contracts_final_account             — final account / close-out summary

Notes:
    * counterparty_id is a plain UUID column (no SQLAlchemy ForeignKey) since
      a counterparty may live in oe_contacts_contact OR in a subcontractor table
      and the resolution is done at the service layer.
    * milestone_id on LDClause is also a plain UUID — milestones may live in
      planning/tasks/schedule modules and are resolved at runtime.
    * All monetary values use Numeric(18, 4) for accountancy precision.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Contract(Base):
    """‌⁠‍A construction contract of any type (lump-sum / GMP / cost-plus / T&M / etc.)."""

    __tablename__ = "oe_contracts_contract"
    __table_args__ = (UniqueConstraint("code", name="uq_oe_contracts_contract_code"),)

    code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    contract_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="lump_sum",
        index=True,
    )
    counterparty_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="client",
    )
    # Plain UUID — could reference oe_contacts_contact OR a subcontractor row.
    # Resolution is service-layer concern; deliberately NOT a ForeignKey.
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_contract_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    retention_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("5.00"),
    )
    retention_release_event: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="practical_completion",
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    signed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Type-specific terms (gmp_cap, cost_plus_fee_percent, tm_nte_cap,
    # gainshare_split_pct, ld_per_day, target_cost, etc.).
    terms: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Contract {self.code} ({self.contract_type}/{self.status})>"


class ContractLine(Base):
    """‌⁠‍Schedule of values (SoV) line item belonging to a Contract."""

    __tablename__ = "oe_contracts_contract_line"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract_line.id", ondelete="SET NULL"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope_section: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="work",
    )
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    unit_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractLine {self.code} {self.total_value}>"


class ContractTypeConfiguration(Base):
    """Catalog row describing the schema for each contract type."""

    __tablename__ = "oe_contracts_type_configuration"
    __table_args__ = (
        UniqueConstraint(
            "contract_type",
            name="uq_oe_contracts_type_configuration_type",
        ),
    )

    contract_type: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    allowed_fields: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    default_fee_structure: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")

    def __repr__(self) -> str:
        return f"<ContractTypeConfiguration {self.contract_type}>"


class RetentionSchedule(Base):
    """Retention accrual + release rules for one Contract."""

    __tablename__ = "oe_contracts_retention_schedule"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    accrual_rule: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    release_rule: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeeStructure(Base):
    """Fee structure (cost-plus / T&M / design-build) for a Contract."""

    __tablename__ = "oe_contracts_fee_structure"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fee_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="percent_of_cost",
    )
    fee_percent: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("0"),
    )
    fee_fixed_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    sliding_scale: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    max_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)


class GainshareConfiguration(Base):
    """GMP gainshare / savings-split configuration for a Contract."""

    __tablename__ = "oe_contracts_gainshare_configuration"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    gmp_cap: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    savings_split_owner_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("50.00"),
    )
    savings_split_contractor_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("50.00"),
    )
    overrun_responsibility: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="contractor",
    )


class LDClause(Base):
    """Liquidated-damages clause for a Contract (per-day capped)."""

    __tablename__ = "oe_contracts_ld_clause"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    per_day_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    max_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )
    # Plain UUID — milestone may live in planning/tasks/schedule modules.
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    enforcement_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="active",
    )


class ProgressClaim(Base):
    """Periodic progress / payment claim against a Contract."""

    __tablename__ = "oe_contracts_progress_claim"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_number: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    claim_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    retention_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    prior_claims_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    net_due: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    approved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    paid_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ProgressClaim {self.claim_number} {self.status}>"


class ProgressClaimLine(Base):
    """Line-level breakdown of a ProgressClaim against a ContractLine."""

    __tablename__ = "oe_contracts_progress_claim_line"

    progress_claim_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_progress_claim.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract_line.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_completed_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    period_completed_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    period_completed_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
    )
    cumulative_completed_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )


class FinalAccount(Base):
    """Close-out / final account for a Contract (1:1)."""

    __tablename__ = "oe_contracts_final_account"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            name="uq_oe_contracts_final_account_contract",
        ),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
    )
    final_contract_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    total_paid: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    retention_held: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    retention_released: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    final_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    sign_off_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sign_off_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
