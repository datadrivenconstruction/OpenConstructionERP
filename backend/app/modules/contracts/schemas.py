# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts Pydantic schemas - request / response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.contracts.models import CLAUSE_RISK_LEVELS

# ── Contract ─────────────────────────────────────────────────────────────

CONTRACT_TYPES = "lump_sum|gmp|cost_plus|tm|unit_price|design_build|combination|remeasurement"
COUNTERPARTY_TYPES = "client|subcontractor"
CONTRACT_STATUSES = "draft|active|suspended|completed|terminated"
RETENTION_RELEASE_EVENTS = "practical_completion|final_account|handover"


class ContractCreate(BaseModel):
    """Create a new contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=80)
    title: str = Field(default="", max_length=500)
    contract_type: str = Field(..., pattern=rf"^({CONTRACT_TYPES})$")
    counterparty_type: str = Field(default="client", pattern=rf"^({COUNTERPARTY_TYPES})$")
    counterparty_id: UUID | None = None
    project_id: UUID
    parent_contract_id: UUID | None = None
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    total_value: Decimal = Field(default=Decimal("0"))
    currency: str = Field(default="", max_length=3)
    retention_percent: Decimal = Field(default=Decimal("5.00"), ge=0, le=100)
    retention_release_event: str = Field(
        default="practical_completion",
        pattern=rf"^({RETENTION_RELEASE_EVENTS})$",
    )
    status: str = Field(default="draft", pattern=rf"^({CONTRACT_STATUSES})$")
    signed_at: str | None = None
    terms: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # The clause template this contract is drawn from, if any. Only the code is
    # accepted; the version is resolved server-side at create time and stored
    # alongside it, so the contract keeps naming the version its author saw
    # rather than whichever one is current when someone next opens it. An
    # authored template must already be published; a built-in resolves to
    # version 0.
    template_code: str | None = Field(default=None, max_length=80)


class ContractUpdate(BaseModel):
    """Partial update for a contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    contract_type: str | None = Field(default=None, pattern=rf"^({CONTRACT_TYPES})$")
    counterparty_type: str | None = Field(default=None, pattern=rf"^({COUNTERPARTY_TYPES})$")
    counterparty_id: UUID | None = None
    parent_contract_id: UUID | None = None
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    total_value: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    retention_percent: Decimal | None = Field(default=None, ge=0, le=100)
    retention_release_event: str | None = Field(
        default=None,
        pattern=rf"^({RETENTION_RELEASE_EVENTS})$",
    )
    status: str | None = Field(default=None, pattern=rf"^({CONTRACT_STATUSES})$")
    signed_at: str | None = None
    terms: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ContractResponse(BaseModel):
    """A contract as returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    title: str
    contract_type: str
    counterparty_type: str
    counterparty_id: UUID | None = None
    project_id: UUID
    parent_contract_id: UUID | None = None
    start_date: str | None = None
    end_date: str | None = None
    total_value: Decimal
    original_contract_value: Decimal | None = None
    currency: str
    retention_percent: Decimal
    retention_release_event: str
    status: str
    signed_at: str | None = None
    terms: dict[str, Any] = Field(default_factory=dict)
    # Both null or both set. A code with no version would mean the contract was
    # drawn from whatever is current, which is what pinning the version exists
    # to prevent. Version 0 means a built-in standard form, which has no
    # versions of its own.
    template_code: str | None = None
    template_version: int | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ContractListResponse(BaseModel):
    """One page of contracts plus the size of the whole matching set.

    ``total`` counts the rows the filters matched, not the length of ``items``.
    The register is the commercial spine of a project, so a page presented as
    the register hides exactly the contracts nobody has looked at yet, and it
    hides them from the totals a reader adds up by eye.

    ``total`` is a count of the query, not of the project. ``status``,
    ``counterparty_type`` and ``contract_type`` are applied before the count is
    taken, so a zero here means this question found nothing rather than the
    project holding nothing.
    """

    items: list[ContractResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── ContractLine (SoV) ───────────────────────────────────────────────────


LINE_TYPES = "work|material|labor|fee|contingency|allowance"


class ContractLineCreate(BaseModel):
    """Create a new SoV line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    parent_line_id: UUID | None = None
    code: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=2000)
    scope_section: str | None = Field(default=None, max_length=255)
    line_type: str = Field(default="work", pattern=rf"^({LINE_TYPES})$")
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal = Field(default=Decimal("0"))
    unit_rate: Decimal = Field(default=Decimal("0"))
    order_index: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractLineUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    parent_line_id: UUID | None = None
    code: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    scope_section: str | None = Field(default=None, max_length=255)
    line_type: str | None = Field(default=None, pattern=rf"^({LINE_TYPES})$")
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal | None = None
    unit_rate: Decimal | None = None
    order_index: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


class ContractLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    parent_line_id: UUID | None = None
    code: str
    description: str
    scope_section: str | None = None
    line_type: str
    unit: str | None = None
    quantity: Decimal
    unit_rate: Decimal
    total_value: Decimal
    order_index: int
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ContractLineBulkCreate(BaseModel):
    """Bulk-insert SoV lines for a contract."""

    lines: list[ContractLineCreate] = Field(default_factory=list)


class ContractCloneRequest(BaseModel):
    """Clone an existing contract into the same or a different project.

    The clone is always created in ``draft`` status: a copy of a live
    contract must be re-signed before becoming commercially binding,
    otherwise the cloned signed_at would falsely represent a wet
    signature on the new instrument.

    Body fields:
        target_project_id: destination project - defaults to the source
            contract's project. When supplied, the caller must have
            project-level access on the DESTINATION (else 404), in
            addition to read access on the SOURCE (also 404).
        new_code: contract code for the clone - required and must be
            unique (``oe_contracts_contract.code`` is a UNIQUE column).
        new_title: human title; defaults to ``"<source.title> (clone)"``.
        include_lines: copy all Schedule-of-Values lines (default True).
        copy_subconfigs: copy retention schedule / fee structure /
            gainshare config / LD clauses (default True). Progress
            claims, final accounts, lien waivers and retention-release
            audit entries are NEVER cloned - those belong to the
            original contract's payment history.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    target_project_id: UUID | None = None
    new_code: str = Field(..., min_length=1, max_length=80)
    new_title: str | None = Field(default=None, max_length=500)
    include_lines: bool = True
    copy_subconfigs: bool = True


# ── ContractTypeConfiguration ────────────────────────────────────────────


class ContractTypeConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_type: str
    display_name: str
    allowed_fields: list[str] = Field(default_factory=list)
    default_fee_structure: dict[str, Any] = Field(default_factory=dict)
    schema_version: str


# ── RetentionSchedule ────────────────────────────────────────────────────


class RetentionScheduleCreate(BaseModel):
    contract_id: UUID
    accrual_rule: dict[str, Any] = Field(default_factory=dict)
    release_rule: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class RetentionScheduleUpdate(BaseModel):
    accrual_rule: dict[str, Any] | None = None
    release_rule: dict[str, Any] | None = None
    notes: str | None = None


class RetentionScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    accrual_rule: dict[str, Any] = Field(default_factory=dict)
    release_rule: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── FeeStructure ─────────────────────────────────────────────────────────


FEE_TYPES = "percent_of_cost|fixed|sliding_scale"


class FeeStructureCreate(BaseModel):
    contract_id: UUID
    fee_type: str = Field(default="percent_of_cost", pattern=rf"^({FEE_TYPES})$")
    fee_percent: Decimal = Field(default=Decimal("0"), ge=0)
    fee_fixed_amount: Decimal | None = None
    sliding_scale: list[dict[str, Any]] = Field(default_factory=list)
    max_fee: Decimal | None = None


class FeeStructureUpdate(BaseModel):
    fee_type: str | None = Field(default=None, pattern=rf"^({FEE_TYPES})$")
    fee_percent: Decimal | None = Field(default=None, ge=0)
    fee_fixed_amount: Decimal | None = None
    sliding_scale: list[dict[str, Any]] | None = None
    max_fee: Decimal | None = None


class FeeStructureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    fee_type: str
    fee_percent: Decimal
    fee_fixed_amount: Decimal | None = None
    sliding_scale: list[dict[str, Any]] = Field(default_factory=list)
    max_fee: Decimal | None = None
    created_at: datetime
    updated_at: datetime


# ── GainshareConfiguration ───────────────────────────────────────────────


OVERRUN_RESPONSIBILITIES = "contractor|shared|owner"


class GainshareConfigurationCreate(BaseModel):
    contract_id: UUID
    target_cost: Decimal = Field(default=Decimal("0"))
    gmp_cap: Decimal = Field(default=Decimal("0"))
    savings_split_owner_pct: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    savings_split_contractor_pct: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    overrun_responsibility: str = Field(
        default="contractor",
        pattern=rf"^({OVERRUN_RESPONSIBILITIES})$",
    )


class GainshareConfigurationUpdate(BaseModel):
    target_cost: Decimal | None = None
    gmp_cap: Decimal | None = None
    savings_split_owner_pct: Decimal | None = Field(default=None, ge=0, le=100)
    savings_split_contractor_pct: Decimal | None = Field(default=None, ge=0, le=100)
    overrun_responsibility: str | None = Field(
        default=None,
        pattern=rf"^({OVERRUN_RESPONSIBILITIES})$",
    )


class GainshareConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    target_cost: Decimal
    gmp_cap: Decimal
    savings_split_owner_pct: Decimal
    savings_split_contractor_pct: Decimal
    overrun_responsibility: str
    created_at: datetime
    updated_at: datetime


# ── LDClause ─────────────────────────────────────────────────────────────


LD_ENFORCEMENT_STATUSES = "active|waived"


class LDClauseCreate(BaseModel):
    contract_id: UUID
    per_day_amount: Decimal = Field(default=Decimal("0"))
    currency: str = Field(default="", max_length=3)
    max_amount: Decimal | None = None
    milestone_id: UUID | None = None
    enforcement_status: str = Field(
        default="active",
        pattern=rf"^({LD_ENFORCEMENT_STATUSES})$",
    )


class LDClauseUpdate(BaseModel):
    per_day_amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=3)
    max_amount: Decimal | None = None
    milestone_id: UUID | None = None
    enforcement_status: str | None = Field(
        default=None,
        pattern=rf"^({LD_ENFORCEMENT_STATUSES})$",
    )


class LDClauseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    per_day_amount: Decimal
    currency: str
    max_amount: Decimal | None = None
    milestone_id: UUID | None = None
    enforcement_status: str
    created_at: datetime
    updated_at: datetime


# ── ProgressClaim ────────────────────────────────────────────────────────


CLAIM_STATUSES = "draft|submitted|approved|certified|paid|rejected"


class ProgressClaimCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    claim_number: str | None = Field(default=None, max_length=40)
    period_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    claim_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str = Field(default="", max_length=3)
    milestone_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgressClaimUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    claim_number: str | None = Field(default=None, max_length=40)
    period_start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    period_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    claim_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = Field(default=None, pattern=rf"^({CLAIM_STATUSES})$")
    currency: str | None = Field(default=None, max_length=3)
    milestone_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class ProgressClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    claim_number: str
    period_start: str | None = None
    period_end: str | None = None
    claim_date: str | None = None
    gross_amount: Decimal
    retention_amount: Decimal
    prior_claims_total: Decimal
    net_due: Decimal
    status: str
    submitted_at: str | None = None
    approved_at: str | None = None
    paid_at: str | None = None
    currency: str
    milestone_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ProgressClaimListResponse(BaseModel):
    """One page of progress claims plus the size of the whole matching set.

    Payment history is read to answer how much has been claimed to date, and
    that question is answered wrongly by a page that does not say it is one.
    ``total`` counts the rows the filters matched, so with ``status`` set it
    describes that query rather than the contract.
    """

    items: list[ProgressClaimResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class ProgressClaimLineCreate(BaseModel):
    progress_claim_id: UUID
    contract_line_id: UUID
    period_completed_qty: Decimal = Field(default=Decimal("0"))
    period_completed_value: Decimal = Field(default=Decimal("0"))
    period_completed_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    cumulative_completed_value: Decimal = Field(default=Decimal("0"))


class ProgressClaimLineUpdate(BaseModel):
    period_completed_qty: Decimal | None = None
    period_completed_value: Decimal | None = None
    period_completed_pct: Decimal | None = Field(default=None, ge=0, le=100)
    cumulative_completed_value: Decimal | None = None


class ProgressClaimLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    progress_claim_id: UUID
    contract_line_id: UUID
    period_completed_qty: Decimal
    period_completed_value: Decimal
    period_completed_pct: Decimal
    cumulative_completed_value: Decimal
    created_at: datetime
    updated_at: datetime


class AutoGenerateClaimRequest(BaseModel):
    """Payload to auto-generate a ProgressClaim from completion data."""

    completion: dict[str, Decimal] = Field(
        default_factory=dict,
        description="contract_line_id (str) → completion percent (0-100)",
    )
    measurements: dict[str, Decimal] = Field(
        default_factory=dict,
        description="contract_line_id (str) → period-completed quantity (unit-price)",
    )
    actual_costs_total: Decimal | None = Field(
        default=None,
        description="Total actual costs incurred this period (cost-plus / T&M)",
    )
    time_entries_total: Decimal | None = Field(
        default=None,
        description="T&M: total labor / equipment hours value this period",
    )
    material_entries_total: Decimal | None = Field(
        default=None,
        description="T&M: total materials value this period",
    )


# ── Progress-claim bridge (Gap I) ────────────────────────────────────────


class ProgressClaimPopulatePreviewItem(BaseModel):
    """One previewed claim line derived from a progress observation.

    The preview is read-only: it shows what the claim line WOULD become if the
    user commits, so the UI can let the user deselect / tweak before saving.
    All monetary values are Decimal-as-string in the claim's currency.
    """

    contract_line_id: UUID
    contract_line_code: str = ""
    contract_line_description: str = ""
    boq_position_id: UUID
    unit: str | None = None
    contract_quantity: Decimal = Field(default=Decimal("0"))
    contract_line_value: Decimal = Field(default=Decimal("0"))
    # Latest observed percent-complete for the linked BOQ position (0-100).
    observed_pct: Decimal = Field(default=Decimal("0"))
    period_label: str | None = None
    recorded_at: datetime | None = None
    # Derived figures at the observed percent.
    period_completed_qty: Decimal = Field(default=Decimal("0"))
    period_completed_value: Decimal = Field(default=Decimal("0"))
    cumulative_completed_value: Decimal = Field(default=Decimal("0"))


class ProgressClaimPopulatePreviewResponse(BaseModel):
    """Preview payload for ``GET /populate-from-progress``.

    ``items`` are the populatable lines (SoV lines that link to a BOQ position
    which has at least one progress observation). ``skipped_unlinked`` counts
    SoV lines with no BOQ-position link, ``skipped_no_progress`` counts linked
    lines that have no observation yet - both surfaced so the UI can hint why a
    line is absent. ``currency`` is the claim currency the values are expressed
    in (never a blend).
    """

    claim_id: UUID
    contract_id: UUID
    currency: str = ""
    items: list[ProgressClaimPopulatePreviewItem] = Field(default_factory=list)
    skipped_unlinked: int = 0
    skipped_no_progress: int = 0
    skipped_foreign_currency: int = 0
    gross: Decimal = Field(default=Decimal("0"))
    retention: Decimal = Field(default=Decimal("0"))
    prior_claims_total: Decimal = Field(default=Decimal("0"))
    net_due: Decimal = Field(default=Decimal("0"))


class ProgressClaimCommitLine(BaseModel):
    """One line the client commits back after editing the preview.

    The client echoes the contract_line_id and the (possibly user-adjusted)
    value/percent it wants persisted. Quantities/values are recomputed and
    re-rolled-up server-side, so a tampered total cannot inflate the claim
    beyond the contract line value.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_line_id: UUID
    period_completed_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    # Optional explicit value override; when omitted the value is derived from
    # the percent × contract line value. When supplied it is clamped to the
    # contract line value so the claim line can never exceed the SoV line.
    period_completed_value: Decimal | None = None


class ProgressClaimCommitRequest(BaseModel):
    """Body for ``PUT /commit-populated-lines``."""

    lines: list[ProgressClaimCommitLine] = Field(default_factory=list)


# ── FinalAccount ─────────────────────────────────────────────────────────


FINAL_ACCOUNT_STATUSES = "draft|agreed|disputed|closed"


class FinalAccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    final_contract_value: Decimal = Field(default=Decimal("0"))
    total_paid: Decimal = Field(default=Decimal("0"))
    retention_held: Decimal = Field(default=Decimal("0"))
    retention_released: Decimal = Field(default=Decimal("0"))
    final_balance: Decimal = Field(default=Decimal("0"))
    sign_off_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sign_off_by: str | None = None
    status: str = Field(default="draft", pattern=rf"^({FINAL_ACCOUNT_STATUSES})$")
    notes: str | None = None


class FinalAccountUpdate(BaseModel):
    final_contract_value: Decimal | None = None
    total_paid: Decimal | None = None
    retention_held: Decimal | None = None
    retention_released: Decimal | None = None
    final_balance: Decimal | None = None
    sign_off_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    sign_off_by: str | None = None
    status: str | None = Field(default=None, pattern=rf"^({FINAL_ACCOUNT_STATUSES})$")
    notes: str | None = None


class FinalAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contract_id: UUID
    final_contract_value: Decimal
    total_paid: Decimal
    retention_held: Decimal
    retention_released: Decimal
    final_balance: Decimal
    sign_off_date: str | None = None
    sign_off_by: str | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Calculated summaries ─────────────────────────────────────────────────


class ContractTotalsResponse(BaseModel):
    """Calculated totals & SoV rollup for a Contract."""

    contract_id: UUID
    total_value: Decimal
    line_total: Decimal
    paid_to_date: Decimal
    retention_held: Decimal
    outstanding: Decimal
    line_count: int


class ProgressClaimSummary(BaseModel):
    """Computed totals for a ProgressClaim."""

    gross: Decimal
    retention: Decimal
    prior_claims_paid: Decimal
    net: Decimal


class GainshareCalculation(BaseModel):
    """Result of a GMP gainshare / overrun computation."""

    actual_cost: Decimal
    target_cost: Decimal
    gmp_cap: Decimal
    savings: Decimal
    owner_share: Decimal
    contractor_share: Decimal
    overrun: Decimal
    overrun_responsibility: str


class FinalAccountSummary(BaseModel):
    """Computed balances on a closed contract."""

    contract_id: UUID
    final_contract_value: Decimal
    total_paid: Decimal
    retention_held: Decimal
    retention_released: Decimal
    final_balance: Decimal
    status: str


class ContractDashboardResponse(BaseModel):
    """Dashboard summary for a single contract."""

    contract_id: UUID
    total_value: Decimal
    original_contract_value: Decimal | None = None
    agreed_variations: Decimal = Decimal("0")
    current_contract_value: Decimal = Decimal("0")
    pending_variations: Decimal = Decimal("0")
    forecast_contract_value: Decimal = Decimal("0")
    paid_to_date: Decimal
    retention_held: Decimal
    outstanding: Decimal
    claims_count: int
    change_orders_count: int
    gainshare_estimate: Decimal | None = None
    status: str


# ── AIA G702/G703 (US/CA/AU only) ──────────────────────────────────────────


class AIAG703Line(BaseModel):
    """One G703 continuation-sheet row."""

    line_number: int
    item_number: str
    description: str
    scheduled_value: Decimal
    previous_value: Decimal
    this_period_value: Decimal
    materials_stored: Decimal
    total_completed_stored: Decimal
    percent_complete: Decimal
    balance_to_finish: Decimal
    retainage: Decimal


class AIAG702Summary(BaseModel):
    """G702 certificate-face summary."""

    original_contract_sum: Decimal
    change_orders_net: Decimal
    contract_sum_to_date: Decimal
    total_completed_stored: Decimal
    retainage: Decimal
    total_earned_less_retainage: Decimal
    previous_certificates_total: Decimal
    current_payment_due: Decimal
    balance_to_finish: Decimal


class AIACertification(BaseModel):
    """Architect / owner certification block stamped on the application."""

    architect_certified_at: str | None = None
    architect_certified_by: str | None = None
    owner_certified_at: str | None = None
    owner_certified_by: str | None = None
    certified_amount: Decimal | None = None


class AIAApplicationResponse(BaseModel):
    """Full AIA G702 + G703 payment-application view for one progress claim."""

    claim_id: UUID
    contract_id: UUID
    project_id: UUID
    application_number: str
    period_start: str | None = None
    period_end: str | None = None
    claim_date: str | None = None
    currency: str
    claim_status: str
    retainage_percent: Decimal
    summary: AIAG702Summary
    lines: list[AIAG703Line]
    certification: AIACertification


# == ContractParty (structured parties / roles) ============================


PARTY_ROLES = "employer|contractor|subcontractor|consultant|architect|engineer|guarantor|other"
PARTY_TYPES = "contact|subcontractor|user|external"


class ContractPartyCreate(BaseModel):
    """Create a structured party / role on a contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    party_role: str = Field(default="other", pattern=rf"^({PARTY_ROLES})$")
    party_type: str = Field(default="external", pattern=rf"^({PARTY_TYPES})$")
    party_id: UUID | None = None
    display_name: str = Field(default="", max_length=500)
    is_primary: bool = False
    contact_details: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractPartyUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    party_role: str | None = Field(default=None, pattern=rf"^({PARTY_ROLES})$")
    party_type: str | None = Field(default=None, pattern=rf"^({PARTY_TYPES})$")
    party_id: UUID | None = None
    display_name: str | None = Field(default=None, max_length=500)
    is_primary: bool | None = None
    contact_details: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ContractPartyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    party_role: str
    party_type: str
    party_id: UUID | None = None
    display_name: str
    # Live name resolved by the service from the linked contact / subcontractor
    # / user. None when the link is missing or unresolved; the UI then falls
    # back to ``display_name``.
    resolved_name: str | None = None
    is_primary: bool
    contact_details: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# == ContractSecurity (bonds / guarantees / insurance) =====================


SECURITY_TYPES = (
    "performance_bond|payment_bond|advance_payment_bond|retention_bond|"
    "parent_company_guarantee|bank_guarantee|insurance_pl|insurance_car|"
    "insurance_pi|other"
)
SECURITY_STATUSES = "required|received|active|expired|released|claimed"


class ContractSecurityCreate(BaseModel):
    """Create a bond / guarantee / insurance record on a contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    security_type: str = Field(default="other", pattern=rf"^({SECURITY_TYPES})$")
    reference: str | None = Field(default=None, max_length=120)
    provider_name: str = Field(default="", max_length=255)
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str = Field(default="required", pattern=rf"^({SECURITY_STATUSES})$")
    document_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractSecurityUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    security_type: str | None = Field(default=None, pattern=rf"^({SECURITY_TYPES})$")
    reference: str | None = Field(default=None, max_length=120)
    provider_name: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    valid_from: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_to: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    status: str | None = Field(default=None, pattern=rf"^({SECURITY_STATUSES})$")
    document_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class ContractSecurityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    security_type: str
    reference: str | None = None
    provider_name: str
    amount: Decimal
    currency: str
    percent_of_contract: Decimal | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    status: str
    document_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# == EOTClaim (extension-of-time claims) ===================================


EOT_STATUSES = "draft|submitted|under_review|granted|partially_granted|rejected|withdrawn"
# Statuses that represent a final decision on an EOT claim.
EOT_DECISIONS = "granted|partially_granted|rejected"


class EOTClaimCreate(BaseModel):
    """Create an extension-of-time claim (always starts in ``draft``)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    eot_number: str | None = Field(default=None, max_length=40)
    cause_category: str = Field(default="other", max_length=80)
    description: str = Field(default="", max_length=4000)
    days_claimed: int = Field(default=0, ge=0)
    claim_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_delay_event_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EOTClaimUpdate(BaseModel):
    """Partial update for an EOT claim.

    Status changes are driven only by the dedicated submit / decide / withdraw
    endpoints (FSM + event emission), so ``status``, ``days_granted`` and the
    decision fields are intentionally not editable here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    eot_number: str | None = Field(default=None, max_length=40)
    cause_category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    days_claimed: int | None = Field(default=None, ge=0)
    claim_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_delay_event_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class EOTDecisionRequest(BaseModel):
    """Body for ``POST /eot-claims/{id}/decide``.

    ``decision`` is the target status (granted / partially_granted / rejected).
    ``days_granted`` is clamped server-side to ``[0, days_claimed]`` so a
    decision can never grant more time than was claimed. A rejected claim
    grants zero days regardless of the supplied value.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: str = Field(..., pattern=rf"^({EOT_DECISIONS})$")
    days_granted: int = Field(default=0, ge=0)
    decision_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    revised_completion_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class EOTClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    eot_number: str
    cause_category: str
    description: str
    days_claimed: int
    days_granted: int
    claim_date: str | None = None
    decision_date: str | None = None
    status: str
    revised_completion_date: str | None = None
    linked_delay_event_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# == ContractDocument (documents register) =================================


DOC_ROLES = "executed_agreement|drawing|specification|bond|insurance|correspondence|variation|other"


class ContractDocumentCreate(BaseModel):
    """Register a document against a contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    document_id: UUID | None = None
    doc_role: str = Field(default="other", pattern=rf"^({DOC_ROLES})$")
    title: str = Field(default="", max_length=500)
    version: str = Field(default="", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractDocumentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: UUID | None = None
    doc_role: str | None = Field(default=None, pattern=rf"^({DOC_ROLES})$")
    title: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class ContractDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    document_id: UUID | None = None
    doc_role: str
    title: str
    version: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# == ContractMilestone (milestones / payment schedule) =====================


MILESTONE_TRIGGERS = "date|completion|approval"
MILESTONE_STATUSES = "pending|reached|invoiced|paid"


class ContractMilestoneCreate(BaseModel):
    """Create a contract milestone / payment-schedule entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    code: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=500)
    planned_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    value: Decimal | None = None
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    trigger: str = Field(default="date", pattern=rf"^({MILESTONE_TRIGGERS})$")
    status: str = Field(default="pending", pattern=rf"^({MILESTONE_STATUSES})$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContractMilestoneUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=500)
    planned_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    value: Decimal | None = None
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    trigger: str | None = Field(default=None, pattern=rf"^({MILESTONE_TRIGGERS})$")
    status: str | None = Field(default=None, pattern=rf"^({MILESTONE_STATUSES})$")
    metadata: dict[str, Any] | None = None


class ContractMilestoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    code: str
    name: str
    planned_date: str | None = None
    value: Decimal | None = None
    percent_of_contract: Decimal | None = None
    trigger: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# Final-account readiness checklist (close-out conditions) ==================


class FinalAccountCheckItemResponse(BaseModel):
    """One close-out condition in the final-account readiness checklist."""

    key: str
    status: str
    reason: str
    based_on: dict[str, str] = Field(default_factory=dict)


class FinalAccountChecklistResponse(BaseModel):
    """Final-account (close-out) readiness checklist for a contract.

    Each item is a close-out condition evaluated from data the contract already
    stores. ``ready`` is true only when every applicable check passed and at
    least one applies; ``completion_percent`` counts passed over applicable
    checks (not-applicable checks excluded), guarded against a zero divisor.
    """

    contract_id: UUID
    ready: bool
    completion_percent: Decimal
    passed_count: int
    applicable_count: int
    total_count: int
    items: list[FinalAccountCheckItemResponse] = Field(default_factory=list)


# Authored clause templates ================================================
#
# The built-in standard forms are module constants that nobody can edit, so
# nothing here describes them: they enter the API through the same read
# endpoints, normalised by ``ContractTemplateRepository.list_all``. These
# schemas cover the authoring side only.

# Built from the column domain rather than restated, so a risk grade cannot be
# accepted by the schema and refused by the service, or the reverse. Sorted for
# a stable pattern; alternation order does not matter.
CLAUSE_RISK_PATTERN = "|".join(sorted(CLAUSE_RISK_LEVELS))

# There is deliberately no status pattern here. A status is never accepted from
# a request: it is set by creating, publishing or archiving, each of which is
# its own endpoint. ``TEMPLATE_STATUSES`` in ``models`` is what those write and
# what the tests assert the API never steps outside of.


class TemplateClauseInput(BaseModel):
    """One clause as the author typed it.

    ``number`` is a string because clause numbering is not arithmetic: "14.3",
    "X7" and "2.32" all have to survive a round trip unchanged.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    number: str = Field(..., min_length=1, max_length=40)
    title: str = Field(default="", max_length=500)
    body: str = Field(default="")
    sort_order: int | None = Field(default=None, ge=0)
    risk_level: str = Field(default="none", pattern=rf"^({CLAUSE_RISK_PATTERN})$")
    risk_note: str = Field(default="")
    is_optional: bool = False


class TemplateClauseResponse(BaseModel):
    """One clause of an authored template version."""

    id: UUID | None = None
    number: str
    title: str
    body: str
    sort_order: int
    risk_level: str
    risk_note: str
    is_optional: bool


class ContractTemplateCreate(BaseModel):
    """Author a new template. It starts at version 1, in draft.

    ``code`` may not name a built-in standard form. Shadowing one would make
    the catalogue ambiguous, and the service refuses it rather than deciding
    which of the two a later lookup meant.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=500)
    # Free text, not a whitelist: a national standard form we have never heard
    # of must not need a migration to be grouped.
    family: str = Field(default="", max_length=40)
    description: str = Field(default="")
    retention_release_event: str = Field(
        default="practical_completion",
        pattern=rf"^({RETENTION_RELEASE_EVENTS})$",
    )
    clauses: list[TemplateClauseInput] = Field(default_factory=list)


class ContractTemplateUpdate(BaseModel):
    """Edit the header of a draft version.

    Neither ``code`` nor ``version`` is here. Together they are the identity of
    the row and the thing a contract stores, so renaming either would break
    the reference the contract holds.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=500)
    family: str | None = Field(default=None, max_length=40)
    description: str | None = None
    retention_release_event: str | None = Field(
        default=None,
        pattern=rf"^({RETENTION_RELEASE_EVENTS})$",
    )


class ContractTemplateForkRequest(BaseModel):
    """Copy a built-in standard form into an authored draft under a new code."""

    model_config = ConfigDict(str_strip_whitespace=True)

    new_code: str = Field(..., min_length=1, max_length=80)
    new_name: str | None = Field(default=None, max_length=500)


class TemplateClauseSetRequest(BaseModel):
    """Replace the whole clause set of a draft version.

    Whole-set rather than per-clause because clause order and numbering are one
    document: renumbering 14.3 to 14.4 while 14.4 exists is a legal edit of the
    document and an illegal sequence of row updates.
    """

    clauses: list[TemplateClauseInput] = Field(default_factory=list)


class ContractTemplateResponse(BaseModel):
    """One template version, with its clauses when they were loaded.

    Both halves of the namespace answer in this shape. ``id`` and ``lineage_id``
    are optional because a built-in standard form is a module constant and has
    neither: it is identified by its code alone and reports version 0. Every
    other field is filled for both halves, so a reader never has to branch.
    """

    id: UUID | None = None
    code: str
    version: int
    lineage_id: UUID | None = None
    name: str
    family: str = ""
    description: str = ""
    retention_release_event: str
    status: str
    published_at: datetime | None = None
    published_by: str | None = None
    derived_from_builtin: str | None = None
    source: str = "authored"
    editable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    clauses: list[TemplateClauseResponse] | None = None
    clause_count: int | None = None


class TemplateCatalogueEntry(BaseModel):
    """One row of the catalogue a user picks from.

    Both halves of the namespace arrive in this shape. ``source`` says which
    half, and ``editable`` says whether the pencil should be drawn: a built-in
    is a constant and a published version is frozen, so both are false.
    ``version`` is 0 for a built-in rather than null, so the field never
    changes type and a caller can sort on it without branching.
    """

    code: str
    name: str
    family: str
    description: str = ""
    retention_release_event: str
    clause_count: int
    source: str
    editable: bool
    version: int
    status: str
    derived_from_builtin: str | None = None
    template_id: UUID | None = None


# ── E-signature bridge ───────────────────────────────────────────────────


class ContractSignatoryEntry(BaseModel):
    """One expected signatory when the caller overrides the derived map."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(..., min_length=1, max_length=64)
    required: bool = True


class ContractSigningSessionOpen(BaseModel):
    """Body for ``POST /contracts/{id}/signing-session``.

    Everything is optional. Left alone, the signatories are derived from the
    contract's own party register, which is the answer that stays right when the
    parties change.

    ``provider_capability`` is deliberately not pattern-validated here. The
    vocabulary of signature capabilities belongs to the signing module, and
    restating it in this file would give the platform two lists that drift. The
    signing schema rejects an unknown value and the service turns that into a
    422 naming the field.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    provider_capability: str = Field(default="simple_electronic", max_length=64)
    expires_at: datetime | None = None
    signatories: list[ContractSignatoryEntry] | None = Field(
        default=None,
        description="Override the signatory map derived from the contract parties.",
    )


class ContractSigningSessionResponse(BaseModel):
    """One signing session opened against a contract.

    ``content_hash_current`` and ``stale_signatories`` are the reason this is not
    just the raw session row. A contract can be edited while it is out for
    signature, and when it is, everyone who already signed signed different
    paper. Those two fields say so in the shape the screen needs: a flag for the
    banner, and the names for the list of who has to sign again.
    """

    id: UUID
    document_ref: str
    document_content_hash: str
    provider_capability: str
    # What the signing registry resolved to, not what was asked for. None when
    # no status derivation has stamped it; never backfilled from the
    # requirement, which is the whole point of carrying both.
    delivered_capability: str | None = None
    status: str
    signatory_map: list[dict[str, Any]] = Field(default_factory=list)
    expires_at: datetime | None = None
    created_at: datetime | None = None
    content_hash_current: bool
    stale_signatories: list[str] = Field(default_factory=list)
    signed_roles: list[str] = Field(default_factory=list)
