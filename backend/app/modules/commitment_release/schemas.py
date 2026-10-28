# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response models of the commitment release API.

Money travels as decimal strings, never floats. Codes (commitment types, tiers,
flags, abort bases) are catalogue data and plain strings; states, sources and
switches are closed vocabularies and are ``Literal``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.modules.commitment_release.catalogue import parse_amount

T = TypeVar("T")

Enforcement = Literal["off", "warn", "block"]
FxPolicy = Literal["fx_service_rate_set", "project_rates"]
PlannedSource = Literal["budget_line", "cost_line", "boq_position", "manual"]
LinkKind = Literal[
    "contract",
    "contract_line",
    "purchase_order",
    "change_order",
    "variation_order",
    "tender_package",
    "bid_package",
    "rfq",
]
PreconditionKind = Literal[
    "manual",
    "gate_decided",
    "frame_document_binding",
    "funding_approved",
    "permit",
    "budget_available",
    "public_commitment_appropriation",
]
CatalogueSource = Literal["shipped", "tenant", "pack"]


def _money_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(parse_amount(value))
    except ValueError as exc:
        raise ValueError("must be a decimal amount (string)") from exc


def _money_required(value: Any) -> str:
    out = _money_or_none(value)
    if out is None:
        raise ValueError("amount required")
    return out


# Decimal strings, validated strictly (junk, NaN, floats refused; never coerced to 0).
Money = Annotated[str, BeforeValidator(_money_required)]
MoneyStr = Annotated[str | None, BeforeValidator(_money_or_none)]


class Page(BaseModel, Generic[T]):
    """The list envelope every collection endpoint answers with."""

    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── matrix ──


class MatrixSet(BaseModel):
    schedule_source: CatalogueSource | None = None
    schedule_id: str | None = Field(default=None, max_length=64)
    schedule_version: int | None = Field(default=None, ge=1)
    enforcement: Enforcement | None = None
    fx_policy: FxPolicy | None = None
    require_link: bool | None = None
    legal_entity_id: UUID | None = None


class MatrixOut(_Out):
    id: UUID
    project_id: UUID
    schedule_source: str
    schedule_id: str
    schedule_version: int
    enforcement: str
    fx_policy: str
    require_link: bool
    tier_routes: dict[str, Any]
    legal_entity_id: UUID | None
    base_currency: str = ""
    schedule_currency: str = ""
    tiers: list[dict[str, Any]] = Field(default_factory=list)
    commitment_types: list[dict[str, Any]] = Field(default_factory=list)
    novelty_flags: list[dict[str, Any]] = Field(default_factory=list)


class AssignmentIn(BaseModel):
    project_role: str = Field(min_length=1, max_length=64)
    # Optional so that a row without an approver reaches the service and is refused by name.
    user_id: UUID | None = None
    deputy_user_id: UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None


class AssignmentsPut(BaseModel):
    assignments: list[AssignmentIn] = Field(max_length=200)


class AssignmentOut(_Out):
    id: UUID
    project_role: str
    user_id: UUID
    deputy_user_id: UUID | None
    valid_from: str | None
    valid_to: str | None


class RoutesGenerate(BaseModel):
    force: bool = False


class TierRoutePin(BaseModel):
    route_id: UUID


# ── items ──


class _ItemFields(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=255)
    commitment_type: str | None = Field(default=None, max_length=40)
    cost_line_id: UUID | None = None
    control_account_id: UUID | None = None
    cost_bearer_legal_entity_id: UUID | None = None
    funding_application_id: UUID | None = None
    risk_id: UUID | None = None
    governance_area_code: str | None = Field(default=None, max_length=64)
    gate_code: str | None = Field(default=None, max_length=64)
    split_group: str | None = Field(default=None, max_length=64)
    owner_user_id: UUID | None = None
    planned_source: PlannedSource | None = None
    planned_source_id: UUID | None = None
    planned_manual_amount: MoneyStr = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    need_activity_id: UUID | None = None
    requisition_id: UUID | None = None
    plant_item_id: UUID | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    decision_buffer_days: int | None = Field(default=None, ge=0, le=3650)
    latest_decision_date_fixed: date | None = None
    flags: list[str] | None = Field(default=None, max_length=20)


class ItemCreate(_ItemFields):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    commitment_type: str = Field(min_length=1, max_length=40)
    planned_source: PlannedSource = "manual"


class ItemPatch(_ItemFields):
    deferred: bool | None = None
    deferred_reason: str | None = Field(default=None, max_length=4000)


class HoldIn(BaseModel):
    hold: bool
    reason: str = Field(default="", max_length=4000)


class LinkIn(BaseModel):
    kind: LinkKind
    document_id: UUID


class LinkOut(_Out):
    id: UUID
    item_id: UUID
    kind: str
    document_id: UUID


class PreconditionIn(BaseModel):
    kind: PreconditionKind
    ref_id: str | None = Field(default=None, max_length=64)
    text: str = Field(default="", max_length=4000)


class PreconditionConfirm(BaseModel):
    met: bool = True
    evidence_ref: str = Field(default="", max_length=255)


# ── releases ──


class ReleaseRequest(BaseModel):
    amount: Money
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    tranche_note: str = Field(default="", max_length=4000)
    external_approval_ref: str = Field(default="", max_length=255)


class WithdrawIn(BaseModel):
    reason: str = Field(default="", max_length=4000)


class DecideIn(BaseModel):
    """A tier holder decides the pending request. A rejection needs ``comment`` (the rationale)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=2000)
    conditions: str = Field(default="", max_length=4000)
    valid_until: date | None = None


class AbortIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=4000)
    external_approval_ref: str = Field(default="", max_length=255)


class TransferIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_item_id: UUID
    target_project_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=4000)


class ReleaseOut(_Out):
    id: UUID
    item_id: UUID
    attempt: int
    purpose: str
    requested_amount: str
    currency: str
    schedule_currency: str
    amount_in_schedule_currency: str
    fx_rate_used: str
    fx_rate_date: str | None
    fx_source: str
    evaluated_amount: str
    cumulative_after: str
    required_tier: str | None
    escalate_outside: bool
    external_approval_ref: str
    schedule_source: str
    schedule_id: str
    schedule_version: int
    approval_instance_id: UUID | None
    outcome: str
    requested_by: UUID | None
    decided_by: UUID | None
    on_behalf_of: UUID | None
    decided_at: datetime | None
    snapshot: dict[str, Any]
    tranche_note: str
    conditions: str
    rationale: str
    valid_until: str | None
    created_at: datetime

    @field_validator(
        "requested_amount", "amount_in_schedule_currency", "evaluated_amount", "cumulative_after", mode="before"
    )
    @classmethod
    def _str(cls, v: Any) -> str:
        return str(v)


# ── abort terms, exposure, guard ──


class ScheduleEntryIn(BaseModel):
    milestone: str = Field(min_length=1, max_length=120)
    from_date: date | None = None
    progress_pct: MoneyStr = None
    charge_amount: MoneyStr = None
    charge_pct: MoneyStr = None


class AbortTermsPut(BaseModel):
    link_id: UUID | None = None
    basis_code: str | None = Field(default=None, max_length=64)
    basis_source: CatalogueSource = "shipped"
    cancellation_schedule: list[ScheduleEntryIn] = Field(default_factory=list, max_length=50)
    parameters: dict[str, str] = Field(default_factory=dict)
    transferable: Literal["no", "to_project", "resale"] = "no"
    transfer_value_estimate: MoneyStr = None
    salvage_value_estimate: MoneyStr = None
    saved_cost_estimate: MoneyStr = None
    other_charge_estimate: MoneyStr = None
    progress_pct: MoneyStr = None
    notice_days: int | None = Field(default=None, ge=0, le=3650)
    source_note: str = Field(default="", max_length=4000)


class AbortTermsOut(_Out):
    id: UUID
    item_id: UUID
    scope: str
    basis_code: str | None
    basis_source: str
    basis_version: int | None
    cancellation_schedule: list[dict[str, Any]]
    parameters: dict[str, Any]
    transferable: str
    transfer_value_estimate: str | None
    salvage_value_estimate: str | None
    saved_cost_estimate: str | None
    other_charge_estimate: str | None
    progress_pct: str | None
    notice_days: int | None
    source_note: str
    entered_by: UUID | None
    entered_at: datetime | None

    @field_validator(
        "transfer_value_estimate",
        "salvage_value_estimate",
        "saved_cost_estimate",
        "other_charge_estimate",
        "progress_pct",
        mode="before",
    )
    @classmethod
    def _str(cls, v: Any) -> str | None:
        return None if v is None else str(v)


class ScenarioIn(BaseModel):
    as_of: date | None = None
    label: str = Field(default="", max_length=255)


class CheckIn(BaseModel):
    kind: LinkKind | Literal["contingency_drawdown"]
    document_id: UUID | None = None
    new_amount: Money
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")


class CheckOut(BaseModel):
    result: Literal["ok", "warn", "block"]
    reasons: list[dict[str, Any]]
    item_id: str | None = None


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


# ── catalogue admin ──


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)
    based_on_source: CatalogueSource | None = None
    based_on_id: str | None = Field(default=None, max_length=64)
    based_on_version: int | None = Field(default=None, ge=1)


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    body: dict[str, Any] | None = None


class EvaluateIn(BaseModel):
    """The schedule test calculator: "who approves 250k works?"."""

    schedule_source: CatalogueSource = "shipped"
    schedule_id: str = Field(max_length=64)
    schedule_version: int | None = Field(default=None, ge=1)
    commitment_type: str = Field(max_length=40)
    amount: Money
    flags: list[str] = Field(default_factory=list, max_length=20)
