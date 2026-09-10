# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts ORM models.

Tables:
    oe_contracts_contract                  - contract header with type-specific terms
    oe_contracts_contract_line             - schedule of values (SoV) line items
    oe_contracts_type_configuration        - type-specific allowed-field catalog
    oe_contracts_retention_schedule        - retention accrual/release rules
    oe_contracts_fee_structure             - fee-structure config (cost-plus / T&M)
    oe_contracts_gainshare_configuration   - GMP gainshare / savings-split config
    oe_contracts_ld_clause                 - liquidated-damages clauses
    oe_contracts_progress_claim            - periodic payment / progress claims
    oe_contracts_progress_claim_line       - line-level claim breakdown
    oe_contracts_final_account             - final account / close-out summary
    oe_contracts_party                     - structured parties / roles
    oe_contracts_security                  - bonds / guarantees / insurance
    oe_contracts_eot_claim                 - extension-of-time claims
    oe_contracts_document                  - contract documents register
    oe_contracts_milestone                 - milestones / payment schedule
    oe_contracts_template                  - authored, versioned clause templates
    oe_contracts_template_clause           - the clauses one template version holds

Notes:
    * counterparty_id is a plain UUID column (no SQLAlchemy ForeignKey) since
      a counterparty may live in oe_contacts_contact OR in a subcontractor table
      and the resolution is done at the service layer.
    * party_id (Party), document_id (Security / Document) and milestone_id
      (LDClause / ProgressClaim / Milestone) follow the same convention: plain
      UUID columns with no ORM ForeignKey, resolved at the service layer, since
      they may reference rows owned by other modules (contacts, subcontractors,
      users, documents, planning / schedule).
    * milestone_id on LDClause / ProgressClaim is a plain UUID - it may point at
      an oe_contracts_milestone row OR a milestone owned by planning / tasks /
      schedule, and is resolved at runtime.
    * All monetary values use Numeric(18, 4) for accountancy precision.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Contract(Base):
    """A construction contract of any type (lump-sum / GMP / cost-plus / T&M / etc.)."""

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
    # Plain UUID - could reference oe_contacts_contact OR a subcontractor row.
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
    start_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    original_contract_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        default=None,
        comment="Frozen copy of total_value at the moment the contract left draft. "
        "Immutable after being set; the current value lives in total_value.",
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
    # ── Which clause template this contract was drawn from ─────────────
    # Both-or-neither. A code without a version would mean "drawn from
    # whatever is current", which is the single thing versioning exists to
    # prevent: publishing version 3 would silently restate what version 2
    # said. Built-in templates carry no versions, so a contract drawn from
    # one stores version 0, which reads as "not a versioned template" and
    # keeps the pair populated instead of carving out a null case.
    template_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    """Schedule of values (SoV) line item belonging to a Contract."""

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
    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive nullable link to the cost line this SoV line is contracted
    # against, so contracted value and claimed-to-date roll up by cost line.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
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
    # Plain UUID - milestone may be an oe_contracts_milestone row OR live in
    # planning/tasks/schedule modules, resolved at the service layer.
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
    claim_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
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
    # Optional link to the payment milestone this claim bills against. Plain
    # UUID - may point at an oe_contracts_milestone row OR a milestone owned by
    # the planning / schedule modules, so it is resolved at the service layer.
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
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
    sign_off_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sign_off_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContractParty(Base):
    """A party to a contract with a structured role.

    Complements the legacy single ``counterparty_*`` columns on Contract with a
    full party register (employer, contractor, consultants, guarantor, etc.).
    ``party_id`` is a plain UUID (no ORM ForeignKey) that may reference a
    contact, a subcontractor, a platform user or nothing (external party); the
    service layer resolves the live display name and falls back to
    ``display_name`` when no row is found.
    """

    __tablename__ = "oe_contracts_party"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    party_role: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="other",
        server_default="other",
        index=True,
    )
    party_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="external",
        server_default="external",
    )
    # Plain UUID - may reference oe_contacts_contact / a subcontractor row /
    # oe_users_user, resolved at the service layer (no ORM ForeignKey).
    party_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    display_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    contact_details: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractParty {self.party_role} {self.display_name!r}>"


class ContractSecurity(Base):
    """Financial security held against a contract.

    Covers performance / payment / advance-payment / retention bonds, parent
    company and bank guarantees, and the standard insurance lines. The optional
    ``document_id`` is a plain UUID to the documents module (resolved at the
    service layer, no ORM ForeignKey).
    """

    __tablename__ = "oe_contracts_security"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    security_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="other",
        server_default="other",
        index=True,
    )
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    percent_of_contract: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="required",
        server_default="required",
        index=True,
    )
    # Plain UUID to oe_documents_document (no ORM ForeignKey, resolved at runtime).
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractSecurity {self.security_type} {self.status}>"


class EOTClaim(Base):
    """Extension-of-time (EOT) claim against a contract.

    Mirrors the ProgressClaim lifecycle style: a status FSM tracks the claim
    from draft through a decision, and ``days_granted`` is constrained by the
    service so it can never exceed ``days_claimed``. ``linked_delay_event_id``
    is a plain UUID to a delay / disruption event owned elsewhere.
    """

    __tablename__ = "oe_contracts_eot_claim"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    eot_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="",
        server_default="",
    )
    cause_category: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="other",
        server_default="other",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    days_claimed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    days_granted: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    claim_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    revised_completion_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Plain UUID to a delay / disruption event (no ORM ForeignKey).
    linked_delay_event_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EOTClaim {self.eot_number} {self.status}>"


class ContractDocument(Base):
    """A document attached to a contract (executed agreement, bond, drawing...).

    ``document_id`` is a plain UUID to the documents module (no ORM ForeignKey),
    resolved at the service layer.
    """

    __tablename__ = "oe_contracts_document"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain UUID to oe_documents_document (no ORM ForeignKey, resolved at runtime).
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    doc_role: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="other",
        server_default="other",
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    version: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="",
        server_default="",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractDocument {self.doc_role} {self.title!r}>"


class ContractMilestone(Base):
    """A contract milestone / payment-schedule entry.

    A milestone may carry a fixed value or a percent of the contract, and is
    triggered by a date, completion, or approval. ProgressClaim / LDClause can
    optionally reference a milestone via their (plain UUID) ``milestone_id``.
    """

    __tablename__ = "oe_contracts_milestone"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="",
        server_default="",
    )
    name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    planned_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    percent_of_contract: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    trigger: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="date",
        server_default="date",
    )
    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractMilestone {self.code} {self.status}>"


#: Statuses an authored template version can hold. Declared here, next to the
#: column, because both the request schemas and the service have to agree on
#: it: the schemas turn it into a validation pattern, the service refuses a
#: write outside it. Two independent literals would drift the first time a
#: status is added.
TEMPLATE_STATUSES: frozenset[str] = frozenset({"draft", "published", "archived"})

#: Risk grades a clause can carry. Advisory: this says what a reviewer should
#: read first, not what a lawyer concluded.
CLAUSE_RISK_LEVELS: frozenset[str] = frozenset({"none", "low", "medium", "high"})


class ContractTemplate(Base):
    """One version of an authored clause template.

    The built-in standard-form catalogue (``CONTRACT_CLAUSE_TEMPLATES`` in
    ``service.py``) is *not* stored here and never will be. Those eleven entries
    are constants a user cannot edit, and the two ways to get them into a table -
    a data migration, or a write at boot - both fail on this codebase: the
    documented deploy path is ``create_all`` plus ``alembic stamp head`` and never
    walks the revision chain, and ``on_startup()`` receives no session and is not
    ordered against table creation. So this table holds authored templates only,
    and the union of the two lives in exactly one place,
    ``ContractTemplateRepository.list_all``.

    Versions of one template share a ``code`` and are told apart by ``version``,
    which is why uniqueness is on the pair. A template is editable while
    ``status`` is ``draft``; publishing freezes it, and the next edit opens
    version N+1 as a fresh draft row rather than mutating a version some contract
    may already name. ``lineage_id`` ties those versions together and is set to
    the id of version 1, so a lineage is addressable before version 2 exists.
    """

    __tablename__ = "oe_contracts_template"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_oe_contracts_template_code_version"),)

    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # The id of version 1 of this template. Self-assigned on create so a lineage
    # has a stable handle from the first version, not from the second.
    lineage_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Free-form grouping the UI renders as a chip: fidic, jct, nec, aia,
    # consensusdocs for forks of a built-in, or whatever a tenant coins for its
    # own paper. Deliberately not a whitelist - a national standard form we have
    # never heard of must not need a migration.
    family: Mapped[str] = mapped_column(String(40), nullable=False, default="", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    retention_release_event: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="practical_completion",
    )
    # draft | published | archived.
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
        index=True,
    )
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Set when this version was forked from a built-in, so the UI can say what
    # the tenant's paper started life as. Never a foreign key: built-ins are
    # constants, not rows.
    derived_from_builtin: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ContractTemplate {self.code} v{self.version} ({self.status})>"


class ContractTemplateClause(Base):
    """A single clause belonging to one version of an authored template.

    Clauses are copied by value when a version is opened, never shared between
    versions: a published version has to keep saying what it said, and a row
    shared with its successor would silently restate it.
    """

    __tablename__ = "oe_contracts_template_clause"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "number",
            name="uq_oe_contracts_template_clause_number",
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_template.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The clause number as the standard form writes it: "14.3", "X7", "2.32".
    # A string, not a number, because clause numbering is not arithmetic.
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # none | low | medium | high. What a reviewer should look at first, not a
    # legal opinion. Open-ended string for the same reason every other code
    # field in this package is.
    risk_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="none",
        server_default="none",
        index=True,
    )
    risk_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # An optional clause can be dropped when a contract is drawn from the
    # template; a mandatory one cannot.
    is_optional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    def __repr__(self) -> str:
        return f"<ContractTemplateClause {self.number} {self.title[:40]!r}>"
