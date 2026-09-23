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
    oe_contracts_sov_adjustment            - one change order's movement of one SoV line
    oe_contracts_retention_release         - retention released at an event, billed on a claim
    oe_contracts_stored_material           - materials delivered but not yet installed
    oe_contracts_stored_material_movement  - deliveries, installs and removals of a stored material

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
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
        default="substantial_completion",
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
    # ── Where the line came from (v42) ───────────────────────────────────
    # original, change_order or variation. Every line that existed before
    # change orders could add lines was part of the contract as signed, so the
    # scalar default is the true value for those rows too, which is why the
    # boot heal may add this NOT NULL.
    origin: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="original",
        server_default="original",
    )
    # The idempotency key of the change order that created this line, in the
    # same "change_order:<uuid>" shape the contract's posted sources use.
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    # The line value frozen when the contract left draft, next to
    # Contract.original_contract_value. Nullable rather than zero: a line on a
    # contract activated before this column existed has no recorded baseline,
    # and zero would read as "added later from nothing".
    original_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
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
    # ── The period as dates (v42) ────────────────────────────────────────
    # The parsed form of period_start, period_end and claim_date, which stay
    # the API contract. Written by the service on every create and update and
    # backfilled by the ``contracts_claim_period_dates`` boot repair, because a
    # String column cannot be retyped on an upgraded install. NULL means the
    # string was empty or unreadable, never "today": the period rules report it.
    period_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Indexed because claim order and "claims in this month" both read it.
    period_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    application_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # ── Certificate snapshot (v42) ───────────────────────────────────────
    # Total completed and stored to date, and retention held to date, as this
    # application certified them (payment application lines 4 and 5). The next
    # claim's "less previous certificates" is this claim's line 4 minus line 5,
    # read from here rather than recomputed, because a later rate change or
    # change order must not restate what was already certified. Nullable on
    # purpose: a claim certified before the snapshot existed has none, and a
    # zero would be a false certificate. Readers fall back to a reconstruction
    # and say so.
    completed_stored_to_date: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    retention_held_to_date: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # ── What the gross is made of (v45) ──────────────────────────────────
    # ``"cost"`` for a claim billed off recorded cost of work, which carries a
    # gross with no schedule of values behind it, and ``"lines"`` for a claim
    # whose gross is the sum of its own period values. It decides one thing:
    # whether a later line write may re-read the gross from the lines. For a
    # cost claim it may not, or fifty thousand of recorded cost becomes the
    # value of whatever single line somebody typed in.
    #
    # NULL means not recorded, not "lines". Every claim written before this
    # column existed carries NULL and keeps exactly the behaviour it had, and
    # the basis cannot be reconstructed for them: by the time anyone looks, a
    # cost claim that was overwritten from its lines is indistinguishable from
    # a line claim that always said that. Readers must treat NULL as "do what
    # we did before" rather than guessing.
    gross_basis: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    # Three-stage QS quantities: submitted -> assessed -> certified
    assessed_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    certified_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # ── Payment application columns (v42) ────────────────────────────────
    # Work completed on this SoV line by the claims strictly before this one
    # (column D). ``aia.build_g703_line`` has read this attribute since it was
    # written and falls back to cumulative minus period when it is None. That
    # fallback is correct for every line written before v42, so the column is
    # nullable: a server default of 0 would land on those rows through the
    # boot heal and silently zero column D on every legacy application.
    prior_completed_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # Materials presently stored and not yet in the work, as a period-end
    # balance (column F). Zero is the true value for every legacy row, because
    # nothing could record stored materials before this column, so it may be
    # NOT NULL with a scalar default.
    materials_stored_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # Retention accrued to date on this line, on completed work and on stored
    # materials, and the rate the engine applied. Nullable for the same reason
    # as prior_completed_value: NULL says the retention engine never ran for
    # this line, and readers keep using the contract's flat rate, which is what
    # the line was billed at. A zero would claim no retention was ever held.
    retention_to_date: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    retention_stored_to_date: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    retention_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)


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
        default="substantial_completion",
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


#: Where a schedule of values line came from. Declared beside the column so the
#: schemas and the change order poster agree on one list.
CONTRACT_LINE_ORIGINS: frozenset[str] = frozenset({"original", "change_order", "variation"})


class SovAdjustment(Base):
    """One change order's movement of one schedule of values line.

    A change order used to move ``Contract.total_value`` and nothing else, so
    the payment application's contract sum to date and the sum of its scheduled
    values drifted apart with every approval. Each row here records the part of
    one change order that landed on one line. The invariant it makes checkable:
    a line's scheduled value equals its value at activation plus the sum of its
    adjustments, and the lines together equal the contract sum to date.

    ``source_key`` is the same idempotency key the contract's posted sources
    use (``_contract_source_key``), and the unique constraint on the pair is
    what stops a change order and its mirrored variation from posting twice.
    """

    __tablename__ = "oe_contracts_sov_adjustment"
    __table_args__ = (
        UniqueConstraint(
            "contract_line_id",
            "source_key",
            name="uq_oe_contracts_sov_adjustment_line_source",
        ),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # change_order or variation_order.
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # Plain UUID to the change order or variation row (another module).
    source_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The human code of the source, for example "CO-004", shown as a badge.
    source_code: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    delta_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    delta_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # True when this adjustment created the line rather than moving an
    # existing one.
    created_line: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # The day the change order was approved. Splits the change order summary
    # into previous and this period against the claim's period. NULL counts as
    # previous: an adjustment of unknown date was certainly approved before now.
    approved_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SovAdjustment {self.source_key} {self.delta_value}>"


#: Lifecycle of a retention release. A release is proposed, approved once the
#: documents the event requires are in, billed on a progress claim, or voided.
RETENTION_RELEASE_STATUSES: frozenset[str] = frozenset({"proposed", "approved", "billed", "void"})


class RetentionRelease(Base):
    """Retention released at an event and billed on a progress claim.

    Accrual and release are two ledgers. Accrual lives on the claims
    (``ProgressClaim.retention_amount`` per period, and the per-line
    retention-to-date snapshot); release lives here, one row per event. The
    retention a payment application shows as held is accrued to date less the
    releases billed on that claim or earlier.

    Before this table a release was an entry appended to
    ``Contract.metadata['retention_releases']``, which cannot be queried by
    period and is read-only from v42 on.
    """

    __tablename__ = "oe_contracts_retention_release"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A canonical event: substantial_completion, final_completion,
    # defects_period_end, or rate_step_down for a recompute-mode reduction.
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="proposed",
        server_default="proposed",
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # Kept back from the release against open items (for example a punch list
    # valued at a multiple of its cost), so the reader sees why the release is
    # smaller than what was held.
    withheld_for_open_items: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    released_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The claim that bills this release. A plain UUID rather than a foreign
    # key: deleting a draft claim must not delete the release it would have
    # billed, it only makes the release billable again.
    progress_claim_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # ContractDocument ids that evidence the event (certificates, affidavits,
    # consent of surety). Checked against what the release rule requires.
    document_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
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
        return f"<RetentionRelease {self.event} {self.status} {self.amount}>"


#: Where a stored material sits. Off-site and bonded storage need more evidence
#: before most owners will pay for them.
STORED_MATERIAL_LOCATIONS: frozenset[str] = frozenset({"on_site", "off_site", "bonded_warehouse", "supplier_premises"})
STORED_MATERIAL_STATUSES: frozenset[str] = frozenset({"recorded", "billable", "installed", "rejected"})
STORED_MATERIAL_MOVEMENT_KINDS: frozenset[str] = frozenset({"delivered", "installed", "removed", "adjusted"})


class StoredMaterial(Base):
    """Materials delivered for a schedule of values line and not yet installed.

    What a payment application bills as "materials presently stored" is a
    period-end balance, delivered less installed less removed, not a delta, so
    the quantities live in :class:`StoredMaterialMovement` rows and the balance
    is computed as of a date. This row holds what does not move: the line it
    belongs to, where it is, what it cost, and the evidence an owner asks for
    before paying for material that is not yet in the work.
    """

    __tablename__ = "oe_contracts_stored_material"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contract_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_contract_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    location_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="on_site",
        server_default="on_site",
    )
    location_text: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    vendor: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # Evidence, as plain UUIDs into the documents module.
    delivery_ticket_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    invoice_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bill_of_sale_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    insurance_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    photo_document_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    title_transferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Plain UUID to a ContractSecurity given in exchange for payment, the other
    # way several jurisdictions let stored materials be billed.
    security_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    owner_approved_offsite: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="recorded",
        server_default="recorded",
        index=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # The movements are the material's quantities, so every read wants them.
    movements: Mapped[list["StoredMaterialMovement"]] = relationship(
        back_populates="material",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StoredMaterialMovement.moved_on",
    )

    def __repr__(self) -> str:
        return f"<StoredMaterial {self.description[:40]!r} {self.status}>"


class StoredMaterialMovement(Base):
    """One delivery, install, removal or adjustment of a stored material."""

    __tablename__ = "oe_contracts_stored_material_movement"

    stored_material_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_contracts_stored_material.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    moved_on: Mapped[date] = mapped_column(Date, nullable=False)
    # The claim an install was billed on, when there is one. Plain UUID for the
    # same reason as RetentionRelease.progress_claim_id.
    progress_claim_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    # Walking up is by id; the collection is loaded from the parent.
    material: Mapped[StoredMaterial] = relationship(back_populates="movements", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<StoredMaterialMovement {self.kind} {self.quantity} on {self.moved_on}>"
