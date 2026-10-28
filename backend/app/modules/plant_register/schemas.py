# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response models of the plant register API.

Money and quantities travel as decimal strings; a JSON float is refused (422),
because a float has already lost the cents. Calendar days are ``YYYY-MM-DD``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_CODE = r"^[A-Za-z0-9][A-Za-z0-9_.\-/]*$"


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimals as strings, not floats")
    return value


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Patch(_In):
    """A body whose fields are all optional: a field left out is untouched.

    An explicit ``null`` is accepted only for the fields in ``CLEARABLE`` (it
    clears them). On any other field it is a 422, never a silent no-op and
    never a NOT NULL violation at flush.
    """

    CLEARABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_on_required(self) -> Self:
        bad = sorted(k for k in self.model_fields_set if getattr(self, k) is None and k not in self.CLEARABLE)
        if bad:
            raise ValueError(f"null is not allowed for: {', '.join(bad)}")
        return self


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int


# ── catalogue ──────────────────────────────────────────────────────────────


class SettingsIn(_In):
    catalogue_source: Literal["shipped", "tenant"] = "shipped"
    catalogue_id: str = Field(min_length=1, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)


class Capability(BaseModel):
    """Whether the caller may do something, and the error code that says why not.

    ``applies`` is false only when the action does not exist in this state, and
    the client then hides it. ``applies`` true with ``allowed`` false means the
    action exists and is refused: the client shows it disabled with the reason.
    """

    applies: bool
    allowed: bool
    reason: str | None = None
    # Every rule that blocks, when ``reason`` is ``transition_blocked`` or one blocking rule:
    # ``{code, message_key, reason, reason_key}``, worded by the client through the two keys.
    violations: list[dict[str, Any]] = Field(default_factory=list)


class SettingsOut(BaseModel):
    catalogue_source: str
    catalogue_id: str
    catalogue_version: int | None
    pinned: bool
    # What the caller may do on this project, decided by the server (the UI never infers it from a role).
    can: dict[str, Capability] = Field(default_factory=dict)


class SubmittalLeadOut(BaseModel):
    """What a submittal shows for lead time once a plant item owns it (SPEC rule 1)."""

    owned_by_plant_item: bool
    reason: str | None = None
    plant_item_id: uuid.UUID | None = None
    plant_item_code: str | None = None
    effective_lead_weeks: int | None = None
    long_lead: bool | None = None
    latest_order_date: date | None = None


# ── items ──────────────────────────────────────────────────────────────────


class PerformanceRow(_In):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=255)
    unit: str = Field(default="", max_length=40)


class _ItemBody(_Patch):
    CLEARABLE = frozenset(
        {
            "wbs_id",
            "boq_position_id",
            "cx_system_id",
            "vendor_id",
            "critical_override",
            "need_activity_id",
            "need_date_fixed",
            "purchase_order_id",
            "submittal_id",
            "long_lead_override",
            "owner_user_id",
        }
    )

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    component_class_code: str | None = Field(default=None, max_length=64)
    quantity: Decimal | None = Field(default=None, max_digits=18, decimal_places=3)
    unit: str | None = Field(default=None, max_length=20)
    tag: str | None = Field(default=None, max_length=64)
    wbs_id: uuid.UUID | None = None
    boq_position_id: uuid.UUID | None = None
    bim_element_ids: list[str] | None = Field(default=None, max_length=500)
    cx_system_id: uuid.UUID | None = None
    space_ref: str | None = Field(default=None, max_length=255)
    performance: list[PerformanceRow] | None = Field(default=None, max_length=100)
    redundancy_scheme: str | None = Field(default=None, max_length=16)
    maintainability: dict[str, Any] | None = None
    vendor_policy: Literal["neutral", "bound"] | None = None
    vendor_bound_reason: str | None = Field(default=None, max_length=40)
    vendor_id: uuid.UUID | None = None
    critical_override: bool | None = None
    critical_reason: str | None = Field(default=None, max_length=4000)
    need_activity_id: uuid.UUID | None = None
    need_date_fixed: date | None = None
    order_buffers: dict[str, int] | None = None
    purchase_order_id: uuid.UUID | None = None
    submittal_id: uuid.UUID | None = None
    maintenance_strategy: str | None = Field(default=None, max_length=40)
    no_strategic_spare_reason: str | None = Field(default=None, max_length=4000)
    long_lead_override: bool | None = None
    long_lead_override_reason: str | None = Field(default=None, max_length=4000)
    owner_user_id: uuid.UUID | None = None

    _q = field_validator("quantity", mode="before")(_no_float)

    @field_validator("order_buffers")
    @classmethod
    def _buffers(cls, value: dict[str, int] | None) -> dict[str, int] | None:
        allowed = {"transport_days", "install_lead_days", "approval_buffer_days", "drawing_review_days"}
        if value is not None:
            if set(value) - allowed:
                raise ValueError(f"order_buffers keys: {sorted(allowed)}")
            if any(v < 0 or v > 365 for v in value.values()):
                raise ValueError("order buffer days must be 0..365")
        return value

    def changes(self) -> dict[str, Any]:
        """Fields the caller sent; a null here is always a clearable link (see ``_Patch``)."""
        data = self.model_dump(exclude_unset=True)
        if "performance" in data:
            data["performance"] = [dict(r) for r in data["performance"]]
        return data


class ItemCreate(_ItemBody):
    code: str = Field(min_length=1, max_length=64, pattern=_CODE)
    title: str = Field(min_length=1, max_length=255)
    component_class_code: str = Field(min_length=1, max_length=64)


class ItemUpdate(_ItemBody):
    pass


class TransitionIn(_In):
    target: str = Field(min_length=1, max_length=30)


class RouteIn(_In):
    procurement_route: Literal[
        "contractor_furnished_installed",
        "owner_furnished_contractor_installed",
        "owner_furnished_owner_installed",
        "owner_procured_novated",
    ]
    contract_package_id: uuid.UUID | None = None


class HandoverIn(_In):
    confirm: bool = False
    service_contract_id: uuid.UUID | None = None
    # Why the item is handed over without a service asset (required when no contract is named).
    no_asset_reason: str = Field(default="", max_length=2000)


class ItemOut(BaseModel):
    """An item with every derived figure (computed on read, never stored)."""

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    title: str
    description: str
    component_class_code: str
    item_class: str
    quantity: Decimal
    unit: str
    tag: str
    wbs_id: uuid.UUID | None
    boq_position_id: uuid.UUID | None
    bim_element_ids: list[str]
    cx_system_id: uuid.UUID | None
    space_ref: str
    performance: list[dict[str, Any]]
    redundancy_scheme: str
    maintainability: dict[str, Any]
    vendor_policy: str
    vendor_bound_reason: str
    vendor_id: uuid.UUID | None
    critical_override: bool | None
    critical_reason: str
    need_activity_id: uuid.UUID | None
    need_date_fixed: date | None
    order_buffers: dict[str, Any]
    procurement_route: str | None
    contract_package_id: uuid.UUID | None
    owner_furnished_item_id: uuid.UUID | None
    purchase_order_id: uuid.UUID | None
    submittal_id: uuid.UUID | None
    maintenance_strategy: str
    no_strategic_spare_reason: str
    long_lead_override: bool | None
    long_lead_override_reason: str
    owner_user_id: uuid.UUID | None
    status: str
    service_asset_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    # derived
    critical: bool
    long_lead: bool
    long_lead_threshold_weeks: int
    effective_lead_weeks: int | None
    lead_source: str
    lead_basis: str
    market_evidence: bool
    basis_quote_id: uuid.UUID | None
    basis_enquiry_date: date | None
    quote_age_days: int | None
    quote_max_age_days: int
    quote_stale: bool
    need_date: date | None
    date_basis: str
    latest_order_date: date | None
    float_days: int | None
    order_status: str
    needs_slot: bool
    paper_id: uuid.UUID | None
    paper_status: str | None
    slot_id: uuid.UUID | None
    slot_status: str | None
    slot_after_order_date: bool
    delivery_limit_gaps: list[str]
    spare_categories: list[str]
    strategic_spares_ok: bool
    redundancy_ok: bool
    vendor_findings: list[str]
    delivery_model: str  # installed | not_installed
    # What the caller may do with this item: edit, edit_specification, edit_classification, set_route, handover
    # and transition_<state> for each state set by hand. Computed by the functions the writes raise from.
    can: dict[str, Capability]

    @classmethod
    def from_view(cls, v: dict[str, Any]) -> ItemOut:
        if "can" not in v:
            # What the caller may do is the server's answer; a response without it would leave the client guessing.
            raise ValueError("item view without capabilities: pass it through PlantService.item_capabilities")
        item = v["item"]
        base = {c: getattr(item, c) for c in cls.model_fields if hasattr(item, c) and c not in v}
        derived = {k: v[k] for k in cls.model_fields if k in v and k != "item"}
        return cls(**base, **derived)


# ── quotes ─────────────────────────────────────────────────────────────────


class QuoteIn(_In):
    source: str = Field(min_length=1, max_length=40)
    vendor_id: uuid.UUID | None = None
    source_name: str = Field(default="", max_length=255)
    # Optional in the schema on purpose: a missing enquiry date is the coded
    # rule ``lead_time_without_enquiry_date``, not a generic schema error.
    enquiry_date: date | None = None
    response_date: date | None = None
    lead_weeks_min: int = Field(ge=0, le=520)
    lead_weeks_max: int = Field(ge=0, le=520)
    lead_basis: Literal["from_order", "from_approved_drawings", "from_down_payment"] = "from_order"
    valid_until: date | None = None
    document_ref: str = Field(default="", max_length=255)
    catalogue_entry_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=4000)
    set_basis: bool = False


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plant_item_id: uuid.UUID
    source: str
    vendor_id: uuid.UUID | None
    source_name: str
    enquiry_date: date
    response_date: date | None
    lead_weeks_min: int
    lead_weeks_max: int
    lead_basis: str
    valid_until: date | None
    document_ref: str
    catalogue_entry_id: uuid.UUID | None
    is_basis: bool
    superseded_by: uuid.UUID | None
    note: str
    created_by: uuid.UUID | None
    created_at: datetime


# ── slot ───────────────────────────────────────────────────────────────────


class SlotIn(_Patch):
    CLEARABLE = frozenset(
        {"vendor_id", "slot_from", "slot_to", "reservation_fee", "convert_by_date", "commitment_item_id"}
    )

    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = Field(default=None, max_length=255)
    slot_from: date | None = None
    slot_to: date | None = None
    reservation_fee: Decimal | None = Field(default=None, max_digits=18, decimal_places=2, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    fee_refundable: Literal["none", "partial", "full"] | None = None
    fee_credited_to_order: bool | None = None
    convert_by_date: date | None = None
    terms: str | None = Field(default=None, max_length=10000)
    commitment_item_id: uuid.UUID | None = None
    document_ref: str | None = Field(default=None, max_length=255)

    _fee = field_validator("reservation_fee", mode="before")(_no_float)


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plant_item_id: uuid.UUID
    vendor_id: uuid.UUID | None
    vendor_name: str
    slot_from: date | None
    slot_to: date | None
    reservation_fee: Decimal | None
    currency: str
    fee_refundable: str
    fee_credited_to_order: bool
    convert_by_date: date | None
    terms: str
    commitment_item_id: uuid.UUID | None
    document_ref: str
    status: str
    created_at: datetime


# ── decision paper ─────────────────────────────────────────────────────────


class PaperOption(_In):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=255)
    vendor_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None
    lead_weeks: int | None = Field(default=None, ge=0, le=520)
    cost: Decimal | None = Field(default=None, max_digits=18, decimal_places=2, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    risk_ref: str | None = Field(default=None, max_length=255)
    scores: dict[str, Decimal] = Field(default_factory=dict)

    _cost = field_validator("cost", mode="before")(_no_float)

    @field_validator("scores", mode="before")
    @classmethod
    def _scores(cls, value: Any) -> Any:
        if isinstance(value, dict) and any(isinstance(v, float) for v in value.values()):
            raise ValueError("send scores as strings, not floats")
        return value


class PaperCriterion(_In):
    code: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=255)
    weight: Decimal = Decimal(1)

    _w = field_validator("weight", mode="before")(_no_float)


class PaperIn(_Patch):
    question: str | None = Field(default=None, max_length=4000)
    options: list[PaperOption] | None = Field(default=None, max_length=20)
    criteria: list[PaperCriterion] | None = Field(default=None, max_length=30)
    recommendation: str | None = Field(default=None, max_length=64)
    rationale: str | None = Field(default=None, max_length=10000)

    def body(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True, mode="json")


class PaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plant_item_id: uuid.UUID
    question: str
    options: list[dict[str, Any]]
    criteria: list[dict[str, Any]]
    scores: dict[str, str] = Field(default_factory=dict)
    recommendation: str
    rationale: str
    approval_instance_id: uuid.UUID | None
    status: str
    snapshot: dict[str, Any] | None
    supersedes_id: uuid.UUID | None
    submitted_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime


# ── delivery limits, spares, IT ────────────────────────────────────────────


class LimitIn(_In):
    step: str = Field(min_length=1, max_length=40)
    party: str = Field(default="", max_length=40)
    contract_package_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=2000)


class LimitsIn(_In):
    limits: list[LimitIn] = Field(max_length=40)


class LimitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str
    party: str
    contract_package_id: uuid.UUID | None
    note: str


class SpareIn(_Patch):
    CLEARABLE = frozenset({"supply_package_id"})

    category: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=4000)
    quantity: Decimal | None = Field(default=None, max_digits=18, decimal_places=3, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    supply_by: str | None = Field(default=None, max_length=40)
    supply_package_id: uuid.UUID | None = None
    handover_target: str | None = Field(default=None, max_length=255)

    _q = field_validator("quantity", mode="before")(_no_float)


class SpareTransitionIn(_In):
    target: Literal["specified", "delivered", "handed_over", "waived"]
    reason: str = Field(default="", max_length=4000)


class SpareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plant_item_id: uuid.UUID
    category: str
    description: str
    quantity: Decimal
    unit: str
    supply_by: str
    supply_package_id: uuid.UUID | None
    handover_target: str
    waiver_reason: str
    status: str


class ItServiceIn(_Patch):
    CLEARABLE = frozenset({"needed_from", "needed_until", "needed_from_activity_id", "cde_container_id"})

    kind: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=4000)
    responsible_party: str | None = Field(default=None, max_length=40)
    needed_from: date | None = None
    needed_until: date | None = None
    needed_from_activity_id: uuid.UUID | None = None
    access_roles: list[str] | None = Field(default=None, max_length=40)
    cde_container_id: uuid.UUID | None = None


class ItServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    description: str
    responsible_party: str
    needed_from: date | None
    needed_until: date | None
    needed_from_activity_id: uuid.UUID | None
    access_roles: list[str]
    cde_container_id: uuid.UUID | None
    status: str


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None
    suggestion: str | None
