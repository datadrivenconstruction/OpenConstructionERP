# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals Pydantic schemas - request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.submittals.tracking import REVIEW_OUTCOMES

# The one list. A submittal type reaches the API from this tuple, the pattern
# below is built from it, and the TypeScript array the pickers import is held
# against it by test_module_vocabularies_close_across_layers.py. Calculation
# was missing: a structural or hydraulic calculation is a submission in its own
# right, and the seeder had been filing one as the shop drawing it supports.
SUBMITTAL_TYPES: tuple[str, ...] = (
    "shop_drawing",
    "product_data",
    "sample",
    "mock_up",
    "test_report",
    "calculation",
    "method_statement",
    "certificate",
    "warranty",
)

SUBMITTAL_TYPE_PATTERN = rf"^({'|'.join(SUBMITTAL_TYPES)})$"

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
# A discipline is a code, not a sentence: lower-case, so the same trade is not
# filed under three spellings. The default list is ``tracking.DISCIPLINES``;
# a code outside it is accepted and prints as stored.
DISCIPLINE_PATTERN = r"^[a-z][a-z0-9_]{0,49}$"
# ISO 3166-1 alpha-2, upper case.
COUNTRY_PATTERN = r"^[A-Z]{2}$"
REVIEW_OUTCOME_PATTERN = rf"^({'|'.join(REVIEW_OUTCOMES)})$"
# A review period or a lead time longer than this is a typing error.
_MAX_REVIEW_PERIOD_DAYS = 365
_MAX_LEAD_TIME_WEEKS = 260

# What the list can be ordered by. Only stored columns: a derived figure
# (days in review, needed-by date) depends on today's date and is filtered
# and counted instead.
SUBMITTAL_SORT_FIELDS: tuple[str, ...] = (
    "created_at",
    "submittal_number",
    "title",
    "submittal_type",
    "discipline",
    "status",
    "review_outcome",
    "manufacturer",
    "date_submitted",
    "date_required",
    "date_returned",
    "required_on_site_date",
    "lead_time_weeks",
)


def _normalise_register_fields(data: Any) -> Any:
    """Bring the hand-typed register codes to their stored spelling.

    A discipline is lower-cased and a country code upper-cased before the
    patterns run, so "HVAC" and "tr" are accepted as what they plainly mean
    instead of being refused over their case.
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    discipline = out.get("discipline")
    if isinstance(discipline, str):
        out["discipline"] = discipline.strip().lower().replace("-", "_").replace(" ", "_") or None
    country = out.get("country_of_origin")
    if isinstance(country, str):
        out["country_of_origin"] = country.strip().upper() or None
    return out


class _RegisterFields(BaseModel):
    """The register columns a create and an update share, all optional."""

    discipline: str | None = Field(default=None, pattern=DISCIPLINE_PATTERN)
    manufacturer: str | None = Field(default=None, max_length=255)
    model_reference: str | None = Field(default=None, max_length=255)
    country_of_origin: str | None = Field(default=None, pattern=COUNTRY_PATTERN)
    supplier: str | None = Field(default=None, max_length=255)
    review_period_days: int | None = Field(default=None, ge=0, le=_MAX_REVIEW_PERIOD_DAYS)
    required_on_site_date: str | None = Field(default=None, pattern=_DATE_PATTERN)
    lead_time_weeks: int | None = Field(default=None, ge=0, le=_MAX_LEAD_TIME_WEEKS)

    _register_codes = model_validator(mode="before")(_normalise_register_fields)

    @field_validator("manufacturer", "model_reference", "supplier", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SubmittalCreate(_RegisterFields):
    """Create a new submittal."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    spec_section: str | None = Field(default=None, max_length=100)
    submittal_type: str = Field(
        ...,
        pattern=SUBMITTAL_TYPE_PATTERN,
    )
    status: str = Field(
        default="draft",
        pattern=(
            r"^(draft|submitted|under_review|approved|"
            r"approved_as_noted|revise_and_resubmit|rejected|closed)$"
        ),
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    current_revision: int = Field(default=1, ge=1)
    submitted_by_org: str | None = Field(default=None, max_length=255)
    reviewer_id: str | None = Field(default=None, max_length=36)
    approver_id: str | None = Field(default=None, max_length=36)
    date_submitted: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_returned: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_boq_item_ids: list[str] = Field(default_factory=list)
    long_lead: bool = False
    linked_drawing_ids: list[str] = Field(default_factory=list, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmittalUpdate(_RegisterFields):
    """Partial update for a submittal.

    The reviewer's stamp (``review_outcome``, ``review_code``) is not here on
    purpose: it is written by the review and approve actions, which are
    role-gated and audited, and never by a plain edit.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    spec_section: str | None = Field(default=None, max_length=100)
    submittal_type: str | None = Field(
        default=None,
        pattern=SUBMITTAL_TYPE_PATTERN,
    )
    status: str | None = Field(
        default=None,
        pattern=(
            r"^(draft|submitted|under_review|approved|"
            r"approved_as_noted|revise_and_resubmit|rejected|closed)$"
        ),
    )
    ball_in_court: str | None = Field(default=None, max_length=100)
    current_revision: int | None = Field(default=None, ge=1)
    submitted_by_org: str | None = Field(default=None, max_length=255)
    reviewer_id: str | None = Field(default=None, max_length=36)
    approver_id: str | None = Field(default=None, max_length=36)
    date_submitted: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_required: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_returned: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    linked_boq_item_ids: list[str] | None = None
    long_lead: bool | None = None
    linked_drawing_ids: list[str] | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None


class SubmittalReviewRequest(BaseModel):
    """Request body for reviewing a submittal."""

    status: str = Field(
        ...,
        pattern=(r"^(approved|approved_as_noted|revise_and_resubmit|rejected)$"),
    )
    notes: str | None = Field(default=None, max_length=5000)
    # The mark as the reviewer stamped it ("B", "2"). Left out, the default
    # letter for the decision is recorded.
    code: str | None = Field(default=None, max_length=20)
    # Approved as noted, with a corrected copy still owed for the record.
    resubmit_for_record: bool = False


class SubmittalApproveRequest(BaseModel):
    """Optional request body for final approval.

    The body is optional (a bare ``POST /approve/`` still works), but when
    present it carries the approver's ``notes`` so an approval with comments
    persists them into the submittal metadata instead of dropping them.
    """

    notes: str | None = Field(default=None, max_length=5000)
    code: str | None = Field(default=None, max_length=20)


class StartApprovalRequest(BaseModel):
    """Request body for starting a routed approval workflow (feature 06)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    route_id: UUID


class SubmittalResponse(BaseModel):
    """Submittal returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    submittal_number: str
    title: str
    spec_section: str | None = None
    submittal_type: str
    status: str = "draft"
    ball_in_court: str | None = None
    ball_in_court_name: str | None = None
    current_revision: int = 1
    submitted_by_org: str | None = None
    reviewer_id: str | None = None
    approver_id: str | None = None
    date_submitted: str | None = None
    date_required: str | None = None
    date_returned: str | None = None
    linked_boq_item_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    # Description and reviewer notes are persisted inside ``metadata`` (the
    # Submittal model has no dedicated columns and we add no migration). They
    # are surfaced as top-level convenience fields by ``_to_response`` so the
    # frontend does not have to dig into the metadata blob.
    description: str | None = None
    review_notes: str | None = None
    # Register columns. Absent on a row from before they existed.
    discipline: str | None = None
    manufacturer: str | None = None
    model_reference: str | None = None
    country_of_origin: str | None = None
    supplier: str | None = None
    supplier_name: str | None = None
    review_period_days: int | None = None
    required_on_site_date: str | None = None
    long_lead: bool = False
    lead_time_weeks: int | None = None
    linked_drawing_ids: list[str] = Field(default_factory=list)
    review_history: list[dict[str, Any]] = Field(default_factory=list)
    # The reviewer's decision on the current revision and the mark for it.
    # ``review_outcome`` falls back to a status that is itself a decision, so
    # an older approved row still reads as approved.
    review_outcome: str | None = None
    review_code: str | None = None
    may_proceed: bool = False
    resubmit_for_record: bool = False
    # Derived as of today. ``None`` means it cannot be said from what is
    # recorded (no review period, no lead time), never zero.
    days_in_review: int | None = None
    review_due_date: str | None = None
    review_overdue_days: int | None = None
    approval_needed_by: str | None = None
    approval_late_days: int | None = None
    submit_by_date: str | None = None
    created_at: datetime
    updated_at: datetime


class SubmittalCodeCount(BaseModel):
    """How many submittals carry one code of a vocabulary."""

    code: str
    count: int


class SubmittalOutcomeCount(SubmittalCodeCount):
    """An outcome count with the default stamp letter for that outcome."""

    review_code: str | None = None


class SubmittalRegisterSummary(BaseModel):
    """The figures printed above the register, for one project as of today."""

    project_id: UUID
    as_of: str
    total: int = 0
    by_status: list[SubmittalCodeCount] = Field(default_factory=list)
    by_type: list[SubmittalCodeCount] = Field(default_factory=list)
    # Rows with no discipline are counted under the empty code "".
    by_discipline: list[SubmittalCodeCount] = Field(default_factory=list)
    by_outcome: list[SubmittalOutcomeCount] = Field(default_factory=list)
    awaiting_review: int = 0
    # Past the contractual review period, and the ones that cannot be judged
    # because no period is recorded. The two never overlap.
    review_overdue: int = 0
    review_period_unknown: int = 0
    long_lead: int = 0
    long_lead_awaiting_approval: int = 0
    # Not approved and already past required on site less lead time.
    approval_late: int = 0
    # Long-lead items still awaiting approval whose needed-by date cannot be
    # worked out: the lead time or the required-on-site date is missing.
    long_lead_without_lead_time: int = 0


class SubmittalVocabularyEntry(BaseModel):
    """One code of a vocabulary with its label in the request language."""

    code: str
    label: str
    short_code: str | None = None


class SubmittalVocabulary(BaseModel):
    """The codes the pickers offer, labelled in one language."""

    locale: str
    types: list[SubmittalVocabularyEntry] = Field(default_factory=list)
    disciplines: list[SubmittalVocabularyEntry] = Field(default_factory=list)
    outcomes: list[SubmittalVocabularyEntry] = Field(default_factory=list)
    sort_fields: list[str] = Field(default_factory=list)
