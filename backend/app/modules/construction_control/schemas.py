# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control Pydantic schemas - request/response models."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Shared regex fragments for the discriminators (kept here so router, service and
# tests reference one source of truth).
INSPECTION_TYPE_PATTERN = r"^(mir|wir|ir|hidden_works|acceptance)$"
PARTY_ROLE_PATTERN = r"^(qc|qa|tpi|ahj)$"
INTERVENTION_POINT_PATTERN = r"^(hold|witness|surveillance|review)$"
ACCEPTANCE_RULE_PATTERN = r"^(range|min|max|boolean|text)$"
RESULT_PATTERN = r"^(pass|fail|conditional)$"

# Pillar 2 - material record (digital passport) + test result discriminators.
# EN 10204 inspection-document grade (2.1 / 2.2 / 3.1 / 3.2) plus the EU CPR / UKCA
# markings (dop / ce / ukca) and a generic certificate of conformity (coc).
CERT_TYPE_PATTERN = r"^(2\.1|2\.2|3\.1|3\.2|dop|ce|ukca|coc|other)$"
MATERIAL_STATUS_PATTERN = r"^(draft|submitted|under_review|accepted|rejected|expired|superseded)$"
# A material may be created or edited only into a pre-decision state; accept / reject
# is reached through the review endpoint (which can raise an NCR), never a plain write.
MATERIAL_CREATE_STATUS_PATTERN = r"^(draft|submitted)$"
MATERIAL_UPDATE_STATUS_PATTERN = r"^(draft|submitted|under_review|superseded)$"
TEST_STATUS_PATTERN = r"^(draft|recorded|void)$"

# Pillar 3 - as-built record discriminators.
# How the as-built was captured (the metrology source).
CAPTURE_METHOD_PATTERN = r"^(laser_scan|photogrammetry|total_station|gnss|tape|drone_lidar|model_extract|manual)$"
# Accuracy class of the capture.
ACCURACY_CLASS_PATTERN = r"^(survey|standard|coarse)$"
# Where the record originated.
SOURCE_KIND_PATTERN = r"^(pointcloud_scan|pointcloud_registration|takeoff_measurement|cde_document|manual)$"
ASBUILT_UPDATE_STATUS_PATTERN = r"^(draft|surveyed|verified|superseded)$"

# Pillar 5 - hold/witness/surveillance/review gate discriminators.
POINT_TYPE_PATTERN = r"^(hold|witness|surveillance|review)$"
GATE_ATTACHED_KIND_PATTERN = r"^(activity|handover_package|inspection|cx_stage)$"

# Pillar 4 - handover / acceptance package discriminators.
# The legal completion regime: taking-over (FIDIC) | substantial (US) | practical (UK).
COMPLETION_REGIME_PATTERN = r"^(taking_over|substantial|practical)$"
# Whole / sectional / partial handover.
COMPLETION_TYPE_PATTERN = r"^(whole|sectional|partial)$"


# ── Small parse helpers for cross-field validation (locale-independent) ────────
# Numeric bounds and calendar dates are stored as strings across the module (the
# platform money/quantity convention). These helpers let the request schemas catch an
# obviously self-contradictory entry (an inverted tolerance range, a validity window
# that ends before it starts) at the edge, in plain terms, without ever guessing at a
# locale-specific number or date format: only ISO-8601 dates and plain decimals parse,
# anything else is left untouched so a free-text bound is never rejected by mistake.


def _try_decimal(value: str | None) -> Decimal | None:
    """Parse a plain numeric string to ``Decimal``; ``None`` for empty / non-numeric input."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _try_iso_date(value: str | None) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of an ISO-8601 string; ``None`` if it does not parse.

    ISO-8601 is the one calendar format that is unambiguous worldwide (unlike a bare
    day/month order), so only it is accepted here. A datetime string works too - only the
    date part is read.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


# ── Universal Element Reference (UER) ─────────────────────────────────────────


class ElementRefIn(BaseModel):
    """Inbound element link. Any subset is accepted; the resolver fills the rest.

    A caller may pass the strong ``bim_element_id``, or the normalised
    ``(model_id, stable_id)``, or ``(model_id, native_id)``, or only denormalised
    display fields when the model is not yet ingested. IFC GlobalId is optional.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    bim_element_id: UUID | None = None
    model_id: UUID | None = None
    stable_id: str | None = Field(default=None, max_length=255)
    source_format: str | None = Field(default=None, max_length=20)
    ifc_global_id: str | None = Field(default=None, max_length=22)
    native_id: str | None = Field(default=None, max_length=255)
    model_version: str | None = Field(default=None, max_length=20)
    element_name: str | None = Field(default=None, max_length=500)
    element_type: str | None = Field(default=None, max_length=100)
    bbox: dict[str, Any] | None = None
    viewpoint: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ElementRefResponse(BaseModel):
    """A resolved UER as returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    owner_type: str
    owner_id: str
    project_id: UUID
    bim_element_id: UUID | None = None
    model_id: UUID | None = None
    stable_id: str | None = None
    source_format: str | None = None
    ifc_global_id: str | None = None
    native_id: str | None = None
    model_version: str | None = None
    element_name: str | None = None
    element_type: str | None = None
    bbox: dict[str, Any] | None = None
    viewpoint: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Acceptance criterion ──────────────────────────────────────────────────────


class AcceptanceCriterionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    code: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    standard_ref: str | None = Field(default=None, max_length=120)
    discipline: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=80)
    characteristic: str | None = Field(default=None, max_length=255)
    method: str | None = Field(default=None, max_length=10000)
    unit: str | None = Field(default=None, max_length=40)
    acceptance_rule: str = Field(default="text", pattern=ACCEPTANCE_RULE_PATTERN)
    nominal_value: str | None = Field(default=None, max_length=80)
    tolerance_lower: str | None = Field(default=None, max_length=80)
    tolerance_upper: str | None = Field(default=None, max_length=80)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_range_bounds(self) -> "AcceptanceCriterionCreate":
        _assert_range_bounds_ordered(self.acceptance_rule, self.tolerance_lower, self.tolerance_upper)
        return self


class AcceptanceCriterionUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    standard_ref: str | None = Field(default=None, max_length=120)
    discipline: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=80)
    characteristic: str | None = Field(default=None, max_length=255)
    method: str | None = Field(default=None, max_length=10000)
    unit: str | None = Field(default=None, max_length=40)
    acceptance_rule: str | None = Field(default=None, pattern=ACCEPTANCE_RULE_PATTERN)
    nominal_value: str | None = Field(default=None, max_length=80)
    tolerance_lower: str | None = Field(default=None, max_length=80)
    tolerance_upper: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_range_bounds(self) -> "AcceptanceCriterionUpdate":
        # Only checkable when this patch itself declares a range rule with both bounds;
        # a patch that touches one bound alone cannot know the stored rule, so it is left
        # to pass and the create-time guard remains the backstop.
        if self.acceptance_rule == "range":
            _assert_range_bounds_ordered(self.acceptance_rule, self.tolerance_lower, self.tolerance_upper)
        return self


def _assert_range_bounds_ordered(
    acceptance_rule: str | None, tolerance_lower: str | None, tolerance_upper: str | None
) -> None:
    """Reject a range criterion whose lower bound is above its upper bound.

    Only fires for a ``range`` rule when both bounds are plain numbers; a non-numeric or
    partial bound is left alone. An inverted range can never accept any measurement, so
    catching it here saves a criterion that would silently fail every survey.
    """
    if acceptance_rule != "range":
        return
    lower = _try_decimal(tolerance_lower)
    upper = _try_decimal(tolerance_upper)
    if lower is not None and upper is not None and lower > upper:
        raise ValueError(
            "tolerance_lower must be less than or equal to tolerance_upper for a range criterion. "
            "Swap the two values so the lower limit comes first."
        )


class AcceptanceCriterionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str
    description: str | None = None
    standard_ref: str | None = None
    discipline: str | None = None
    category: str | None = None
    characteristic: str | None = None
    method: str | None = None
    unit: str | None = None
    acceptance_rule: str = "text"
    nominal_value: str | None = None
    tolerance_lower: str | None = None
    tolerance_upper: str | None = None
    is_active: bool = True
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Inspection ────────────────────────────────────────────────────────────────


class InspectionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    inspection_type: str = Field(..., pattern=INSPECTION_TYPE_PATTERN)
    party_role: str = Field(default="qc", pattern=PARTY_ROLE_PATTERN)
    intervention_point: str | None = Field(default=None, pattern=INTERVENTION_POINT_PATTERN)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    location_description: str | None = Field(default=None, max_length=500)
    activity_id: str | None = Field(default=None, max_length=36)
    criterion_id: UUID | None = None
    scheduled_at: str | None = Field(default=None, max_length=40)
    # Optional element under inspection (the UER). When omitted the inspection is
    # not model-linked, which is valid for purely location-based checks.
    element: ElementRefIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InspectionUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    inspection_type: str | None = Field(default=None, pattern=INSPECTION_TYPE_PATTERN)
    party_role: str | None = Field(default=None, pattern=PARTY_ROLE_PATTERN)
    intervention_point: str | None = Field(default=None, pattern=INTERVENTION_POINT_PATTERN)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    location_description: str | None = Field(default=None, max_length=500)
    activity_id: str | None = Field(default=None, max_length=36)
    criterion_id: UUID | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|scheduled|in_progress|passed|failed|closed|void)$")
    scheduled_at: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class InspectionResultIn(BaseModel):
    """Record the outcome of an inspection. A ``fail`` (or ``conditional``) raises an NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    result: str = Field(..., pattern=RESULT_PATTERN)
    measured_value: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=10000)
    performed_at: str | None = Field(default=None, max_length=40)
    # Severity used for an auto-raised NCR; defaults are derived from the result.
    ncr_severity: str | None = Field(default=None, pattern=r"^(critical|major|minor|observation)$")


class InspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    inspection_number: str
    inspection_type: str
    party_role: str = "qc"
    intervention_point: str | None = None
    title: str
    description: str | None = None
    location_description: str | None = None
    activity_id: str | None = None
    criterion_id: str | None = None
    status: str = "draft"
    result: str | None = None
    measured_value: str | None = None
    result_notes: str | None = None
    raised_ncr_id: str | None = None
    scheduled_at: str | None = None
    performed_at: str | None = None
    performed_by: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    # Resolved element links (populated by the service, not from_attributes).
    elements: list[ElementRefResponse] = Field(default_factory=list)


# ── Material record (digital passport, EN 10204) ──────────────────────────────


class MaterialRecordCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=500)
    material_type: str | None = Field(default=None, max_length=80)
    spec_grade: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    supplier: str | None = Field(default=None, max_length=255)
    supplier_id: str | None = Field(default=None, max_length=36)
    product_code: str | None = Field(default=None, max_length=255)
    # Conformity certificate (EN 10204 grade + EU CPR / UKCA markings).
    cert_type: str | None = Field(default=None, pattern=CERT_TYPE_PATTERN)
    cert_number: str | None = Field(default=None, max_length=120)
    cert_issuer: str | None = Field(default=None, max_length=255)
    cert_document_id: str | None = Field(default=None, max_length=36)
    dop_number: str | None = Field(default=None, max_length=120)
    ce_marking: bool = False
    ukca_marking: bool = False
    issued_at: str | None = Field(default=None, max_length=40)
    valid_from: str | None = Field(default=None, max_length=40)
    valid_until: str | None = Field(default=None, max_length=40)
    # Traceability.
    batch_number: str | None = Field(default=None, max_length=120)
    heat_number: str | None = Field(default=None, max_length=120)
    lot_number: str | None = Field(default=None, max_length=120)
    quantity: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=40)
    # Links. ``criterion_id`` is a UUID so a cross-project criterion is rejected (IDOR);
    # the procurement ids are soft references (no FK) to the goods receipt.
    criterion_id: UUID | None = None
    po_id: str | None = Field(default=None, max_length=36)
    gr_id: str | None = Field(default=None, max_length=36)
    gr_item_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="draft", pattern=MATERIAL_CREATE_STATUS_PATTERN)
    received_at: str | None = Field(default=None, max_length=40)
    # Optional model element the material is installed in / linked to (the UER).
    element: ElementRefIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_validity_window(self) -> "MaterialRecordCreate":
        _assert_validity_window_ordered(self.valid_from, self.valid_until)
        return self


def _assert_validity_window_ordered(valid_from: str | None, valid_until: str | None) -> None:
    """Reject a certificate whose validity ends before it starts.

    Only fires when both dates parse as ISO-8601; a free-text or single date is left
    alone. Catches a transposed pair of dates at entry rather than surfacing the
    certificate as already expired later on.
    """
    start = _try_iso_date(valid_from)
    end = _try_iso_date(valid_until)
    if start is not None and end is not None and end < start:
        raise ValueError(
            "valid_until cannot be earlier than valid_from. "
            "Check the certificate dates; the validity window must start before it ends."
        )


class MaterialRecordUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=500)
    material_type: str | None = Field(default=None, max_length=80)
    spec_grade: str | None = Field(default=None, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=255)
    supplier: str | None = Field(default=None, max_length=255)
    supplier_id: str | None = Field(default=None, max_length=36)
    product_code: str | None = Field(default=None, max_length=255)
    cert_type: str | None = Field(default=None, pattern=CERT_TYPE_PATTERN)
    cert_number: str | None = Field(default=None, max_length=120)
    cert_issuer: str | None = Field(default=None, max_length=255)
    cert_document_id: str | None = Field(default=None, max_length=36)
    dop_number: str | None = Field(default=None, max_length=120)
    ce_marking: bool | None = None
    ukca_marking: bool | None = None
    issued_at: str | None = Field(default=None, max_length=40)
    valid_from: str | None = Field(default=None, max_length=40)
    valid_until: str | None = Field(default=None, max_length=40)
    batch_number: str | None = Field(default=None, max_length=120)
    heat_number: str | None = Field(default=None, max_length=120)
    lot_number: str | None = Field(default=None, max_length=120)
    quantity: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=40)
    criterion_id: UUID | None = None
    po_id: str | None = Field(default=None, max_length=36)
    gr_id: str | None = Field(default=None, max_length=36)
    gr_item_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, pattern=MATERIAL_UPDATE_STATUS_PATTERN)
    received_at: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_validity_window(self) -> "MaterialRecordUpdate":
        # Checkable only when the patch carries both dates; a one-sided patch cannot be
        # compared against the stored counterpart here, so the create-time guard backs it.
        if self.valid_from is not None and self.valid_until is not None:
            _assert_validity_window_ordered(self.valid_from, self.valid_until)
        return self


class MaterialReviewIn(BaseModel):
    """Record a conformity decision on a material submittal.

    ``decision`` reuses the inspection result grammar: ``pass`` accepts the material,
    ``fail`` rejects it (raises a material NCR), ``conditional`` accepts it subject to a
    tracked observation (raises a low-severity NCR).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    decision: str = Field(..., pattern=RESULT_PATTERN)
    notes: str | None = Field(default=None, max_length=10000)
    reviewed_at: str | None = Field(default=None, max_length=40)
    ncr_severity: str | None = Field(default=None, pattern=r"^(critical|major|minor|observation)$")


class MaterialRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    record_number: str
    name: str
    material_type: str | None = None
    spec_grade: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    supplier_id: str | None = None
    product_code: str | None = None
    cert_type: str | None = None
    cert_number: str | None = None
    cert_issuer: str | None = None
    cert_document_id: str | None = None
    dop_number: str | None = None
    ce_marking: bool = False
    ukca_marking: bool = False
    issued_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    batch_number: str | None = None
    heat_number: str | None = None
    lot_number: str | None = None
    quantity: str | None = None
    unit: str | None = None
    criterion_id: str | None = None
    po_id: str | None = None
    gr_id: str | None = None
    gr_item_id: str | None = None
    status: str = "draft"
    review_notes: str | None = None
    raised_ncr_id: str | None = None
    received_at: str | None = None
    received_by: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    # Computed (service-set, not from the ORM): certificate past its validity window.
    is_expired: bool = False
    elements: list[ElementRefResponse] = Field(default_factory=list)


# ── Test result (ISO/IEC 17025 lab) ───────────────────────────────────────────


class TestResultCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    # UUIDs so a cross-project material / criterion is rejected (IDOR); the inspection
    # link is a soft reference within the same module.
    material_record_id: UUID | None = None
    inspection_id: str | None = Field(default=None, max_length=36)
    criterion_id: UUID | None = None
    sample_id: str | None = Field(default=None, max_length=120)
    test_method: str | None = Field(default=None, max_length=255)
    lab_name: str | None = Field(default=None, max_length=255)
    lab_accreditation: str | None = Field(default=None, max_length=120)
    is_accredited: bool = False
    measured_value: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=40)
    specimen_age_days: int | None = Field(default=None, ge=0)
    sampled_at: str | None = Field(default=None, max_length=40)
    calibration_id: UUID | None = None
    element: ElementRefIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestResultUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    material_record_id: UUID | None = None
    inspection_id: str | None = Field(default=None, max_length=36)
    criterion_id: UUID | None = None
    sample_id: str | None = Field(default=None, max_length=120)
    test_method: str | None = Field(default=None, max_length=255)
    lab_name: str | None = Field(default=None, max_length=255)
    lab_accreditation: str | None = Field(default=None, max_length=120)
    is_accredited: bool | None = None
    measured_value: str | None = Field(default=None, max_length=80)
    unit: str | None = Field(default=None, max_length=40)
    specimen_age_days: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern=TEST_STATUS_PATTERN)
    sampled_at: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None


class TestResultRecordIn(BaseModel):
    """Record a test outcome. A ``fail`` (or ``conditional``) raises a linked NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    result: str = Field(..., pattern=RESULT_PATTERN)
    measured_value: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=10000)
    tested_at: str | None = Field(default=None, max_length=40)
    ncr_severity: str | None = Field(default=None, pattern=r"^(critical|major|minor|observation)$")


class TestResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    result_number: str
    title: str
    description: str | None = None
    material_record_id: str | None = None
    inspection_id: str | None = None
    criterion_id: str | None = None
    sample_id: str | None = None
    test_method: str | None = None
    lab_name: str | None = None
    lab_accreditation: str | None = None
    is_accredited: bool = False
    measured_value: str | None = None
    unit: str | None = None
    specimen_age_days: int | None = None
    status: str = "draft"
    result: str | None = None
    result_notes: str | None = None
    raised_ncr_id: str | None = None
    calibration_id: str | None = None
    sampled_at: str | None = None
    tested_at: str | None = None
    performed_by: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    elements: list[ElementRefResponse] = Field(default_factory=list)


# ── As-built record (Pillar 3) ────────────────────────────────────────────────


class AsBuiltRecordCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    discipline: str | None = Field(default=None, max_length=50)
    location_description: str | None = Field(default=None, max_length=500)
    capture_method: str = Field(default="manual", pattern=CAPTURE_METHOD_PATTERN)
    instrument: str | None = Field(default=None, max_length=255)
    instrument_calibration_ref: str | None = Field(default=None, max_length=120)
    accuracy_class: str = Field(default="standard", pattern=ACCURACY_CLASS_PATTERN)
    accuracy_value: str | None = Field(default=None, max_length=80)
    accuracy_unit: str | None = Field(default=None, max_length=40)
    coordinate_system: str | None = Field(default=None, max_length=120)
    survey_date: str | None = Field(default=None, max_length=40)
    surveyed_by: str | None = Field(default=None, max_length=255)
    # A UUID so a cross-project criterion is rejected (IDOR); the source is a soft ref.
    criterion_id: UUID | None = None
    measured_value: str | None = Field(default=None, max_length=80)
    source_kind: str = Field(default="manual", pattern=SOURCE_KIND_PATTERN)
    source_ref: str | None = Field(default=None, max_length=36)
    deviation_map_uri: str | None = Field(default=None, max_length=2000)
    # Optional model element the as-built was captured against (the UER).
    element: ElementRefIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AsBuiltRecordUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    discipline: str | None = Field(default=None, max_length=50)
    location_description: str | None = Field(default=None, max_length=500)
    capture_method: str | None = Field(default=None, pattern=CAPTURE_METHOD_PATTERN)
    instrument: str | None = Field(default=None, max_length=255)
    instrument_calibration_ref: str | None = Field(default=None, max_length=120)
    accuracy_class: str | None = Field(default=None, pattern=ACCURACY_CLASS_PATTERN)
    accuracy_value: str | None = Field(default=None, max_length=80)
    accuracy_unit: str | None = Field(default=None, max_length=40)
    coordinate_system: str | None = Field(default=None, max_length=120)
    survey_date: str | None = Field(default=None, max_length=40)
    surveyed_by: str | None = Field(default=None, max_length=255)
    criterion_id: UUID | None = None
    measured_value: str | None = Field(default=None, max_length=80)
    source_kind: str | None = Field(default=None, pattern=SOURCE_KIND_PATTERN)
    source_ref: str | None = Field(default=None, max_length=36)
    deviation_map_uri: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern=ASBUILT_UPDATE_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class AsBuiltSurveyIn(BaseModel):
    """Record the captured survey value. The service computes ``tolerance_result``
    against the linked criterion; an out-of-tolerance result raises a workmanship NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    measured_value: str | None = Field(default=None, max_length=80)
    deviation_value: str | None = Field(default=None, max_length=80)
    accuracy_value: str | None = Field(default=None, max_length=80)
    accuracy_unit: str | None = Field(default=None, max_length=40)
    survey_date: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=10000)


class AsBuiltVerifyIn(BaseModel):
    """Verify a surveyed as-built. An out-of-tolerance record raises a workmanship NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notes: str | None = Field(default=None, max_length=10000)
    ncr_severity: str | None = Field(default=None, pattern=r"^(critical|major|minor|observation)$")


class AsBuiltSignIn(BaseModel):
    """Sign the legal-record attestation. Only ``valid=True`` (with a verified record)
    moves the as-built to ``recorded``; the signature, timestamp and IP are captured."""

    model_config = ConfigDict(str_strip_whitespace=True)

    valid: bool = True
    notes: str | None = Field(default=None, max_length=10000)
    signed_at: str | None = Field(default=None, max_length=40)


class AsBuiltImportFromScanIn(BaseModel):
    """Create an as-built from a point-cloud scan registration (deviation result)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    # The point-cloud scan registration to import (IDOR-checked against the project).
    registration_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    discipline: str | None = Field(default=None, max_length=50)
    criterion_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AsBuiltRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    record_number: str
    title: str
    discipline: str | None = None
    location_description: str | None = None
    capture_method: str = "manual"
    instrument: str | None = None
    instrument_calibration_ref: str | None = None
    accuracy_class: str = "standard"
    accuracy_value: str | None = None
    accuracy_unit: str | None = None
    coordinate_system: str | None = None
    survey_date: str | None = None
    surveyed_by: str | None = None
    criterion_id: str | None = None
    measured_value: str | None = None
    deviation_value: str | None = None
    tolerance_result: str | None = None
    valid_for_legal_record: bool = False
    validity_signed_by: str | None = None
    validity_signed_at: str | None = None
    validity_signature_ip: str | None = None
    validity_signature_sha256: str | None = None
    source_kind: str = "manual"
    source_ref: str | None = None
    deviation_map_uri: str | None = None
    status: str = "draft"
    raised_ncr_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    elements: list[ElementRefResponse] = Field(default_factory=list)


# ── Hold gate (Pillar 5) ───────────────────────────────────────────────────────


class HoldGateCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    point_type: str = Field(default="hold", pattern=POINT_TYPE_PATTERN)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    required_party_role: str = Field(default="qa", pattern=PARTY_ROLE_PATTERN)
    # The inspection that satisfies the point, and the criterion it checks; UUIDs so a
    # cross-project reference is rejected (IDOR).
    inspection_id: UUID | None = None
    criterion_id: UUID | None = None
    attached_kind: str | None = Field(default=None, pattern=GATE_ATTACHED_KIND_PATTERN)
    attached_id: str | None = Field(default=None, max_length=36)
    package_ref: str | None = Field(default=None, max_length=64)
    # Whether this gate blocks progress. Omitted -> derived from point_type (hold blocks,
    # witness/surveillance/review do not).
    blocks_progress: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_attachment_pair(self) -> "HoldGateCreate":
        # A gate is found for enforcement by (attached_kind, attached_id) together. One
        # without the other can never match that lookup, so the gate would silently never
        # block anything. Require both or neither and say so plainly.
        if bool(self.attached_kind) != bool(self.attached_id):
            raise ValueError(
                "attached_kind and attached_id must be set together. "
                "Provide both to attach the gate to an activity, handover package or "
                "inspection, or leave both empty for an unattached gate."
            )
        return self


class HoldGateUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    point_type: str | None = Field(default=None, pattern=POINT_TYPE_PATTERN)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    required_party_role: str | None = Field(default=None, pattern=PARTY_ROLE_PATTERN)
    inspection_id: UUID | None = None
    criterion_id: UUID | None = None
    attached_kind: str | None = Field(default=None, pattern=GATE_ATTACHED_KIND_PATTERN)
    attached_id: str | None = Field(default=None, max_length=36)
    blocks_progress: bool | None = None
    metadata: dict[str, Any] | None = None


class HoldGateReleaseIn(BaseModel):
    """Release a gate. ``party_role`` is the role the caller asserts and must satisfy the
    gate's ``required_party_role`` (defence in depth alongside RBAC)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    party_role: str = Field(..., pattern=PARTY_ROLE_PATTERN)
    justification: str | None = Field(default=None, max_length=10000)
    released_at: str | None = Field(default=None, max_length=40)


class HoldGateWaiveIn(BaseModel):
    """Waive a gate. Only witness / surveillance / review gates may be waived."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=10000)


class HoldGateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    gate_number: str
    point_type: str = "hold"
    title: str
    description: str | None = None
    required_party_role: str = "qa"
    inspection_id: str | None = None
    criterion_id: str | None = None
    attached_kind: str | None = None
    attached_id: str | None = None
    package_ref: str | None = None
    blocks_progress: bool = True
    status: str = "pending"
    released_by: str | None = None
    released_party_role: str | None = None
    released_at: str | None = None
    release_justification: str | None = None
    release_signature_ip: str | None = None
    release_signature_sha256: str | None = None
    waived_by: str | None = None
    waived_reason: str | None = None
    approval_instance_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class GateProceedResponse(BaseModel):
    """The result of a can-proceed check for an attached entity."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    attached_kind: str
    attached_id: str
    can_proceed: bool
    blocking_gate_numbers: list[str] = Field(default_factory=list)
    blocking_gate_ids: list[str] = Field(default_factory=list)


# ── Handover / acceptance package (Pillar 4) ──────────────────────────────────


class HandoverPackageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    completion_regime: str = Field(default="taking_over", pattern=COMPLETION_REGIME_PATTERN)
    completion_type: str = Field(default="whole", pattern=COMPLETION_TYPE_PATTERN)
    section_ref: str | None = Field(default=None, max_length=255)
    regime_code: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9][a-z0-9_]*$")
    package_refs: list[str] | None = Field(default=None, max_length=200)
    # Optional model element the package covers (a sectional area, a system) - the UER.
    element: ElementRefIn | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HandoverPackageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    completion_regime: str | None = Field(default=None, pattern=COMPLETION_REGIME_PATTERN)
    completion_type: str | None = Field(default=None, pattern=COMPLETION_TYPE_PATTERN)
    section_ref: str | None = Field(default=None, max_length=255)
    regime_code: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9][a-z0-9_]*$")
    package_refs: list[str] | None = Field(default=None, max_length=200)
    certificate_no: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] | None = None


class HandoverOverrideIn(BaseModel):
    """Override a blocked completion gate. A manager act, recorded with a justification
    and captured as a documentation NCR so the override is auditable."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=10000)
    # Severity of the documentation NCR raised to record the override.
    ncr_severity: str | None = Field(default=None, pattern=r"^(critical|major|minor|observation)$")


class HandoverIssueIn(BaseModel):
    """Issue the acceptance certificate. Refused unless the gate is clear or overridden;
    the signature, timestamp and IP are captured (the certificate is never auto-issued)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    certificate_no: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=10000)
    issued_at: str | None = Field(default=None, max_length=40)


class HandoverGateReport(BaseModel):
    """The computed completion gate for a handover package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    project_id: UUID
    gating_state: str
    can_issue: bool
    open_ncr_count: int
    unreleased_hold_count: int
    completeness_pct: int
    # The gate numbers of the unreleased blocking gates attached to this package.
    blocking_gate_numbers: list[str] = Field(default_factory=list)


class HandoverPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    package_number: str
    title: str
    completion_regime: str = "taking_over"
    completion_type: str = "whole"
    section_ref: str | None = None
    regime_code: str | None = None
    package_refs: list[str] | None = None
    status: str = "draft"
    gating_state: str = "blocked"
    open_ncr_count: int = 0
    unreleased_hold_count: int = 0
    completeness_pct: int = 0
    gating_override_by: str | None = None
    gating_override_reason: str | None = None
    certificate_no: str | None = None
    issued_at: str | None = None
    issued_by: str | None = None
    issue_signature_ip: str | None = None
    issue_signature_sha256: str | None = None
    closeout_package_id: str | None = None
    dossier_key: str | None = None
    dossier_built_at: str | None = None
    assembled_at: str | None = None
    approval_instance_id: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    elements: list[ElementRefResponse] = Field(default_factory=list)
