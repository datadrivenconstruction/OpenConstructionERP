# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations Pydantic schemas (request/response models)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ── R7 money serialization helper ───────────────────────────────────────
#
# Pydantic v2 serializes ``Decimal`` to a JSON *number* by default, which
# JS truncates to ``Number`` (~15 sig-digit float). The platform-wide
# convention (mirrors property_dev / boq / contracts R7 audits) is to
# emit money fields as plain-decimal *strings* so the wire format is
# locale-neutral and exact. NaN/Infinity collapse to "0" rather than
# crashing the encoder.


def _serialize_money_string(value: Any) -> str | None:
    """Render a Decimal-ish value as a plain-decimal string, or ``None``."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


# Status / category patterns
_NOTICE_STATUS = r"^(issued|acknowledged|responded|closed)$"
_NOTICE_RECIPIENT = r"^(owner|contractor|architect|engineer|consultant)$"
_VR_STATUS = r"^(draft|submitted|under_review|approved|rejected|converted_to_vo)$"
_VR_CLASSIFICATION = r"^(scope_change|unforeseen|owner_change|design_dev|regulatory|other)$"
_VR_URGENCY = r"^(low|med|high)$"
_VO_STATUS = r"^(issued|in_progress|completed|voided)$"
_DAYWORK_STATUS = r"^(draft|signed|disputed|billed)$"
_DAYWORK_LINE_TYPE = r"^(labor|material|equipment)$"
_DISRUPTION_STATUS = r"^(draft|submitted|under_review|agreed|rejected)$"
_EOT_STATUS = r"^(draft|submitted|under_review|granted|rejected)$"
_EOT_CAUSE = r"^(employer_caused|neutral|contractor_caused|concurrent)$"
_FA_STATUS = r"^(draft|agreed|disputed|closed)$"
_COST_IMPACT_CATEGORY = r"^(labor|material|equipment|subcontractor|overhead|profit)$"
_COST_IMPACT_SOURCE = r"^(manual|from_bom|from_estimate)$"


# ── Notice ────────────────────────────────────────────────────────────────


class NoticeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10000)
    raised_at: str | None = Field(default=None, max_length=40)
    raised_by: str | None = Field(default=None, max_length=36)
    recipient_type: str = Field(default="owner", pattern=_NOTICE_RECIPIENT)
    recipient_name: str = Field(default="", max_length=255)
    target_response_date: str | None = Field(default=None, max_length=20)
    response_summary: str = Field(default="", max_length=10000)
    status: str = Field(default="issued", pattern=_NOTICE_STATUS)
    reference_change_order_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NoticeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    recipient_type: str | None = Field(default=None, pattern=_NOTICE_RECIPIENT)
    recipient_name: str | None = Field(default=None, max_length=255)
    target_response_date: str | None = Field(default=None, max_length=20)
    response_received_at: str | None = Field(default=None, max_length=40)
    response_summary: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(default=None, pattern=_NOTICE_STATUS)
    reference_change_order_id: UUID | None = None
    ball_in_court: str | None = Field(default=None, max_length=36)
    response_due_date: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class NoticeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str = ""
    description: str = ""
    raised_at: str | None = None
    raised_by: str | None = None
    recipient_type: str = "owner"
    recipient_name: str = ""
    target_response_date: str | None = None
    response_received_at: str | None = None
    response_summary: str = ""
    status: str = "issued"
    reference_change_order_id: UUID | None = None
    ball_in_court: str | None = None
    response_due_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── VariationRequest ──────────────────────────────────────────────────────


class VariationRequestCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    notice_id: UUID | None = None
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=20000)
    requested_by: str | None = Field(default=None, max_length=36)
    requested_at: str | None = Field(default=None, max_length=40)
    classification: str = Field(default="scope_change", pattern=_VR_CLASSIFICATION)
    urgency: str = Field(default="med", pattern=_VR_URGENCY)
    estimated_cost_impact: Decimal = Decimal("0")
    estimated_schedule_days: int = Field(default=0, ge=-3650, le=3650)
    currency: str = Field(default="", max_length=10)
    status: str = Field(default="draft", pattern=_VR_STATUS)
    # Contract standard (e.g. "FIDIC_RED_2017", "JCT_SBC_2016", "NEC4_ECC")
    # and the sub-clause reference (e.g. "Sub-Clause 13.2", "Clause 5.3.1").
    contract_standard: str = Field(default="", max_length=20)
    contract_clause_ref: str = Field(default="", max_length=60)
    # NEC4 quotation + assessment deadlines (auto-computed for NEC4 if blank).
    quotation_due_at: str | None = Field(default=None, max_length=40)
    assessment_due_at: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VariationRequestUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20000)
    classification: str | None = Field(default=None, pattern=_VR_CLASSIFICATION)
    urgency: str | None = Field(default=None, pattern=_VR_URGENCY)
    estimated_cost_impact: Decimal | None = None
    estimated_schedule_days: int | None = Field(default=None, ge=-3650, le=3650)
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, pattern=_VR_STATUS)
    decision_notes: str | None = Field(default=None, max_length=10000)
    ball_in_court: str | None = Field(default=None, max_length=36)
    response_due_date: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class VariationRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    notice_id: UUID | None = None
    code: str
    title: str = ""
    description: str = ""
    requested_by: str | None = None
    requested_at: str | None = None
    classification: str = "scope_change"
    urgency: str = "med"
    estimated_cost_impact: Decimal = Decimal("0")
    estimated_schedule_days: int = 0
    currency: str = ""
    status: str = "draft"
    submitted_at: str | None = None
    decision_at: str | None = None
    decision_notes: str = ""
    decided_by: str | None = None
    # Issue #435: the commercial approval boundary. Served so a caller can
    # see what was priced, what was agreed and why the two differ, without
    # having to reconstruct any of it from the bill as it stands now.
    submitted_boq_id: UUID | None = None
    submitted_boq_total: Decimal | None = None
    #: The bill as it stood at submission, as a snapshot in the bill's own
    #: version history. NULL for a request with no bill and for one
    #: submitted before the snapshot was taken.
    submitted_boq_snapshot_id: UUID | None = None
    agreed_cost_impact: Decimal | None = None
    agreed_basis: str = ""
    agreed_variance_note: str = ""
    contract_standard: str = ""
    contract_clause_ref: str = ""
    quotation_due_at: str | None = None
    assessment_due_at: str | None = None
    ball_in_court: str | None = None
    response_due_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("estimated_cost_impact", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"

    @field_serializer("submitted_boq_total", "agreed_cost_impact", when_used="json")
    @classmethod
    def _ser_optional_money(cls, v: Decimal | None) -> str | None:
        # No zero fallback here, unlike its neighbour, and the absence is the
        # point rather than an omission. These two are nullable: a request
        # nobody has decided and one agreed at nothing are different facts,
        # and a fallback would make them read the same on every screen
        # downstream. ``_serialize_money_string`` already returns None only
        # for None, so there is nothing else a fallback would catch.
        #
        # Spelled without the three characters themselves on purpose. The gate
        # in tests/unit/test_an_or_zero_fallback_stays_unreachable.py reads the
        # function's SOURCE, comments included, so a comment explaining why the
        # fallback is absent is enough to convict the function of having one.
        return _serialize_money_string(v)


# ── Variation request BOQ (Issue #435) ────────────────────────────────────
#
# A variation request may own a dedicated bill of quantities holding only the
# scope that variation changes. The bill is an ordinary BOQ row, so these
# schemas describe the two things the BOQ module has no place for: how the
# bill is seeded from what already exists, and what each of its lines traces
# back to.


class VariationBOQSourcePosition(BaseModel):
    """An estimating-BOQ position the variation scope is taken from."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position_id: UUID
    #: The quantity this variation changes, which is rarely the contracted
    #: one - a variation usually re-measures part of a line. Omit to carry
    #: the source position's quantity across unchanged.
    quantity: Decimal | None = None
    note: str = Field(default="", max_length=2000)


class VariationBOQSourceContractLine(BaseModel):
    """A contract schedule-of-values line the variation affects."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contract_line_id: UUID
    quantity: Decimal | None = None
    note: str = Field(default="", max_length=2000)


class VariationBOQCreate(BaseModel):
    """Open a dedicated bill for a variation request.

    Both source lists are optional and may be combined. An empty request
    opens an empty bill, which is the right answer for a variation that
    prices scope nobody has estimated or contracted yet.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    base_date: str | None = Field(default=None, max_length=20)
    source_positions: list[VariationBOQSourcePosition] = Field(default_factory=list, max_length=500)
    source_contract_lines: list[VariationBOQSourceContractLine] = Field(default_factory=list, max_length=500)


class VariationBOQLineTraceUpdate(BaseModel):
    """Where one line of an existing variation bill came from.

    Seeding a bill records this for every line it copies, but a bill is an
    ordinary bill and grows the ordinary way: a surveyor adds lines to it
    through the BOQ editor long after it was opened, and those lines arrive
    with no provenance at all. This is how one acquires it afterwards.

    Both references are optional and independent, exactly as they are on the
    seeded path. Naming neither is not the same as declining to answer - it
    is the answer "this line derives from nothing", which is a legitimate
    thing for a variation line to be and is recorded as ``origin='manual'``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    #: The contract schedule-of-values line this line changes.
    contract_line_id: UUID | None = None
    #: The estimating bill position the scope was taken from.
    source_position_id: UUID | None = None
    note: str = Field(default="", max_length=2000)


class VariationBOQTraceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    variation_request_id: UUID
    boq_id: UUID
    position_id: UUID
    origin: str = "manual"
    source_boq_id: UUID | None = None
    source_position_id: UUID | None = None
    contract_id: UUID | None = None
    contract_line_id: UUID | None = None
    note: str = ""
    created_at: datetime


class VariationBOQCheck(BaseModel):
    """One validation result about a variation request's bill."""

    rule_id: str
    severity: str = "warning"
    passed: bool = True
    message: str = ""


class VariationBOQResponse(BaseModel):
    """A variation request's dedicated bill, priced, with its provenance.

    ``has_boq`` false is the answer for every request that predates this
    feature and every request whose author never opened a bill: the headline
    ``estimated_cost_impact`` is then the only figure there is, which is
    exactly how the request behaved before. The money fields are ``None``
    rather than zero in that case, because a request with no bill has no
    priced total, and nil is not the same statement as "priced at nothing".
    """

    variation_request_id: UUID
    has_boq: bool = False
    boq_id: UUID | None = None
    name: str = ""
    status: str = ""
    is_locked: bool = False
    parent_estimate_id: UUID | None = None
    position_count: int = 0
    base_currency: str = ""
    direct_cost: Decimal | None = None
    markups_total: Decimal | None = None
    grand_total: Decimal | None = None
    #: True when the bill blends currencies, so ``grand_total`` is a number
    #: the reader must not treat as final. Carried through from
    #: ``BOQService.compute_boq_totals`` rather than recomputed.
    is_mixed_currency: bool = False
    #: The request's own headline figure, unchanged by the presence of a bill.
    estimated_cost_impact: Decimal = Decimal("0")
    #: True when the headline already equals the bill's grand total, i.e. the
    #: priced figure has been adopted and the two do not disagree.
    estimate_matches_boq: bool = False
    traces: list[VariationBOQTraceResponse] = Field(default_factory=list)
    checks: list[VariationBOQCheck] = Field(default_factory=list)

    @field_serializer("direct_cost", "markups_total", "grand_total", when_used="json")
    @classmethod
    def _ser_optional_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)

    @field_serializer("estimated_cost_impact", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── VariationOrder ────────────────────────────────────────────────────────


class VariationOrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    variation_request_id: UUID | None = None
    title: str = Field(default="", max_length=500)
    final_cost_impact: Decimal = Decimal("0")
    final_schedule_days: int = Field(default=0, ge=-3650, le=3650)
    currency: str = Field(default="", max_length=10)
    agreed_at: str | None = Field(default=None, max_length=40)
    signed_by: str | None = Field(default=None, max_length=36)
    status: str = Field(default="issued", pattern=_VO_STATUS)
    reference_change_order_id: UUID | None = None
    # Soft link - when set, completion of this VO emits a
    # ``variations.contract_sum.updated`` event the contracts module
    # subscribes to.
    affected_contract_id: UUID | None = None
    contract_standard: str = Field(default="", max_length=20)
    contract_clause_ref: str = Field(default="", max_length=60)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VariationOrderUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    final_cost_impact: Decimal | None = None
    final_schedule_days: int | None = Field(default=None, ge=-3650, le=3650)
    currency: str | None = Field(default=None, max_length=10)
    agreed_at: str | None = Field(default=None, max_length=40)
    signed_by: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, pattern=_VO_STATUS)
    reference_change_order_id: UUID | None = None
    # Same soft link as on create. Without it the contract an order amends
    # could only ever be named at creation, and nothing in the UI names it
    # there - so an order promoted from a request had no way to reach a
    # contract at all. ``update_order`` already refuses a completed or
    # voided order, so the link can only be corrected while the order is
    # still in force.
    affected_contract_id: UUID | None = None
    implementation_started_at: str | None = Field(default=None, max_length=40)
    implementation_completed_at: str | None = Field(default=None, max_length=40)
    ball_in_court: str | None = Field(default=None, max_length=36)
    response_due_date: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class VariationOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    variation_request_id: UUID | None = None
    code: str
    title: str = ""
    final_cost_impact: Decimal = Decimal("0")
    final_schedule_days: int = 0
    currency: str = ""
    agreed_at: str | None = None
    signed_by: str | None = None
    status: str = "issued"
    reference_change_order_id: UUID | None = None
    affected_contract_id: UUID | None = None
    contract_standard: str = ""
    contract_clause_ref: str = ""
    implementation_started_at: str | None = None
    implementation_completed_at: str | None = None
    ball_in_court: str | None = None
    response_due_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("final_cost_impact", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Cost impact ───────────────────────────────────────────────────────────


class VariationCostImpactCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    variation_order_id: UUID
    category: str = Field(default="material", pattern=_COST_IMPACT_CATEGORY)
    description: str = Field(default="", max_length=2000)
    quantity: Decimal = Decimal("0")
    unit: str = Field(default="", max_length=20)
    unit_rate: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    source: str = Field(default="manual", pattern=_COST_IMPACT_SOURCE)


class VariationCostImpactUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, pattern=_COST_IMPACT_CATEGORY)
    description: str | None = Field(default=None, max_length=2000)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: Decimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, pattern=_COST_IMPACT_SOURCE)


class VariationCostImpactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    variation_order_id: UUID
    category: str = "material"
    description: str = ""
    quantity: Decimal = Decimal("0")
    unit: str = ""
    unit_rate: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    currency: str = ""
    source: str = "manual"
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", "unit_rate", "total", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Schedule impact ───────────────────────────────────────────────────────


class VariationScheduleImpactCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    variation_order_id: UUID
    affected_activity_ref: str = Field(default="", max_length=255)
    original_finish_date: str | None = Field(default=None, max_length=20)
    revised_finish_date: str | None = Field(default=None, max_length=20)
    days_added: int = Field(default=0, ge=-3650, le=3650)
    is_critical_path: bool = False
    justification: str = Field(default="", max_length=5000)


class VariationScheduleImpactUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    affected_activity_ref: str | None = Field(default=None, max_length=255)
    original_finish_date: str | None = Field(default=None, max_length=20)
    revised_finish_date: str | None = Field(default=None, max_length=20)
    days_added: int | None = Field(default=None, ge=-3650, le=3650)
    is_critical_path: bool | None = None
    justification: str | None = Field(default=None, max_length=5000)


class VariationScheduleImpactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    variation_order_id: UUID
    affected_activity_ref: str = ""
    original_finish_date: str | None = None
    revised_finish_date: str | None = None
    days_added: int = 0
    is_critical_path: bool = False
    justification: str = ""
    created_at: datetime
    updated_at: datetime


# ── Site measurement ──────────────────────────────────────────────────────


class SiteMeasurementCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    recorded_at: str | None = Field(default=None, max_length=40)
    recorded_by: str | None = Field(default=None, max_length=36)
    location: str = Field(default="", max_length=500)
    item_description: str = Field(default="", max_length=5000)
    unit: str = Field(default="", max_length=20)
    measured_quantity: Decimal = Decimal("0")
    agreed_with_owner_at: str | None = Field(default=None, max_length=40)
    owner_signature_ref: str = Field(default="", max_length=255)
    photos: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=10000)
    contract_line_id: UUID | None = None
    variation_order_id: UUID | None = None


class SiteMeasurementUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    recorded_at: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=500)
    item_description: str | None = Field(default=None, max_length=5000)
    unit: str | None = Field(default=None, max_length=20)
    measured_quantity: Decimal | None = None
    agreed_with_owner_at: str | None = Field(default=None, max_length=40)
    owner_signature_ref: str | None = Field(default=None, max_length=255)
    photos: list[str] | None = None
    notes: str | None = Field(default=None, max_length=10000)
    contract_line_id: UUID | None = None
    variation_order_id: UUID | None = None


class SiteMeasurementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    recorded_at: str | None = None
    recorded_by: str | None = None
    location: str = ""
    item_description: str = ""
    unit: str = ""
    measured_quantity: Decimal = Decimal("0")
    agreed_with_owner_at: str | None = None
    owner_signature_ref: str = ""
    photos: list[str] = Field(default_factory=list)
    notes: str = ""
    contract_line_id: UUID | None = None
    variation_order_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("measured_quantity", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Daywork sheet ─────────────────────────────────────────────────────────


class DayworkSheetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    work_date: str | None = Field(default=None, max_length=20)
    description: str = Field(default="", max_length=10000)
    currency: str = Field(default="", max_length=10)
    status: str = Field(default="draft", pattern=_DAYWORK_STATUS)
    owner_signature_ref: str = Field(default="", max_length=255)
    supplied_via_contract_id: UUID | None = None
    # BS 6079 §6.4.2 - markup percentage applied to subtotal of all lines.
    markup_percent: Decimal = Field(default=Decimal("0"), ge=0, le=100)


class DayworkSheetUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    work_date: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=10000)
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, pattern=_DAYWORK_STATUS)
    owner_signature_ref: str | None = Field(default=None, max_length=255)
    supplied_via_contract_id: UUID | None = None
    markup_percent: Decimal | None = Field(default=None, ge=0, le=100)


class DayworkSheetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    sheet_number: str
    work_date: str | None = None
    description: str = ""
    subtotal_amount: Decimal = Decimal("0")
    markup_percent: Decimal = Decimal("0")
    total_amount: Decimal = Decimal("0")
    currency: str = ""
    status: str = "draft"
    signed_by: str | None = None
    signed_at: str | None = None
    owner_signature_ref: str = ""
    supplied_via_contract_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "subtotal_amount",
        "markup_percent",
        "total_amount",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class DayworkSheetLineCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sheet_id: UUID
    line_type: str = Field(default="labor", pattern=_DAYWORK_LINE_TYPE)
    description: str = Field(default="", max_length=2000)
    quantity: Decimal = Decimal("0")
    unit: str = Field(default="", max_length=20)
    unit_rate: Decimal = Decimal("0")
    worker_name: str | None = Field(default=None, max_length=255)
    equipment_code: str | None = Field(default=None, max_length=100)


class DayworkSheetLineUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    line_type: str | None = Field(default=None, pattern=_DAYWORK_LINE_TYPE)
    description: str | None = Field(default=None, max_length=2000)
    quantity: Decimal | None = None
    unit: str | None = Field(default=None, max_length=20)
    unit_rate: Decimal | None = None
    worker_name: str | None = Field(default=None, max_length=255)
    equipment_code: str | None = Field(default=None, max_length=100)


class DayworkSheetLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sheet_id: UUID
    line_type: str = "labor"
    description: str = ""
    quantity: Decimal = Decimal("0")
    unit: str = ""
    unit_rate: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    worker_name: str | None = None
    equipment_code: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", "unit_rate", "total", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Disruption claim ──────────────────────────────────────────────────────


class DisruptionClaimCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    raised_at: str | None = Field(default=None, max_length=40)
    raised_by: str | None = Field(default=None, max_length=36)
    claim_period_start: str | None = Field(default=None, max_length=20)
    claim_period_end: str | None = Field(default=None, max_length=20)
    description: str = Field(default="", max_length=20000)
    root_cause: str = Field(default="", max_length=10000)
    cost_amount: Decimal = Decimal("0")
    schedule_days: int = Field(default=0, ge=0, le=3650)
    currency: str = Field(default="", max_length=10)
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = Field(default="draft", pattern=_DISRUPTION_STATUS)
    notes: str = Field(default="", max_length=10000)
    # AICPA measured-mile fields - units per hour.
    baseline_productivity: Decimal | None = Field(default=None, ge=0)
    impacted_productivity: Decimal | None = Field(default=None, ge=0)
    unit_of_measure: str = Field(default="", max_length=30)
    # If both productivities are set + measured_quantity, the service
    # will derive labour_hours_lost automatically.
    measured_quantity: Decimal | None = Field(default=None, ge=0)
    labour_hours_lost: Decimal | None = Field(default=None, ge=0)


class DisruptionClaimUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, max_length=20000)
    root_cause: str | None = Field(default=None, max_length=10000)
    cost_amount: Decimal | None = None
    schedule_days: int | None = Field(default=None, ge=0, le=3650)
    currency: str | None = Field(default=None, max_length=10)
    evidence_refs: list[str] | None = None
    status: str | None = Field(default=None, pattern=_DISRUPTION_STATUS)
    decision_at: str | None = Field(default=None, max_length=40)
    decided_amount: Decimal | None = None
    notes: str | None = Field(default=None, max_length=10000)


class DisruptionClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    raised_at: str | None = None
    raised_by: str | None = None
    claim_period_start: str | None = None
    claim_period_end: str | None = None
    description: str = ""
    root_cause: str = ""
    cost_amount: Decimal = Decimal("0")
    schedule_days: int = 0
    currency: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = "draft"
    decision_at: str | None = None
    decided_amount: Decimal | None = None
    notes: str = ""
    baseline_productivity: Decimal | None = None
    impacted_productivity: Decimal | None = None
    unit_of_measure: str = ""
    labour_hours_lost: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "cost_amount",
        "decided_amount",
        "baseline_productivity",
        "impacted_productivity",
        "labour_hours_lost",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal | None) -> str | None:
        return _serialize_money_string(v)


# ── EOT claim ─────────────────────────────────────────────────────────────


class ExtensionOfTimeClaimCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    raised_at: str | None = Field(default=None, max_length=40)
    raised_by: str | None = Field(default=None, max_length=36)
    claim_period_start: str | None = Field(default=None, max_length=20)
    claim_period_end: str | None = Field(default=None, max_length=20)
    description: str = Field(default="", max_length=20000)
    root_cause_category: str = Field(default="neutral", pattern=_EOT_CAUSE)
    requested_days: int = Field(default=0, ge=0, le=3650)
    critical_path_impact: bool = False
    status: str = Field(default="draft", pattern=_EOT_STATUS)
    # Schedule-activity affected - either UUID-string of oe_tasks_task or
    # a free-text activity name. Required for TIA.
    affected_activity_ref: str = Field(default="", max_length=255)


class ExtensionOfTimeClaimUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, max_length=20000)
    root_cause_category: str | None = Field(default=None, pattern=_EOT_CAUSE)
    requested_days: int | None = Field(default=None, ge=0, le=3650)
    granted_days: int | None = Field(default=None, ge=0, le=3650)
    critical_path_impact: bool | None = None
    status: str | None = Field(default=None, pattern=_EOT_STATUS)
    decision_at: str | None = Field(default=None, max_length=40)
    decision_notes: str | None = Field(default=None, max_length=10000)


class ExtensionOfTimeClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    raised_at: str | None = None
    raised_by: str | None = None
    claim_period_start: str | None = None
    claim_period_end: str | None = None
    description: str = ""
    root_cause_category: str = "neutral"
    requested_days: int = 0
    granted_days: int | None = None
    critical_path_impact: bool = False
    status: str = "draft"
    decision_at: str | None = None
    decision_notes: str = ""
    affected_activity_ref: str = ""
    tia_delta_days: int | None = None
    tia_computed_at: str | None = None
    created_at: datetime
    updated_at: datetime


class EOTTIARecordRequest(BaseModel):
    """Stamp a TIA result onto an EoT claim."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tia_delta_days: int = Field(..., ge=0, le=3650)
    critical_path_impact: bool | None = None


class NEC4TimerStatusResponse(BaseModel):
    """NEC4 SLA-overdue status for a VariationRequest."""

    request_id: UUID
    contract_standard: str
    contract_clause_ref: str
    quotation_due_at: str | None = None
    assessment_due_at: str | None = None
    quotation_overdue: bool = False
    assessment_overdue: bool = False


# ── Final account ─────────────────────────────────────────────────────────


class FinalAccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    original_contract_value: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    retention_held: Decimal = Decimal("0")
    retention_released: Decimal = Decimal("0")
    status: str = Field(default="draft", pattern=_FA_STATUS)


class FinalAccountUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    original_contract_value: Decimal | None = None
    variations_total: Decimal | None = None
    daywork_total: Decimal | None = None
    claims_total: Decimal | None = None
    retention_held: Decimal | None = None
    retention_released: Decimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, pattern=_FA_STATUS)
    agreed_at: str | None = Field(default=None, max_length=40)


class FinalAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    original_contract_value: Decimal = Decimal("0")
    variations_total: Decimal = Decimal("0")
    daywork_total: Decimal = Decimal("0")
    claims_total: Decimal = Decimal("0")
    retention_held: Decimal = Decimal("0")
    retention_released: Decimal = Decimal("0")
    final_value: Decimal = Decimal("0")
    currency: str = ""
    status: str = "draft"
    agreed_at: str | None = None
    closed_at: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "original_contract_value",
        "variations_total",
        "daywork_total",
        "claims_total",
        "retention_held",
        "retention_released",
        "final_value",
        when_used="json",
    )
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


# ── Aggregated/summary responses ──────────────────────────────────────────


class VariationDashboardResponse(BaseModel):
    """Summary KPIs for the variations dashboard on a project."""

    project_id: UUID
    notices_total: int = 0
    notices_open: int = 0
    requests_total: int = 0
    requests_pending: int = 0
    requests_approved: int = 0
    requests_rejected: int = 0
    variation_orders_total: int = 0
    variation_orders_active: int = 0
    variation_orders_completed: int = 0
    cost_impact_total: Decimal = Decimal("0")
    schedule_impact_days: int = 0
    daywork_sheets_total: int = 0
    daywork_sheets_signed: int = 0
    daywork_value_signed: Decimal = Decimal("0")
    disruption_claims_open: int = 0
    eot_claims_open: int = 0
    final_account_status: str = "none"
    currency: str = ""

    # ── Multi-currency disclosure (additive, optional) ────────────────
    #
    # Currency bug fix: ``cost_impact_total`` / ``daywork_value_signed``
    # are scalar SUMs that historically blended VOs / daywork sheets of
    # different ISO currencies into one number labelled with whichever
    # currency was created first. These optional fields make the dashboard
    # honest WITHOUT changing the existing scalar fields (the frontend
    # still reads them). ``currency`` is now the project BASE currency
    # (not the earliest row's), and the scalar totals are FX-converted to
    # it via the project's ``fx_rates`` when a rate exists.
    #
    # ``*_by_currency`` maps hold the raw per-currency breakdown (ISO code
    # -> money string). ``*_unconverted_by_currency`` maps hold foreign
    # amounts that have NO FX rate, so the UI can show "+ 5,000.00 USD (no
    # rate)" alongside -- never inside -- the base total. ``multi_currency``
    # flags that more than one currency is present so the UI can warn the
    # scalar total is a converted figure.
    cost_impact_by_currency: dict[str, str] = Field(default_factory=dict)
    cost_impact_unconverted_by_currency: dict[str, str] = Field(default_factory=dict)
    daywork_value_by_currency: dict[str, str] = Field(default_factory=dict)
    daywork_value_unconverted_by_currency: dict[str, str] = Field(default_factory=dict)
    multi_currency: bool = False

    @field_serializer("cost_impact_total", "daywork_value_signed", when_used="json")
    @classmethod
    def _ser_money(cls, v: Decimal) -> str:
        return _serialize_money_string(v) or "0"


class FinalAccountSummary(BaseModel):
    """Detailed roll-up of a project's final account."""

    project_id: UUID
    original_contract_value: Decimal = Decimal("0")
    variations_total: Decimal = Decimal("0")
    daywork_total: Decimal = Decimal("0")
    claims_total: Decimal = Decimal("0")
    retention_held: Decimal = Decimal("0")
    retention_released: Decimal = Decimal("0")
    final_value: Decimal = Decimal("0")
    currency: str = ""
    status: str = "draft"
    variation_order_count: int = 0
    daywork_sheet_count: int = 0
    disruption_claim_count: int = 0
    eot_claim_count: int = 0


class DayworkBillingResponse(BaseModel):
    """A daywork sheet ready (or already) billed."""

    sheet_id: UUID
    sheet_number: str
    project_id: UUID
    work_date: str | None = None
    status: str
    total_amount: Decimal = Decimal("0")
    currency: str = ""
    signed_at: str | None = None
    line_count: int = 0


# ── Page envelopes ────────────────────────────────────────────────────────
#
# One per list route. Each route already received a total from its repository
# and discarded it, so the register answered with the first fifty rows and no
# way for the reader to know there were more. These carry it.
#
# They live together at the end rather than beside their entity because the
# seven are one decision, not seven: same fields, same defaults, same reason.
# ``limit`` defaults to 50 because that is what the routes default to; a
# response that reports a limit the route did not use is worse than silence.


class NoticeListResponse(BaseModel):
    """A page of variation notices, with the project's full notice count."""

    items: list[NoticeResponse]
    total: int
    offset: int = 0
    limit: int = 50


class VariationRequestListResponse(BaseModel):
    """A page of variation requests, with the project's full request count."""

    items: list[VariationRequestResponse]
    total: int
    offset: int = 0
    limit: int = 50


class VariationOrderListResponse(BaseModel):
    """A page of variation orders, with the project's full order count."""

    items: list[VariationOrderResponse]
    total: int
    offset: int = 0
    limit: int = 50


class SiteMeasurementListResponse(BaseModel):
    """A page of site measurements, with the project's full measurement count."""

    items: list[SiteMeasurementResponse]
    total: int
    offset: int = 0
    limit: int = 50


class DayworkSheetListResponse(BaseModel):
    """A page of daywork sheets, with the project's full sheet count."""

    items: list[DayworkSheetResponse]
    total: int
    offset: int = 0
    limit: int = 50


class DisruptionClaimListResponse(BaseModel):
    """A page of disruption claims, with the project's full claim count."""

    items: list[DisruptionClaimResponse]
    total: int
    offset: int = 0
    limit: int = 50


class ExtensionOfTimeClaimListResponse(BaseModel):
    """A page of EOT claims, with the project's full claim count."""

    items: list[ExtensionOfTimeClaimResponse]
    total: int
    offset: int = 0
    limit: int = 50
