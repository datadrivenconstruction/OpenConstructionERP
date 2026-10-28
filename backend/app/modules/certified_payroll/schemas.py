# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Certified payroll Pydantic schemas.

Money and hours are Decimal-as-string end to end, matching ``oe_payroll``, so
the JSON never loses cents to binary float. Rates are validated as non-negative
finite numbers at the edge, because a negative or NaN wage rate that reaches the
comparison rules would produce a compliance finding about arithmetic rather than
about wages.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

DeterminationAuthority = Literal["federal", "state", "awarding_body"]
DeterminationMethod = Literal["published_schedule", "local_wage_survey", "federal_locality_determination"]
FringeElection = Literal["plan", "cash", "mixed"]


def _validate_money(value: str | None, *, field: str) -> str | None:
    """Reject non-numeric, negative and non-finite money at the edge."""
    if value is None or value == "":
        return value
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return str(parsed)


# ── Wage determination ──────────────────────────────────────────────────────


class WageClassificationCreate(BaseModel):
    """One craft inside a determination, with basic and fringe stated apart."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    code: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=255)
    # The basic hourly wage. The overtime multiplier applies to this figure and
    # to nothing else, which is why it is a separate required field and not a
    # component of some combined rate.
    basic_hourly_rate: str = Field(default="0", max_length=50)
    # The hourly fringe benefit amount, paid to a plan or in cash.
    fringe_rate: str = Field(default="0", max_length=50)
    note: str = Field(default="", max_length=2000)
    ordinal: int = 0

    @field_validator("basic_hourly_rate")
    @classmethod
    def _check_basic(cls, v: str) -> str:
        return _validate_money(v, field="basic_hourly_rate") or "0"

    @field_validator("fringe_rate")
    @classmethod
    def _check_fringe(cls, v: str) -> str:
        return _validate_money(v, field="fringe_rate") or "0"


class WageClassificationResponse(BaseModel):
    """A craft line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    determination_id: UUID
    code: str
    title: str
    basic_hourly_rate: str
    fringe_rate: str
    note: str
    ordinal: int
    created_at: datetime
    updated_at: datetime


class WageDeterminationCreate(BaseModel):
    """Request body to record a wage determination the contractor holds.

    Nothing here is seeded by the platform. The contractor enters the document
    the awarding body issued, and the record says which document it was.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    authority: DeterminationAuthority = "federal"
    authority_name: str = Field(default="", max_length=255)
    jurisdiction: str = Field(default="", max_length=20)
    locality: str = Field(default="", max_length=160)
    identifier: str = Field(min_length=1, max_length=120)
    title: str = Field(default="", max_length=255)
    determination_method: DeterminationMethod | None = None
    decision_date: str | None = Field(default=None, max_length=20)
    effective_date: str | None = Field(default=None, max_length=20)
    expires_on: str | None = Field(default=None, max_length=20)
    statute_reference: str = Field(default="", max_length=255)
    source_note: str = Field(default="", max_length=4000)
    currency: str = Field(default="USD", max_length=10)
    classifications: list[WageClassificationCreate] = Field(default_factory=list)


class WageDeterminationUpdate(BaseModel):
    """Partial update of a determination that no certified week cites yet."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    authority: DeterminationAuthority | None = None
    authority_name: str | None = Field(default=None, max_length=255)
    jurisdiction: str | None = Field(default=None, max_length=20)
    locality: str | None = Field(default=None, max_length=160)
    identifier: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=255)
    determination_method: DeterminationMethod | None = None
    decision_date: str | None = Field(default=None, max_length=20)
    effective_date: str | None = Field(default=None, max_length=20)
    expires_on: str | None = Field(default=None, max_length=20)
    statute_reference: str | None = Field(default=None, max_length=255)
    source_note: str | None = Field(default=None, max_length=4000)
    currency: str | None = Field(default=None, max_length=10)


class WageDeterminationResponse(BaseModel):
    """A determination with its craft lines."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    authority: str
    authority_name: str
    jurisdiction: str
    locality: str
    identifier: str
    title: str
    determination_method: str | None
    decision_date: str | None
    effective_date: str | None
    expires_on: str | None
    statute_reference: str
    source_note: str
    currency: str
    locked: bool
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    classifications: list[WageClassificationResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Worker classification ───────────────────────────────────────────────────


class AssignmentCreate(BaseModel):
    """Put a worker under a trade classification on a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    resource_id: UUID | None = None
    worker_name: str = Field(min_length=1, max_length=255)
    worker_identifier: str = Field(default="", max_length=60)
    classification_id: UUID
    valid_from: str | None = Field(default=None, max_length=20)
    valid_to: str | None = Field(default=None, max_length=20)
    # The split of what this worker is actually paid. Optional: left out, the
    # service derives it from the payroll rate against the determination.
    paid_basic_rate: str | None = Field(default=None, max_length=50)
    paid_fringe_rate: str | None = Field(default=None, max_length=50)
    fringe_election: FringeElection | None = None
    note: str = Field(default="", max_length=2000)

    @field_validator("paid_basic_rate", "paid_fringe_rate")
    @classmethod
    def _check_paid(cls, v: str | None) -> str | None:
        return _validate_money(v, field="paid rate")


class AssignmentUpdate(BaseModel):
    """Partial update of a worker's classification."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    resource_id: UUID | None = None
    worker_name: str | None = Field(default=None, max_length=255)
    worker_identifier: str | None = Field(default=None, max_length=60)
    classification_id: UUID | None = None
    valid_from: str | None = Field(default=None, max_length=20)
    valid_to: str | None = Field(default=None, max_length=20)
    paid_basic_rate: str | None = Field(default=None, max_length=50)
    paid_fringe_rate: str | None = Field(default=None, max_length=50)
    fringe_election: FringeElection | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("paid_basic_rate", "paid_fringe_rate")
    @classmethod
    def _check_paid(cls, v: str | None) -> str | None:
        return _validate_money(v, field="paid rate")


class AssignmentResponse(BaseModel):
    """A worker-to-classification assignment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    resource_id: UUID | None
    worker_name: str
    worker_identifier: str
    classification_id: UUID
    valid_from: str | None
    valid_to: str | None
    paid_basic_rate: str | None
    paid_fringe_rate: str | None
    fringe_election: str | None
    note: str
    created_at: datetime
    updated_at: datetime


# ── Weekly payroll ──────────────────────────────────────────────────────────


class CertifiedWeekCreate(BaseModel):
    """Open a draft certified payroll week for a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    week_ending: str = Field(min_length=1, max_length=20, description="ISO YYYY-MM-DD")
    batch_id: UUID | None = None
    payroll_number: str = Field(default="", max_length=40)
    is_final: bool = False
    contractor_name: str = Field(default="", max_length=255)
    contractor_address: str = Field(default="", max_length=2000)
    is_subcontractor: bool = False
    project_name: str = Field(default="", max_length=255)
    project_location: str = Field(default="", max_length=255)
    contract_number: str = Field(default="", max_length=120)
    # Which regimes cover the work. Both are recorded when both apply, because
    # a determination under one does not discharge the obligation under another.
    covered_authorities: list[DeterminationAuthority] = Field(default_factory=list)
    fringe_election: FringeElection = "plan"
    fringe_exception_note: str = Field(default="", max_length=4000)
    # Hours per day beyond which work is overtime, and hours per week likewise.
    # Both optional and both explicit: no working-time rule is assumed.
    daily_overtime_threshold: str | None = Field(default=None, max_length=20)
    weekly_overtime_threshold: str | None = Field(default=None, max_length=20)
    overtime_multiplier: str = Field(default="1.5", max_length=20)
    notes: str = Field(default="", max_length=4000)

    @field_validator("daily_overtime_threshold", "weekly_overtime_threshold", "overtime_multiplier")
    @classmethod
    def _check_numbers(cls, v: str | None) -> str | None:
        return _validate_money(v, field="threshold")


class CertifiedWeekUpdate(BaseModel):
    """Partial update of a draft week. A certified week rejects every field."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    payroll_number: str | None = Field(default=None, max_length=40)
    is_final: bool | None = None
    contractor_name: str | None = Field(default=None, max_length=255)
    contractor_address: str | None = Field(default=None, max_length=2000)
    is_subcontractor: bool | None = None
    project_name: str | None = Field(default=None, max_length=255)
    project_location: str | None = Field(default=None, max_length=255)
    contract_number: str | None = Field(default=None, max_length=120)
    covered_authorities: list[DeterminationAuthority] | None = None
    fringe_election: FringeElection | None = None
    fringe_exception_note: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)


class CertifyRequest(BaseModel):
    """Sign the statement of compliance and freeze the week.

    ``statement_text`` is optional: left blank, the module renders the standard
    four assertions from the week's own facts. Supplied, it is stored verbatim,
    because the wording a contractor submits is the contractor's to settle.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    signatory_name: str = Field(min_length=1, max_length=255)
    signatory_title: str = Field(min_length=1, max_length=160)
    statement_text: str = Field(default="", max_length=20000)
    fringe_election: FringeElection | None = None
    fringe_exception_note: str | None = Field(default=None, max_length=4000)


class CertifiedLineResponse(BaseModel):
    """One worker's week, derived from payroll or frozen at certification."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, extra="ignore")

    id: UUID | None = None
    week_id: UUID | None = None
    resource_id: UUID | None = None
    worker_name: str = ""
    worker_identifier: str = ""
    classification_id: UUID | None = None
    classification_code: str = ""
    classification_title: str = ""
    determination_id: UUID | None = None
    determination_identifier: str = ""
    determination_authority: str = ""
    # Present on a derived line so the out-of-window rule can read them; not
    # frozen onto the row, because the determination itself carries them.
    determination_effective_date: str | None = None
    determination_expires_on: str | None = None
    hours_by_day: dict[str, Any] = Field(default_factory=dict)
    straight_hours: str = "0"
    overtime_hours: str = "0"
    required_basic_rate: str = "0"
    required_fringe_rate: str = "0"
    paid_basic_rate: str = "0"
    paid_fringe_rate: str = "0"
    fringe_election: str = ""
    overtime_multiplier: str = "1.5"
    overtime_base_rate: str = "0"
    gross_amount: str = "0"
    total_deductions: str = "0"
    net_amount: str = "0"
    deductions_detail: list[dict[str, Any]] = Field(default_factory=list)
    currency: str = ""
    ordinal: int = 0
    note: str = ""


class CertifiedWeekResponse(BaseModel):
    """A certified payroll week header."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    batch_id: UUID | None
    week_ending: str
    payroll_number: str
    is_final: bool
    contractor_name: str
    contractor_address: str
    is_subcontractor: bool
    project_name: str
    project_location: str
    contract_number: str
    covered_authorities: list[Any] = Field(default_factory=list)
    governing_determination_id: UUID | None
    governing_reason: str
    fringe_election: str
    fringe_exception_note: str
    status: str
    signatory_name: str | None
    signatory_title: str | None
    signed_at: datetime | None
    signed_by: UUID | None
    statement_text: str
    currency: str
    notes: str
    created_by: UUID | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CertifiedWeekDetailResponse(CertifiedWeekResponse):
    """A week with its lines, derived for a draft and frozen for a certified one."""

    lines: list[CertifiedLineResponse] = Field(default_factory=list)
    # True when the lines were computed live from payroll rather than read back
    # from the frozen record. A reader should know which they are looking at.
    lines_are_derived: bool = True


class ValidationFindingResponse(BaseModel):
    """One validation finding on a week."""

    model_config = ConfigDict(extra="ignore")

    rule_id: str
    rule_name: str
    severity: str
    category: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WeekValidationResponse(BaseModel):
    """The validation report for one week."""

    model_config = ConfigDict(extra="ignore")

    week_id: UUID
    status: str
    error_count: int
    warning_count: int
    can_certify: bool
    findings: list[ValidationFindingResponse] = Field(default_factory=list)
